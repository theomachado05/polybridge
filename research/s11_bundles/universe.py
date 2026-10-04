"""S11 universe: bundles of questions that must be consistent with each other, from catalogue text only.

Three kinds, all within one event:
  strike   same wording apart from the level ("hit $100" / "hit $105"); YES at a further level implies YES at a nearer one
  date     same wording apart from a "by <date>" date; YES by an earlier date implies YES by a later one
  negrisk  a one-of-many event (Polymarket's negRisk flag): exactly one member resolves YES

No price is read: every price field of the catalogue record is dropped before anything is stored.
Writes `bundles.json` (history: S9's strike ladders and S5's events) and `live_bundles.json` (events open tonight).

Run from `research/`:  python -m s11_bundles.universe
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
PRICE_FIELDS = {"bestAsk", "bestBid", "lastTradePrice", "spread", "outcomePrices", "oneDayPriceChange", "oneHourPriceChange",
                "oneWeekPriceChange", "oneMonthPriceChange", "oneYearPriceChange", "volume24hr", "volume1wk", "volume1mo", "volume1yr",
                "competitive", "liquidity", "liquidityNum", "liquidityClob", "volume24hrClob", "volume1wkClob", "volume1moClob",
                "volume1yrClob", "lastTradePrice"}
KEEP = ("id", "question", "groupItemTitle", "conditionId", "clobTokenIds", "startDate", "endDate", "closedTime", "closed", "active",
        "negRisk", "negRiskOther", "feesEnabled", "feeSchedule", "volume", "enableOrderBook", "orderPriceMinTickSize", "acceptingOrders")


# ---------------------------------------------------------------- text rules (pure)

def date_template(q: str) -> tuple[str, str | None]:
    """The question with its date phrase replaced by <D>, and the phrase. Only the last date phrase is replaced."""
    found = list(re.finditer(cfg.DATE_RE, q))
    if not found:
        return q, None
    m = found[-1]
    return q[:m.start()] + "@D@" + q[m.end():], m.group(0)


def parse_date(phrase: str, default_year: int) -> date | None:
    s = phrase.lower().replace(".", "").replace(",", " ")
    end_of = s.startswith("end of")
    s = s.replace("end of", "").strip()
    toks = s.split()
    if not toks:
        return None
    mon = next((i + 1 for i, m in enumerate(cfg.MONTHS) if toks[0] == m or toks[0] == m[:3]), None)
    if mon is None:
        return None
    day, year = None, default_year
    for t in toks[1:]:
        t = re.sub(r"(st|nd|rd|th)$", "", t)
        if t.isdigit():
            if len(t) == 4:
                year = int(t)
            else:
                day = int(t)
    if day is None or end_of:
        nxt = date(year + (mon == 12), mon % 12 + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)
    try:
        return date(year, mon, day)
    except ValueError:
        return None


def strike_template(q: str) -> tuple[str, float | None, int]:
    """The question with its one level replaced by <N>, the level, and the orientation: +1 when YES needs a higher level,
    -1 when YES needs a lower one, 0 when the wording does not say (left out). Questions with a date phrase keep it."""
    body, _ = date_template(q)
    nums = [m for m in re.finditer(cfg.NUM_RE, body) if m.group(0).strip() and not re.fullmatch(r"(?:19|20)\d\d", m.group(0).strip())]
    if len(nums) != 1:
        return q, None, 0
    m = nums[0]
    raw = m.group(0).strip()
    val = float(re.sub(r"[^\d.]", "", raw.replace(",", "")) or "nan")
    mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}.get(raw[-1].lower(), 1.0) if raw[-1].isalpha() else 1.0
    templ = body[:m.start()] + "@N@" + body[m.end():]
    up, down = re.search(cfg.UP_WORDS, templ), re.search(cfg.DOWN_WORDS, templ)
    orient = 1 if up and not down else (-1 if down and not up else 0)
    return templ, val * mult, orient


def date_ladders(event: str, markets: list[dict]) -> list[dict]:
    groups: dict[str, list[tuple[date, dict]]] = {}
    for m in markets:
        templ, phrase = date_template(m["question"])
        if phrase is None or not re.search(cfg.CUMULATIVE_DATE_RE, templ, re.I):
            continue
        end = date.fromisoformat(str(m.get("endDate") or "2026-12-31")[:10])
        d = parse_date(phrase, end.year)
        if d is not None and not re.search(r"20\d\d", phrase) and d > date.fromordinal(end.toordinal() + 7):
            d = parse_date(phrase, end.year - 1)    # amendment 1: an end date just past midnight UTC on Jan 1 is still the old year
        if d is not None:
            groups.setdefault(templ, []).append((d, m))
    out = []
    for templ, rungs in groups.items():
        rungs.sort(key=lambda x: (x[0], x[1]["id"]))
        if len({d for d, _ in rungs}) != len(rungs) or len(rungs) < 2:
            continue                    # two markets on one date: not a clean ladder
        ids = [m["id"] for _, m in rungs]
        out.append({"kind": "date", "event": event, "template": templ, "legs": ids, "keys": [d.isoformat() for d, _ in rungs],
                    "pairs": [[ids[i], ids[i + 1]] for i in range(len(ids) - 1)]})       # [rich (earlier), cheap (later)]
    return out


def strike_ladders(event: str, markets: list[dict]) -> list[dict]:
    groups: dict[tuple[str, int], list[tuple[float, dict]]] = {}
    for m in markets:
        templ, val, orient = strike_template(m["question"])
        if val is None or orient == 0 or val != val:
            continue
        groups.setdefault((templ, orient), []).append((val, m))
    out = []
    for (templ, orient), rungs in groups.items():
        rungs.sort(key=lambda x: x[0])
        if len({v for v, _ in rungs}) != len(rungs) or len(rungs) < 2:
            continue
        ids = [m["id"] for _, m in rungs]
        # orientation +1: P falls as the level rises, so the higher level is the rich leg; -1 the mirror
        pairs = [[ids[i + 1], ids[i]] if orient > 0 else [ids[i], ids[i + 1]] for i in range(len(ids) - 1)]
        out.append({"kind": "strike", "event": event, "template": templ, "orient": orient, "legs": ids,
                    "keys": [v for v, _ in rungs], "pairs": pairs})
    return out


def negrisk_set(event: str, markets: list[dict], neg_risk: bool) -> list[dict]:
    if not neg_risk or not (2 <= len(markets) <= cfg.NEGRISK_MAX_MEMBERS):
        return []
    return [{"kind": "negrisk", "event": event, "legs": [m["id"] for m in markets], "pairs": []}]


# ---------------------------------------------------------------- catalogue

def strip(m: dict) -> dict:
    out = {k: m.get(k) for k in KEEP}
    out["id"] = str(out["id"])
    toks = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else []
    out["token"], out["no_token"] = (toks + [None, None])[:2]
    fs = m.get("feeSchedule") or {}
    fee_on = bool(m.get("feesEnabled")) and bool(fs)
    out["fee_rate"] = float(fs.get("rate", 0.0)) if fee_on else 0.0
    out["fee_exponent"] = float(fs.get("exponent", 1)) if fee_on else 1.0
    out.pop("feeSchedule", None)
    out.pop("clobTokenIds", None)
    assert not PRICE_FIELDS & set(out)
    return out


def event_bundles(e: dict) -> tuple[list[dict], dict]:
    ms = [strip(m) for m in e.get("markets") or [] if m.get("clobTokenIds")]
    neg = bool(e.get("negRisk") or e.get("enableNegRisk"))
    slug = e.get("slug") or str(e["id"])
    big = [m for m in ms if float(m.get("volume") or 0) >= cfg.MIN_MARKET_VOLUME]
    out = date_ladders(slug, big) + strike_ladders(slug, big)
    if not out:                          # a ladder is never also a one-of-many set
        out += negrisk_set(slug, [m for m in ms if m.get("enableOrderBook") is not False], neg)
    for b in out:
        b["negRiskAugmented"] = bool(e.get("negRiskAugmented"))
        b["event_title"] = e.get("title")
        b["event_volume"] = float(e.get("volume") or 0)
    return out, {m["id"]: m for m in ms}


def s9_strike_bundles() -> tuple[list[dict], dict]:
    """S9's strike ladders, with S9's own level sign; one ladder per event and sign. 'settle at' ranges are left out."""
    u = json.loads((RESEARCH / "s9_weekend_price_markets" / "universe.json").read_text())
    by: dict[str, list[dict]] = {}
    for m in u["markets"]:
        if m["sign"] != 0:
            by.setdefault(m["event"], []).append(m)
    out, meta = [], {}

    def level(m):
        hit = re.search(r"[\d][\d,]*(?:\.\d+)?", (m["label"] or "") + " " + m["question"])
        return float(hit.group(0).replace(",", "")) if hit else None

    for ev, ms in by.items():
        for sign in (1, -1):
            rungs = sorted(((level(m), m) for m in ms if m["sign"] == sign and level(m) is not None), key=lambda x: x[0])
            if len(rungs) < 2 or len({v for v, _ in rungs}) != len(rungs):
                continue
            ids = [m["id"] for _, m in rungs]
            pairs = [[ids[i + 1], ids[i]] if sign > 0 else [ids[i], ids[i + 1]] for i in range(len(ids) - 1)]
            out.append({"kind": "strike", "event": ev, "event_title": ms[0]["event_title"], "orient": sign, "legs": ids,
                        "keys": [v for v, _ in rungs], "pairs": pairs, "source": "s9", "weekend_only": True})
        for m in ms:
            meta[m["id"]] = {"id": m["id"], "question": m["question"], "token": m["token"], "conditionId": m["condition"],
                             "startDate": m["start"], "endDate": m["end_date"], "closedTime": m.get("closed_time"), "closed": m["closed"],
                             "volume": m["volume"], "fee_rate": m["fee_rate"], "fee_exponent": m["fee_exponent"],
                             "asset_class": m["asset_class"], "outcome": m.get("outcome")}
    return out, meta


def s5_slugs() -> list[str]:
    c = json.loads((RESEARCH / "s5_big_moves" / "candidates.json").read_text())
    u = json.loads((RESEARCH / "s5_big_moves" / "universe.json").read_text())
    return sorted({m["event"] for m in c} | {m["event"] for m in u["markets"]})


def main() -> int:
    pt = ds.Throttle(cfg.PULL_RATE)
    # history: S9's strike ladders, and S5's events re-read whole from the catalogue
    bundles, meta = s9_strike_bundles()
    s9n = len(bundles)
    for b in bundles:
        b.setdefault("source", "s9")
    n_ev = 0
    for slug in s5_slugs():
        d = ds.get_json(f"{ds.GAMMA}/events", {"slug": slug}, throttle=pt, allow=(400, 404))
        if not isinstance(d, list) or not d:
            continue
        n_ev += 1
        bs, mm = event_bundles(d[0])
        for b in bs:
            b["source"], b["weekend_only"] = "s5", False
            for i in b["legs"]:
                meta.setdefault(i, mm[i])
        bundles += bs
    s5_legs = {i for b in bundles if b["source"] == "s5" for i in b["legs"]}
    dropped = [b for b in bundles if b["source"] == "s9" and set(b["legs"]) & s5_legs]
    bundles = [b for b in bundles if not (b["source"] == "s9" and set(b["legs"]) & s5_legs)]   # the full-week version wins
    hist = {"built_utc": datetime.now(timezone.utc).isoformat(), "s5_events_read": n_ev, "s9_ladders_superseded": len(dropped), "bundles": bundles,
            "markets": {i: meta[i] for b in bundles for i in b["legs"]}}
    (HERE / "bundles.json").write_text(json.dumps(hist, indent=1))

    # live: events open tonight, by 24-hour volume, plus S9's still-open price events
    live, lmeta, seen = [], {}, set()
    for page in range(cfg.LIVE_SEARCH_PAGES):
        d = ds.get_json(f"{ds.GAMMA}/events", {"closed": "false", "active": "true", "order": "volume24hr", "ascending": "false",
                                               "limit": 100, "offset": page * 100}, throttle=pt, allow=(400, 422))
        for e in d if isinstance(d, list) else []:
            if str(e["id"]) in seen or float(e.get("volume") or 0) < cfg.LIVE_MIN_EVENT_VOLUME:
                continue
            seen.add(str(e["id"]))
            e = dict(e, markets=[m for m in e.get("markets") or [] if not m.get("closed") and m.get("acceptingOrders") is not False])
            bs, mm = event_bundles(e)
            for b in bs:
                for i in b["legs"]:
                    lmeta[i] = mm[i]
            live += bs
    (HERE / "live_bundles.json").write_text(json.dumps({"built_utc": datetime.now(timezone.utc).isoformat(), "events_read": len(seen),
                                                       "bundles": live, "markets": lmeta}, indent=1))
    for name, bs in (("history", bundles), ("live", live)):
        k = {}
        for b in bs:
            x = k.setdefault(b["kind"], [0, 0, 0])
            x[0] += 1
            x[1] += len(b["legs"])
            x[2] += len(b["pairs"])
        print(name, {kk: f"{v[0]} bundles, {v[1]} legs, {v[2]} pairs" for kk, v in k.items()})
    print(f"S9 strike ladders {s9n}; S5 events read {n_ev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
