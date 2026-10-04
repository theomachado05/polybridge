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

from .run import BUY, RESULTS as R, SELL  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def charts(sell_m: pd.DataFrame, buy_m: pd.DataFrame, k_sell: float, k_buy: float, oos_from: str) -> None:
    series = (("Sold YES at traded bids, held to the result", BLUE, pd.to_datetime(sell_m.result_month + "-01"), np.cumsum(sell_m.pnl.to_numpy()) / k_sell * 100),
              ("Bought YES at traded asks, held to the result", ORANGE, pd.to_datetime(buy_m.result_month + "-01"), np.cumsum(buy_m.pnl.to_numpy()) / k_buy * 100))
    for name, title, dd in (("equity_curve.png", "cumulative P&L after fees", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for label, color, xx, y in series:
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{label.split(' at ')[0].lower()} {y.min():.0f}%")
            ax.plot(xx, y, color=color, linewidth=2, label=label, solid_capstyle="round", marker="o", markersize=3.5)
            if not dd:
                ax.annotate(f"{y[-1]:+.0f}%", (xx.iloc[-1], y[-1]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(oos_from)
        ax.axvline(split, color=INK2, linewidth=1)
        ax.annotate("out-of-sample events start ▸", (split, 0.0 if dd else 1.0), xycoords=("data", "axes fraction"), xytext=(-5, 5 if dd else -4),
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
        ax.set_ylabel("% of each book's capital base", fontsize=9, color=INK2)
        ax.set_title(f"S19, crypto price markets at traded prices: {title}, by month of the result", loc="left", fontsize=11, color=INK)
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.14 if dd else 0.02), frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    tt, bk, d = pd.read_csv(R / "tests.csv"), pd.read_csv(R / "book.csv"), pd.read_csv(R / "markets.csv")
    sell_m, buy_m = pd.read_csv(R / "book_monthly_sellers.csv"), pd.read_csv(R / "book_monthly_buyers.csv")
    meta = json.loads((R / "run_meta.json").read_text())

    def t(test, scope):
        return tt[(tt.test == test) & (tt.scope == scope)].iloc[0]

    def b(book, seg):
        return bk[(bk.book == book) & (bk.segment == seg)].iloc[0]

    s_all, s_is, s_oos, s_2x = t(SELL, "all markets"), t(SELL, "in-sample events"), t(SELL, "out-of-sample events"), t(SELL + ", fee doubled", "all markets")
    b_all, b_is, b_oos = t(BUY, "all markets"), t(BUY, "in-sample events"), t(BUY, "out-of-sample events")
    s25, s26 = t(SELL, "listed up to 2025-12-31"), t(SELL, "listed in 2026")
    sb, bb = b("sellers", "ALL"), b("buyers", "ALL")
    charts(sell_m, buy_m, float(sb.capital_base), float(bb.capital_base), meta["oos_from"])
    reading = [("Sellers' mean P&L above zero, interval excluding zero (whole sample)", s_all.mean_pnl_points > 0 and s_all.ci_lo > 0,
                f"{pts(s_all.mean_pnl_points)} points {ci(s_all.ci_lo, s_all.ci_hi)}"),
               ("Above zero in-sample", s_is.mean_pnl_points > 0, f"{pts(s_is.mean_pnl_points)} {ci(s_is.ci_lo, s_is.ci_hi)}"),
               ("Above zero out-of-sample", s_oos.mean_pnl_points > 0,
                f"{pts(s_oos.mean_pnl_points)} {ci(s_oos.ci_lo, s_oos.ci_hi)} on {int(s_oos.markets)} markets, {int(s_oos.events)} events"),
               ("Above zero with the fee doubled", s_2x.mean_pnl_points > 0, f"{pts(s_2x.mean_pnl_points)} {ci(s_2x.ci_lo, s_2x.ci_hi)}")]
    ok = all(bool(r[1]) for r in reading)
    verdict = "the premium replicates" if ok else "the premium does not replicate"
    ttab = md_table(tt.assign(T=tt.test, S=tt.scope, N=tt.markets.astype(int), E=tt.events.astype(int), P=tt.mean_traded_price.map(lambda x: num(x, 1)),
                              Y=tt.share_yes.map(lambda x: num(x, 1)), L=tt.mean_pnl_points.map(pts), CI=tt.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1),
                              Z=tt.median_size.map(lambda x: "n/a" if x != x else f"{x:,.0f}")),
                    {"T": "Test", "S": "Markets", "N": "Markets with such prints", "E": "Events", "P": "Mean traded price, %", "Y": "Resolved YES, %",
                     "L": "P&L per contract, points", "CI": "95% interval", "Z": "Median printed size"})
    btab = md_table(bk.assign(B=bk.book.map({"sellers": "Sold YES at traded bids", "buyers": "Bought YES at traded asks"}), S=bk.segment, T=bk.markets.astype(int),
                              E=bk.events.astype(int), P=bk.pnl.map(lambda x: f"{'-' if x < 0 else '+'}${abs(x):,.0f}"), K=bk.capital_base.map(lambda x: f"${x:,.0f}"),
                              SH=bk.sharpe.map(num), MD=bk.max_drawdown.map(pct), WM=bk.worst_month.map(pct), TO=bk.turnover_ann.map(lambda x: f"{x:.1f}×"),
                              W=bk.winners.map(lambda x: pct(x, 0)), WE=bk.worst_event.map(lambda x: f"{'-' if x < 0 else '+'}${abs(x):,.0f}"),
                              DL=bk.median_days_locked.map(lambda x: num(x, 0))),
                    {"B": "Book", "S": "Segment", "T": "Markets", "E": "Events", "P": "Net P&L", "K": "Capital base", "SH": "Sharpe (monthly)", "MD": "Max DD",
                     "WM": "Worst month", "TO": "Turnover / yr", "W": "Winners", "WE": "Worst event", "DL": "Median days locked"})
    lo = meta["left_out"]
    S = ["# S19: does the price-market premium replicate on crypto?", "",
         "Method, pre-registered before any print of these markets was pulled: "
         "[`research/s19_crypto_price_markets/METHOD.md`](../../s19_crypto_price_markets/METHOD.md) (commit `f5fe8e5`). "
         f"Data: {meta['markets_in_sample']:,} crypto price markets drawn at random, four per event, from {meta['events_in_sample']} weekly or longer events "
         f"listed from {meta['first_listing']} to {meta['last_listing']}; public prints of at least $50 in each market's first 48 hours. "
         "Files: [`tests.csv`](tests.csv), [`markets.csv`](markets.csv), [`book.csv`](book.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**By the rule fixed before the prints were pulled: {verdict}.**", "",
         f"**Sellers.** Takers who sold YES into a bid in a market's first 48 hours received {num(s_all.mean_traded_price, 1)}% on average; "
         f"{num(s_all.share_yes, 1)}% of those markets resolved YES. Held to the result: {pts(s_all.mean_pnl_points)} points per contract after the "
         f"fee, event-bootstrap 95% interval {ci(s_all.ci_lo, s_all.ci_hi)}, on {int(s_all.markets)} markets in {int(s_all.events)} events; "
         f"{pts(s_2x.mean_pnl_points)} with the fee doubled. In-sample {pts(s_is.mean_pnl_points)} {ci(s_is.ci_lo, s_is.ci_hi)}; out-of-sample "
         f"({meta['oos_events']} events from {meta['oos_from']}) {pts(s_oos.mean_pnl_points)} {ci(s_oos.ci_lo, s_oos.ci_hi)}. Listed up to the end "
         f"of 2025: {pts(s25.mean_pnl_points)} {ci(s25.ci_lo, s25.ci_hi)}; listed in 2026: {pts(s26.mean_pnl_points)} {ci(s26.ci_lo, s26.ci_hi)}.", "",
         f"**Buyers.** Takers who bought YES paid {num(b_all.mean_traded_price, 1)}% on average; {num(b_all.share_yes, 1)}% resolved YES. Held to "
         f"the result: {pts(b_all.mean_pnl_points)} points per contract {ci(b_all.ci_lo, b_all.ci_hi)} on {int(b_all.markets)} markets; in-sample "
         f"{pts(b_is.mean_pnl_points)} {ci(b_is.ci_lo, b_is.ci_hi)}, out-of-sample {pts(b_oos.mean_pnl_points)} {ci(b_oos.ci_lo, b_oos.ci_hi)}.", "",
         f"**As a book** (up to 100 contracts per market, never more than the printed size, P&L booked in the month of the result): selling made "
         f"{'-' if sb.pnl < 0 else '+'}${abs(sb.pnl):,.0f} on a capital base of ${sb.capital_base:,.0f} over {int(sb.months)} months, monthly Sharpe "
         f"{num(sb.sharpe)}, maximum drawdown {pct(sb.max_drawdown)}, worst month {pct(sb.worst_month)}, worst event "
         f"{'-' if sb.worst_event < 0 else '+'}${abs(sb.worst_event):,.0f}.", "",
         "**Set against S18** (oil, metals, the S&P 500 and stocks, one year): sellers +3.63 points [+0.72, +6.57] and -0.99 out-of-sample; buyers "
         "-8.87 [-11.94, -5.93].", "",
         "## The reading fixed before the prints were pulled", "", "| Needed | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'met' if c_ else '**not met**'} | {e} |" for a, c_, e in reading]
    S += ["", f"**{verdict[0].upper() + verdict[1:]}.**", "",
          "## Every cut that was fixed in advance", "",
          "One observation per market: the size-weighted mean price of the prints of one taker side in the market's first 48 hours, held to the "
          "result, after the market's own taker fee. Intervals resample events.", "", ttab, "",
          "## The two sides as books", "", btab, "",
          "The capital base is the largest capital locked at one time. In the charts each point is a calendar month; a market listed in-sample "
          "that resolves late is booked after the out-of-sample line.", "", "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
          "## Costs", "",
          "- The price is the print, so no spread is assumed. The fee is the market's own taker fee where it charges one "
          f"({int((d.fee_rate > 0).sum())} of the {len(d):,} markets checked); nothing is paid at the result.",
          f"- In bp of the capital locked, the fee averages {b('sellers', 'ALL').fee_bp_of_capital:.0f} bp for the sellers' book.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Markets left out", "",
          f"Of the {meta['markets_in_sample']:,} markets drawn, " + "; ".join(f"{n} because {k}" for k, n in lo.items()) + f". Of the {meta['markets_checked']:,} "
          f"checked, {meta['checked_with_no_print_in_the_window']} have no print of $50 or more in their first 48 hours, {meta['with_a_taker_sell']} have a "
          f"taker sale of YES and {meta['with_a_taker_buy']} a taker purchase.", "",
          "## Caveats", "",
          "- Crypto never shuts: this tests the premium, not the closed-market idea.",
          "- Prints under $50 are not seen.",
          "- Selling these markets is selling insurance against large moves; the loss on one contract can be many times the gain.",
          "- A taker's sale needs a bid. The prints show what traded, not what else could have.",
          "- Four markets per event, drawn at random before any print was seen.", "",
          "## Reproduce", "", "```", "cd research", "python -m s19_crypto_price_markets.universe      # catalogue only; already committed",
          "python -m s19_crypto_price_markets.run --pull", "python -m s19_crypto_price_markets.run", "python -m s19_crypto_price_markets.report",
          "python -m pytest s19_crypto_price_markets/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    ss = d[d.sell_prints > 0]
    cap = ["# S19 capacity", "",
           f"- **Printed size behind the sellers' test** (prints of $50 or more): a median of {ss.sell_size.median():,.0f} contracts sold into bids per "
           f"market in its first 48 hours (quartiles {ss.sell_size.quantile(.25):,.0f} to {ss.sell_size.quantile(.75):,.0f}); in dollars of premium, a "
           f"median of ${(ss.sell_size * ss.sell_price).median():,.0f} per market.",
           f"- **The book as run:** up to 100 contracts per market, {int(sb.markets)} markets, ${sb.mean_capital:,.0f} of capital per market on average, a "
           f"capital base of ${sb.capital_base:,.0f}, locked a median of {sb.median_days_locked:.0f} days.",
           "- The sample is four markets per event; the events hold about three times as many eligible markets.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
