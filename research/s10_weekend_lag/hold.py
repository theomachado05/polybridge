"""S10 Part 4: hold Part 2's stale-side entries to the question's result (METHOD.md amendment 3).

Run from `research/` after `python -m s10_weekend_lag.mechanism`:  python -m s10_weekend_lag.hold
"""
from __future__ import annotations

import json
import math
import sys
import time

import pandas as pd

from s1_twin_spread import data as ds
from s6_monday_fade.run import write_csv

from . import config as cfg
from .mechanism import book
from .run import CACHE, RESULTS, boot_mean, trade

R = RESULTS / "hold"


def yes_result(m: dict) -> float | None:
    """1.0 or 0.0 if the catalogue shows the market resolved; None otherwise."""
    try:
        outs, prices = json.loads(m.get("outcomes") or "[]"), json.loads(m.get("outcomePrices") or "[]")
    except (TypeError, ValueError):
        return None
    if not m.get("closed") or "Yes" not in outs or len(prices) != len(outs):
        return None
    p = float(prices[outs.index("Yes")])
    return p if p in (0.0, 1.0) else None


def results(ids: list[str]) -> dict[str, float | None]:
    f = CACHE / "results.json"
    known = json.loads(f.read_text()) if f.exists() else {}
    pt = ds.Throttle(0.4)                     # shares Polymarket's limit with the Part 3 pull
    for mid in ids:
        if mid in known:
            continue
        try:
            d = ds.get_json(f"{ds.GAMMA}/markets/{mid.split(':')[1]}", throttle=pt, allow=(404,))
            known[mid] = yes_result(d) if isinstance(d, dict) else None
        except Exception:  # noqa: BLE001
            known[mid] = None
        f.write_text(json.dumps(known))
    return known


def main() -> int:
    t0 = time.time()
    R.mkdir(parents=True, exist_ok=True)
    src = pd.read_csv(RESULTS.parent.parent / cfg.HOLD_SOURCE)
    e = src[(src.kind == "B") & (src.cost_mult == 1.0)].copy()
    res = results(sorted(e.stale_market.unique()))
    e["result"] = e.stale_market.map(res)
    unresolved = e[e.result.isna()]
    e = e[e.result.notna()]
    trades = []
    for r in e.itertuples():
        buy = r.side == "buy YES"
        for c in cfg.COST_MULTIPLIERS:
            entry, gross, pnl = trade(buy, r.p_entry, r.result, True, cfg.EVENT_HALF_SPREAD, cfg.EVENT_FEE_RATE, 1.0, c)
            trades.append({"date": r.date, "t": r.t, "question_id": r.stale_market, "question": r.question, "side": r.side, "p_entry": r.p_entry,
                           "entry": entry, "result": r.result, "cost_mult": c, "gross_points": 100 * gross, "cost_points": 100 * (gross - pnl),
                           "net_points": 100 * pnl, "pnl": cfg.CONTRACTS * pnl, "capital": cfg.CONTRACTS * (entry if buy else 1 - entry),
                           "checkable": bool(r.checkable), "verified": bool(r.verified), "net_points_30m": r.net_points})
    dates = sorted({t["date"] for t in trades})
    oos_from = dates[len(dates) - int(math.ceil(cfg.OOS_FRACTION * len(dates)))]
    for t in trades:
        t["segment"] = "OOS" if t["date"] >= oos_from else "IS"
    span = pd.date_range(dates[0], dates[-1]).strftime("%Y-%m-%d").tolist()
    metrics = book(trades, "date", 365.0, span, oos_from, "hold to result")
    for row in metrics:                       # intervals resampling questions (all entries on one question share a result)
        seg = {"IS": ("IS",), "OOS": ("OOS",), "ALL": ("IS", "OOS")}[row["segment"]]
        st = [t for t in trades if t["cost_mult"] == row["cost_mult"] and t["segment"] in seg]
        by_q: dict[str, list] = {}
        for t in st:
            by_q.setdefault(t["question_id"], []).append(t)
        b = boot_mean({k: [x["net_points"] for x in v] for k, v in by_q.items()})
        g = boot_mean({k: [x["gross_points"] for x in v] for k, v in by_q.items()})
        bv = boot_mean({k: [x["net_points"] for x in v if x["verified"]] for k, v in by_q.items()})
        row.update({"questions": len(by_q), "q_ci_lo": b[1], "q_ci_hi": b[2], "q_gross_ci_lo": g[1], "q_gross_ci_hi": g[2],
                    "q_ci_lo_verified": bv[1], "q_ci_hi_verified": bv[2]})
    write_csv(R / "trades.csv", trades)
    write_csv(R / "metrics.csv", metrics)
    meta = {"entries": int(len(src[(src.kind == "B") & (src.cost_mult == 1.0)])), "entries_with_result": int(len(e)),
            "entries_unresolved": int(len(unresolved)), "questions": int(e.stale_market.nunique()),
            "questions_unresolved": int(unresolved.stale_market.nunique()), "oos_from": oos_from, "seconds": round(time.time() - t0, 1)}
    (R / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for x in metrics:
        print(f"{x['segment']:3} {x['cost_mult']:.0f}x trades {x['trades']:5d} q {x['questions']:3d} net {x['mean_net_points']:6.2f} "
              f"[q {x['q_ci_lo']:6.2f},{x['q_ci_hi']:6.2f}] [d {x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] gross {x['mean_gross_points']:6.2f} "
              f"[q {x['q_gross_ci_lo']:6.2f},{x['q_gross_ci_hi']:6.2f}] cost {x['mean_cost_points']:5.2f} ver {x['verified_trades']} "
              f"ver_net {x['mean_net_points_verified']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
