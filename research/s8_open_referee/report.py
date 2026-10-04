from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s7_weekend_straddle.run import boot_mean  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#1baf7a"


def pts(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:+.{d}f}"


def num(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def ci(lo: float, hi: float) -> str:
    return "n/a" if lo != lo else f"[{lo:+.2f}, {hi:+.2f}]"


def pct(x: float, d: int = 1) -> str:
    return "n/a" if x != x else f"{100 * x:.{d}f}%"


def md_table(df: pd.DataFrame, cols: dict) -> str:
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[k]) for k in cols) + " |")
    return "\n".join(out)


def pooled(mo: pd.DataFrame, thr: float, source: str | None = None) -> dict:
    s = mo[(mo.x.abs() >= thr) & mo.y_close.notna()]
    if source:
        s = s[s.source == source]
    m = boot_mean({d: list(v) for d, v in s.groupby("day").y_close})
    return {"n": len(s), "dates": s.day.nunique(), "markets": s.market.nunique(), "mean": m[0], "lo": m[1], "hi": m[2],
            "confirmed": float((s.vote == "confirmed").mean()) if len(s) else float("nan")}


def charts(tr: pd.DataFrame, days: list[str], K: float, oos_from: str) -> None:
    p1 = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)]
    p2 = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 2.0)]
    x = pd.to_datetime(days)
    series = (("Before costs", GREEN, p1.groupby("day").gross_points.sum()), ("After costs", BLUE, p1.groupby("day").pnl.sum()),
              ("After doubled costs", ORANGE, p2.groupby("day").pnl.sum()))
    for name, title, dd in (("equity_curve.png", "cumulative P&L", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for label, color, by_day in series:
            y = np.cumsum(by_day.reindex(days).fillna(0.0).to_numpy()) / K * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{label.lower()} {y.min():.0f}%")
            ax.plot(x, y, color=color, linewidth=2, label=label, solid_capstyle="round")
            if not dd:
                ax.plot([x[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
                ax.annotate(f"{y[-1]:+.0f}%", (x[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
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
        ax.set_title(f"S8, primary variant: {title} by session", loc="left", fontsize=11, color=INK)
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.14 if dd else 0.02), frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m, tr, gb = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "trades.csv"), pd.read_csv(R / "giveback.csv")
    mo, eq = pd.read_csv(R / "mornings.csv"), pd.read_csv(R / "equity.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    days = list(eq[(eq.variant == cfg.PRIMARY) & (eq.cost_mult == 1.0)].day)

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    def g(thr, scope, window, group):
        return gb[(gb.threshold == thr) & (gb.scope == scope) & (gb.window == window) & (gb.group == group)].iloc[0]

    a1, a2, i1, o1, o2 = (row("ALL", cfg.PRIMARY, 1.0), row("ALL", cfg.PRIMARY, 2.0), row("IS", cfg.PRIMARY, 1.0),
                          row("OOS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 2.0))
    h1, v3, v1 = row("from 2026-07-01", cfg.PRIMARY, 1.0), row("ALL", "V3", 1.0), row("ALL", "V1", 1.0)
    charts(tr, days, float(a1.capital_base), meta["oos_from"])
    W = "09:40 to the close"
    d5, d10 = g(5.0, "all nights", W, "not confirmed minus confirmed"), g(10.0, "all nights", W, "not confirmed minus confirmed")
    n5, c5_, n10, c10 = (g(5.0, "all nights", W, "not confirmed"), g(5.0, "all nights", W, "confirmed"),
                         g(10.0, "all nights", W, "not confirmed"), g(10.0, "all nights", W, "confirmed"))
    P5, P10, P10s4, P10s5 = pooled(mo, 5.0), pooled(mo, 10.0), pooled(mo, 10.0, "S4"), pooled(mo, 10.0, "S5")
    wkn = g(5.0, "weekends and holidays", "09:40 to the next 09:40", "not confirmed")
    diffs = gb[gb.group == "not confirmed minus confirmed"]
    sig = diffs[(diffs.ci_lo > 0) | (diffs.ci_hi < 0)]
    sig_txt = "; ".join(f"{r.threshold:.0f}+ points, {r.scope}, {r.window}: {pts(r['mean'])} {ci(r.ci_lo, r.ci_hi)}" for _, r in sig.iterrows())
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} OOS trades on at least {cfg.MIN_OOS_DATES} OOS dates",
         o1.trades >= cfg.MIN_OOS_TRADES and o1.dates_traded >= cfg.MIN_OOS_DATES, f"{int(o1.trades)} trades on {int(o1.dates_traded)} dates"),
        ("OOS mean net P&L per trade above zero, date-bootstrap interval excluding zero (1× costs)", o1.mean_net_points > 0 and o1.ci_lo > 0,
         f"{pts(o1.mean_net_points)} points {ci(o1.ci_lo, o1.ci_hi)}"),
        ("OOS above zero at 2× costs", o2.mean_net_points > 0, f"{pts(o2.mean_net_points)} points"),
        ("In-sample above zero at 1× costs", i1.mean_net_points > 0, f"{pts(i1.mean_net_points)} points {ci(i1.ci_lo, i1.ci_hi)} on {int(i1.trades)} trades"),
        ("Whole sample: a larger give-back on \"not confirmed\" mornings, interval excluding zero", d5["mean"] < 0 and d5.ci_hi < 0,
         f"difference {pts(d5['mean'])} points {ci(d5.ci_lo, d5.ci_hi)}"),
    ]
    passed = all(bool(c[1]) for c in crit)
    verdict = "pass" if passed else "null"
    if passed and a1.verified_share < cfg.MIN_VERIFIED_SHARE:
        verdict = "passes on modelled prices, not verified"

    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == cfg.PRIMARY, " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"),
                  T=m.trades.astype(int), D=m.dates_traded.astype(int), N=m.mean_net_points.map(pts),
                  CI=m.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1), G=m.mean_gross_points.map(pts), K=m.mean_cost_points.map(num),
                  H=m.hit_rate.map(lambda x: pct(x, 0)), P=m.pnl.map(lambda x: f"{'-' if x < 0 else '+'}${abs(x):,.0f}"), SH=m.sharpe.map(num),
                  DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(pct), WM=m.worst_month.map(pct),
                  TO=m.turnover_ann.map(lambda x: "n/a" if x != x else f"{x:.1f}×"),
                  VE=m.verified_trades.astype(int).astype(str) + " of " + m.checkable_trades.astype(int).astype(str) + " checkable")
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "D": "Dates", "N": "Net, points per trade", "CI": "95% interval",
             "G": "Before costs", "K": "Costs, points", "H": "Winners", "P": "Net P&L", "SH": "Sharpe", "DS": "Deflated Sharpe prob.",
             "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr", "VE": "Print-verified"}
    gt = gb[gb.group != "no vote"].pivot_table(index=["threshold", "scope", "window"], columns="group", values=["n", "mean", "ci_lo", "ci_hi"], sort=False)
    grow = []
    for (thr, scope, window), r in gt.iterrows():
        cell = lambda k: f"{pts(r[('mean', k)])} {ci(r[('ci_lo', k)], r[('ci_hi', k)])}"  # noqa: E731
        grow.append({"T": f"{thr:.0f}+ points", "S": scope, "W": window, "NC": f"{cell('not confirmed')}, n {int(r[('n', 'not confirmed')])}",
                     "C": f"{cell('confirmed')}, n {int(r[('n', 'confirmed')])}", "D": cell("not confirmed minus confirmed")})
    gtab = md_table(pd.DataFrame(grow), {"T": "Overnight move", "S": "Nights", "W": "Window", "NC": "Asset did not confirm",
                                         "C": "Asset confirmed", "D": "Difference"})
    votes = meta["votes_5pt"]
    S = ["# S8: is the stock market's open a referee for the overnight move in the odds?", "",
         "Method, pre-registered before the give-back was split by the asset's move: "
         "[`research/s8_open_referee/METHOD.md`](../../s8_open_referee/METHOD.md) (commit `1cb7cb3`). "
         f"Data: the S4 and S5 caches, {meta['markets_used']} markets, {meta['links']} links to {meta['tickers']} tickers, {meta['sessions']} sessions from "
         f"{meta['first_session']} to {meta['last_session']}. Files: [`metrics.csv`](metrics.csv), [`giveback.csv`](giveback.csv), "
         "[`trades.csv`](trades.csv), [`mornings.csv`](mornings.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**What holds up: the odds give back part of an overnight move, and a second set of markets shows it too.** After an overnight move of "
         f"10 points or more, the odds move back {num(-P10['mean'])} points between 09:40 and the close ({P10['n']} market-mornings on "
         f"{P10['dates']} dates, date-bootstrap 95% interval {ci(P10['lo'], P10['hi'])}). The S5 markets, where this was first seen, give "
         f"{pts(P10s5['mean'])} {ci(P10s5['lo'], P10s5['hi'])}; the S4 markets, never tested for it before, give {pts(P10s4['mean'])} "
         f"{ci(P10s4['lo'], P10s4['hi'])} on {P10s4['n']} mornings. After 5 points or more the give-back is {num(-P5['mean'])} points "
         f"{ci(P5['lo'], P5['hi'])} on {P5['n']} mornings.", "",
         f"**It cannot be taken at these costs.** Crossing the spread twice and paying the fee twice costs {num(a1.mean_cost_points)} points per "
         f"trade here. Selling every move of 5 points or more at 09:40 (V3) earns {pts(v3.mean_gross_points)} before costs and "
         f"{pts(v3.mean_net_points)} after {ci(v3.ci_lo, v3.ci_hi)}.", "",
         f"**The stock market's open is not a referee.** The idea was that the odds overshoot when the linked asset opens without confirming "
         f"them. It does not work: on \"not confirmed\" mornings the odds give back {num(-n5['mean'])} points, on \"confirmed\" mornings "
         f"{num(-c5_['mean'])}; difference {pts(d5['mean'])} {ci(d5.ci_lo, d5.ci_hi)}. At 10 points: {num(-n10['mean'])} against "
         f"{num(-c10['mean'])}, difference {pts(d10['mean'])} {ci(d10.ci_lo, d10.ci_hi)}.", "",
         f"**Verdict on the pre-registered criterion: {verdict}.** The primary trade loses {num(-a1.mean_net_points)} points per trade after costs "
         f"{ci(a1.ci_lo, a1.ci_hi)} on {int(a1.trades)} trades, and {num(-a2.mean_net_points)} at doubled costs. Out-of-sample has "
         f"{int(o1.trades)} trades ({pts(o1.mean_net_points)} points each), fewer than the {cfg.MIN_OOS_TRADES} the criterion needs; "
         "in-sample is negative on its own.", "",
         "## Headline numbers (primary V0: overnight move of 5+ points, asset did not confirm, sold at 09:40, closed at the close)", "",
         md_table(vt[m.variant == cfg.PRIMARY], vcols), "",
         f"100 contracts per trade; a point is one cent per contract. Capital base ${a1.capital_base:,.0f}, the largest amount deployed in one "
         f"session. Out-of-sample is the last {meta['oos_sessions']} sessions, from {meta['oos_from']}. Sharpe on session returns, 252 a year. "
         "\"From 2026-07-01\" is the hindsight check: sessions after the labelling models' knowledge ends.", "",
         "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## The test behind the trade (before costs)", "",
         "The change in the odds after the open, in points, signed so that a negative number is a give-back of the overnight move. "
         "Intervals resample dates.", "", gtab, "",
         f"Of the {len(mo)} mornings after a move of 5 points or more, the linked assets had moved the way the odds did by 09:35 on "
         f"{votes.get('confirmed', 0)} ({pct(votes.get('confirmed', 0) / len(mo), 0)}), and on {pct(P10['confirmed'], 0)} after 10 points or "
         "more. That is S5's opening-gap relation seen as a count.", "",
         f"{len(sig)} of the {len(diffs)} differences have an interval excluding zero: {sig_txt}. Both signs are the opposite of the idea "
         "(the moves the asset did not confirm gave back less, or went further), the rows overlap, and nothing is built on them. Taken at "
         f"face value, following an unconfirmed weekend move to the next morning earns {pts(wkn['mean'])} points before costs "
         f"{ci(wkn.ci_lo, wkn.ci_hi)}, less than the {num(a1.mean_cost_points)} points it costs.", "",
         "## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {verdict}.**", "",
          "## Costs", "",
          f"- **Polymarket half-spread: {100 * cfg.HALF_SPREAD:.1f} point** per fill, half of the median spread of "
          f"{meta['cost_snapshot']['spread_points_median_mid']:.1f} point on {meta['cost_snapshot']['mid_10_90']} open markets priced between 10% "
          f"and 90% (snapshot of {meta['cost_snapshot']['snapshot_utc'][:16]} UTC). Historical books are not published.",
          "- **Polymarket fee:** 0.04 × P × (1 − P) per contract, at entry and at exit. Near 50% that is one point each way, which is why the "
          f"round trip here ({num(a1.mean_cost_points)} points) is above the 2.0 points of the snapshot's markets.",
          f"- **In bp of the capital of a trade:** {a1.cost_bp_of_capital:,.0f} bp at 1×, {a2.cost_bp_of_capital:,.0f} bp at 2×.",
          f"- **Print check:** {int(a1.checkable_trades)} of the {int(a1.trades)} primary entries are recent enough for the data API to serve "
          f"their prints; {int(a1.verified_trades)} have a print at the assumed price or better"
          + (f", averaging {pts(a1.mean_net_points_verified)} points {ci(a1.ci_lo_verified, a1.ci_hi_verified)}." if a1.verified_trades else "."), "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Every variant tried", "", md_table(vt, vcols), "", "The deflated Sharpe probability uses 5 trials.", "",
          "## What didn't work", "",
          "- **The asset's vote.** It does not separate the moves that reverse from the ones that hold, at 5 or at 10 points, on all nights or "
          "on weekends.",
          f"- **The primary trade.** {pts(a1.mean_net_points)} points per trade {ci(a1.ci_lo, a1.ci_hi)}; {pct(a1.hit_rate, 0)} winners.",
          f"- **Larger moves only (V1).** {pts(v1.mean_gross_points)} before costs, {pts(v1.mean_net_points)} after {ci(v1.ci_lo, v1.ci_hi)} on "
          f"{int(v1.trades)} trades: the give-back and the cost are the same size.",
          f"- **Holding to the next morning (V2)** and **weekends only (V4)**: {pts(row('ALL', 'V2', 1.0).mean_net_points)} and "
          f"{pts(row('ALL', 'V4', 1.0).mean_net_points)} points per trade.",
          f"- **Since July (hindsight check and out-of-sample):** {pts(h1.mean_net_points)} points per trade on {int(h1.trades)} trades, and no "
          f"give-back before costs ({pts(h1.mean_gross_points)}).", "",
          "## Caveats", "",
          "- The give-back is measured on mid prices. Someone resting orders instead of crossing the spread would not pay the 2.6 points, but "
          "whether such orders fill cannot be tested on this data, and it is not claimed.",
          "- Several markets on one date are often the same news; intervals resample dates for that reason.",
          "- The links are model judgements.",
          "- One year, one snapshot for the spread.", "",
          "## Reproduce", "", "```", "cd research", "python -m s8_open_referee.run", "python -m s8_open_referee.report",
          "python -m pytest s8_open_referee/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    cs = meta["cost_snapshot"]
    p = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)]
    ver = p[p.verified]
    cap = ["# S8 capacity", "",
           f"- **Size at the best price:** median **${cs['touch_dollars_median_mid']:,.0f}** on {cs['mid_10_90']} open markets priced between 10% "
           f"and 90% (snapshot of {cs['snapshot_utc'][:16]} UTC).",
           f"- **The trade as run:** 100 contracts, ${p.capital.mean():,.0f} of capital on average, at most {cfg.MAX_POSITIONS} trades a session "
           f"({p.groupby('day').size().max()} at the busiest); {len(p)} trades in {meta['sessions']} sessions.",
           (f"- **Printed sizes behind the verified entries:** median {ver.verify_size.median():,.0f} shares on {len(ver)} entries."
            if len(ver) else "- **No entry is print-verified**, so no printed size is reported."),
           "- The trade loses after costs, so capacity is not the binding question. If it had worked it would have been a trade of a few hundred "
           "dollars per market.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
