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
    e1 = eq[(eq.variant == cfg.PRIMARY) & (eq.cost_mult == 1.0)].sort_values("weekend")
    e2 = eq[(eq.variant == cfg.PRIMARY) & (eq.cost_mult == 2.0)].sort_values("weekend")
    x = pd.to_datetime(e1.weekend)
    series = (("Before costs", GREEN, e1.gross.to_numpy()), ("After costs", BLUE, e1.pnl.to_numpy()), ("After doubled costs", ORANGE, e2.pnl.to_numpy()))
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
        ax.set_title(f"S15, primary trade (sell every weekend rise of 5+ points): {title} by weekend", loc="left", fontsize=11, color=INK)
        ax.legend(loc="upper left" if not dd else "lower left", bbox_to_anchor=(0.0, 0.92) if not dd else (0.0, 0.14), frameon=False,
                  fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m, tr, tt = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "trades.csv"), pd.read_csv(R / "tests.csv")
    wk, eq = pd.read_csv(R / "weekends.csv"), pd.read_csv(R / "equity.csv")
    meta = json.loads((R / "run_meta.json").read_text())

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    def t(thr, scope, side):
        return tt[(tt.threshold == thr) & (tt.scope == scope) & (tt.side == side)].iloc[0]

    ALL, FAR, OIL = "all fresh markets", "not in an S9 event (other and weekly)", "oil \"hit high\" markets"
    r5, f5, r10, far5, oil5 = t(5.0, ALL, "risers"), t(5.0, ALL, "fallers"), t(10.0, ALL, "risers"), t(5.0, FAR, "risers"), t(5.0, OIL, "risers")
    a1, a2, i1, o1, o2 = row("ALL", "V0", 1.0), row("ALL", "V0", 2.0), row("IS", "V0", 1.0), row("OOS", "V0", 1.0), row("OOS", "V0", 2.0)
    charts(eq, float(a1.capital_base), meta["oos_from"])
    h1 = bool(r5.mean_y < 0 and r5.ci_hi < 0)
    h2 = bool(r5.diff_vs_quiet < 0 and r5.diff_ci_hi < 0)
    replicates = h1 and h2
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} OOS trades on at least {cfg.MIN_OOS_WEEKENDS} OOS weekends",
         o1.trades >= cfg.MIN_OOS_TRADES and o1.weekends_traded >= cfg.MIN_OOS_WEEKENDS, f"{int(o1.trades)} trades on {int(o1.weekends_traded)} weekends"),
        ("OOS mean net P&L per trade above zero, weekend-bootstrap interval excluding zero (1× costs)", o1.mean_net_points > 0 and o1.ci_lo > 0,
         f"{pts(o1.mean_net_points)} points {ci(o1.ci_lo, o1.ci_hi)}"),
        ("OOS above zero at 2× costs", o2.mean_net_points > 0, f"{pts(o2.mean_net_points)} points"),
        ("In-sample above zero at 1× costs", i1.mean_net_points > 0, f"{pts(i1.mean_net_points)} points {ci(i1.ci_lo, i1.ci_hi)} on {int(i1.trades)} trades"),
    ]
    passed = all(bool(c[1]) for c in crit)
    thin = a1.checkable_trades > 0 and a1.verified_trades / a1.checkable_trades < cfg.MIN_VERIFIED_SHARE
    headline = ("No." if not replicates else "Yes." if not thin else
                f"In quoted mid prices, yes. In prices someone traded at, it cannot be shown: {int(a1.verified_trades)} of the "
                f"{int(a1.checkable_trades)} entries that can be checked have a print.")
    verdict = "pass" if passed else "not a pass"
    if passed and a1.verified_share < cfg.MIN_VERIFIED_SHARE:
        verdict = "passes on modelled prices, not verified"

    p = tr[(tr.variant == "V0") & (tr.cost_mult == 1.0)]
    ver = p[p.verified]
    ttab = md_table(tt.assign(T=tt.threshold.map(lambda x: f"{x:.0f}+ points"), S=tt.scope, D=tt.side, N=tt.n.astype(int), K=tt.weekends.astype(int),
                              Y=tt.mean_y.map(pts), CI=tt.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1), Q=tt.quiet_mean_y.map(pts),
                              DF=tt.diff_vs_quiet.map(pts), DCI=tt.apply(lambda r: ci(r.diff_ci_lo, r.diff_ci_hi), axis=1)),
                    {"T": "Weekend move", "S": "Markets", "D": "Side", "N": "Market-weekends", "K": "Weekends", "Y": "Change to the next session 09:40",
                     "CI": "95% interval", "Q": "Quiet markets", "DF": "Difference", "DCI": "95% interval "})
    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == "V0", " (primary trade)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"),
                  T=m.trades.astype(int), W=m.weekends_traded.astype(int), N=m.mean_net_points.map(pts), CI=m.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1),
                  G=m.mean_gross_points.map(pts), K=m.mean_cost_points.map(num), H=m.hit_rate.map(lambda x: pct(x, 0)),
                  P=m.pnl.map(lambda x: "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.0f}"), SH=m.sharpe.map(num),
                  DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(pct), WM=m.worst_month.map(pct),
                  TO=m.turnover_ann.map(lambda x: "n/a" if x != x else f"{x:.1f}×"),
                  VE=m.verified_trades.astype(int).astype(str) + " of " + m.checkable_trades.astype(int).astype(str) + " checkable",
                  GV=m.mean_gross_points_verified.map(pts))
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "W": "Weekends", "N": "Net, points per trade", "CI": "95% interval",
             "G": "Before costs", "K": "Costs, points", "H": "Winners", "P": "Net P&L", "SH": "Sharpe", "DS": "Deflated Sharpe prob.",
             "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr", "VE": "Print-verified", "GV": "Verified, before costs"}
    flat = float((wk.p_entry == wk.p_start).mean())
    S = ["# S15: do price markets that rise over the weekend fall back on Monday? A test on markets S9 did not use", "",
         "Method, pre-registered before any price of these markets was pulled: "
         "[`research/s15_weekend_scare/METHOD.md`](../../s15_weekend_scare/METHOD.md) (commit `c1a41ea`). "
         f"Data: {meta['markets_in_universe']} price markets that S9 never used ({meta['markets_live']} live on at least one weekend), "
         f"{meta['market_weekends']:,} market-weekends on {meta['weekends_live']} weekends from {meta['first_weekend']} to {meta['last_weekend']}. "
         "Files: [`tests.csv`](tests.csv), [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`weekends.csv`](weekends.csv), "
         "[`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**Does the pattern replicate on fresh markets? {headline}** S9's markets that rose over a weekend fell 4.90 "
         f"points by Monday. On {int(r5.n)} fresh market-weekends with a rise of 5 points or more ({int(r5.weekends)} weekends), the change to the "
         f"next session's 09:40 is {pts(r5.mean_y)} points, weekend-bootstrap 95% interval {ci(r5.ci_lo, r5.ci_hi)} (H1: "
         f"{'holds' if h1 else 'does not hold'}). Quiet markets drift {pts(r5.quiet_mean_y)} over the same window; risers minus quiet markets: "
         f"{pts(r5.diff_vs_quiet)} {ci(r5.diff_ci_lo, r5.diff_ci_hi)} (H2: {'holds' if h2 else 'does not hold'}).", "",
         f"**By how far the markets are from S9's.** Markets in events S9 did not use at all: {pts(far5.mean_y)} {ci(far5.ci_lo, far5.ci_hi)} on "
         f"{int(far5.n)} market-weekends, {pts(far5.diff_vs_quiet)} {ci(far5.diff_ci_lo, far5.diff_ci_hi)} against quiet markets. Oil \"hit high\" "
         f"markets, the group that fell 7.85 points in S9: {pts(oil5.mean_y)} {ci(oil5.ci_lo, oil5.ci_hi)} on {int(oil5.n)}. After a rise of 10 "
         f"points or more: {pts(r10.mean_y)} {ci(r10.ci_lo, r10.ci_hi)} on {int(r10.n)}.", "",
         f"**The other side.** Markets that fell 5 points or more change by {pts(f5.mean_y)} {ci(f5.ci_lo, f5.ci_hi)} on {int(f5.n)} "
         f"market-weekends; against quiet markets {pts(f5.diff_vs_quiet)} {ci(f5.diff_ci_lo, f5.diff_ci_hi)}. Once the drift is "
         "removed the reversal is the same size on both sides. It is S9's give-back again, not something special to rises.", "",
         f"**Selling the rise (the trade): {verdict}.** {pts(a1.mean_gross_points)} points per trade before costs, {pts(a1.mean_net_points)} after "
         f"{ci(a1.ci_lo, a1.ci_hi)} on {int(a1.trades)} trades; {pts(a2.mean_net_points)} at doubled costs. In-sample {pts(i1.mean_net_points)} "
         f"{ci(i1.ci_lo, i1.ci_hi)}; out-of-sample ({meta['oos_weekends']} weekends from {meta['oos_from']}) {pts(o1.mean_net_points)} "
         f"{ci(o1.ci_lo, o1.ci_hi)} on {int(o1.trades)} trades.", "",
         f"**How much of it was a real price.** {int(a1.checkable_trades)} of the {int(a1.trades)} entries are recent enough for their prints to "
         f"be served; {int(a1.verified_trades)} have a print at the assumed price or better within 10 minutes of Sunday 17:55"
         + (f". Those earn {pts(a1.mean_gross_points_verified)} points before costs {ci(a1.gross_ci_lo_verified, a1.gross_ci_hi_verified)} and "
            f"{pts(a1.mean_net_points_verified)} after {ci(a1.ci_lo_verified, a1.ci_hi_verified)}." if a1.verified_trades else "."), "",
         "## The test (before costs)", "",
         "The change in the price from Sunday 17:55 to the next session's 09:40, in points. \"Quiet markets\" moved less than 2 points over the "
         "weekend and carry the ordinary drift. Intervals resample weekends.", "", ttab, "",
         "## The trade (V0: sell YES on every rise of 5+ points at Sunday 17:55, buy back at the next session's 09:40)", "",
         md_table(vt[m.variant == "V0"], vcols), "",
         f"100 contracts per trade. Capital base ${a1.capital_base:,.0f}, the largest amount deployed on one weekend. Sharpe on weekend returns, "
         "52 a year.", "", "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## Pre-registered criteria", "", "| Criterion | Result | Evidence |", "|---|---|---|",
         f"| H1: risers fall, interval excluding zero | {'pass' if h1 else '**fail**'} | {pts(r5.mean_y)} {ci(r5.ci_lo, r5.ci_hi)} |",
         f"| H2: risers fall more than quiet markets, interval excluding zero | {'pass' if h2 else '**fail**'} | {pts(r5.diff_vs_quiet)} {ci(r5.diff_ci_lo, r5.diff_ci_hi)} |"]
    S += [f"| Trade: {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**The pattern {'replicates' if replicates else 'does not replicate'}; the trade: {verdict}.**", "",
          "## Costs", "",
          "- **Half-spread per fill:** S9's by asset class (crude oil 0.5 point, S&P 500 1.0, gold 1.25, silver 2.0, stocks 2.5), natural gas "
          "2.0, and 3.0 for every market of a weekly event. From the live books of Sat 2026-10-03 22:13 New York time.",
          "- **Fee:** each market's own schedule.",
          f"- **Round trip:** {num(a1.mean_cost_points)} points per trade on average; {a1.cost_bp_of_capital:,.0f} bp of the capital of a trade at "
          f"1×, {a2.cost_bp_of_capital:,.0f} bp at 2×.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Every variant tried", "", md_table(vt, vcols), "", "V1: rises of 10 points or more. V2: crude oil only. The deflated Sharpe "
          "probability uses 3 trials.", "",
          "## Caveats", "",
          "- **Thin books.** These markets traded $10,000 to $50,000 in their life. A riser is chosen on a high Sunday reading; if that reading "
          "is noise in a thin book, the next one is lower by construction, and nobody could have sold at it. The print-verified rows are the "
          f"guard. {pct(flat, 0)} of live market-weekends show exactly the same price on Sunday as on Friday.",
          "- **The same weekends as S9.** Different markets, not a different period.",
          "- Half-spreads come from one night's books.", "",
          "## Reproduce", "", "```", "cd research", "python -m s15_weekend_scare.universe      # catalogue only; already committed",
          "python -m s15_weekend_scare.run --pull --gentle", "python -m s15_weekend_scare.run", "python -m s15_weekend_scare.report",
          "python -m pytest s15_weekend_scare/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    cap = ["# S15 capacity", "",
           "- **Size at the best price on a weekend** (live books of Sat 2026-10-03 22:13 New York time, 196 open price markets priced between "
           "10% and 90%): a median of **$17**, with a median spread of 6 points. These fresh markets are the small ones.",
           f"- **The trade as run:** 100 contracts, ${p.capital.mean():,.0f} of capital on average, at most {cfg.MAX_POSITIONS} trades a weekend; "
           f"{len(p)} trades on {p.weekend.nunique()} weekends.",
           (f"- **Printed sizes behind the verified entries:** median {ver.verify_size.median():,.0f} shares on {len(ver)} entries."
            if len(ver) else "- **No entry is print-verified.**"),
           "- Whatever the test shows, this is a trade of tens of dollars per market.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
