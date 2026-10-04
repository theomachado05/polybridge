"""S9 universe: Polymarket price markets on assets that are shut over the weekend, from catalogue metadata only.
No price is read. Writes `universe.json`, committed with METHOD.md.

Run from `research/`:  python -m s9_weekend_price_markets.universe
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent


def asset_class(title: str) -> str | None:
    for name, pat in cfg.ASSET_CLASSES:
        if re.search(pat, title, re.I):
            return name
    return None


def strike_sign(question: str, label: str) -> int:
    """+1 if YES needs a higher price (a HIGH or ↑ target), -1 for a LOW or ↓ target, 0 for a range or unsigned market."""
    text = f"{question} {label}"
    if "(HIGH)" in text or "↑" in text:
        return 1
    if "(LOW)" in text or "↓" in text:
        return -1
    return 0


def wanted(title: str) -> bool:
    return bool(re.search(cfg.KIND_RE, title, re.I)) and not re.search(cfg.EXCLUDE_RE, title, re.I) and asset_class(title) is not None


def add_outcomes() -> int:
    """Amendment 1: each market's result (1, 0 or None while open) and closing time, from the catalogue. The list is unchanged."""
    f = HERE / "universe.json"
    u, pt, n = json.loads(f.read_text()), ds.Throttle(4.0), 0
    for m in u["markets"]:
        g = ds.get_json(f"{ds.GAMMA}/markets/{m['id']}", throttle=pt)
        prices = json.loads(g["outcomePrices"]) if g.get("outcomePrices") else []
        yes = float(prices[0]) if prices else float("nan")
        m["outcome"] = yes if g.get("closed") and yes in (0.0, 1.0) else None
        m["closed_time"] = g.get("closedTime")
        n += m["outcome"] is not None
    u["outcomes_added_utc"] = datetime.now(timezone.utc).isoformat()
    f.write_text(json.dumps(u, indent=1))
    print(f"{len(u['markets'])} markets, {n} with a result; YES {sum(1 for m in u['markets'] if m['outcome'] == 1.0)}")
    return 0


def main() -> int:
    if "--outcomes" in sys.argv:
        return add_outcomes()
    pt, seen = ds.Throttle(3.0), {}
    for q in cfg.SEARCHES:
        for page in range(1, cfg.SEARCH_PAGES + 1):
            d = ds.get_json(f"{ds.GAMMA}/public-search", {"q": q, "limit_per_type": 50, "page": page, "keep_closed_markets": 1,
                                                          "events_status": "all"}, throttle=pt, allow=(400, 404, 422))
            evs = (d or {}).get("events") or [] if isinstance(d, dict) else []
            if not evs:
                break
            for e in evs:
                seen[str(e["id"])] = e
    events, markets, counts = [], [], {"events_seen": len(seen), "events_matching": 0, "events_kept": 0, "markets_in_kept_events": 0, "markets_kept": 0}
    for e in sorted(seen.values(), key=lambda e: -float(e.get("volume") or 0)):
        if not wanted(e["title"]):
            continue
        counts["events_matching"] += 1
        if float(e.get("volume") or 0) < cfg.MIN_EVENT_VOLUME:
            continue
        counts["events_kept"] += 1
        cls, kept = asset_class(e["title"]), 0
        for m in e.get("markets") or []:
            counts["markets_in_kept_events"] += 1
            tokens = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else []
            if float(m.get("volume") or 0) < cfg.MIN_MARKET_VOLUME or not tokens or not m.get("startDate"):
                continue
            fs = m.get("feeSchedule") or {}
            fee_on = bool(m.get("feesEnabled")) and bool(fs)
            markets.append({"id": str(m["id"]), "event": str(e["id"]), "event_title": e["title"], "asset_class": cls, "question": m["question"],
                            "label": m.get("groupItemTitle") or "", "sign": strike_sign(m["question"], m.get("groupItemTitle") or ""),
                            "volume": float(m.get("volume") or 0), "start": m["startDate"], "end": m.get("closedTime") or m.get("endDate"),
                            "end_date": m.get("endDate"), "closed": bool(m.get("closed")), "token": tokens[0], "condition": m.get("conditionId"),
                            "fee_rate": float(fs.get("rate", 0.0)) if fee_on else 0.0, "fee_exponent": float(fs.get("exponent", 1)) if fee_on else 1.0})
            kept += 1
        events.append({"id": str(e["id"]), "title": e["title"], "asset_class": cls, "volume": float(e.get("volume") or 0),
                       "start": e.get("startDate"), "end": e.get("endDate"), "markets": len(e.get("markets") or []), "markets_kept": kept})
    counts["markets_kept"] = len(markets)
    (HERE / "universe.json").write_text(json.dumps({"built_utc": datetime.now(timezone.utc).isoformat(), "counts": counts, "events": events,
                                                    "markets": markets}, indent=1))
    print(json.dumps(counts))
    by: dict[str, list[int]] = {}
    for m in markets:
        b = by.setdefault(m["asset_class"], [0, 0, 0, 0, 0])
        b[0] += 1
        b[1] += m["sign"] > 0
        b[2] += m["sign"] < 0
        b[3] += m["sign"] == 0
        b[4] += m["fee_rate"] > 0
    for k, (n, up, dn, zero, fee) in by.items():
        print(f"{k:7} markets {n:4d} | high {up:3d} low {dn:3d} unsigned {zero:3d} | with a fee {fee:3d}")
    for e in events:
        print(f"{e['volume']:14,.0f} {str(e['start'])[:10]} {str(e['end'])[:10]} {e['asset_class']:7} kept {e['markets_kept']:3d} of {e['markets']:3d}  {e['title'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
