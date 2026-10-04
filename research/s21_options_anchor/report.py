"""S21 report: SUMMARY.md, capacity.md and the three charts, every number read back from the result CSVs.

Run from `research/`:  python -m s21_options_anchor.report
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

from s8_open_referee.report import ci, md_table, num, pts  # noqa: E402

from . import config as cfg  # noqa: E402
from .pull import S18  # noqa: E402
from .run import BUCKETS, RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
SERIES = {"B0": "#2a78d6", "U": "#eb6834", "B1": "#1baf7a"}        # validated order: blue, orange, aqua (B2 took two markets and is not drawn)
NAMES = {"B0": "B0: sell, 5+ points above the central anchor", "B1": "B1: sell, 10+ points above the central anchor",
         "B2": "B2: buy, 5+ points below the lower-bound anchor", "U": "U: sell every anchored market (S18's book)",
         "U-all": "U-all: sell every stock and S&P market (S18's book)", "R1": "R1: B0 without zero-bid anchors",
         "U-left": "the anchored markets B0 leaves"}


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.axhline(0, color=INK2, linewidth=1)
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)


def chart_buckets(t1: pd.DataFrame) -> None:
    b = t1[(t1.anchor == "central") & t1.gap_bucket.isin(BUCKETS)].set_index("gap_bucket").reindex(BUCKETS)
    fig, ax = plt.subplots(figsize=(9.5, 4.8), facecolor=SURFACE)
    style(ax)
    x = np.arange(len(b))
    y = b.buyers_pnl_points.to_numpy(float)
    ax.bar(x, np.nan_to_num(y), width=0.56, color=SERIES["B0"], edgecolor=SURFACE, linewidth=2)
    for i, r in enumerate(b.itertuples()):
        if r.markets != r.markets or r.markets == 0:
            ax.annotate("no markets", (i, 0), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=9, color=INK2)
            continue
        has = r.ci_lo == r.ci_lo
        if has:
            ax.plot([i, i], [r.ci_lo, r.ci_hi], color=INK, linewidth=1.4, solid_capstyle="butt")
            for e in (r.ci_lo, r.ci_hi):
                ax.plot([i - 0.07, i + 0.07], [e, e], color=INK, linewidth=1.4)
        ax.annotate(f"{y[i]:+.1f}" + ("" if has else " (no interval: under 5 events)"), (i + 0.28, y[i]), xytext=(6, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=10, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{k}\n{int(r.markets) if r.markets == r.markets else 0} markets, {int(r.events) if r.events == r.events else 0} events\n"
                        f"paid {num(r.mean_traded_price, 0)}%, anchor {num(r.mean_anchor, 0)}%" for k, r in zip(BUCKETS, b.itertuples())], fontsize=8.5, color=INK2)
    ax.set_xlabel("Buyers' traded price minus the central options anchor, points", fontsize=9, color=INK2)
    ax.set_ylabel("points per contract, after the fee", fontsize=9, color=INK2)
    ax.set_title("S21: what buyers of YES made, held to the result, by how far they paid above the options anchor\n"
                 "(bars: mean; whiskers: 95% interval, resampling events)", loc="left", fontsize=10.5, color=INK)
    ax.margins(y=0.08)
    ax.set_xlim(-0.6, len(b) - 0.25)
    fig.tight_layout()
    fig.savefig(R / "gap_buckets.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def chart_books(eq: pd.DataFrame, oos_from: str) -> None:
    for name, title, dd in (("equity_curve.png", "cumulative P&L after fees", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.6), facecolor=SURFACE)
        style(ax)
        ends = []
        for bid, color in SERIES.items():
            e = eq[eq.book == bid].sort_values("result_month")
            if not len(e) or not (e.capital_base.iloc[0] > 0):
                continue
            xx = pd.to_datetime(e.result_month + "-01")
            y = np.cumsum(e.pnl.to_numpy()) / e.capital_base.iloc[0] * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
            ax.plot(xx, y, color=color, linewidth=2, label=NAMES[bid], solid_capstyle="round", marker="o", markersize=4)
            ends.append((y[-1] if not dd else y.min(), xx.iloc[-1], y[-1], bid))
        if dd:
            ax.annotate("Deepest: " + ", ".join(f"{bid} {val:.1f}%" for val, _, _, bid in ends) + ". A book with no losing month lies on zero.",
                        (0.0, 0.0), xycoords="axes fraction", xytext=(12, 78), textcoords="offset points", ha="left", va="bottom", fontsize=9, color=INK)
        else:
            for val, x_, y_, bid in ends:
                ax.annotate(f"{bid} {val:+.0f}%", (x_, y_), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(oos_from)
        ax.axvline(split, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
        ax.annotate("S18's out-of-sample events start ▸", (split, 1.0), xycoords=("data", "axes fraction"), xytext=(-5, -4),
                    textcoords="offset points", va="top", ha="right", fontsize=8.5, color=INK2)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.margins(x=0.14)
        if dd:
            ax.set_ylim(min(ax.get_ylim()[0], -5.0), 1.0)
        ax.set_ylabel("% of each book's capital base", fontsize=9, color=INK2)
        ax.set_title(f"S21 books at traded prices: {title}, booked in the month of the result", loc="left", fontsize=11, color=INK)
        ax.legend(loc="upper left" if not dd else "lower left", frameon=False, fontsize=8.5, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def money(x: float) -> str:
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.0f}"


def pc(x: float, d: int = 1) -> str:
    return "n/a" if x != x else f"{100 * x:.{d}f}%"


def main() -> int:
    meta = json.loads((R / "run_meta.json").read_text())
    s18 = json.loads((S18 / "run_meta.json").read_text())
    t1, sl, t2 = pd.read_csv(R / "t1_buckets.csv"), pd.read_csv(R / "t1_slope.csv"), pd.read_csv(R / "t2_regression.csv")
    m, imp, eq = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "improvement.csv"), pd.read_csv(R / "equity.csv")
    anc, tr, ck = pd.read_csv(R / "anchors.csv"), pd.read_csv(R / "trades.csv"), pd.read_csv(R / "checks.csv")

    def chk(check, item):
        return ck[ck.check.str.startswith(check) & ck.item.str.startswith(item)].iloc[0]
    chart_buckets(t1)
    chart_books(eq, s18["oos_from"])

    def row(book, seg, c=1.0):
        return m[(m.book == book) & (m.segment == seg) & (m.fee_mult == c)].iloc[0]

    def stat(r):
        return f"{pts(r.mean_pnl_points)} points {ci(r.ci_lo, r.ci_hi)} on {int(r.markets)} markets in {int(r.events)} events"

    def coef(model, term):
        return t2[(t2.kind == "regression") & (t2.model == model) & (t2.term == term)].iloc[0]

    def brier(name):
        return t2[(t2.kind != "regression") & (t2.model == name)].iloc[0]

    b0a, b0i, b0o, b0a2, b0i2, b0o2 = row("B0", "ALL"), row("B0", "IS"), row("B0", "OOS"), row("B0", "ALL", 2.0), row("B0", "IS", 2.0), row("B0", "OOS", 2.0)
    ua, ui, uo = row("U", "ALL"), row("U", "IS"), row("U", "OOS")
    la = row("U-left", "ALL")
    sc, slw = sl[sl.anchor == "central"].iloc[0], sl[sl.anchor == "lower"].iloc[0]
    M2 = "result on central anchor and traded price"
    ca, cp = coef(M2, "anchor_central"), coef(M2, "price")
    ML = "result on lower-bound anchor and traded price"
    la_, lp_ = coef(ML, "anchor_lower"), coef(ML, "price")
    br_p, br_c, br_l = brier("traded price"), brier("central anchor"), brier("lower-bound anchor")
    bd_c, bd_l = brier("traded price minus central anchor"), brier("traded price minus lower-bound anchor")
    means = t2[t2.kind == "means"].iloc[0]
    im = imp.set_index("segment")
    every = t1[(t1.anchor == "central") & (t1.gap_bucket == "every gap")].iloc[0]
    tb = t1[(t1.anchor == "central") & t1.gap_bucket.isin(BUCKETS)].set_index("gap_bucket").reindex(BUCKETS)

    lines = [("(1) in-sample mean P&L above zero, interval excluding zero", bool(b0i.mean_pnl_points > 0 and b0i.ci_lo > 0), stat(b0i)),
             ("(2) out-of-sample mean P&L above zero, interval excluding zero", bool(b0o.mean_pnl_points > 0 and b0o.ci_lo > 0),
              stat(b0o) + ("" if b0o.ci_lo == b0o.ci_lo else " (under 5 events: no interval can be drawn)")),
             ("(3) above zero with the fee doubled, in-sample and out-of-sample", bool(b0i2.mean_pnl_points > 0 and b0o2.mean_pnl_points > 0),
              f"in-sample {pts(b0i2.mean_pnl_points)}, out-of-sample {pts(b0o2.mean_pnl_points)}"),
             (f"(4) at least {cfg.MIN_OOS_MARKETS} out-of-sample markets in the book", bool(b0o.markets >= cfg.MIN_OOS_MARKETS),
              f"{int(b0o.markets)} markets: too few" if b0o.markets < cfg.MIN_OOS_MARKETS else f"{int(b0o.markets)} markets")]
    passed = all(x[1] for x in lines)
    failed = "; ".join(a.split(") ", 1)[0] + ")" for a, ok, _ in lines if not ok)

    dose = sc.slope_points_per_point < 0 and sc.boot_hi < 0
    carries = ca.ci_lo > 0 and ca.value > cp.value
    better = bd_c.value > 0 and bd_c.ci_lo > 0
    worse = bd_c.value < 0 and bd_c.ci_hi < 0
    improves = im.loc["ALL"].difference_points > 0 and im.loc["ALL"].ci_lo > 0
    status = pd.Series(meta["status"])
    not_ok = status.drop("ok", errors="ignore")
    zero = int(meta["zero_bid_leg"])

    btab = md_table(pd.DataFrame([{"B": k, "N": int(r.markets), "E": int(r.events), "G": pts(r.mean_gap_points, 1), "P": num(r.mean_traded_price, 1),
                                   "A": num(r.mean_anchor, 1), "Y": num(r.share_yes, 1), "L": pts(r.buyers_pnl_points), "CI": ci(r.ci_lo, r.ci_hi)}
                                  for k, r in list(zip(BUCKETS, tb.itertuples())) + [("every gap", every)]]),
                    {"B": "Gap (buyers' price minus central anchor), points", "N": "Markets", "E": "Events", "G": "Mean gap", "P": "Mean price paid, %",
                     "A": "Mean central anchor, %", "Y": "Resolved YES, %", "L": "Buyers' P&L, points", "CI": "95% interval"})
    tl = t1[(t1.anchor == "lower")]
    ltab = md_table(tl.assign(B=tl.gap_bucket, N=tl.markets.astype(int), E=tl.events.astype(int), P=tl.mean_traded_price.map(lambda v: num(v, 1)),
                              A=tl.mean_anchor.map(lambda v: num(v, 1)), Y=tl.share_yes.map(lambda v: num(v, 1)), L=tl.buyers_pnl_points.map(pts),
                              CI=tl.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1)),
                    {"B": "Gap (buyers' price minus lower-bound anchor), points", "N": "Markets", "E": "Events", "P": "Mean price paid, %",
                     "A": "Mean lower-bound anchor, %", "Y": "Resolved YES, %", "L": "Buyers' P&L, points", "CI": "95% interval"})
    reg = t2[t2.kind == "regression"]
    rtab = md_table(reg.assign(M=reg.model, T=reg.term.replace({"anchor_central": "central anchor", "anchor_lower": "lower-bound anchor", "price": "traded price"}),
                               V=reg.value.map(lambda v: f"{v:+.3f}"), SE=reg.clustered_se.map(lambda v: f"{v:.3f}"), TT=reg.t.map(lambda v: f"{v:+.2f}"),
                               CI=reg.apply(lambda r: f"[{r.ci_lo:+.3f}, {r.ci_hi:+.3f}]", axis=1)),
                    {"M": "Regression", "T": "Term", "V": "Coefficient", "SE": "Clustered error", "TT": "t", "CI": "95% interval"})
    order = ["B0", "B1", "B2", "R1", "U", "U-left", "U-all"]
    mm = m.assign(o=m.book.map({k: i for i, k in enumerate(order)})).sort_values(["o", "fee_mult", "segment"])
    mtab = md_table(mm.assign(B=mm.book.map(NAMES), S=mm.segment.replace({"IS": "in-sample", "OOS": "out-of-sample", "ALL": "all"}), C=mm.fee_mult.map(lambda v: f"{v:.0f}×"),
                              N=mm.markets.astype(int), E=mm.events.astype(int), L=mm.mean_pnl_points.map(pts), CI=mm.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1),
                              P=mm.mean_traded_price.map(lambda v: num(v, 1)), A=mm.mean_anchor.map(lambda v: num(v, 1)), Y=mm.share_yes.map(lambda v: num(v, 1)),
                              D=mm.pnl.map(money), K=mm.capital_base.map(lambda v: "n/a" if v != v else f"${v:,.0f}"), SH=mm.sharpe.map(num),
                              MD=mm.max_drawdown.map(pc), WM=mm.worst_month.map(pc), MO=mm.months.map(lambda v: "n/a" if v != v else f"{int(v)}")),
                    {"B": "Book", "S": "Segment", "C": "Fee", "N": "Markets", "E": "Events", "L": "P&L per contract, points", "CI": "95% interval",
                     "P": "Mean traded price, %", "A": "Mean anchor, %", "Y": "Resolved YES, %", "D": "Book P&L", "K": "Capital base",
                     "SH": "Sharpe (monthly)", "MD": "Max DD", "WM": "Worst month", "MO": "Months"})
    itab = md_table(imp.assign(S=imp.segment.replace({"IS": "in-sample", "OOS": "out-of-sample", "ALL": "all"}), T=imp.taken_markets.astype(int),
                               L=imp.left_markets.astype(int), TM=imp.taken_mean_points.map(pts), LM=imp.left_mean_points.map(pts),
                               D=imp.difference_points.map(pts), CI=imp.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1)),
                    {"S": "Segment", "T": "Markets B0 takes", "TM": "Their P&L, points", "L": "Anchored markets B0 leaves", "LM": "Their P&L, points",
                     "D": "Difference", "CI": "95% interval"})
    tk = pd.DataFrame([{"T": k, "N": v["markets"], "A": v["anchored"]} for k, v in sorted(meta["by_ticker"].items(), key=lambda kv: -kv[1]["markets"])])
    ok = anc[anc.status == "ok"]
    seg_name = {"IS": "in-sample", "OOS": "out-of-sample", "ALL": "whole sample"}
    high_sharpe = [f"{r.book} {seg_name[r.segment]} {r.sharpe:.2f} ({int(r.markets)} markets)" for r in m.itertuples()
                   if r.fee_mult == 1.0 and r.sharpe == r.sharpe and abs(r.sharpe) >= 2.995]

    S = ["# S21: does the options chain tell which \"will it hit\" tickets are overpriced?", "",
         "Method, pre-registered before any option quote was pulled: [`research/s21_options_anchor/METHOD.md`](../../s21_options_anchor/METHOD.md) "
         f"(commit `df3cb4a`). Data: the {meta['markets_in_s18_file']} stock and S&P 500 price markets of S18's traded-price file, their first weekends from "
         f"{anc.anchor_day.min()} to {anc.anchor_day.max()}; real NBBO option quotes from Massive at 15:55 New York on the Friday before. Files: "
         "[`anchors.csv`](anchors.csv), [`t1_buckets.csv`](t1_buckets.csv), [`t1_slope.csv`](t1_slope.csv), [`t2_regression.csv`](t2_regression.csv), "
         "[`metrics.csv`](metrics.csv), [`improvement.csv`](improvement.csv), [`trades.csv`](trades.csv), [`checks.csv`](checks.csv), [`capacity.md`](capacity.md), "
         "[`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", ""]
    ktab = md_table(ck.assign(C=ck.check, I=ck["item"], V=ck.value.map(lambda x: f"{x:+.3f}"),
                              CI=ck.apply(lambda r: "" if r.lo != r.lo else f"[{r.lo:+.2f}, {r.hi:+.2f}]", axis=1),
                              N=ck.n.map(lambda x: "" if x != x else f"{x:,.0f}"), NO=ck.note.fillna("")),
                    {"C": "Check", "I": "What", "V": "Value", "CI": "Interval or range", "N": "n", "NO": "Note"})
    S += ANSWER({**locals(), "money": money, "pc": pc})
    S += ["", "## How many markets", "",
          f"- In S18's file: {meta['markets_in_s18_file']} stock and S&P markets. Parsed (ticker, level, direction, window end): {meta['parsed']}; dropped in parsing: "
          f"{sum(meta['dropped_in_parsing'].values())}.",
          f"- Anchored with two real leg quotes: **{meta['anchored']}** in {meta['anchored_events']} events ({meta['anchored_by_segment'].get('IS', 0)} in-sample, "
          f"{meta['anchored_by_segment'].get('OOS', 0)} out-of-sample). With a first-weekend taker purchase: {meta['anchored_with_a_taker_purchase']}; with a taker "
          f"sale: {meta['anchored_with_a_taker_sale']}.",
          "- Not anchored: " + ("; ".join(f"{int(n)}: {k}" for k, n in not_ok.items()) if len(not_ok) else "none") + ".",
          f"- Of the anchors, {zero} used a leg with a zero bid, {meta['stepped']} moved a leg outward, {meta['noarb_violation']} had a mid outside 0 to 1 before "
          f"clamping. Expiry tried first / second / third: {meta['expiry_rank_counts'].get('1', 0)} / {meta['expiry_rank_counts'].get('2', 0)} / "
          f"{meta['expiry_rank_counts'].get('3', 0)}; the expiry is a median of {num(meta['median_days_expiry_after_end'], 0)} days after the window's last "
          f"session (at most {num(meta['max_days_expiry_after_end'], 0)}). The band from bid and ask is a median of {num(meta['median_band_width_points'], 1)} "
          "points wide on the finish-beyond probability (twice that on the central anchor).", "",
          md_table(tk, {"T": "Ticker", "N": "Markets", "A": "Anchored"}), "",
          "## T1: dose and response (buyers' P&L by gap against the central anchor)", "", btab, "",
          f"Slope of buyers' P&L on the gap: **{sc.slope_points_per_point:+.3f} points of P&L per point of gap** (clustered error {sc.clustered_se:.3f}, "
          f"t = {sc.t:+.2f}; event-bootstrap interval [{sc.boot_lo:+.3f}, {sc.boot_hi:+.3f}]; {int(sc.markets)} markets, {int(sc.events)} events). "
          "The thesis predicts a negative slope.", "", "![Buyers' P&L by gap bucket](gap_buckets.png)", "",
          "Secondary, against the lower-bound anchor (slope "
          f"{slw.slope_points_per_point:+.3f}, t = {slw.t:+.2f}, interval [{slw.boot_lo:+.3f}, {slw.boot_hi:+.3f}]):", "", ltab, "",
          "## T2: which price knows more", "",
          f"{int(means.markets)} anchored markets with a first-weekend print, {int(means.events)} events. Mean traded price {num(means.value, 1)}%, mean central anchor "
          f"{num(means.ci_lo, 1)}%, mean lower-bound anchor {num(means.ci_hi, 1)}%, resolved YES {num(means.t, 1)}%.", "", rtab, "",
          "| Forecast | Brier score (lower is better) |", "|---|---|",
          f"| traded price | {br_p.value:.4f} |", f"| central anchor (twice the finish-beyond probability) | {br_c.value:.4f} |",
          f"| lower-bound anchor (the finish-beyond probability) | {br_l.value:.4f} |", "",
          f"Brier difference, traded price minus central anchor (positive = the anchor is better): **{bd_c.value:+.4f}** [{bd_c.ci_lo:+.4f}, {bd_c.ci_hi:+.4f}]. "
          f"Traded price minus lower-bound anchor: {bd_l.value:+.4f} [{bd_l.ci_lo:+.4f}, {bd_l.ci_hi:+.4f}].", "",
          "## T3: the PolyBridge rule as books", "", mtab, "",
          "Books by S18's own function: up to 100 contracts per market, never more than the printed size; P&L booked in the month of the result; the capital base is "
          "the largest capital locked at one time; Sharpe on monthly P&L. P&L per contract weighs each market once. Many of these markets charge no fee, so the 2× "
          "rows differ little.", "",
          "### Does the anchor improve S18's unfiltered book?", "", itab, "",
          f"The out-of-sample row rests on {int(im.loc['OOS'].taken_markets)} taken markets; its interval is a resampling artefact of so few and says nothing.", "",
          "### The pass rule (fixed before the pull)", "", "| Needed | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'met' if okk else '**not met**'} | {e} |" for a, okk, e in lines]
    S += ["", f"**Verdict: {'pass (a lead needing a replication, not an edge)' if passed else 'not a pass'}.**" + ("" if passed else f" Lines not met: {failed}."), "",
          "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
          "Each point is a calendar month, as a percentage of that book's own capital base (the largest capital locked at one time). B2 took two markets and is not "
          "drawn. In the table, rows with one or three months (the out-of-sample rows, B2) are there for completeness: a \"worst month\" above zero means no month "
          "lost, and a Sharpe on three months means nothing.", "",
          "## Bug hunt and checks added after the result (not pre-registered; METHOD.md amendment 2)", "",
          "Books showed a Sharpe above 3, so the result was hunted for a bug before it was written up. None of these checks is one of the three tests, none "
          "changed a rule, and all of them were run once and are all listed.", "", ktab, "",
          "## Costs", "",
          "- The Polymarket price is the print (S18's size-weighted traded price of one taker side over the first weekend), so no spread is assumed. The fee is the "
          "market's own taker fee, 0.04 × P × (1 − P) where the market charges one; nothing is paid at the result. At 2× the fee is doubled.",
          "- The option side is a yardstick. Nothing is traded there, so no option cost enters.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Caveats", "",
          "- **We were not blind to the results**, only to the anchor: S18's file already held every market's result and traded prices.",
          f"- **The anchor itself ran above the results this year.** On the anchored markets with a taker sale the central anchor averaged {num(ua.mean_anchor, 1)}% "
          f"and the sellers' traded price {num(ua.mean_traded_price, 1)}%, while {num(ua.share_yes, 1)}% resolved YES. So part of what a seller earned is the premium "
          "any seller of listed options earns when moves come in smaller than the options implied, plus the reflection rule's upward lean. Only the part above the "
          "anchor is special to Polymarket, and that is what T1 and B0 measure.",
          "- **The central anchor is an approximation.** Twice the finish-beyond probability is the reflection rule for a touch; it ignores drift, and the expiry is at "
          "or after the question's end, which makes the anchor a little high. Stock and SPY options are American and are read as if European.",
          "- **The anchor is taken at 15:55 on Friday; the tickets traded from Friday 20:00 to Sunday 20:00.** News in between moves the ticket and not the anchor.",
          "- **The traded price is an average over a weekend of prints**, not one fill; a seller could not have chosen only the best of them.",
          "- **One year, 18 Fridays.** Markets on the same Friday share the same market weather; resampling events does not cure that.",
          f"- **A zero bid was accepted on a leg** ({zero} anchors), a stated difference from the existing code; R1 reruns the primary without them.",
          f"- **The loss on one contract can be several times the gain.** B0's worst market lost {num(-chk('subsets', 'B0 worst').value, 1)} points; "
          f"{num(100 * chk('subsets', 'B0 share').value, 0)}% of its markets made money. It is selling insurance against large moves.",
          "- **Small prints count as much as large ones** in the per-contract means (each market once). Weighted by the contracts the book holds B0 earned "
          f"{pts(chk('subsets', 'B0 weighted').value)} points per contract.",
          "- " + ("**A Sharpe above 3 appears in: " + ", ".join(high_sharpe) + ".** It comes from ten or eleven monthly numbers with one losing month; see the bug "
                  "hunt above and RUN_LOG.md. Do not read it as the Sharpe of a strategy." if high_sharpe else "No book shows a Sharpe above 3 in absolute value."), "",
          "## Reproduce", "", "```", "cd research", "python -m s21_options_anchor.pull      # Massive, 2 requests a second, resumable", "python -m s21_options_anchor.run",
          "python -m s21_options_anchor.checks     # the bug hunt, added after the result", "python -m s21_options_anchor.report", "python -m pytest s21_options_anchor/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))

    b0t = tr[tr.book == "B0"]
    cap = ["# S21 capacity", "",
           f"- **Printed size behind B0:** a median of {b0t.printed_size.median():,.0f} contracts sold into bids per market over its first weekend (quartiles "
           f"{b0t.printed_size.quantile(.25):,.0f} to {b0t.printed_size.quantile(.75):,.0f}); in dollars of premium, a median of "
           f"${(b0t.printed_size * b0t.traded_price).median():,.0f} per market." if len(b0t) else "- B0 took no market.",
           f"- **The book as run:** up to 100 contracts per market, {int(b0a.markets)} markets, a capital base of ${b0a.capital_base:,.0f}, "
           f"${b0a.mean_capital:,.0f} of capital per market on average, locked a median of {b0a.median_days_locked:.0f} days; book P&L {money(b0a.pnl)}.",
           f"- **The ceiling the prints prove:** every contract takers sold into bids in B0's markets over those weekends: {b0t.printed_size.sum():,.0f} contracts, "
           f"${(b0t.printed_size * b0t.traded_price).sum():,.0f} of premium; held to the result those sales made "
           f"{money((b0t.printed_size * b0t.pnl_points / 100).sum())}. They were other people's sales: a newcomer hitting the same bids would have moved them.",
           "- This is a trade of tens of dollars per market as run, about ten thousand dollars a year at the ceiling. The prints show what did trade at these "
           "prices, not what else could have been sold; a taker's sale needs a bid.",
           "- The option side is not traded, so listed-option liquidity does not limit the book; it limits only how precisely the anchor is known "
           f"(median band {num(meta['median_band_width_points'], 1)} points on the finish-beyond probability).", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:16]))
    return 0


def ANSWER(v: dict) -> list[str]:
    """The plain-language answer, every number from the result files (the local variables of main)."""
    from .answer import answer
    return answer(v)


if __name__ == "__main__":
    sys.exit(main())
