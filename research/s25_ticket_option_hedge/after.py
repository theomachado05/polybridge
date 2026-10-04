"""S25, looked at AFTER the run (METHOD.md, amendment 2). Not pre-registered, not tests: each was run once and is reported
whatever it shows. Reads `trades.csv`; writes `after_run.csv`. No network.

Run from `research/`:  python -m s25_ticket_option_hedge.after
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from s7_weekend_straddle.run import boot_diff, boot_mean, write_csv

from . import config as cfg
from . import engine as eg
from .run import RESULTS, by_event, subset

FRESH_S = 60.0          # L1: a Monday leg quote older than this at 09:35 is an opening quote that was never refreshed


def line(look: str, set_: str, what: str, t: pd.DataFrame, col: str, base: str = "ticket_pnl_points") -> dict:
    m = boot_mean(by_event(t, col))
    r = eg.boot_sd_ratio(t[col], t[base], t.event) if len(t) > 1 else (float("nan"),) * 3
    return {"look": look, "set": set_, "what": what, "markets": len(t), "events": int(t.event.nunique()), "mean_pnl_points": m[0], "ci_lo": m[1], "ci_hi": m[2],
            **eg.risk_stats(t[col]), "sd_unhedged": float(np.std(t[base], ddof=1)) if len(t) > 1 else float("nan"), "sd_ratio": r[0], "sd_ratio_lo": r[1],
            "sd_ratio_hi": r[2]}


def main() -> int:
    tr = pd.read_csv(RESULTS / "trades.csv", dtype={"market": str, "event": str})
    ok = tr[tr.status == "ok"].copy()
    out = []

    # L1: the primary and variant A on fresh Monday quotes only
    age = np.maximum(ok.mon_lo_age_s, ok.mon_hi_age_s)
    fresh = ok[age <= FRESH_S].copy()
    for s in ("rule", "full", "left"):
        t = subset(fresh, s)
        out.append(line("L1 fresh quotes", s, "unhedged", t, "ticket_pnl_points"))
        out.append(line("L1 fresh quotes", s, "hedged, primary", t, "hedged_pnl_points_P"))
        out.append(line("L1 fresh quotes", s, "hedged, variant A", t, "hedged_pnl_points_A"))
    ru, le = subset(fresh, "rule"), subset(fresh, "left")
    d = boot_diff(by_event(ru, "hedged_pnl_points_P"), by_event(le, "hedged_pnl_points_P"))
    out.append({"look": "L1 fresh quotes", "set": "rule minus left", "what": "hedged, primary", "markets": len(ru), "events": int(fresh.event.nunique()),
                "mean_pnl_points": d[0], "ci_lo": d[1], "ci_hi": d[2]})
    out.append({"look": "L1 fresh quotes", "set": "full", "what": "markets left out (a leg quote older than 60 s)", "markets": int(len(ok) - len(fresh)),
                "events": int(ok[age > FRESH_S].event.nunique()), "mean_pnl_points": float(ok[age > FRESH_S].hedged_pnl_points_P.mean())})
    out.append({"look": "L1 fresh quotes", "set": "rule", "what": "markets left out (a leg quote older than 60 s)", "markets": int((ok.rule & (age > FRESH_S)).sum()),
                "events": int(ok[ok.rule & (age > FRESH_S)].event.nunique()), "mean_pnl_points": float(ok[ok.rule & (age > FRESH_S)].hedged_pnl_points_P.mean())})

    # L2: the same two spreads at Monday's mid quotes plus commission, on the fresh quotes (not executable)
    comm = 2.0 * cfg.OPTION_COMMISSION_PER_CONTRACT / (cfg.SHARES_PER_CONTRACT * fresh.width)
    fresh["hedged_mid"] = fresh.ticket_pnl_points + 100.0 * cfg.HEDGE_RATIO_PRIMARY * (fresh.payoff_unit - (fresh.unit_mid_P.clip(lower=0.0) + comm))
    fresh["cross_points"] = fresh.hedge_cost_points_P - 100.0 * cfg.HEDGE_RATIO_PRIMARY * (fresh.unit_mid_P.clip(lower=0.0) + comm)
    for s in ("rule", "full", "left"):
        t = subset(fresh, s)
        row = line("L2 at Monday mids", s, "hedged at mid quotes, 2 spreads (not executable)", t, "hedged_mid")
        row["mean_hedge_pnl_at_mid_points"] = float((t.hedged_mid - t.ticket_pnl_points).mean())
        row["mean_hedge_pnl_paid_points"] = float(t.hedge_pnl_points_P.mean())
        row["mean_crossing_cost_points"] = float(t.cross_points.mean())
        row["median_crossing_cost_points"] = float(t.cross_points.median())
        out.append(row)

    # L3: the hedge ratio that would have minimised the SD of P&L per market, found after the fact
    for s in ("rule", "full"):
        t = subset(ok, s).copy()
        T, H = t.ticket_pnl_points.to_numpy(), 100.0 * (t.payoff_unit - t.unit_cost_P).to_numpy()
        c = np.cov(T, H, ddof=1)
        h = float(-c[0, 1] / c[1, 1])
        t["best"] = T + h * H
        row = line("L3 SD-minimising ratio (after the fact)", s, f"hedged at h = {h:.2f} spreads per ticket", t, "best")
        row.update({"h": h, "correlation_ticket_vs_one_spread": float(np.corrcoef(T, H)[0, 1])})
        out.append(row)
    write_csv(RESULTS / "after_run.csv", out)
    for r in out:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
