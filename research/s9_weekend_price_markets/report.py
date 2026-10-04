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
from s8_open_referee.report import ci, md_table, num, pct, pts  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#1baf7a"
CLASS_NAME = {"all": "All markets", "crude": "Crude oil", "gold": "Gold", "silver": "Silver", "sp500": "S&P 500", "stock": "Stocks"}


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
        ax.set_title(f"S9, primary variant: {title} by weekend", loc="left", fontsize=11, color=INK)
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

    def t1(thr, markets, window="to the next session 09:40"):
        return tt[(tt.test == "T1 give-back") & (tt.threshold == thr) & (tt.markets == markets) & (tt.window == window)].iloc[0]

    a1, a2, i1, o1, o2 = (row("ALL", cfg.PRIMARY, 1.0), row("ALL", cfg.PRIMARY, 2.0), row("IS", cfg.PRIMARY, 1.0),
                          row("OOS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 2.0))
    charts(eq, float(a1.capital_base), meta["oos_from"])
    link = tt[tt.test == "T2 link"].reset_index(drop=True)
    lw, ly, le = link.iloc[0], link.iloc[1], link.iloc[2]
    t3 = tt[tt.test.str.startswith("T3")].reset_index(drop=True)
    g5, g10, c5, e5 = t1(5.0, "all"), t1(10.0, "all"), t1(5.0, "crude"), t1(5.0, "all", "to Sunday 19:00")
    v2i, v2o, v2a, v2a2 = row("IS", "V2", 1.0), row("OOS", "V2", 1.0), row("ALL", "V2", 1.0), row("ALL", "V2", 2.0)
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} OOS trades on at least {cfg.MIN_OOS_WEEKENDS} OOS weekends",
         o1.trades >= cfg.MIN_OOS_TRADES and o1.weekends_traded >= cfg.MIN_OOS_WEEKENDS, f"{int(o1.trades)} trades on {int(o1.weekends_traded)} weekends"),
        ("OOS mean net P&L per trade above zero, weekend-bootstrap interval excluding zero (1× costs)", o1.mean_net_points > 0 and o1.ci_lo > 0,
         f"{pts(o1.mean_net_points)} points {ci(o1.ci_lo, o1.ci_hi)}"),
        ("OOS above zero at 2× costs", o2.mean_net_points > 0, f"{pts(o2.mean_net_points)} points"),
        ("In-sample above zero at 1× costs", i1.mean_net_points > 0, f"{pts(i1.mean_net_points)} points {ci(i1.ci_lo, i1.ci_hi)} on {int(i1.trades)} trades"),
    ]
    passed = all(bool(c[1]) for c in crit)
    verdict = "pass" if passed else "not a pass"
    if passed and a1.verified_share < cfg.MIN_VERIFIED_SHARE:
        verdict = "passes on modelled prices, not verified"

    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == cfg.PRIMARY, " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"),
                  T=m.trades.astype(int), W=m.weekends_traded.astype(int), N=m.mean_net_points.map(pts),
                  CI=m.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1), G=m.mean_gross_points.map(pts), K=m.mean_cost_points.map(num),
                  H=m.hit_rate.map(lambda x: pct(x, 0)), P=m.pnl.map(lambda x: f"{'-' if x < 0 else '+'}${abs(x):,.0f}"), SH=m.sharpe.map(num),
                  DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(pct), WM=m.worst_month.map(pct),
                  TO=m.turnover_ann.map(lambda x: "n/a" if x != x else f"{x:.1f}×"),
                  VE=m.verified_trades.astype(int).astype(str) + " of " + m.checkable_trades.astype(int).astype(str) + " checkable")
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "W": "Weekends", "N": "Net, points per trade", "CI": "95% interval",
             "G": "Before costs", "K": "Costs, points", "H": "Winners", "P": "Net P&L", "SH": "Sharpe", "DS": "Deflated Sharpe prob.",
             "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr", "VE": "Print-verified"}
    g = tt[tt.test == "T1 give-back"]
    gtab = md_table(g.assign(T=g.threshold.map(lambda x: f"{x:.0f}+ points"), M=g.markets.map(CLASS_NAME), W=g.window, N=g.n.astype(int),
                             K=g.weekends.astype(int), A=g["mean"].map(pts), CI=g.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1)),
                    {"T": "Weekend move", "M": "Markets", "W": "Window", "N": "Market-weekends", "K": "Weekends", "A": "Change, signed by the move", "CI": "95% interval"})
    big = wk[(wk.w.abs() >= 5) & wk.y.notna()]
    diag = []
    for name, s in (("Markets that rose over the weekend", big[big.w > 0]), ("Markets that fell over the weekend", big[big.w < 0]),
                    ("Oil, \"hit high\" markets that rose", big[(big.asset_class == "crude") & (big.sign == 1) & (big.w > 0)]),
                    ("Oil, \"hit high\" markets that fell", big[(big.asset_class == "crude") & (big.sign == 1) & (big.w < 0)]),
                    ("Oil, \"hit low\" markets that rose", big[(big.asset_class == "crude") & (big.sign == -1) & (big.w > 0)]),
                    ("Oil, \"hit low\" markets that fell", big[(big.asset_class == "crude") & (big.sign == -1) & (big.w < 0)])):
        b = boot_mean({k: list(v) for k, v in s.groupby("weekend").y})
        diag.append({"G": name, "N": len(s), "K": s.weekend.nunique(), "W": pts(s.w.mean()), "Y": pts(b[0]), "CI": ci(b[1], b[2])})
    drift = boot_mean({k: list(v) for k, v in wk[wk.y.notna()].groupby("weekend").y})
    p = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)]
    ver = p[p.verified]
    by_w = p.groupby("weekend").pnl.sum().sort_values()
    months = tr[(tr.variant == "V2") & (tr.cost_mult == 1.0)].assign(month=lambda d: d.weekend.str[:7]).groupby("month").agg(
        T=("pnl", "size"), K=("weekend", "nunique"), G=("gross_points", "mean"), N=("net_points", "mean")).reset_index()
    mtab = md_table(months.assign(G=months.G.map(pts), N=months.N.map(pts)), {"month": "Month", "T": "Trades", "K": "Weekends", "G": "Before costs", "N": "Net, points per trade"})
    bc = meta["market_weekends_by_class"]

    S = ["# S9: Polymarket's own price markets over the weekend, while the asset is shut", "",
         "Method, pre-registered before any price of these markets was pulled: "
         "[`research/s9_weekend_price_markets/METHOD.md`](../../s9_weekend_price_markets/METHOD.md) (commit `6e1876a`, amendment 1 `deb2e65`). "
         f"Data: {meta['markets_in_universe']} markets in 25 events ({meta['markets_live']} live on at least one weekend), "
         f"{meta['market_weekends']:,} market-weekends on {meta['weekends_live']} weekends from {meta['first_weekend']} to {meta['last_weekend']}. "
         "Files: [`metrics.csv`](metrics.csv), [`tests.csv`](tests.csv), [`trades.csv`](trades.csv), [`weekends.csv`](weekends.csv), "
         "[`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**What holds up 1: on a weekend, oil's reaction to the news can be seen on Polymarket itself.** While oil futures are shut, "
         f"Polymarket's oil price markets (\"Will WTI hit $100?\") move {num(lw.slope)} points for every point the odds of oil-linked events "
         f"move the same weekend (t = {num(lw.t)}; {int(lw.n)} market-weekends on {int(lw.weekends)} weekends, errors clustered by weekend). "
         f"After the reopen nothing more follows: {pts(ly.slope)} by Monday 09:40 (t = {num(ly.t)}). The link between an event question and an "
         "asset holds inside the weekend, in a market that is open.", "",
         f"**What holds up 2: part of the weekend move is given back by Monday.** After a weekend move of 5 points or more, these markets "
         f"move back {num(-g5['mean'])} points by Monday 09:40 ({int(g5.n)} market-weekends on {int(g5.weekends)} weekends, weekend-bootstrap "
         f"95% interval {ci(g5.ci_lo, g5.ci_hi)}); oil {num(-c5['mean'])} {ci(c5.ci_lo, c5.ci_hi)}; after 10 points or more "
         f"{num(-g10['mean'])} {ci(g10.ci_lo, g10.ci_hi)}. About {abs(t3.iloc[0].slope) * 100:.0f}% of a weekend move is undone (slope "
         f"{pts(t3.iloc[0].slope)}, t = {num(t3.iloc[0].t)}). It does not happen when futures reopen: by Sunday 19:00 the change is "
         f"{pts(e5['mean'])} {ci(e5.ci_lo, e5.ci_hi)}.", "",
         f"**It does not pay after costs, and it is gone in the last two months.** A round trip costs {num(a1.mean_cost_points)} points here. "
         f"Selling every weekend move of 5 points or more earns {pts(a1.mean_gross_points)} before costs and {pts(a1.mean_net_points)} after "
         f"{ci(a1.ci_lo, a1.ci_hi)} on {int(a1.trades)} trades; {pts(a2.mean_net_points)} at doubled costs. Out-of-sample ({meta['oos_weekends']} "
         f"weekends from {meta['oos_from']}): {pts(o1.mean_net_points)} {ci(o1.ci_lo, o1.ci_hi)} on {int(o1.trades)} trades, and before costs "
         f"the give-back is absent ({pts(o1.mean_gross_points)}).", "",
         f"**Verdict on the pre-registered criterion: {verdict}.**", "",
         f"**The oil-only variant is positive in-sample and negative out-of-sample.** V2: {pts(v2i.mean_net_points)} points per trade "
         f"{ci(v2i.ci_lo, v2i.ci_hi)} on {int(v2i.trades)} in-sample trades (Sharpe {num(v2i.sharpe)}), then {pts(v2o.mean_net_points)} "
         f"{ci(v2o.ci_lo, v2o.ci_hi)} on {int(v2o.trades)} out-of-sample trades; over the whole year {pts(v2a.mean_net_points)} "
         f"{ci(v2a.ci_lo, v2a.ci_hi)} and {pts(v2a2.mean_net_points)} at doubled costs. It is one of five variants and it failed the part of "
         "the sample it was not chosen on. It is not an edge.", "",
         "## Headline numbers (primary V0: weekend move of 5+ points, sold Sunday 17:55, closed at the next session's 09:40)", "",
         md_table(vt[m.variant == cfg.PRIMARY], vcols), "",
         f"100 contracts per trade; a point is one cent per contract. Capital base ${a1.capital_base:,.0f}, the largest amount deployed on one "
         f"weekend. Sharpe on weekend returns, 52 a year. {int(a1.settled_trades)} trades were settled at the market's result because the target "
         "was hit before the exit (amendment 1); all were losses for the fade.", "",
         "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## T1, the give-back (before costs)", "",
         "The change in the price after the Sunday 17:55 entry, in points, signed so that a negative number is a give-back of the weekend move.", "",
         gtab, "",
         "## T2, the link (oil price markets against oil-linked event odds)", "",
         "| Relation | Slope | t | Market-weekends | Weekends |", "|---|---|---|---|---|",
         f"| The oil price markets' weekend move, per point of weekend move in the event odds | {pts(lw.slope)} | {num(lw.t)} | {int(lw.n)} | {int(lw.weekends)} |",
         f"| Their move from Sunday 17:55 to the next session 09:40, per point | {pts(ly.slope)} | {num(ly.t)} | {int(ly.n)} | {int(ly.weekends)} |",
         f"| Their move from Sunday 17:55 to Sunday 19:00, per point | {pts(le.slope)} | {num(le.t)} | {int(le.n)} | {int(le.weekends)} |", "",
         f"The event odds are the mean weekend move of the {meta['oil_event_questions']} S5 and S4 questions whose agreed links name USO, XLE, XOP, "
         "XOM, CVX or OXY, each signed by its link direction. The price markets are signed by their own side (a \"hit high\" market is +1). "
         "Both legs are Polymarket mid prices over the same weekend, so this is co-movement, not a lead.", "",
         "## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {verdict}.**", "",
          "## Looked at after the run (not pre-registered)", "",
          "Two splits that explain the result. Neither was in the method; they are description, not tests.", "",
          md_table(pd.DataFrame(diag), {"G": "After a weekend move of 5+ points", "N": "Market-weekends", "K": "Weekends", "W": "Mean weekend move",
                                        "Y": "Change to the next session 09:40", "CI": "95% interval"}), "",
          f"- **The give-back is on the side that rose.** Markets that rose over the weekend fall back; markets that fell barely recover. "
          "For oil the pattern is a weekend scare: \"hit high\" markets that jumped are lower by Monday, and \"hit low\" markets that dropped "
          "are higher.",
          f"- **These markets drift down anyway.** Over all {int(wk.y.notna().sum()):,} live market-weekends the price falls {num(-drift[0])} "
          f"points from Sunday 17:55 to Monday 09:40 {ci(drift[1], drift[2])}: a \"hit\" market loses value as time passes without a hit. "
          "Part of the give-back after rises is this drift.", "",
          "## The oil-only variant by month (V2, 1× costs)", "", mtab, "",
          "## Costs", "",
          "- **Half-spread per fill:** crude oil 0.5 point, S&P 500 1.0, gold 1.25, silver 2.0, stocks 2.5: half of the median spreads on the "
          "live books of Sat 2026-10-03 22:13 New York time. Historical books are not published.",
          "- **Fee:** each market's own schedule from the catalogue: 0.04 × P × (1 − P) for takers on 263 of the 391 markets, nothing on the rest.",
          f"- **Round trip:** {num(a1.mean_cost_points)} points per trade on average; {a1.cost_bp_of_capital:,.0f} bp of the capital of a trade at 1×, "
          f"{a2.cost_bp_of_capital:,.0f} bp at 2×.",
          f"- **Print check:** {int(a1.checkable_trades)} of the {int(a1.trades)} primary entries are recent enough for the data API to serve "
          f"their prints; {int(a1.verified_trades)} have a print at the assumed price or better within 10 minutes of Sunday 17:55"
          + (f", averaging {pts(a1.mean_net_points_verified)} points {ci(a1.ci_lo_verified, a1.ci_hi_verified)}." if a1.verified_trades else "."), "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Every variant tried", "", md_table(vt, vcols), "",
          "V1: 10 points or more. V2: crude oil only. V3: exit on Sunday at 19:00. V4: follow the move instead of fading it. "
          "The deflated Sharpe probability uses 5 trials.", "",
          "## What didn't work", "",
          f"- **The primary fade.** {pts(a1.mean_net_points)} points per trade {ci(a1.ci_lo, a1.ci_hi)}; out-of-sample {pts(o1.mean_net_points)}.",
          f"- **Closing an hour after futures reopen (V3).** {pts(row('ALL', 'V3', 1.0).mean_gross_points)} before costs, "
          f"{pts(row('ALL', 'V3', 1.0).mean_net_points)} after: the give-back is not there yet on Sunday evening.",
          f"- **Following the move (V4).** {pts(row('ALL', 'V4', 1.0).mean_net_points)} points per trade.",
          f"- **Oil only (V2).** Positive in-sample, {pts(v2o.mean_net_points)} out-of-sample.",
          f"- **Concentration.** The primary's best weekend made ${by_w.iloc[-1]:,.0f} and its worst lost ${-by_w.iloc[0]:,.0f}, against a total of "
          f"{'-' if a1.pnl < 0 else '+'}${abs(a1.pnl):,.0f}.", "",
          "## Caveats", "",
          f"- One year and one theme: {bc.get('crude', 0)} of the {meta['market_weekends']:,} market-weekends are oil, most of them from March to "
          "June 2026.",
          "- Prices are mids. The half-spreads come from one night of much smaller markets than last spring's.",
          "- The strikes of one asset on one weekend are one bet; intervals resample weekends for that reason.",
          "- T2's link directions are model judgements (S4 and S5).", "",
          "## Reproduce", "", "```", "cd research", "python -m s9_weekend_price_markets.universe      # catalogue only; already committed",
          "python -m s9_weekend_price_markets.run --pull", "python -m s9_weekend_price_markets.run", "python -m s9_weekend_price_markets.report",
          "python -m pytest s9_weekend_price_markets/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    cap = ["# S9 capacity", "",
           "- **Size at the best price on a weekend** (live books, Sat 2026-10-03 22:13 New York time, markets priced between 10% and 90%): "
           "crude oil a median of **$20** across 7 markets (from $1 to $256), with a spread of 1.0 point. This month's oil markets have traded "
           "$0.6 million; April 2026's traded $61 million, so spring books were deeper, by an amount that cannot be recovered.",
           f"- **The trade as run:** 100 contracts, ${p.capital.mean():,.0f} of capital on average, at most {cfg.MAX_POSITIONS} trades a weekend; "
           f"{len(p)} trades on {p.weekend.nunique()} weekends.",
           (f"- **Printed sizes behind the verified entries:** median {ver.verify_size.median():,.0f} shares on {len(ver)} entries."
            if len(ver) else "- **No entry is print-verified.**"),
           "- The trade does not pay after costs, so capacity is not the binding question.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
