"""S6 report: SUMMARY.md, equity_curve.png, drawdown.png and capacity.md from the result CSVs.

Run from `research/`:  python -m s6_monday_fade.report
"""
from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def money(x: float) -> str:
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.2f}"


def num(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def md_table(df: pd.DataFrame, cols: dict) -> str:
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[k]) for k in cols) + " |")
    return "\n".join(out)


def charts(eq: pd.DataFrame, K: float, oos_from: str) -> None:
    e = eq[(eq.variant == cfg.PRIMARY) & (eq.cost_mult == 1.0)].sort_values("closure")
    x = pd.to_datetime(e.closure)
    series = (("pnl", "All modelled entries", BLUE), ("pnl_verified", "Print-verified entries only, at the printed size", ORANGE))
    for name, title, dd in (("equity_curve.png", "cumulative net P&L", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for col, label, color in series:
            y = e[col].to_numpy() / K * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{label.split(' entries')[0].lower()} {y.min():.1f}%")
            ax.plot(x, y, color=color, linewidth=2, label=label, solid_capstyle="round")
            if not dd:
                ax.plot([x.iloc[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
                ax.annotate(f"{y[-1]:+.0f}%", (x.iloc[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(oos_from)
        ax.axvline(split, color=INK2, linewidth=1)
        ax.annotate("out-of-sample starts ▸", (split, 0.0 if dd else 1.0), xycoords=("data", "axes fraction"), xytext=(-5, 5 if dd else -4),
                    textcoords="offset points", va="bottom" if dd else "top", ha="right", fontsize=8.5, color=INK2)
        if deepest:
            ax.annotate("Deepest: " + ", ".join(deepest), (0.0, 0.0), xycoords="axes fraction", xytext=(12, 30), textcoords="offset points",
                        ha="left", va="bottom", fontsize=8.5, color=INK)
        ax.grid(True, axis="y", color=GRID, linewidth=1)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.margins(x=0.08)
        ax.set_ylabel(f"% of the ${K:,.0f} capital base", fontsize=9, color=INK2)
        ax.set_title(f"S6, primary variant, 1× costs: {title} by closure", loc="left", fontsize=11, color=INK)
        ax.legend(loc="upper left" if not dd else "lower left", bbox_to_anchor=(0.0, 0.9) if not dd else (0.0, 0.14), frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m, tr, eq = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "trades.csv"), pd.read_csv(R / "equity.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    hs = meta["half_spread"]

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    a1, a2, i1, o1, o2 = row("ALL", cfg.PRIMARY, 1.0), row("ALL", cfg.PRIMARY, 2.0), row("IS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 2.0)
    charts(eq, float(a1.capital_base), meta["oos_from"])
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} OOS trades on at least {cfg.MIN_OOS_CLOSURES} OOS closures",
         o1.trades >= cfg.MIN_OOS_TRADES and o1.closures_traded >= cfg.MIN_OOS_CLOSURES, f"{int(o1.trades)} trades, {int(o1.closures_traded)} closures"),
        ("OOS mean net P&L per trade above zero, closure-bootstrap interval excluding zero (1× costs)", o1.mean_pnl_per_trade > 0 and o1.ci_lo > 0,
         f"{money(o1.mean_pnl_per_trade)} [{num(o1.ci_lo)}, {num(o1.ci_hi)}]"),
        ("OOS above zero at 2× costs", o2.mean_pnl_per_trade > 0, f"{money(o2.mean_pnl_per_trade)} on {int(o2.trades)} trades"),
        ("In-sample above zero", i1.mean_pnl_per_trade > 0, f"{money(i1.mean_pnl_per_trade)} on {int(i1.trades)} trades"),
        ("At least half of OOS entries print-verified, and those above zero", o1.verified_share >= cfg.MIN_VERIFIED_SHARE and o1.pnl_verified > 0,
         f"{int(o1.verified_trades)} of {int(o1.trades)} verified"),
    ]
    few = not bool(crit[0][1])
    verdict = "pass" if all(bool(c[1]) for c in crit) else ("too few observations" if few else "not a pass")
    p = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)]
    ver, unv = p[p.verified], p[~p.verified]
    near_half = int(((p.pm_0945 >= 0.45) & (p.pm_0945 <= 0.55)).sum())
    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == cfg.PRIMARY, " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"),
                  T=m.trades.astype(int), CL=m.closures_traded.astype(int), P=m.pnl.map(money), N=m.mean_pnl_per_trade.map(money),
                  CI=m.apply(lambda r: f"[{num(r.ci_lo)}, {num(r.ci_hi)}]", axis=1), H=m.hit_rate.map(lambda x: "n/a" if x != x else f"{100 * x:.0f}%"),
                  SH=m.sharpe.map(num), DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(lambda x: "n/a" if x != x else f"{100 * x:.1f}%"),
                  WM=m.worst_month.map(lambda x: "n/a" if x != x else f"{100 * x:.1f}%"), TO=m.turnover_ann.map(lambda x: "n/a" if x != x else f"{x:.1f}×"),
                  VE=m.verified_trades.astype(int).astype(str) + " of " + m.trades.astype(int).astype(str),
                  VP=m.mean_pnl_per_verified_trade.map(money), VCI=m.apply(lambda r: f"[{num(r.ci_lo_verified)}, {num(r.ci_hi_verified)}]", axis=1))
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "CL": "Closures", "P": "Net P&L", "N": "Per trade", "CI": "95% interval",
             "H": "Winners", "SH": "Sharpe", "DS": "Deflated Sharpe prob.", "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr",
             "VE": "Print-verified", "VP": "Per verified trade", "VCI": "95% interval "}
    vtab = ver.assign(D=ver.closure, Q=ver.question.str.slice(0, 62), S=ver.side, PM=ver.pm_0945.map(lambda x: num(x, 3)),
                      O=ver.apply(lambda r: f"{r.opt_lo:.2f} to {r.opt_hi:.2f}", axis=1), E=ver.entry.map(lambda x: num(x, 3)),
                      R=ver.outcome.map(lambda x: "YES" if x == 1 else "NO"), P=ver.pnl.map(money), Z=ver.verify_size.map(lambda x: f"{x:,.0f}"))

    S = ["# S6: on Monday morning, bet with the options against the prediction market", "",
         "Method, pre-registered before any P&L of this trade was computed: [`research/s6_monday_fade/METHOD.md`](../../s6_monday_fade/METHOD.md) "
         "(commit `7ef1a8d`). Data: R3's `research/results/open_options/events.csv` "
         f"({meta['event_rows']:,} events, {meta['closures']} closures from {meta['first_closure']} to {meta['last_closure']}). "
         "Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**Verdict on the pre-registered criterion: {verdict}.** Out-of-sample ({meta['oos_closures']} closures from {meta['oos_from']}) has "
         f"{int(o1.trades)} trades on {int(o1.closures_traded)} closures, against the {cfg.MIN_OOS_TRADES} the criterion needs.", "",
         f"**What the confirmed trades show.** Over the whole year, {len(ver)} of the {len(p)} entries have a public Polymarket trade print at the "
         f"price the trade needs. {int((ver.pnl > 0).sum())} of the {len(ver)} won. At the printed size they average "
         f"{money(a1.mean_pnl_per_verified_trade)} per trade of up to 100 contracts (closure-bootstrap 95% interval {num(a1.ci_lo_verified)} to "
         f"{num(a1.ci_hi_verified)}): positive, and not distinguishable from zero.", "",
         f"**The modelled backtest is not evidence.** All {len(p)} entries: {money(a1.mean_pnl_per_trade)} per trade "
         f"[{num(a1.ci_lo)}, {num(a1.ci_hi)}], {100 * a1.hit_rate:.0f}% winners, Sharpe {num(a1.sharpe)}. The {len(unv)} entries with no print "
         f"carry {money(unv.pnl.sum())} of the {money(p.pnl.sum())}. {near_half} of the {len(p)} entries have a Polymarket \"price\" between 0.45 "
         "and 0.55, the midpoint of an empty or very wide book. It is the S1 artifact again.", "",
         "## Headline numbers (primary V0: gap of 2 points beyond the options' band after costs, held to resolution)", "",
         md_table(vt[m.variant == cfg.PRIMARY], vcols), "",
         f"100 contracts per trade. Capital base ${a1.capital_base:,.0f}, the largest amount deployed on one closure. Sharpe on closure returns, "
         f"{meta['closures_per_year']:.0f} closures a year.", "",
         "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {verdict}.**", "",
          "## The print-verified entries (primary, 1× costs)", "",
          md_table(vtab, {"D": "Reopening day", "Q": "Question", "S": "Trade", "PM": "Polymarket at 09:45", "O": "Options' band", "E": "Entry",
                          "R": "Result", "P": "P&L, 100 contracts", "Z": "Printed shares"}), "",
          "A print confirms that the price traded within ten minutes of 09:45. Four of these entries are on one morning "
          "(2026-03-09), which is why the interval is wide.", "",
          "## Costs", "",
          f"- **Polymarket half-spread: {100 * hs['h']:.1f} points**, measured on this weekend's recorded books of {hs['markets']} threshold markets "
          f"(quartiles {100 * hs['h_p25']:.1f} to {100 * hs['h_p75']:.1f}). Historical books are not published.",
          "- **Polymarket fee:** 0.04 × P × (1 − P) per contract, the market's own schedule.",
          f"- **In bp of the capital locked:** {a1.cost_bp_of_capital:,.0f} bp per trade at 1×, {a2.cost_bp_of_capital:,.0f} bp at 2×. No option is traded, "
          "so there is no option cost.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md). Short version: about $2 at the best price on a weekend.", "",
          "## Every variant tried", "", md_table(vt, vcols), "",
          "V2 (every pair with valid measurements) is identical to V0: R3's file keeps full measurements only for its events, so there were no "
          "extra rows to add. The deflated Sharpe probability uses 4 trials.", "",
          "## Sharpe above 3: the bug hunt", "",
          "| Check | Outcome |", "|---|---|",
          "| The signal uses only 09:45 prices | Yes: `pm_0945` and the options' band at 09:45. Tests pin the rule. |",
          "| The result is never an input | Yes: `outcome` enters only the P&L. |",
          "| Costs on every trade | Yes: half-spread and fee on entry, and again on the end-of-day exit variant. |",
          f"| **Polymarket prices that are not prices** | **This is the cause.** {len(unv)} of {len(p)} entries have no print at the assumed price, and {near_half} sit near 0.50. R3 removed prices of exactly 0.500 at the close and the open; near-0.50 midpoints at 09:45 remain. |", "",
          "## What didn't work", "",
          f"- **Too few out-of-sample trades** ({int(o1.trades)}) for any verdict.",
          f"- **Only {100 * a1.verified_share:.0f}% of entries are print-verified**, and the verified ones are not significant.",
          f"- **Closing at the end of the reopening day (V3)** earns {money(row('ALL', 'V3', 1.0).mean_pnl_per_trade)} per trade at 1× costs and "
          f"{money(row('ALL', 'V3', 2.0).mean_pnl_per_trade)} at 2×: the second spread eats it.", "",
          "## Caveats", "",
          "- Unhedged: a closure's trades win or lose together when the stock moves through its strikes.",
          "- The half-spread is measured on one weekend, not on the mornings traded.",
          "- One year, 45 closures.", "",
          "## Reproduce", "", "```", "cd research", "python -m s6_monday_fade.run", "python -m s6_monday_fade.report",
          "python -m pytest s6_monday_fade/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    cap = ["# S6 capacity", "",
           f"- **This weekend's recorded books** ({hs['markets']} Polymarket threshold markets, Sat 2026-10-03 evening): median "
           f"**${hs['touch_dollars_median']:.2f}** at the best price, half-spread {100 * hs['h']:.1f} points.",
           f"- **Printed sizes behind the verified entries:** median {ver.verify_size.median():,.0f} shares, smallest {ver.verify_size.min():,.0f}, "
           f"largest {ver.verify_size.max():,.0f}. Counted at the printed size and capped at 100: {a1.verified_contracts:,.0f} contracts over the year.",
           "- These markets cannot absorb more than a few hundred dollars per trade. Whatever edge exists here is a retail-size edge.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
