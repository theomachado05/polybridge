"""S23, looked at AFTER the run (not pre-registered; never changes a verdict). Checks on the T2 book, which passed its line:
an interval for its Sharpe, the plain t-statistic of its closure returns, duplicated print records, how late the prints
were, and how concentrated the profit is. Writes after_run.json.

    .venv/bin/python -m s23_monday_fade_real.after
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from . import config as cfg
from . import run as s23


def sharpe(r: np.ndarray) -> float:
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(cfg.CLOSURES_PER_YEAR)) if sd > 0 else float("nan")


def sharpe_interval(pnl_by_closure: dict[str, float], calendar: list[str]) -> dict:
    """Resample the calendar's closures (idle ones included) and recompute the Sharpe. The capital base cancels."""
    r = np.array([pnl_by_closure.get(d, 0.0) for d in calendar])
    pick = np.random.default_rng(cfg.BOOT_SEED).integers(0, len(r), size=(cfg.N_BOOT, len(r)))
    x = r[pick]
    sd = x.std(axis=1, ddof=1)
    ok = sd > 0
    s = x.mean(axis=1)[ok] / sd[ok] * math.sqrt(cfg.CLOSURES_PER_YEAR)
    lo, hi = np.percentile(s, [2.5, 97.5])
    return {"sharpe": sharpe(r), "lo": float(lo), "hi": float(hi), "share_of_draws_at_or_below_zero": float((s <= 0).mean()),
            "t_stat_closure_returns": float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))), "closures": int(len(r)),
            "closures_traded": int((r != 0).sum())}


def main() -> int:
    calendar = sorted(pd.read_csv(cfg.EVENTS, usecols=["open_day"]).open_day.dropna().unique())
    t = pd.read_csv(cfg.RESULTS / "trades.csv", low_memory=False)
    out = {}
    for label, mode in (("T2", "best"), ("T2b first print", "first")):
        b = t[(t.test == "T2") & (t["mode"] == mode) & (t.cost_mult == 1.0) & (t.status == "trade")]
        by = b.groupby("closure").pnl.sum().to_dict()
        best = max(by, key=by.get)
        out[label] = {"sharpe_all": sharpe_interval(by, calendar),
                      "sharpe_best_closure_removed": sharpe_interval({k: v for k, v in by.items() if k != best}, [d for d in calendar if d != best])}
    b = t[(t.test == "T2") & (t["mode"] == "best") & (t.cost_mult == 1.0) & (t.status == "trade")]
    b = b.assign(s6_verified=b.s6_verified.astype(str).str.lower() == "true")
    by = b.groupby("closure").pnl.sum().sort_values(ascending=False)
    out["concentration"] = {"total": float(by.sum()), "best_closure": by.index[0], "best_closure_pnl": float(by.iloc[0]),
                            "best_closure_share": float(by.iloc[0] / by.sum()), "top_two_closures_share": float(by.iloc[:2].sum() / by.sum()),
                            "closures_up": int((by > 0).sum()), "closures_down": int((by < 0).sum()),
                            "largest_single_trade_pnl": float(b.pnl.max()), "trades_at_the_100_cap": int((b.contracts >= 100).sum()),
                            "trades_under_20_contracts": int((b.contracts < 20).sum())}
    late = b.print_minutes > 15
    out["print_timing"] = {"within_15_min": {"trades": int((~late).sum()), "pnl": float(b[~late].pnl.sum())},
                           "from_15_to_30_min": {"trades": int(late.sum()), "pnl": float(b[late].pnl.sum())},
                           "median_print_minutes": float(b.print_minutes.median())}
    out["overlap_with_s6_verified"] = {"t2_trades_that_s6_verified": int(b.s6_verified.sum()), "t2_trades_s6_did_not_verify": int((~b.s6_verified).sum()),
                                       "pnl_s6_verified": float(b[b.s6_verified].pnl.sum()), "pnl_not_s6_verified": float(b[~b.s6_verified].pnl.sum())}

    # duplicated print records: the same hash, side, token, price and size listed twice. Count each once and replay.
    s6 = s23.load_s6()
    tot, n, dup_markets = 0.0, 0, 0
    for r in s6.itertuples():
        ps = json.loads((cfg.S6_PRINTS / f"prints_{int(r.market_id)}.json").read_text())
        seen, uniq = set(), []
        for p in ps:
            key = (p.get("transactionHash"), p.get("side"), p.get("outcome"), p.get("price"), p.get("size"), p.get("timestamp"))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        dup_markets += int(len(uniq) < len(ps))
        x = s23.replay(s23.yes_prints(uniq, s23.snapshot_epoch(r.closure)), r.side, float(r.opt_lo), float(r.opt_hi))
        if x["status"] == "trade":
            k = min(x["print_size"], cfg.T2_MAX_CONTRACTS)
            tot, n = tot + k * s23.pnl_per_contract(r.side, x["entry"], float(r.outcome)), n + 1
    out["duplicate_records_counted_once"] = {"entries_whose_market_has_duplicates": dup_markets, "trades": n, "total": tot}

    # an independent replay of T2 that shares no function with run.py: straight from the raw records
    tot, n = 0.0, 0
    for r in s6.itertuples():
        ps = json.loads((cfg.S6_PRINTS / f"prints_{int(r.market_id)}.json").read_text())
        t0 = pd.Timestamp(r.closure + " 09:45", tz="America/New_York").timestamp()
        best, size = None, 0.0
        for q in ps:
            if not (t0 <= q["timestamp"] <= t0 + 1800):
                continue
            yes = q["outcome"].lower() == "yes"
            px, bought_yes = (q["price"] if yes else 1 - q["price"]), ((q["side"] == "BUY") == yes)
            if (r.side == "buy YES") != bought_yes:
                continue
            better = best is None or (px < best - 1e-9 if r.side == "buy YES" else px > best + 1e-9)
            if better:
                best, size = px, q["size"]
            elif abs(px - best) < 1e-9:
                size += q["size"]
        if best is None:
            continue
        e = best + 0.01 if r.side == "buy YES" else best - 0.01
        f = 0.04 * e * (1 - e)
        if ((r.opt_lo - e - f) if r.side == "buy YES" else (e - f - r.opt_hi)) < 0.02 - 1e-12:
            continue
        tot, n = tot + min(size, 100) * ((r.outcome - e - f) if r.side == "buy YES" else (e - f - r.outcome)), n + 1
    out["independent_replay"] = {"trades": n, "total": tot}
    (cfg.RESULTS / "after_run.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
