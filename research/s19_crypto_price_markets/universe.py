"""S19 universe: Polymarket's crypto price markets ("What price will Bitcoin hit in October?"), weekly and longer,
from catalogue metadata only, and a seeded random draw of markets from each event. No price or print is read.

Run from `research/`:  python -m s19_crypto_price_markets.universe
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent


def horizon(title: str) -> str:
    """daily (left out), monthly or longer, weekly, or another date range."""
    if re.search(rf"\bon ({cfg.MONTHS}) \d", title):
        return "daily"
    if re.search(rf"\bin ({cfg.MONTHS})|\bin 20\d\d|before 20\d\d|by ", title):
        return "monthly or longer"
    if re.search(r"week|\d\s*[-–]\s*\d", title, re.I):
        return "weekly"
    return "other range"


def main() -> int:
    pt, seen = ds.Throttle(2.0), {}
    for q in cfg.SEARCHES:
        for page in range(1, cfg.SEARCH_PAGES + 1):
            d = ds.get_json(f"{ds.GAMMA}/public-search", {"q": q, "limit_per_type": 50, "page": page, "keep_closed_markets": 1,
                                                          "events_status": "all"}, throttle=pt, allow=(400, 404, 422))
            evs = (d or {}).get("events") or [] if isinstance(d, dict) else []
            if not evs:
                break
            for e in evs:
                seen[str(e["id"])] = e
    rng = np.random.default_rng(cfg.SAMPLE_SEED)
    markets, counts = [], {"events_seen": len(seen), "events_matching": 0, "daily_events_left_out": 0, "events_kept": 0, "eligible_markets": 0, "markets_drawn": 0}
    for e in sorted(seen.values(), key=lambda e: (e.get("startDate") or "", str(e["id"]))):
        m_ = re.search(cfg.TITLE_RE, e["title"], re.I)
        if not m_:
            continue
        counts["events_matching"] += 1
        h = horizon(e["title"])
        if h == "daily":
            counts["daily_events_left_out"] += 1
            continue
        elig = []
        for m in sorted(e.get("markets") or [], key=lambda m: str(m["id"])):
            prices = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else []
            yes = float(prices[0]) if prices else float("nan")
            if (m.get("closed") and yes in (0.0, 1.0) and m.get("conditionId") and m.get("startDate") and m.get("closedTime")
                    and float(m.get("volume") or 0) >= cfg.MIN_MARKET_VOLUME):
                elig.append((m, yes))
        counts["eligible_markets"] += len(elig)
        if not elig:
            continue
        counts["events_kept"] += 1
        pick = sorted(rng.choice(len(elig), size=min(cfg.PER_EVENT, len(elig)), replace=False))
        for i in pick:
            m, yes = elig[i]
            fs = m.get("feeSchedule") or {}
            fee_on = bool(m.get("feesEnabled")) and bool(fs)
            markets.append({"id": str(m["id"]), "event": str(e["id"]), "event_title": e["title"], "asset": m_.group(1).lower(), "horizon": h,
                            "question": m["question"], "label": m.get("groupItemTitle") or "", "volume": float(m.get("volume") or 0),
                            "start": m["startDate"], "closed_time": m["closedTime"], "outcome": yes, "condition": m["conditionId"],
                            "fee_rate": float(fs.get("rate", 0.0)) if fee_on else 0.0, "fee_exponent": float(fs.get("exponent", 1)) if fee_on else 1.0})
    counts["markets_drawn"] = len(markets)
    (HERE / "universe.json").write_text(json.dumps({"built_utc": datetime.now(timezone.utc).isoformat(), "counts": counts, "markets": markets}, indent=1))
    print(json.dumps(counts))
    for key in ("asset", "horizon"):
        by: dict[str, int] = {}
        for m in markets:
            by[m[key]] = by.get(m[key], 0) + 1
        print(key, by)
    print("events", len({m["event"] for m in markets}), "| first", min(m["start"] for m in markets)[:10], "last", max(m["start"] for m in markets)[:10],
          "| with a fee", sum(m["fee_rate"] > 0 for m in markets), "| resolved YES (not looked at as a share of price)", sum(m["outcome"] == 1.0 for m in markets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
