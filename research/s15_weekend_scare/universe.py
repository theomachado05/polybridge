"""S15 universe: the Polymarket price markets S9 did NOT use, from catalogue metadata only. No price is read.
Writes `universe.json`, committed with METHOD.md.

Run from `research/`:  python -m s15_weekend_scare.universe
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds
from s9_weekend_price_markets import config as c9
from s9_weekend_price_markets.universe import strike_sign

from . import config as cfg

HERE = Path(__file__).resolve().parent
S9_UNIVERSE = HERE.parent / "s9_weekend_price_markets" / "universe.json"


def asset_class(title: str) -> str | None:
    for name, pat in cfg.ASSET_CLASSES:
        if re.search(pat, title, re.I):
            return name
    return None


def wanted(title: str) -> bool:
    return bool(re.search(c9.KIND_RE, title, re.I)) and not re.search(c9.EXCLUDE_RE, title, re.I) and asset_class(title) is not None


def kind(title: str, in_s9_event: bool) -> str:
    if in_s9_event:
        return "leftover of an S9 event"
    return "weekly" if "week of" in title.lower() else "other event"


def main() -> int:
    s9 = json.loads(S9_UNIVERSE.read_text())
    s9_markets, s9_events = {m["id"] for m in s9["markets"]}, {e["id"] for e in s9["events"]}
    pt, seen = ds.Throttle(3.0), {}
    for q in c9.SEARCHES:
        for page in range(1, c9.SEARCH_PAGES + 1):
            d = ds.get_json(f"{ds.GAMMA}/public-search", {"q": q, "limit_per_type": 50, "page": page, "keep_closed_markets": 1,
                                                          "events_status": "all"}, throttle=pt, allow=(400, 404, 422))
            evs = (d or {}).get("events") or [] if isinstance(d, dict) else []
            if not evs:
                break
            for e in evs:
                seen[str(e["id"])] = e
    markets, counts = [], {"events_seen": len(seen), "events_matching": 0, "events_kept": 0, "markets_kept": 0, "s9_markets_excluded": 0}
    for e in sorted(seen.values(), key=lambda e: -float(e.get("volume") or 0)):
        if not wanted(e["title"]):
            continue
        counts["events_matching"] += 1
        inside = str(e["id"]) in s9_events
        if not inside and float(e.get("volume") or 0) < cfg.MIN_EVENT_VOLUME:
            continue
        cls, kept = asset_class(e["title"]), 0
        for m in e.get("markets") or []:
            if str(m["id"]) in s9_markets:
                counts["s9_markets_excluded"] += 1
                continue
            tokens = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else []
            if float(m.get("volume") or 0) < cfg.MIN_MARKET_VOLUME or not tokens or not m.get("startDate"):
                continue
            fs = m.get("feeSchedule") or {}
            fee_on = bool(m.get("feesEnabled")) and bool(fs)
            prices = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else []
            yes = float(prices[0]) if prices else float("nan")
            markets.append({"id": str(m["id"]), "event": str(e["id"]), "event_title": e["title"], "asset_class": cls,
                            "kind": kind(e["title"], inside), "question": m["question"], "label": m.get("groupItemTitle") or "",
                            "sign": strike_sign(m["question"], m.get("groupItemTitle") or ""), "volume": float(m.get("volume") or 0),
                            "start": m["startDate"], "end": m.get("closedTime") or m.get("endDate"), "closed_time": m.get("closedTime"),
                            "outcome": yes if m.get("closed") and yes in (0.0, 1.0) else None, "token": tokens[0],
                            "condition": m.get("conditionId"), "fee_rate": float(fs.get("rate", 0.0)) if fee_on else 0.0,
                            "fee_exponent": float(fs.get("exponent", 1)) if fee_on else 1.0})
            kept += 1
        counts["events_kept"] += kept > 0
    counts["markets_kept"] = len(markets)
    (HERE / "universe.json").write_text(json.dumps({"built_utc": datetime.now(timezone.utc).isoformat(), "counts": counts, "markets": markets}, indent=1))
    print(json.dumps(counts))
    by: dict[tuple[str, str], int] = {}
    for m in markets:
        by[(m["asset_class"], m["kind"])] = by.get((m["asset_class"], m["kind"]), 0) + 1
    for k, n in sorted(by.items()):
        print(f"{k[0]:7} {k[1]:24} {n:4d}")
    print("with a result:", sum(m["outcome"] is not None for m in markets), "| signs:", {s: sum(m["sign"] == s for m in markets) for s in (1, -1, 0)},
          "| with a fee:", sum(m["fee_rate"] > 0 for m in markets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
