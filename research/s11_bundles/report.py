from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as cfg  # noqa: E402
from .pull import CACHE  # noqa: E402
from .run import RESULTS, boot, perf  # noqa: E402


def fmt(x, d=2):
    return "n/a" if x is None or x != x else f"{x:+.{d}f}"


def main() -> int:
    S = pd.read_pickle(CACHE / "run_state.pkl")
    V, P, X, T, H = S["V"], S["P"], S["X"], S["T"], S["H"]
    lines, metrics = [], []

    lines.append("## Violation episodes in the history (mids moved by half-spreads and fees)\n")
    lines.append("| Kind | Costs | Episodes | Weekend | Weekday | Per 1,000 hours, weekend | Per 1,000 hours, weekday | Median gap, points | Median minutes beyond costs | Median minutes to gap close |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for k in ("strike", "date", "negrisk"):
        x = X[X.kind == k] if len(X) else X
        hw, hd = (float(x.hours_weekend.sum()), float(x.hours_weekday.sum())) if len(x) else (0, 0)
        for c in cfg.COST_MULTIPLIERS:
            v = V[(V.kind == k) & (V.cost_mult == c)] if len(V) else V
            nw, nd = int(v.weekend.sum()) if len(v) else 0, int((~v.weekend.astype(bool)).sum()) if len(v) else 0
            lines.append(f"| {k} | {c:g}× | {len(v)} | {nw} | {nd} | {1000 * nw / hw if hw else float('nan'):.2f} | {1000 * nd / hd if hd else float('nan'):.2f} | "
                         f"{v.gap_points.median() if len(v) else float('nan'):.1f} | {v.minutes_beyond_cost.median() if len(v) else float('nan'):.0f} | "
                         f"{v.minutes_to_gap_close.median() if len(v) else float('nan'):.0f} |")
            metrics.append({"part": "a", "row": f"episodes {k}", "cost_mult": c, "n": len(v), "weekend": nw, "weekday": nd,
                            "hours_weekend": hw, "hours_weekday": hd})
    lines.append("")

    def block(study: str, pnl_col: str, label: str):
        out = []
        for c in cfg.COST_MULTIPLIERS:
            for seg in ("IS", "OOS", "ALL"):
                t = T[(T.study == study) & (T.cost_mult == c)]
                if seg != "ALL":
                    t = t[t.segment == seg]
                for which, tt in (("all", t), ("print-verified", t[t.prints == "verified"])):
                    if not len(tt):
                        out.append({"study": label, "segment": seg, "cost_mult": c, "entries": which, "trades": 0})
                        continue
                    pc = tt[pnl_col] * 100
                    m, lo, hi, n, nd = boot(tt.assign(_p=pc), "_p")
                    pf = perf(tt.assign(_pnl=tt[pnl_col] * cfg.CONTRACTS, _cap=tt.capital * cfg.CONTRACTS), "_pnl", "_cap")
                    bp = float((tt[pnl_col] / tt.capital).mean() * 1e4)
                    out.append({"study": label, "segment": seg, "cost_mult": c, "entries": which, "trades": n, "dates": nd,
                                "net_points_per_trade": m, "ci_lo": lo, "ci_hi": hi, "net_bp_of_capital": bp,
                                "winners": float((tt[pnl_col] > 0).mean()), "net_pnl_usd": pf.get("net_pnl"),
                                "capital_base_usd": pf.get("capital_base"), "sharpe": pf.get("sharpe"), "max_drawdown": pf.get("max_drawdown"),
                                "worst_month": pf.get("worst_month"), "turnover_per_year": pf.get("turnover_per_year"),
                                "verified": int((t.prints == "verified").sum()), "not_verified": int((t.prints == "not verified").sum()),
                                "uncheckable": int((t.prints == "uncheckable").sum())})
        return out

    rows = (block("violation", "pnl_close", "violation, exit at gap close or result") + block("violation", "pnl_hold", "violation H, hold to result")
            + block("P0", "pnl", "propagation P0") + block("P1", "pnl", "propagation P1 (laggards)"))
    M = pd.DataFrame(rows)
    M.to_csv(RESULTS / "metrics.csv", index=False)
    lines.append("## Trades\n")
    lines.append("| Trade | Segment | Costs | Entries | Trades | Dates | Net, points per trade | 95% interval | Net, bp of capital | Winners | Net P&L | Sharpe | Max DD | Worst month | Turnover / yr | Prints: verified / not / uncheckable |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in M.itertuples():
        if not r.trades:
            lines.append(f"| {r.study} | {r.segment} | {r.cost_mult:g}× | {r.entries} | 0 | | | | | | | | | | | |")
            continue
        lines.append(f"| {r.study} | {r.segment} | {r.cost_mult:g}× | {r.entries} | {r.trades} | {r.dates} | {fmt(r.net_points_per_trade)} | "
                     f"[{fmt(r.ci_lo)}, {fmt(r.ci_hi)}] | {fmt(r.net_bp_of_capital, 0)} | {r.winners:.0%} | ${r.net_pnl_usd:,.0f} | {fmt(r.sharpe)} | "
                     f"{r.max_drawdown:.1%} | {r.worst_month:+.1%} | {r.turnover_per_year:.1f}× | {r.verified} / {r.not_verified} / {r.uncheckable} |")
    lines.append("")

    lines.append("## Propagation: the sibling's move after a 3+ point jump (points, signed: positive = follows the jump)\n")
    lines.append("| Kind | Segment | Jumps | Dates | During the jump's 5 min | Next 5 min | Next 15 min | Next 30 min | Next 60 min (95% interval) | Jumper's own next 60 min |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for k in ("all", "strike", "date"):
        for seg in ("IS", "OOS", "ALL"):
            p = P if k == "all" else P[P.kind == k]
            if seg != "ALL":
                p = p[p.segment == seg]
            if not len(p):
                continue
            m60 = boot(p, "sibling_next_60m")
            r = {c: boot(p, c)[0] for c in ("sibling_during_jump", "sibling_next_5m", "sibling_next_15m", "sibling_next_30m", "jumper_next_60m")}
            lines.append(f"| {k} | {seg} | {len(p)} | {p.date.nunique()} | {fmt(r['sibling_during_jump'])} | {fmt(r['sibling_next_5m'])} | "
                         f"{fmt(r['sibling_next_15m'])} | {fmt(r['sibling_next_30m'])} | {fmt(m60[0])} [{fmt(m60[1])}, {fmt(m60[2])}] | {fmt(r['jumper_next_60m'])} |")
            metrics.append({"part": "b", "row": f"sibling move {k} {seg}", "n": len(p), "dates": p.date.nunique(), "next_60m": m60[0], "lo": m60[1], "hi": m60[2]})
    for wk in (True, False):
        p = P[P.weekend.astype(bool) == wk]
        if len(p):
            m60 = boot(p, "sibling_next_60m")
            lines.append(f"| {'weekend' if wk else 'weekday'} | ALL | {len(p)} | {p.date.nunique()} | {fmt(boot(p, 'sibling_during_jump')[0])} | "
                         f"{fmt(boot(p, 'sibling_next_5m')[0])} | {fmt(boot(p, 'sibling_next_15m')[0])} | {fmt(boot(p, 'sibling_next_30m')[0])} | "
                         f"{fmt(m60[0])} [{fmt(m60[1])}, {fmt(m60[2])}] | {fmt(boot(p, 'jumper_next_60m')[0])} |")
    lines.append("")
    pd.DataFrame(metrics).to_csv(RESULTS / "metrics_tests.csv", index=False)
    (RESULTS / "tables.md").write_text("\n".join(lines))

    fig, ax = plt.subplots(figsize=(9, 4.5))
    fig2, ax2 = plt.subplots(figsize=(9, 3.5))
    for study, col, lab in (("violation", "pnl_close", "violation trade"), ("P0", "pnl", "propagation P0")):
        t = T[(T.study == study) & (T.cost_mult == 1.0)]
        if not len(t):
            continue
        pf = perf(t.assign(_pnl=t[col] * cfg.CONTRACTS, _cap=t.capital * cfg.CONTRACTS), "_pnl", "_cap")
        eq = pf["equity"]
        ax.plot(eq.index, eq / eq.iloc[0], label=f"{lab} (base ${pf['capital_base']:,.0f})")
        ax2.plot(eq.index, -(eq.cummax() - eq) / pf['capital_base'], label=lab)
        t2 = t[t.prints == "verified"]
        if len(t2):
            pf2 = perf(t2.assign(_pnl=t2[col] * cfg.CONTRACTS, _cap=t2.capital * cfg.CONTRACTS), "_pnl", "_cap")
            ax.plot(pf2["equity"].index, pf2["equity"] / pf2["equity"].iloc[0], ls="--", label=f"{lab}, print-verified only")
    for a in (ax, ax2):
        a.axvline(pd.Timestamp(cfg.OOS_START), color="grey", lw=0.8, ls=":")
        a.legend(fontsize=8)
        a.grid(alpha=0.3)
    ax.set_title("S11: equity, 1× costs, 100 contracts a leg (dotted line: out-of-sample starts)")
    ax.set_ylabel("equity / capital base")
    ax2.set_title("Drawdown, as a share of the capital base")
    fig.tight_layout()
    fig2.tight_layout()
    fig.savefig(RESULTS / "equity_curve.png", dpi=120)
    fig2.savefig(RESULTS / "drawdown.png", dpi=120)
    print("\n".join(lines))
    print("H", H, "coverage", S["coverage"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
