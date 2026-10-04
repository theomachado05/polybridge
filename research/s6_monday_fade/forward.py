from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from s1_twin_spread.engine import kalshi_fee

from .run import RAW, RESEARCH, RESULTS, fee

ARB = RESEARCH / "results" / "arb" / "arb_gaps.csv"
UTC = timezone.utc
START = datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC)
END = datetime(2026, 10, 4, 11, 0, 0, tzinfo=UTC)
END_FINAL = datetime(2026, 10, 4, 13, 30, 0, tzinfo=UTC)
THETA, MIN_SIZE, MAX_SIZE, ADJACENT_S = 0.02, 5.0, 500.0, 45.0


def unit_fee(venue: str, price: float) -> float:
    return fee(price) if venue == "pm" else float(kalshi_fee(price, 1e6, 1.0))


def fill(levels: list, band_edge: float, side: str, venue: str) -> dict:
    q = cash = gap = fees = 0.0
    for price, size in levels:
        f = unit_fee(venue, price)
        edge = (price - f - band_edge) if side == "sell YES" else (band_edge - price - f)
        if edge < THETA or q >= MAX_SIZE - 1e-9:
            break
        take = min(size, MAX_SIZE - q)
        q, cash, gap, fees = q + take, cash + take * price, gap + take * edge, fees + take * f
    return {"qty": q, "avg_price": cash / q if q else float("nan"), "gap_dollars": gap, "fees": fees,
            "capital": cash if side == "buy YES" else q - cash}


def signal(book: dict, lo: float, hi: float, venue: str) -> tuple[str, dict] | None:
    for side, levels, edge in (("sell YES", book["b"], hi), ("buy YES", book["a"], lo)):
        f = fill(levels, edge, side, venue)
        if f["qty"] >= MIN_SIZE:
            return side, f
    return None


def main() -> int:
    end = END_FINAL if "--final" in sys.argv else END
    tag = "forward_final" if "--final" in sys.argv else "forward"
    arb = pd.read_csv(ARB, low_memory=False)
    live = arb[(arb.live == True) & (arb.clean == True) & arb.p_lo.notna() & arb.p_hi.notna()]  # noqa: E712
    band_by_market = {str(r.market_id): (float(r.p_lo), float(r.p_hi), r.underlying, float(r.strike), r.res_date, r.venue) for r in live.itertuples()}
    uni = json.loads(sorted(RAW.glob("universe_*.json"))[-1].read_text())
    key = {m["token"]: str(m["id"]) for m in uni["pm"]} | {m["ticker"]: m["ticker"] for m in uni["kalshi"]}
    books: dict[str, list[dict]] = {}
    s, e = START.timestamp(), end.timestamp()
    for f in sorted(RAW.glob("*.jsonl.gz")):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if "err" in r or not (s <= r["t"] < e) or key.get(r["id"]) not in band_by_market:
                        continue
                    books.setdefault(r["id"], []).append(r)
        except (EOFError, OSError):
            continue
    fills, moves = [], []
    for rid, rows in books.items():
        lo, hi, und, strike, res, venue_name = band_by_market[key[rid]]
        venue = rows[0]["v"]
        rows.sort(key=lambda r: r["t"])
        two = [r for r in rows if r["b"] and r["a"]]
        if two:
            mids = np.array([(r["b"][0][0] + r["a"][0][0]) / 2 for r in two])
            moves.append({"venue": venue_name, "underlying": und, "strike": strike, "res_date": res, "snapshots": len(rows),
                          "two_sided_share": len(two) / len(rows), "mid_first": float(mids[0]), "mid_last": float(mids[-1]),
                          "mid_change": float(mids[-1] - mids[0]), "mid_range": float(mids.max() - mids.min()),
                          "spread_median": float(np.median([r["a"][0][0] - r["b"][0][0] for r in two])),
                          "touch_dollars_median": float(np.median([min(r["b"][0][1] * r["b"][0][0], r["a"][0][1] * (1 - r["a"][0][0])) for r in two])),
                          "options_lo_friday": lo, "options_hi_friday": hi,
                          "outside_band_share": float(np.mean([(r["b"][0][0] > hi) or (r["a"][0][0] < lo) for r in two]))})
        prev, done = None, False
        for r in rows:
            sg = signal(r, lo, hi, venue)
            if not done and sg and prev and prev[1] and prev[1][0] == sg[0] and 0 < r["t"] - prev[0] <= ADJACENT_S:
                side, f = sg
                if venue == "k":
                    f["fees"] = float(np.ceil(f["fees"] * 100 - 1e-9) / 100)
                fills.append({"venue": venue_name, "underlying": und, "strike": strike, "res_date": res, "utc": datetime.fromtimestamp(r["t"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "side": side, "options_lo_friday": lo, "options_hi_friday": hi, **f})
                done = True
            prev = (r["t"], sg)
    RESULTS.mkdir(parents=True, exist_ok=True)

    def write(name, recs):
        keys: list[str] = []
        for rec in recs:
            for k in rec:
                if k not in keys:
                    keys.append(k)
        with open(RESULTS / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(recs)

    write(f"fills_{tag}.csv", fills)
    write(f"books_{tag}.csv", moves)
    mv = pd.DataFrame(moves)
    out = {"window": [START.isoformat(), end.isoformat()], "markets_with_a_band_and_a_book": len(books), "fills": len(fills),
           "contracts": float(sum(f["qty"] for f in fills)), "capital": float(sum(f["capital"] for f in fills)),
           "gap_dollars": float(sum(f["gap_dollars"] for f in fills)), "by_venue": {}}
    for v, d in mv.groupby("venue") if len(mv) else []:
        fv = [f for f in fills if f["venue"] == v]
        out["by_venue"][v] = {"markets": int(len(d)), "fills": len(fv), "contracts": float(sum(f["qty"] for f in fv)), "capital": float(sum(f["capital"] for f in fv)),
                              "gap_dollars": float(sum(f["gap_dollars"] for f in fv)), "spread_median_points": float(100 * d.spread_median.median()),
                              "touch_dollars_median": float(d.touch_dollars_median.median()), "moved_3_points_share": float((d.mid_change.abs() >= 0.03).mean()),
                              "mid_change_abs_median_points": float(100 * d.mid_change.abs().median()), "mid_range_median_points": float(100 * d.mid_range.median()),
                              "quote_outside_friday_band_share": float(d.outside_band_share.mean())}
    (RESULTS / f"{tag}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    for f in fills[:30]:
        print(f"  {f['utc']} {f['venue']:10} {f['underlying']:5} >{f['strike']:<8} {f['side']:8} {f['qty']:6.0f} @ {f['avg_price']:.3f} band {f['options_lo_friday']:.2f}-{f['options_hi_friday']:.2f} gap ${f['gap_dollars']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
