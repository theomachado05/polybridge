"""S16 report: SUMMARY.md, equity_curve.png, drawdown.png and capacity.md from the result CSVs.

Run from `research/`:  python -m s16_kalshi_quotes.report
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

from s8_open_referee.report import ci, md_table, num, pct, pts  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#1baf7a"


def charts(eq: pd.DataFrame, K: float, oos_from: str) -> None:
    e1 = eq[(eq.variant == cfg.PRIMARY) & (eq.cost_mult == 1.0)].sort_values("day")
    e2 = eq[(eq.variant == cfg.PRIMARY) & (eq.cost_mult == 2.0)].sort_values("day")
    x = pd.to_datetime(e1.day)
    series = (("At mid prices, no costs", GREEN, e1.gross.to_numpy()), ("At the real bid and ask, with fees", BLUE, e1.pnl.to_numpy()),
              ("Doubled costs", ORANGE, e2.pnl.to_numpy()))
    for name, title, dd in (("equity_curve.png", "cumulative P&L", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for label, color, cum in series:
            y = cum / K * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{label.lower()} {y.min():.0f}%")
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
        ax.axhline(0, color=GRID, linewidth=1)
        ax.grid(True, axis="y", color=GRID, linewidth=1)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.margins(x=0.08)
        ax.set_ylabel(f"% of the ${K:,.0f} capital base", fontsize=9, color=INK2)
        ax.set_title(f"S16, primary variant on Kalshi: {title} by session", loc="left", fontsize=11, color=INK)
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.14 if dd else 0.02), frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m, tr, tt, eq = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "trades.csv"), pd.read_csv(R / "tests.csv"), pd.read_csv(R / "equity.csv")
    meta = json.loads((R / "run_meta.json").read_text())

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    def t(prefix, thr, age="6h"):
        return tt[tt.test.str.startswith(prefix) & (tt.threshold == thr) & (tt.quote_age == age)].iloc[0]

    a1, a2, i1, o1, o2 = row("ALL", "V0", 1.0), row("ALL", "V0", 2.0), row("IS", "V0", 1.0), row("OOS", "V0", 1.0), row("OOS", "V0", 2.0)
    charts(eq, float(a1.capital_base), meta["oos_from"])
    k1_5, k1_10 = t("K1", 5.0), t("K1", 10.0)
    k2p, k2k, k2d = t("K2 the same nights, Polymarket", 10.0), t("K2 the same nights, Kalshi", 10.0), t("K2 Polymarket minus", 10.0)
    k3p, k3k, k3d = t("K3 nights picked on Polymarket's move: Polymarket", 10.0), t("K3 nights picked on Polymarket's move: Kalshi", 10.0), t("K3 Polymarket minus", 10.0)
    k2d5, k3d5 = t("K2 Polymarket minus", 5.0), t("K3 Polymarket minus", 5.0)
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} OOS trades on at least {cfg.MIN_OOS_DATES} OOS dates",
         o1.trades >= cfg.MIN_OOS_TRADES and o1.dates_traded >= cfg.MIN_OOS_DATES, f"{int(o1.trades)} trades on {int(o1.dates_traded)} dates"),
        ("OOS mean net P&L per trade above zero, date-bootstrap interval excluding zero (1× costs)", o1.mean_net_points > 0 and o1.ci_lo > 0,
         f"{pts(o1.mean_net_points)} points {ci(o1.ci_lo, o1.ci_hi)}"),
        ("OOS above zero at 2× costs", o2.mean_net_points > 0, f"{pts(o2.mean_net_points)} points"),
        ("In-sample above zero", i1.mean_net_points > 0, f"{pts(i1.mean_net_points)} points {ci(i1.ci_lo, i1.ci_hi)} on {int(i1.trades)} trades"),
    ]
    verdict = "pass" if all(bool(c[1]) for c in crit) else ("too few observations" if not crit[0][1] else "not a pass")
    ttab = md_table(tt.assign(T=tt.test, A=tt.quote_age.map({"6h": "6 hours", "15m": "15 minutes"}), H=tt.threshold.map(lambda x: f"{x:.0f}+ points"),
                              N=tt.n.astype(int), D=tt.dates.astype(int), K=tt.markets.astype(int), M=tt["mean"].map(pts),
                              CI=tt.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1)),
                    {"T": "Test", "A": "Kalshi quote age allowed", "H": "Overnight move", "N": "Market-sessions", "D": "Dates", "K": "Markets",
                     "M": "Change from 09:40 to the close, signed by the move", "CI": "95% interval"})
    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == "V0", " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"), T=m.trades.astype(int),
                  D=m.dates_traded.astype(int), N=m.mean_net_points.map(pts), CI=m.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1),
                  G=m.mean_gross_points.map(pts), SP=m.mean_spread_cost_points.map(num), FE=m.mean_fee_cost_points.map(num),
                  H=m.hit_rate.map(lambda x: pct(x, 0)), P=m.pnl.map(lambda x: "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.0f}"),
                  SH=m.sharpe.map(num), DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(pct), WM=m.worst_month.map(pct),
                  TO=m.turnover_ann.map(lambda x: "n/a" if x != x else f"{x:.1f}×"))
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "D": "Dates", "N": "Net, points per trade", "CI": "95% interval",
             "G": "At mid, no costs", "SP": "Spread, points", "FE": "Fee, points", "H": "Winners", "P": "Net P&L", "SH": "Sharpe",
             "DS": "Deflated Sharpe prob.", "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr"}
    sp = meta["spread_at_entry_points"]
    p = tr[(tr.variant == "V0") & (tr.cost_mult == 1.0)]
    S = ["# S16: the give-back at real quotes, on Kalshi", "",
         "Method, pre-registered before any give-back or P&L was computed on Kalshi's quotes: "
         "[`research/s16_kalshi_quotes/METHOD.md`](../../s16_kalshi_quotes/METHOD.md) (commit `f7ce87e`, amendment 1 `31c20aa`). "
         f"Data: S1's cache, nothing pulled: {meta['markets_with_sessions']} Kalshi markets with their best bid and ask, and their Polymarket twins, "
         f"{meta['sessions_live']} sessions from {meta['first_session']} to {meta['last_session']}. Files: [`tests.csv`](tests.csv), "
         "[`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`sessions.csv`](sessions.csv), [`capacity.md`](capacity.md), "
         "[`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         "**What holds up: each venue gives back the large moves measured on itself, and the other venue's price for the same question does "
         "not move. The give-back is noise in one venue's price, not the event's odds overshooting.**", "",
         f"- Nights picked on **Kalshi's** overnight move of 10 points or more ({int(k2k.n)} market-sessions): Kalshi's quoted mid changes by "
         f"{pts(k2k['mean'])} points by the close {ci(k2k.ci_lo, k2k.ci_hi)}. Polymarket's price for the same question: {pts(k2p['mean'])} "
         f"{ci(k2p.ci_lo, k2p.ci_hi)}. Difference {pts(k2d['mean'])} {ci(k2d.ci_lo, k2d.ci_hi)}.",
         f"- Nights picked on **Polymarket's** overnight move of 10 points or more ({int(k3p.n)} market-sessions): Polymarket's price changes by "
         f"{pts(k3p['mean'])} {ci(k3p.ci_lo, k3p.ci_hi)}. Kalshi's quoted mid: {pts(k3k['mean'])} {ci(k3k.ci_lo, k3k.ci_hi)}. Difference "
         f"{pts(k3d['mean'])} {ci(k3d.ci_lo, k3d.ci_hi)}.",
         f"- At 5 points the same signs with intervals through zero (differences {pts(k2d5['mean'])} {ci(k2d5.ci_lo, k2d5.ci_hi)} and "
         f"{pts(k3d5['mean'])} {ci(k3d5.ci_lo, k3d5.ci_hi)}). The samples are small: about 30 market-sessions at 10 points.", "",
         "This is the likeliest reading of the give-back that S5, S8, S9 and S15 found on Polymarket: a large move in one venue's price that "
         "the same question elsewhere did not share is mostly that venue's quote moving, and it comes back. It is the size of the spread "
         "because it is the spread.", "",
         f"**At Kalshi's real bid and ask the fade loses {num(-a1.mean_net_points)} points per trade** {ci(a1.ci_lo, a1.ci_hi)} on {int(a1.trades)} "
         f"trades; {pct(a1.hit_rate, 0)} winners. At mid prices it earns {pts(a1.mean_gross_points)}. Crossing the quoted spread costs "
         f"{num(a1.mean_spread_cost_points)} points and the fee {num(a1.mean_fee_cost_points)}. The quoted spread is {num(sp['median'], 1)} point at "
         f"the median over all sessions, but after a large overnight move in the mid it is wide: the \"move\" was largely the quote widening.", "",
         f"**Verdict on the pre-registered criterion: {verdict}.** Out-of-sample ({meta['oos_sessions']} sessions from {meta['oos_from']}): "
         f"{pts(o1.mean_net_points)} points per trade {ci(o1.ci_lo, o1.ci_hi)} on {int(o1.trades)} trades.", "",
         "## Headline numbers (primary V0: overnight move of 5+ points in Kalshi's mid, faded at 09:40 at the bid or ask, closed at the close)", "",
         md_table(vt[m.variant == "V0"], vcols), "",
         f"100 contracts per trade. Capital base ${a1.capital_base:,.0f}, the largest amount deployed in one session. Sharpe on session returns, "
         f"252 a year. Most of the sessions fall out-of-sample because most twins began trading on both venues in 2026.", "",
         "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## The tests (before costs)", "",
         "K1: Kalshi's quoted mid after its own overnight move. K2: the same nights on Polymarket. K3 (amendment 1): nights picked on "
         "Polymarket's own move, and Kalshi's quoted mid on those nights. Negative = the move was given back. Intervals resample dates.", "",
         ttab, "",
         "## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {verdict}.**", "",
          "## Costs", "",
          "- **Spread:** the real quoted bid and ask of each fill, from Kalshi's candles.",
          f"- **Fee:** Kalshi's taker formula, 0.07 × multiplier × contracts × P × (1 − P), rounded up to the cent, on each fill "
          f"(multipliers in this sample: {', '.join(str(x) for x in meta['fee_multipliers'])}).",
          f"- **Per trade:** spread {num(a1.mean_spread_cost_points)} points and fee {num(a1.mean_fee_cost_points)} points at 1×; "
          f"{a1.cost_bp_of_capital:,.0f} bp of capital. At 2×: {a2.cost_bp_of_capital:,.0f} bp.",
          f"- **Trades dropped for want of a quote at the exit:** {meta['dropped_no_exit_quote']['V0']} for the primary.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Every variant tried", "", md_table(vt, vcols), "",
          "V1: 3 points or more. V2: 10 points or more. V3: quotes at most 15 minutes old. The deflated Sharpe probability uses 4 trials.", "",
          "## What didn't work", "",
          f"- **The fade at real quotes**, in every variant and both segments. The best is V3 at {pts(row('ALL', 'V3', 1.0).mean_net_points)} points per trade.",
          f"- **Kalshi's mid after a move of 5 points or more** is not significantly given back: {pts(k1_5['mean'])} {ci(k1_5.ci_lo, k1_5.ci_hi)}. "
          f"Only the moves of 10 points or more are ({pts(k1_10['mean'])} {ci(k1_10.ci_lo, k1_10.ci_hi)}).", "",
          "## Caveats", "",
          "- 31 markets on a few themes, and about 30 market-sessions behind each 10-point figure.",
          "- K3 was added after the first run, before it was computed (amendment 1).",
          "- A quote allowed to stand for 6 hours may not be fillable; the strict 15-minute rule (V3) has 28 trades.",
          "- This shows that the give-back on these twin questions is venue noise. It suggests, and does not prove, the same for the "
          "Polymarket-only samples of S8, S9 and S15.", "",
          "## Reproduce", "", "```", "cd research", "python -m s16_kalshi_quotes.run", "python -m s16_kalshi_quotes.report",
          "python -m pytest s16_kalshi_quotes/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    w = (p.ask_in - p.bid_in) * 100
    cap = ["# S16 capacity", "",
           "- **Kalshi's candles carry the best bid and ask but no size**, so capacity cannot be read from this data.",
           f"- **Quoted spread at 09:40:** {num(sp['median'], 1)} point at the median over all {sp['n']:,} market-sessions priced between 5% and 95% "
           f"(quartiles {num(sp['p25'], 1)} to {num(sp['p75'], 1)}). On the {len(p)} sessions the primary trades, after a large overnight move: "
           f"median {w.median():.1f} points, mean {w.mean():.1f}.",
           "- The trade loses at real quotes, so capacity is not the binding question.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
