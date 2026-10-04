"""Macro market selection by a fixed rule (METHOD.md sections 2-3) using gamma METADATA only (no prices).

    cd research && .venv/bin/python -m macro_panel.select          # print the ranked eligible list
    cd research && .venv/bin/python -m macro_panel.select --write  # freeze it to macro_panel/markets.json

Never prints or stores outcome prices, last-trade prices or price changes from gamma.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

import pandas as pd
import requests

from leadlag_replication.select import _outcomes, _tokens, market_window

from .config import (EXCLUDED_SLUGS, MARKETS_PATH, PARAMS, POOL_EVENTS_PER_QUERY, POOL_TAG_IDS, POOL_TAG_SLUGS,
                     WINDOW_END, WINDOW_START)

GAMMA = "https://gamma-api.polymarket.com"

EXCLUDE = [
    r"canada", r"canadian", r"uk", r"britain", r"british", r"england", r"euro\w*", r"ecb", r"germany", r"german",
    r"japan\w*", r"boj", r"china", r"chinese", r"india\w*", r"australia\w*", r"rba", r"boe", r"snb", r"swiss",
    r"mexic\w*", r"brazil\w*", r"turk\w*", r"argentin\w*", r"russia\w*", r"korea\w*", r"france", r"french", r"ital\w*",
    r"spain", r"spanish", r"new zealand", r"rbnz",
    r"say", r"says", r"said", r"mention\w*", r"tweet\w*", r"post\w*", r"powell", r"chair", r"nominee", r"nominat\w*",
    r"fire\w*", r"resign\w*", r"replace\w*", r"elect\w*", r"president", r"trump", r"biden", r"harris", r"who",
    r"which", r"approval",
    r"s&p", r"spx", r"nasdaq", r"dow", r"stocks?", r"spy", r"bitcoin", r"btc", r"eth", r"ethereum", r"crypto\w*",
    r"gold", r"oil", r"gas", r"prices?(?! index)", r"treasury", r"yields?", r"mortgage", r"dollar",
    r"how many", r"how much", r"exactly", r"between", r"range", r"no change", r"unchanged", r"pause\w*", r"hold",
    r"holds", r"maintain\w*", r"emergency",
    r"not", r"no", r"never", r"if", r"unless", r"without",
]
NUM_RANGE = re.compile(r"\d+(?:\.\d+)?\s*%?\s*(?:-|–|to)\s*\d")

CLASS_TERMS = {
    "recession": [r"recession"],
    "fed": [r"fed", r"fomc", r"federal reserve", r"fed funds", r"interest rates?", r"rate cuts?", r"rate hikes?"],
    "inflation": [r"inflation", r"cpi", r"pce", r"consumer price index"],
    "unemployment": [r"unemployment", r"jobless"],
    "gdp": [r"gdp"],
}
FED_DOWN = [r"cut\w*", r"decrease\w*", r"lower\w*", r"reduc\w*"]
FED_UP = [r"hike\w*", r"increase\w*", r"raise\w*"]
TH_UP = [r"above", r"over", r"more than", r"greater than", r"at least", r"or more", r"or higher", r"exceed\w*"]
TH_DOWN = [r"below", r"under", r"less than", r"fewer than", r"or less", r"or lower"]
GDP_DOWN = [r"negative", r"contract\w*", r"shrink\w*"]
SYM_UP = re.compile(r"≥|>=|>|\d\s*%?\s*\+")
SYM_DOWN = re.compile(r"≤|<=|<")
VALENCE = {"inflation": -1, "unemployment": -1, "gdp": +1}


def _any(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(rf"\b{p}\b", text)]


def classify(question: str) -> tuple[int, str, str]:
    """Return (sign, class, reason). sign 0 means excluded."""
    q = (question or "").lower()
    ex = _any(EXCLUDE, q)
    if ex:
        return 0, "", f"excluded: {ex[0]}"
    if NUM_RANGE.search(q):
        return 0, "", "excluded: numeric range"
    hits = [c for c, pats in CLASS_TERMS.items() if _any(pats, q)]
    if len(hits) != 1:
        return 0, "", "no class" if not hits else f"ambiguous class: {'/'.join(hits)}"
    cls = hits[0]
    if cls == "recession":
        return -1, cls, "recession: yes is risk-off"
    if cls == "fed":
        down, up = bool(_any(FED_DOWN, q)), bool(_any(FED_UP, q))
        if down == up:
            return 0, cls, "fed: no single direction"
        return (+1, cls, "fed: cut") if down else (-1, cls, "fed: hike")
    up = bool(_any(TH_UP, q) or SYM_UP.search(q))
    down = bool(_any(TH_DOWN, q) or SYM_DOWN.search(q) or (cls == "gdp" and _any(GDP_DOWN, q)))
    if up == down:
        return 0, cls, f"{cls}: no single threshold direction"
    d = 1 if up else -1
    return VALENCE[cls] * d, cls, f"{cls}: {'up' if up else 'down'}"


def overlap_days(start, end) -> float:
    if start is None or end is None:
        return 0.0
    a = max(start, pd.Timestamp(WINDOW_START, tz="UTC"))
    b = min(end, pd.Timestamp(WINDOW_END, tz="UTC") + pd.Timedelta(days=1))
    return max(0.0, (b - a).total_seconds() / 86400)


def _pages(s, params: dict) -> list[dict]:
    out, offset = [], 0
    while len(out) < POOL_EVENTS_PER_QUERY:
        lim = min(100, POOL_EVENTS_PER_QUERY - len(out))
        r = s.get(f"{GAMMA}/events", params={**params, "order": "volume", "ascending": "false", "limit": lim,
                                              "offset": offset}, timeout=60)
        r.raise_for_status()
        rows = r.json()
        out.extend(rows)
        offset += len(rows)
        if len(rows) < lim:
            break
    return out


def fetch_pool(session=None) -> list[dict]:
    s = session or requests.Session()
    events: dict[str, dict] = {}
    queries = [{"tag_id": t} for t in POOL_TAG_IDS.values()] + [{"tag_slug": t} for t in POOL_TAG_SLUGS]
    for q in queries:
        for closed in ("true", "false"):
            for e in _pages(s, {**q, "closed": closed}):
                events.setdefault(str(e["id"]), e)
    return list(events.values())


def candidates(events: list[dict]) -> pd.DataFrame:
    """Eligible markets, the highest-volume eligible market per event, ranked by lifetime volume."""
    rows = []
    for e in events:
        best = None
        for m in e.get("markets", []):
            if m.get("slug") in EXCLUDED_SLUGS:
                continue
            toks, outs = _tokens(m), _outcomes(m)
            if len(toks) != 2 or [o.lower() for o in outs] != ["yes", "no"] or not m.get("enableOrderBook", True):
                continue
            sign, cls, why = classify(m.get("question", ""))
            if sign == 0:
                continue
            vol = float(m.get("volumeNum") or m.get("volume") or 0)
            if vol < PARAMS.min_volume_usd:
                continue
            start, end = market_window(m)
            ov = overlap_days(start, end)
            if ov < PARAMS.min_window_days:
                continue
            row = {"event_slug": e.get("slug"), "market_slug": m.get("slug"), "question": m.get("question"),
                   "token_id": toks[0], "condition_id": m.get("conditionId"), "sign": sign, "cls": cls,
                   "sign_reason": why, "volume_usd": vol, "start": start.isoformat(), "end": end.isoformat(),
                   "window_days": round(ov, 1)}
            if best is None or vol > best["volume_usd"]:
                best = row
        if best is not None:
            rows.append(best)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates("market_slug").sort_values("volume_usd", ascending=False, kind="mergesort").reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


def freeze(path=MARKETS_PATH, session=None) -> pd.DataFrame:
    ev = fetch_pool(session)
    df = candidates(ev)
    doc = {"snapshot_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_pool_events": len(ev),
           "candidates": df.to_dict(orient="records")}
    path.write_text(json.dumps(doc, indent=1))
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--top", type=int, default=80)
    a = ap.parse_args(argv)
    if a.write:
        df = freeze()
        print(f"wrote {MARKETS_PATH}")
    else:
        df = candidates(fetch_pool())
    print(f"{len(df)} eligible markets")
    with pd.option_context("display.width", 250, "display.max_colwidth", 70):
        print(df.head(a.top)[["rank", "market_slug", "cls", "sign", "volume_usd", "start", "end", "window_days"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
