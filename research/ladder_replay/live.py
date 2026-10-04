"""Live check (METHOD step 4): every open date ladder's real books, once. Run from `research/`: python -m ladder_replay.live"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds
from s11_bundles import engine as en
from s11_bundles import live as s11live
from s11_bundles import universe as s11u

from . import config as cfg
from . import replay as rp

OUT = Path(__file__).resolve().parent.parent / "results" / "ladder_replay"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pt = ds.Throttle(cfg.REQ_RATE)
    bundles, meta, n_ev, cur = [], {}, 0, None
    while True:
        p = {"closed": "false", "active": "true", "volume_min": 100000, "limit": cfg.GAMMA_PAGE}
        if cur:
            p["after_cursor"] = cur
        d = ds.get_json(f"{ds.GAMMA}/events/keyset", p, throttle=pt)
        for e in d.get("events") or []:
            n_ev += 1
            raw = {str(m["id"]): m for m in e.get("markets") or []}
            e = dict(e, markets=[m for m in e.get("markets") or [] if not m.get("closed") and m.get("acceptingOrders") is not False])
            bs, mm = s11u.event_bundles(e)
            for b in bs:
                if b["kind"] != "date":
                    continue
                bundles.append(b)
                for i in b["legs"]:
                    meta[i] = dict(mm[i], description=raw[i].get("description"), resolutionSource=raw[i].get("resolutionSource"),
                                   _event_resolutionSource=e.get("resolutionSource") or "", startDate=raw[i].get("startDate"))
        cur = d.get("next_cursor")
        if not cur or not d.get("events"):
            break
    tokens = sorted({meta[i]["token"] for b in bundles for i in b["legs"] if meta[i].get("token")})
    t0 = datetime.now(timezone.utc).isoformat()
    books = s11live.fetch_books(tokens, pt)
    rows = []
    for b in bundles:
        for rich, cheap in b["pairs"]:
            ma, mb = meta[rich], meta[cheap]
            ok, why = rp.nested("date", b, rich, cheap, meta)
            bids, asks = s11live.levels(books.get(ma["token"]), "bids"), s11live.levels(books.get(mb["token"]), "asks")
            r = en.pair_arb(bids, asks, (ma["fee_rate"], ma["fee_exponent"]), (mb["fee_rate"], mb["fee_exponent"]))
            rows.append({"event": b.get("event_title"), "rich": ma["question"], "cheap": mb["question"], "nested": ok, "reason": why,
                         "bid_rich": bids[0][0] if bids else None, "ask_cheap": asks[0][0] if asks else None,
                         "edge_top": r["edge"], "contracts": r["size"], "locked_usd": r["locked"], "has_books": bool(bids and asks)})
    with (OUT / "live_pairs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    viol = [r for r in rows if r["contracts"] > 0]
    tot = {"snapshot_utc": t0, "events_read": n_ev, "date_ladders": len(bundles), "pairs": len(rows),
           "pairs_with_books": sum(r["has_books"] for r in rows), "nested_pairs": sum(r["nested"] for r in rows),
           "violations_net_of_fees": len(viol), "violations_nested": sum(r["nested"] for r in viol),
           "locked_usd": sum(r["locked_usd"] for r in viol), "locked_usd_nested": sum(r["locked_usd"] for r in viol if r["nested"]),
           "median_gap_points_to_arb": sorted(-100 * r["edge_top"] for r in rows if r["has_books"])[sum(r["has_books"] for r in rows) // 2]
           if any(r["has_books"] for r in rows) else None}
    (OUT / "live_totals.json").write_text(json.dumps(tot, indent=1))
    print(json.dumps(tot, indent=1))
    for r in viol:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
