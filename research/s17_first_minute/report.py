"""S17 report: metrics.csv, tests.csv, trades.csv, events.csv, criterion.csv, exploratory.csv, charts, capacity.md."""
from __future__ import annotations

import json
import math
import subprocess
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s6_monday_fade.run import closure_metrics  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS, boot  # noqa: E402

SAMPLE_START, SAMPLE_END = "2025-10-01", "2026-10-02"


def book(t: pd.DataFrame, sess_days: list[str]) -> tuple[np.ndarray, list[str]]:
    """Daily return (mean of that day's trades, as a fraction) over every session of the window; zero without a trade."""
    r = (t.groupby("day").net_bp.mean() / 1e4).reindex(sess_days, fill_value=0.0)
    return r.to_numpy(), sess_days


def trade_metrics(tr: pd.DataFrame, sess: pd.DataFrame) -> pd.DataFrame:
    days = [d for d in sess.day if SAMPLE_START <= d <= SAMPLE_END]
    seg_days = {"IS": [d for d in days if d < cfg.OOS_FROM], "OOS": [d for d in days if d >= cfg.OOS_FROM], "ALL": days}
    rows = []
    for (tid, thr, cm), g in tr.groupby(["trade", "threshold", "cost_mult"], sort=False):
        for seg, sd in seg_days.items():
            s = g if seg == "ALL" else g[g.segment == seg]
            net, gross = boot(list(s.day), s.net_bp), boot(list(s.day), s.gross_bp)
            r, _ = book(s, sd)
            m = closure_metrics(r, sd, 1.0, float(s.day.nunique()), cfg.DAYS_PER_YEAR)
            rows.append({"trade": tid, "primary": tid == "T1" and thr == cfg.MAIN_THRESHOLD, "threshold": thr, "cost_mult": cm,
                         "segment": seg, "trades": len(s), "dates": s.day.nunique(), "net_bp": net[0], "net_lo": net[1], "net_hi": net[2],
                         "gross_bp": gross[0], "gross_lo": gross[1], "gross_hi": gross[2], "cost_bp": float(s.cost_bp.mean()) if len(s) else np.nan,
                         "median_spread_in_bp": float(s.spread_in_bp.median()) if len(s) else np.nan,
                         "winners": float((s.net_bp > 0).mean()) if len(s) else np.nan, "pnl_usd": float(s.pnl.sum()),
                         "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"], "worst_month": m["worst_month"],
                         "total_return": m["total_return"], "turnover_ann": 2.0 * s.day.nunique() / max(len(sd) / cfg.DAYS_PER_YEAR, 1e-9)})
    return pd.DataFrame(rows)


def criterion(met: pd.DataFrame) -> list[dict]:
    out = []
    for tid in [t.id for t in cfg.TRADES]:
        g = met[(met.trade == tid) & (met.threshold == cfg.MAIN_THRESHOLD)]
        if g.empty:
            out.append({"trade": tid, "criterion": "VERDICT", "pass": False, "evidence": "no trades"})
            continue
        o1 = g[(g.segment == "OOS") & (g.cost_mult == 1.0)].iloc[0]
        o2 = g[(g.segment == "OOS") & (g.cost_mult == 2.0)].iloc[0]
        i1 = g[(g.segment == "IS") & (g.cost_mult == 1.0)].iloc[0]
        lines = [("at least 30 OOS trades", o1.trades >= cfg.MIN_OOS_TRADES, f"{int(o1.trades)} on {int(o1.dates)} dates"),
                 ("OOS net > 0, interval excludes 0 (1x)", bool(o1.net_lo > 0), f"{o1.net_bp:+.1f} bp [{o1.net_lo:+.1f}, {o1.net_hi:+.1f}]"),
                 ("OOS net > 0 at 2x", bool(o2.net_bp > 0), f"{o2.net_bp:+.1f} bp"),
                 ("IS net > 0 (1x)", bool(i1.net_bp > 0), f"{i1.net_bp:+.1f} bp [{i1.net_lo:+.1f}, {i1.net_hi:+.1f}]")]
        for n, ok, ev in lines:
            out.append({"trade": tid, "criterion": n, "pass": bool(ok), "evidence": ev})
        out.append({"trade": tid, "criterion": "VERDICT", "pass": all(x[1] for x in lines), "evidence": ""})
    return out


def exploratory(ev: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    e = ev[ev.threshold == cfg.MAIN_THRESHOLD]
    t = tr[(tr.trade == "T1") & (tr.threshold == cfg.MAIN_THRESHOLD) & (tr.cost_mult == 1.0)]
    rows = []
    for label, sel_e, sel_t in [("theme: oil", e.theme == "oil", t.theme == "oil"), ("theme: rates", e.theme == "rates", t.theme == "rates"),
                                ("theme: other", e.theme == "other", t.theme == "other"),
                                ("after a weekend or holiday", e.weekend, t.weekend), ("ordinary night", ~e.weekend, ~t.weekend)]:
        s, u = e[sel_e], t[sel_t]
        f1, gp, t1 = boot(list(s.day), s["0931_close"]), boot(list(s.day), s["gap"]), boot(list(u.day), u.net_bp)
        rows.append({"cut": label, "events": len(s), "dates": s.day.nunique(), "gap_bp": gp[0], "gap_lo": gp[1], "gap_hi": gp[2],
                     "after_0931_bp": f1[0], "after_lo": f1[1], "after_hi": f1[2], "T1_trades": len(u), "T1_net_bp": t1[0], "T1_lo": t1[1], "T1_hi": t1[2]})
    return pd.DataFrame(rows)


def charts(tr: pd.DataFrame, sess: pd.DataFrame) -> None:
    days = [d for d in sess.day if SAMPLE_START <= d <= SAMPLE_END]
    x = pd.to_datetime(pd.Series(days))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    fig2, ax2 = plt.subplots(figsize=(9, 3.5))
    for tid, cm, style in (("T1", 1.0, "-"), ("T1", 2.0, "--"), ("T2", 1.0, ":"), ("T3", 1.0, "-.")):
        t = tr[(tr.trade == tid) & (tr.threshold == cfg.MAIN_THRESHOLD) & (tr.cost_mult == cm)]
        if t.empty:
            continue
        r, _ = book(t, days)
        eq = 100 * np.cumsum(r)
        lab = f"{tid} {cm:g}x"
        ax.plot(x, eq, style, label=lab)
        ax2.plot(x, eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:], style, label=lab)
    for a in (ax, ax2):
        a.axvline(pd.Timestamp(cfg.OOS_FROM), color="grey", lw=0.8)
        a.axhline(0, color="black", lw=0.5)
        a.legend()
    ax.set_title("Follow the overnight odds move from the 09:31 quote (10+ points): cumulative return, %")
    ax2.set_title("Drawdown from the running peak, % points")
    fig.tight_layout()
    fig.savefig(RESULTS / "equity_curve.png", dpi=130)
    fig2.tight_layout()
    fig2.savefig(RESULTS / "drawdown.png", dpi=130)
    plt.close("all")


def capacity(tr: pd.DataFrame) -> str:
    t = tr[(tr.trade == "T1") & (tr.threshold == cfg.MAIN_THRESHOLD) & (tr.cost_mult == 1.0)]
    lines = ["# S17 capacity", "", "Size displayed at the touch (the side the trade takes) in the 09:31 quote, T1 at 10+ points.", "",
             "| Theme | Trades | Median $ at the touch | 10th percentile | Median spread, bp |", "|---|---|---|---|---|"]
    for th, g in [("all", t), *t.groupby("theme")]:
        lines.append(f"| {th} | {len(g)} | ${g.touch_size_usd.median():,.0f} | ${g.touch_size_usd.quantile(0.1):,.0f} | {g.spread_in_bp.median():.1f} |")
    lines += ["", "The displayed touch is a floor on what one order can take at the quoted price; deeper levels are not seen here. "
              "$10,000 per trade is below the median touch on most themes."]
    return "\n".join(lines) + "\n"


def report(ev: pd.DataFrame, stats: pd.DataFrame, tr: pd.DataFrame, sess: pd.DataFrame, meta: dict, c, t_run: float) -> None:
    stats.to_csv(RESULTS / "tests.csv", index=False, float_format="%.6g")
    keep = [k for k in ev.columns if not k.startswith("q_") or k.endswith(("_ok", "_bid", "_ask"))]
    ev[keep].to_csv(RESULTS / "events.csv", index=False, float_format="%.6g")
    tr.to_csv(RESULTS / "trades.csv", index=False, float_format="%.6g")
    met = trade_metrics(tr, sess) if len(tr) else pd.DataFrame()
    met.to_csv(RESULTS / "metrics.csv", index=False, float_format="%.6g")
    crit = pd.DataFrame(criterion(met)) if len(met) else pd.DataFrame()
    crit.to_csv(RESULTS / "criterion.csv", index=False)
    exp = exploratory(ev, tr)
    exp.to_csv(RESULTS / "exploratory.csv", index=False, float_format="%.6g")
    e10 = ev[(ev.threshold == cfg.MAIN_THRESHOLD) & (ev.day >= "2026-07-01")].sort_values(["absx", "day", "ticker"], ascending=[False, True, True]).head(12)
    e10[["day", "ticker", "question", "x", "d", "gap", "open_0931", "0931_0935", "0935_1000", "1000_close"]].to_csv(
        RESULTS / "largest_recent.csv", index=False, float_format="%.4g")
    if len(tr):
        charts(tr, sess)
        (RESULTS / "capacity.md").write_text(capacity(tr))
    head = subprocess.run(["git", "log", "-1", "--format=%h %cI", "--", "research/s17_first_minute"], capture_output=True, text=True,
                          cwd=RESULTS.parents[2]).stdout.strip()
    meta.update({"run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - t_run, 1), "code_commit": head,
                 "massive_calls_this_run": c.calls,
                 "events": {f"{t:g}": int((ev.threshold == t).sum()) for t in cfg.THRESHOLDS},
                 "valid_entry_quotes": {f"{t:g}": int(ev[(ev.threshold == t)].get(f"q_{cfg.ENTRY}_ok", pd.Series(dtype=bool)).fillna(False).sum())
                                        for t in cfg.THRESHOLDS}})
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    pd.set_option("display.width", 250)
    print(stats.round(2).to_string(index=False))
    if len(met):
        print(met[["trade", "threshold", "cost_mult", "segment", "trades", "dates", "net_bp", "net_lo", "net_hi", "gross_bp", "cost_bp", "sharpe"]].round(2).to_string(index=False))
        print(crit.to_string(index=False))
    print(exp.round(1).to_string(index=False))
    print(json.dumps(meta, default=str))
