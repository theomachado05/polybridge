"""S5 report: SUMMARY.md, equity_curve.png, drawdown.png and capacity.md from the result CSVs.

Run from `research/`:  python -m s5_big_moves.report
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
SERIES = (("V0", "V0 primary: 10 points, exit at the close", "#2a78d6"), ("V2", "V2: 5 points, exit at the close", "#eb6834"),
          ("V3", "V3: 10 points, weekends only", "#1baf7a"))


def money(x: float) -> str:
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.0f}"


def num(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def bp(x: float) -> str:
    return "n/a" if x != x else f"{x:+.1f} bp"


def md_table(df: pd.DataFrame, cols: dict) -> str:
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[k]) for k in cols) + " |")
    return "\n".join(out)


def charts(eq: pd.DataFrame, recent_from: str) -> None:
    for name, title, dd in (("equity_curve.png", "cumulative net P&L", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for vid, label, color in SERIES:
            e = eq[(eq.variant == vid) & (eq.cost_mult == 1.0)].sort_values("day")
            x, y = pd.to_datetime(e.day), e.pnl.to_numpy() / cfg.CAPITAL * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{vid} {y.min():.2f}%")
            ax.plot(x, y, color=color, linewidth=2, label=label, solid_capstyle="round")
            if not dd:
                ax.plot([x.iloc[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
                ax.annotate(f"{y[-1]:+.2f}%", (x.iloc[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(recent_from)
        ax.axvline(split, color=INK2, linewidth=1)
        ax.annotate("most recent 20% ▸", (split, 0.0 if dd else 1.0), xycoords=("data", "axes fraction"), xytext=(-5, 5 if dd else -4),
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
        ax.set_ylabel("% of the $100,000 book", fontsize=9, color=INK2)
        ax.set_title(f"S5 continuation trade on fresh markets, 1× costs: {title}", loc="left", fontsize=11, color=INK)
        ax.legend(loc="upper left" if not dd else "lower left", bbox_to_anchor=(0.0, 0.92) if not dd else (0.0, 0.14), frameon=False,
                  fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def intraday_section() -> list[str]:
    """S5b (amendment 2) and the give-back check (amendment 3); empty until `python -m s5_big_moves.intraday` has run."""
    if not (R / "intraday.csv").exists():
        return []
    it, z = pd.read_csv(R / "intraday.csv"), json.loads((R / "intraday.json").read_text())

    def jump(prefix, lab):
        r = it[it.test == f"{prefix} {lab}"].iloc[0]
        return f"{r['mean']:+.2f} [{r.ci_lo:+.2f}, {r.ci_hi:+.2f}]"

    def slope(prefix, lab):
        r = it[it.test == f"{prefix} the next {lab} on this bin's " + ("odds move" if prefix.startswith("odds") else "equity move")].iloc[0]
        return f"{r.slope:+.3f} (t {r.t:+.1f})"

    snap = json.loads((R / "pm_cost_snapshot.json").read_text()) if (R / "pm_cost_snapshot.json").exists() else None
    cost_txt = (f"{snap['round_trip_points_median_mid']:.1f} points (measured on the live books of {snap['mid_10_90']} open linked markets "
                f"priced between 0.10 and 0.90: one spread plus two fees, quartiles {snap['round_trip_points_p25_mid']:.1f} to "
                f"{snap['round_trip_points_p75_mid']:.1f}; ${snap['touch_dollars_median_mid']:,.0f} at the touch)") if snap else "2 to 4 points"
    labs = ["5 min", "15 min", "30 min", "60 min"]
    tbl = pd.DataFrame([{"H": lab, "A": jump("odds jump of 3+ points: equity over the next", lab),
                         "B": slope("odds first: equity over", lab), "C": jump("equity jump of 50+ bp: odds over the next", lab),
                         "D": slope("equity first: odds over", lab)} for lab in labs])
    t1, t2 = z["trade"][0], z["trade"][1]
    out = ["## Exploratory: who moves first inside the session? (S5b)", "",
           f"Designed after the S5 run (amendment 2). Regular session, 5-minute bins: {z['bins']:,} link-bins on {z['links']} links and "
           f"{z['dates']} dates; {z['odds_jumps']:,} bins with an odds jump of 3 points or more, {z['equity_jumps']:,} with an equity jump of "
           "50 bp or more.", "",
           md_table(tbl, {"H": "Next", "A": "After an odds jump: equity, bp", "B": "Equity on odds, bp per point",
                          "C": "After an equity jump: odds, points", "D": "Odds on equity, points per 100 bp"}), "",
           "- **Each leads the other a little, and neither by enough to trade.** After a 3-point jump in the odds the equity moves about "
           f"2 bp more over the next half hour. After a 50 bp jump in the equity the odds move about 0.1 point more.",
           f"- **The odds-first trade loses.** Entering the equity in the bin after an odds jump and holding 30 minutes: {t1['trades']:,} trades, "
           f"{t1['mean_gross_bp']:+.1f} bp before costs [{t1['gross_ci_lo']:+.1f}, {t1['gross_ci_hi']:+.1f}], {t1['mean_net_bp']:+.1f} bp after "
           f"[{t1['ci_lo']:+.1f}, {t1['ci_hi']:+.1f}]; {t2['mean_net_bp']:+.1f} bp at 2× costs.",
           "- **The equity-first direction is statistically clear (t about 5) and economically nothing:** 0.1 point of odds against a "
           f"Polymarket round trip of about {cost_txt}.", ""]
    if (R / "reversal.csv").exists():
        rv = pd.read_csv(R / "reversal.csv")

        def rr(scope, window, kind):
            return rv[(rv.scope == scope) & (rv.window == window) & (rv.kind == kind)].iloc[0]

        s1 = rr("all closures", "09:29 to the close", "slope, points per point")
        a5, a10 = rr("all closures", "09:29 to the close", "after an overnight move of 5+ points"), rr("all closures", "09:29 to the close", "after an overnight move of 10+ points")
        n10, w10 = rr("all closures", "09:29 to the next 09:29", "after an overnight move of 10+ points"), rr("weekends only", "09:29 to the close", "after an overnight move of 10+ points")
        out += ["## Exploratory: do the odds give back their overnight move? (amendment 3)", "",
                f"The 93 S5 markets, odds only. After an overnight move, the odds retrace part of it during the next session: slope "
                f"{s1.slope:+.3f} (t = {s1.t:.1f}, {int(s1.n):,} market-days).", "",
                "| Overnight move | Cases | Dates | Average move | Change by the close, signed by the move | By the next 09:29 |", "|---|---|---|---|---|---|",
                f"| 5 points or more | {int(a5.n)} | {int(a5.dates)} | {a5.mean_abs_move:.1f} points | {a5['mean']:+.2f} points [{a5.ci_lo:+.2f}, {a5.ci_hi:+.2f}] | "
                f"{rr('all closures', '09:29 to the next 09:29', 'after an overnight move of 5+ points')['mean']:+.2f} |",
                f"| 10 points or more | {int(a10.n)} | {int(a10.dates)} | {a10.mean_abs_move:.1f} points | {a10['mean']:+.2f} points [{a10.ci_lo:+.2f}, {a10.ci_hi:+.2f}] | "
                f"{n10['mean']:+.2f} [{n10.ci_lo:+.2f}, {n10.ci_hi:+.2f}] |",
                f"| 10 points or more, weekends only | {int(w10.n)} | {int(w10.dates)} | {w10.mean_abs_move:.1f} points | {w10['mean']:+.2f} points [{w10.ci_lo:+.2f}, {w10.ci_hi:+.2f}] | |", "",
                f"A give-back of about {abs(a10['mean']):.1f} points after a {a10.mean_abs_move:.0f}-point move is significant in this price series. "
                f"A round trip costs about {cost_txt}. So after 10-point moves the point estimate is a little above the cost and its "
                f"interval ({abs(a10.ci_hi):.1f} to {abs(a10.ci_lo):.1f} points) straddles it; after 5-point moves it is below the cost. "
                "Three reasons not to call it an edge: it is not significant by the next morning or on weekends alone; a give-back is "
                "exactly what bid-ask bounce in a history of last trades and midpoints looks like (S1 showed how far such prices can be "
                "from executable ones); and the size on offer at the touch is a few hundred dollars. Only recorded order books can settle it.", ""]
    return out


def main() -> int:
    m, rg, bk = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "regressions.csv"), pd.read_csv(R / "buckets.csv")
    tr = pd.read_csv(R / "trades.csv") if (R / "trades.csv").stat().st_size > 5 else pd.DataFrame(columns=["variant", "cost_mult"])
    eq, lk = pd.read_csv(R / "equity.csv"), pd.read_csv(R / "links.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    charts(eq, meta["recent_from"])

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    a1, a2, e1, r1 = row("all", cfg.PRIMARY, 1.0), row("all", cfg.PRIMARY, 2.0), row("earlier", cfg.PRIMARY, 1.0), row("recent", cfg.PRIMARY, 1.0)
    crit = [
        (f"At least {cfg.MIN_TRADES} trades on at least {cfg.MIN_DATES} dates and {cfg.MIN_TICKERS} tickers",
         a1.trades >= cfg.MIN_TRADES and a1.trade_dates >= cfg.MIN_DATES and a1.tickers >= cfg.MIN_TICKERS,
         f"{int(a1.trades)} trades, {int(a1.trade_dates)} dates, {int(a1.tickers)} tickers"),
        ("Mean net return per trade above zero, date-bootstrap 95% interval excluding zero (1× costs)", a1.mean_net_bp > 0 and a1.ci_lo > 0,
         f"{bp(a1.mean_net_bp)} [{num(a1.ci_lo, 1)}, {num(a1.ci_hi, 1)}]"),
        ("Mean net return above zero at 2× costs", a2.mean_net_bp > 0, bp(a2.mean_net_bp)),
        ("Mean net return above zero in both time segments", e1.mean_net_bp > 0 and r1.mean_net_bp > 0,
         f"earlier {bp(e1.mean_net_bp)} on {int(e1.trades)}; recent {bp(r1.mean_net_bp)} on {int(r1.trades)}"),
    ]
    few = not bool(crit[0][1])
    p2 = "pass" if all(bool(c[1]) for c in crit) else ("too few observations" if few else "not a pass")
    gap = rg[rg.relation == "opening gap on overnight odds move"].set_index("sample")
    aft = rg[rg.relation == "move after the open on overnight odds move"].set_index("sample")
    g0, f0 = gap.loc["all link-days"], aft.loc["all link-days"]
    post = "sessions from 2026-07-01 (after the labellers' knowledge)"
    gp = gap.loc[post] if post in gap.index else None
    p1 = g0.slope > 0 and g0.t >= cfg.P1_MIN_T and gp is not None and gp.slope > 0 and gp.t >= cfg.P1_MIN_T
    st = meta["label_stats"]

    def cell(r):
        return f"{r.slope:+.2f} (t {r.t:+.1f}, n {int(r.n):,})"

    reg_tbl = pd.DataFrame([{"S": s, "G": cell(gap.loc[s]), "A": cell(aft.loc[s]) if s in aft.index else "n/a"} for s in gap.index])
    bt = bk.assign(SC=bk.scope, M=bk.odds_move_pp + " points", N=bk.link_days.astype(int), D=bk.dates.astype(int),
                   G=bk.apply(lambda r: f"{r.signed_gap_bp:+.0f} bp [{r.gap_ci_lo:+.0f}, {r.gap_ci_hi:+.0f}]", axis=1),
                   S=bk.gap_same_sign.map(lambda x: f"{100 * x:.0f}%"),
                   A=bk.apply(lambda r: f"{r.signed_after_open_bp:+.0f} bp [{r.after_ci_lo:+.0f}, {r.after_ci_hi:+.0f}]", axis=1))
    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == cfg.PRIMARY, " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"),
                  T=m.trades.astype(int), K=m.tickers.astype(int), D=m.trade_dates.astype(int), P=m.pnl.map(money), N=m.mean_net_bp.map(bp),
                  CI=m.apply(lambda r: f"[{num(r.ci_lo, 1)}, {num(r.ci_hi, 1)}]", axis=1), G=m.mean_gross_bp.map(bp),
                  H=m.hit_rate.map(lambda x: "n/a" if x != x else f"{100 * x:.0f}%"), SH=m.sharpe.map(num),
                  DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(lambda x: f"{100 * x:.2f}%"),
                  WM=m.worst_month.map(lambda x: "n/a" if x != x else f"{100 * x:.2f}%"), TO=m.turnover_ann.map(lambda x: f"{x:.1f}×"))
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "K": "Tickers", "D": "Dates", "P": "Net P&L", "N": "Net per trade",
             "CI": "95% interval", "G": "Gross per trade", "H": "Winners", "SH": "Sharpe", "DS": "Deflated Sharpe prob.", "MD": "Max DD",
             "WM": "Worst month", "TO": "Turnover / yr"}
    used = lk[lk.status == "used"]
    by_t = used.groupby("ticker").size().sort_values(ascending=False)
    p = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)] if len(tr) else tr
    big = bk[(bk.scope == "all closures") & (bk.odds_move_pp == "10 or more")]

    S = ["# S5: do the S4 findings hold on markets S4 never used?", "",
         "Method, pre-registered before any S5 price was pulled: [`research/s5_big_moves/METHOD.md`](../../s5_big_moves/METHOD.md) "
         "(commit `3f0539e`). Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`links.csv`](links.csv), "
         "[`regressions.csv`](regressions.csv), [`buckets.csv`](buckets.csv), [`universe.csv`](universe.csv), [`capacity.md`](capacity.md), "
         "[`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**P1, the replication: {'replicates' if p1 else 'does not replicate'}.** On {meta['markets_in_test']} fresh markets linked to "
         f"{meta['tickers_in_test']} tickers ({meta['link_days']:,} link-days, {meta['dates_in_test']} dates), a 1-point overnight move in odds "
         f"comes with a {g0.slope:+.2f} bp excess gap in the linked equity at the open (t = {g0.t:.2f}; S4 found +4.69, t = 4.01). "
         f"After the open: {f0.slope:+.2f} bp per point (t = {f0.t:.2f}). On sessions from 2026-07-01, which the labelling models "
         f"cannot have seen (amendment 1): " + (f"{gp.slope:+.2f} bp per point (t = {gp.t:.2f}, {int(gp.n):,} link-days)." if gp is not None else "no data."), "",
         f"**P2, the trade: {p2}.** Buying (or shorting) the linked equity at the open after an overnight move of 10 points or more, "
         f"exit at the close: {int(a1.trades)} trades on {int(a1.tickers)} tickers and {int(a1.trade_dates)} dates, {bp(a1.mean_net_bp)} net per "
         f"trade at 1× costs (95% interval {num(a1.ci_lo, 1)} to {num(a1.ci_hi, 1)}), {bp(a1.mean_gross_bp)} before costs, "
         f"{bp(a2.mean_net_bp)} net at 2× costs. Sharpe {num(a1.sharpe)}, maximum drawdown {100 * a1.max_drawdown:.2f}% of a $100,000 book.", ""]
    if len(big):
        b0 = big.iloc[0]
        S += [f"After a move of 10 points or more the gap is {b0.signed_gap_bp:+.0f} bp in the direction of the odds "
              f"[{b0.gap_ci_lo:+.0f}, {b0.gap_ci_hi:+.0f}] ({int(b0.link_days)} link-days, {int(b0.dates)} dates, same sign "
              f"{100 * b0.gap_same_sign:.0f}%); S4 had +91 bp [+40, +145].", ""]
    S += ["## P1: the opening gap and the odds", "",
          md_table(reg_tbl, {"S": "Sample", "G": "Opening gap, bp per point", "A": "After the open, bp per point"}), "",
          "Through-origin slopes, errors clustered by date. The gap and the odds move are measured over the same closure: this is "
          "co-movement, not a forecast. The second column is the part a trade at the open could earn.", "",
          "## How big, by size of the overnight move", "",
          md_table(bt, {"SC": "Closures", "M": "Overnight odds move", "N": "Link-days", "D": "Dates", "G": "Gap, signed by the odds move",
                        "S": "Same sign", "A": "After the open, to the close"}), "",
          f"Share of link-days by move: " + ", ".join(f"{k} points {100 * v:.1f}%" for k, v in meta["share_moves"].items()) + ". "
          f"The gap's standard deviation is {meta['gap_sd_bp']:.0f} bp.", "",
          "## P2: the trade (primary V0)", "",
          md_table(vt[m.variant == cfg.PRIMARY], vcols), "",
          "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
          "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {p2}.**", "",
          *intraday_section(),
          "## The links", "",
          f"{meta['universe_counts']['events']:,} events scanned, {meta['universe_candidates']} markets eligible, the 240 with the largest volume "
          f"kept. Two blind labellers per question: both called {st['both_event']} of {st['questions']} questions an event; they agreed on "
          f"{st['agreed']} links (ticker and direction) across {st['markets_with_link']} markets, named a ticker the other did not "
          f"{st['named_by_one']} times, and named the same ticker with opposite directions {st['opposite_direction']} times. "
          f"{meta['links_with_data']} links have odds inside the window. Tickers with the most links: "
          + ", ".join(f"{t} {n}" for t, n in by_t.head(10).items()) + ".", "",
          "## Costs and capacity", "",
          f"Round trip on the primary's trades: {num(a1.mean_cost_bp, 1)} bp at 1×, {num(a2.mean_cost_bp, 1)} bp at 2× (per side: SPY "
          f"{cfg.COST_SPY:.0f} bp, liquid names {cfg.COST_LIQUID:.0f} bp, others {cfg.COST_OTHER:.0f} bp; sources in S4's METHOD section 3). "
          "Capacity: [`capacity.md`](capacity.md).", "",
          "## Every variant tried", "", md_table(vt, vcols), "",
          "The deflated Sharpe probability uses 4 trials. The whole S5 sample is out-of-sample for the rule (it was fixed on S4's "
          "markets); \"earlier\" and \"recent\" split it by time.", "",
          "## Caveats", "",
          "- Links are judgements of two models; agreement is not truth.",
          "- **Hindsight.** Most S5 markets have resolved, and one labeller said some of its links draw on how markets reacted at the "
          "time. Figures on sessions from 2026-07-01 are free of that; figures before it may be inflated.",
          "- A resolved market's last big move is the news itself, when the equity's own news flow is heaviest.",
          "- Fills at the first regular bar's open stand for the opening auction.",
          "- S4 and S5 overlap in calendar time: different markets, same market regimes.", "",
          "## Reproduce", "", "```", "cd research", "python -m s5_big_moves.universe", "python -m s5_big_moves.run links",
          "python -m s5_big_moves.run pull", "python -m s5_big_moves.run", "python -m s5_big_moves.report", "python -m pytest s5_big_moves/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))

    cap = ["# S5 capacity", ""]
    if len(p):
        g = p.groupby("ticker").agg(trades=("pnl", "size"), vol30=("vol30", "median")).reset_index()
        g["capacity"] = cfg.CAPACITY_SHARE * g.vol30
        g = g.sort_values("trades", ascending=False)
        cap += [f"Primary variant, {len(p)} trades. The position is ${cfg.NOTIONAL:,.0f}. Capacity is {100 * cfg.CAPACITY_SHARE:.0f}% of the "
                "median dollar volume in the first 30 minutes on the days traded.", "",
                md_table(g.assign(T=g.ticker, N=g.trades, B=g.vol30.map(lambda x: f"${x:,.0f}"), C=g.capacity.map(lambda x: f"${x:,.0f}")),
                         {"T": "Ticker", "N": "Trades", "B": "Median first 30 minutes", "C": "Capacity per position"}), "",
                f"Smallest capacity per position ${g.capacity.min():,.0f}; median ${g.capacity.median():,.0f}.", ""]
    else:
        cap += ["The primary variant made no trade.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:9]))
    print([bool(c[1]) for c in crit], p2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
