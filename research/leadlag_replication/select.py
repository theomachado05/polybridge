from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

import pandas as pd
import requests

from .config import EXCLUDED_SLUGS, MARKETS_PATH, PARAMS, POOL_EVENTS_PER_QUERY, POOL_TAGS, WINDOW_END, WINDOW_START

GAMMA = "https://gamma-api.polymarket.com"

EXCLUDE = [
    r"fed", r"fomc", r"federal reserve", r"interest rates?", r"rate cuts?", r"rate hikes?", r"bps", r"powell",
    r"elect\w*", r"win", r"wins", r"nominee", r"nominat\w*", r"president", r"prime minister", r"approval", r"who",
    r"which", r"out as", r"resign\w*", r"impeach\w*", r"pardon\w*", r"leader",
    r"s&p", r"spx", r"nasdaq", r"dow", r"stocks?", r"spy", r"ipo", r"market cap", r"largest company",
    r"bitcoin", r"btc", r"eth", r"ethereum", r"crypto\w*", r"microstrategy", r"solana", r"gold", r"oil", r"price",
    r"treasury", r"yields?",
    r"inflation", r"cpi", r"gdp", r"unemployment", r"jobs", r"payrolls?",
    r"how many", r"how much", r"exactly", r"between", r"above", r"below", r"more than", r"less than", r"at least",
    r"greater than", r"fewer than", r"nothing",
    r"revenue", r"emergency", r"no change", r"sanctions?",
    r"not", r"no", r"broken", r"break\w*", r"collaps\w*", r"fail\w*", r"violat\w*", r"surviv\w*", r"if",
]
RISK_ON = [
    r"cease-?fire", r"truce", r"peace deal", r"peace agreement", r"trade deal", r"trade agreement", r"nuclear deal",
    r"war ends?", r"end (?:of )?the war", r"ends? the war",
]
RISK_OFF = [
    r"recession", r"shutdown", r"default\w*", r"invade\w*", r"invasion", r"blockade\w*", r"military", r"strikes?",
    r"airstrikes?", r"attacks?", r"declares? war", r"war with", r"go to war", r"at war", r"martial law",
    r"nuclear (?:test|weapon|strike)\w*",
]
TARIFF = r"tariffs?"
TARIFF_EASING = [r"lower\w*", r"reduc\w*", r"cut\w*", r"paus\w*", r"remov\w*", r"lift\w*", r"exempt\w*", r"deal",
                 r"agreement", r"ends? (?:the )?tariffs?", r"suspend\w*", r"drop\w*", r"repeal\w*"]


def _any(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(rf"\b{p}\b", text)]


def classify(question: str) -> tuple[int, str]:
    q = (question or "").lower()
    ex = _any(EXCLUDE, q)
    if ex:
        return 0, f"excluded: {ex[0]}"
    on, off = _any(RISK_ON, q), _any(RISK_OFF, q)
    if re.search(rf"\b{TARIFF}\b", q):
        (on if _any(TARIFF_EASING, q) else off).append("tariff")
    if on and off:
        return 0, f"ambiguous: {on[0]} / {off[0]}"
    if on:
        return +1, f"risk-on: {on[0]}"
    if off:
        return -1, f"risk-off: {off[0]}"
    return 0, "no sign term"


def _ts(s) -> pd.Timestamp | None:
    if not s:
        return None
    try:
        t = pd.Timestamp(s)
    except (ValueError, TypeError):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def market_window(m: dict) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    start = _ts(m.get("startDate")) or _ts(m.get("createdAt"))
    end = _ts(m.get("closedTime")) if m.get("closed") else None
    end = end or _ts(m.get("endDate"))
    return start, end


def overlap_days(start, end) -> float:
    if start is None or end is None:
        return 0.0
    a = max(start, pd.Timestamp(WINDOW_START, tz="UTC"))
    b = min(end, pd.Timestamp(WINDOW_END, tz="UTC") + pd.Timedelta(days=1))
    return max(0.0, (b - a).total_seconds() / 86400)


def _tokens(m: dict) -> list[str]:
    raw = m.get("clobTokenIds") or "[]"
    return json.loads(raw) if isinstance(raw, str) else list(raw)


def _outcomes(m: dict) -> list[str]:
    raw = m.get("outcomes") or "[]"
    return json.loads(raw) if isinstance(raw, str) else list(raw)


def fetch_pool(session=None) -> list[dict]:
    s = session or requests.Session()
    events: dict[str, dict] = {}
    for tag_id in POOL_TAGS.values():
        for closed in ("true", "false"):
            got, offset = 0, 0
            while got < POOL_EVENTS_PER_QUERY:
                lim = min(100, POOL_EVENTS_PER_QUERY - got)
                r = s.get(f"{GAMMA}/events", params={"tag_id": tag_id, "closed": closed, "order": "volume",
                                                      "ascending": "false", "limit": lim, "offset": offset}, timeout=60)
                r.raise_for_status()
                rows = r.json()
                for e in rows:
                    events.setdefault(str(e["id"]), e)
                got += len(rows)
                offset += len(rows)
                if len(rows) < lim:
                    break
    return list(events.values())


MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
STEM_STOP = {"will", "the", "a", "an", "in", "by", "before", "after", "on", "of", "end", "to", "year", "this"}


def question_stem(question: str) -> str:
    words = re.findall(r"[a-z]+", (question or "").lower())
    return " ".join(w for w in words if w not in MONTHS and w not in STEM_STOP)


def dedupe_overlapping(df: pd.DataFrame) -> pd.DataFrame:
    kept: list[int] = []
    for i, r in df.iterrows():
        s0, e0 = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
        clash = any(df.at[j, "stem"] == r["stem"] and s0 < pd.Timestamp(df.at[j, "end"]) and pd.Timestamp(df.at[j, "start"]) < e0
                    for j in kept)
        if not clash:
            kept.append(i)
    return df.loc[kept]


def candidates(events: list[dict]) -> pd.DataFrame:
    rows = []
    for e in events:
        best = None
        for m in e.get("markets", []):
            if m.get("slug") in EXCLUDED_SLUGS:
                continue
            toks, outs = _tokens(m), _outcomes(m)
            if len(toks) != 2 or [o.lower() for o in outs] != ["yes", "no"] or not m.get("enableOrderBook", True):
                continue
            sign, why = classify(m.get("question", ""))
            if sign == 0:
                continue
            start, end = market_window(m)
            ov = overlap_days(start, end)
            if ov < PARAMS.min_window_days:
                continue
            vol = float(m.get("volumeNum") or m.get("volume") or 0)
            row = {"event_slug": e.get("slug"), "market_slug": m.get("slug"), "question": m.get("question"),
                   "token_id": toks[0], "condition_id": m.get("conditionId"), "sign": sign, "sign_reason": why,
                   "stem": question_stem(m.get("question", "")),
                   "volume_usd": vol, "start": start.isoformat(), "end": end.isoformat(), "window_days": round(ov, 1)}
            if best is None or vol > best["volume_usd"]:
                best = row
        if best is not None:
            rows.append(best)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates("market_slug").sort_values("volume_usd", ascending=False, kind="mergesort").reset_index(drop=True)
    df = dedupe_overlapping(df).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args(argv)
    ev = fetch_pool()
    df = candidates(ev)
    print(f"{len(ev)} pool events, {len(df)} eligible markets")
    with pd.option_context("display.width", 250, "display.max_colwidth", 80):
        print(df.head(a.top)[["rank", "market_slug", "sign", "sign_reason", "volume_usd", "start", "end", "window_days"]].to_string(index=False))
    if a.write:
        doc = {"snapshot_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_pool_events": len(ev),
               "candidates": df.to_dict(orient="records")}
        MARKETS_PATH.write_text(json.dumps(doc, indent=1))
        print(f"wrote {MARKETS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
