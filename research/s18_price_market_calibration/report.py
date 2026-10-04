from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s6_monday_fade.run import closure_metrics, write_csv  # noqa: E402
from s8_open_referee.report import ci, md_table, num, pct, pts  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS as R  # noqa: E402
from .run import max_locked  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE = "#2a78d6", "#eb6834"
SELL, BUY = "sellers: sold YES into a bid, held to the result", "buyers: bought YES at the ask, held to the result"


def book(pm: pd.DataFrame, entries: pd.DataFrame, side: str) -> tuple[pd.DataFrame, dict]:
    e = entries.set_index("market")
    col, pcol, zcol = f"{side}_pnl_points", f"{side}_price", f"{side}_size"
    s = pm[pm[col].notna()].copy()
    s["size"] = np.minimum(s[zcol], cfg.CONTRACTS)
    s["pnl"] = s["size"] * s[col] / 100.0
    s["capital"] = s["size"] * ((1.0 - s[pcol]) if side == "sell" else s[pcol])
    s["entry_epoch"] = s.market.map(e.entry_epoch)
    s["result_epoch"] = s.market.map(e.result_epoch)
    s["result_month"] = s.result_epoch.map(lambda x: datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m"))
    months = sorted(pd.period_range(s.result_month.min(), s.result_month.max(), freq="M").strftime("%Y-%m"))
    out = {}
    for seg in ("IS", "OOS", "ALL"):
        t = s if seg == "ALL" else s[s.segment == seg]
        ml = [m for m in months if t.result_month.min() <= m <= t.result_month.max()] if len(t) else []
        pc = np.array([t[t.result_month == m].pnl.sum() for m in ml])
        K = max_locked(t[["entry_epoch", "result_epoch", "capital"]].to_dict("records"))
        ev = t.groupby("event").pnl.sum()
        out[seg] = {**closure_metrics(pc, ml, K, float(t.capital.sum()), cfg.MONTHS_PER_YEAR), "capital_base": K, "trades": len(t),
                    "pnl": float(t.pnl.sum()), "months": len(ml), "winners": float((t.pnl > 0).mean()) if len(t) else float("nan"),
                    "worst_event": float(ev.min()) if len(ev) else float("nan"), "best_event": float(ev.max()) if len(ev) else float("nan"),
                    "mean_capital": float(t.capital.mean()) if len(t) else float("nan"),
                    "median_days_locked": float(((t.result_epoch - t.entry_epoch) / 86400).median()) if len(t) else float("nan")}
    monthly = s.groupby("result_month").pnl.sum().reindex(months).fillna(0.0)
    return monthly.reset_index().rename(columns={"index": "result_month"}), out


def charts(sell_m: pd.DataFrame, buy_m: pd.DataFrame, k_sell: float, k_buy: float, oos_from: str) -> None:
    x = pd.to_datetime(sell_m.result_month + "-01")
    xb = pd.to_datetime(buy_m.result_month + "-01")
    series = (("Sold YES at traded bids, held to the result", BLUE, x, np.cumsum(sell_m.pnl.to_numpy()) / k_sell * 100),
              ("Bought YES at traded asks, held to the result", ORANGE, xb, np.cumsum(buy_m.pnl.to_numpy()) / k_buy * 100))
    for name, title, dd in (("equity_curve.png", "cumulative P&L after fees", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for label, color, xx, y in series:
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{label.split(' at ')[0].lower()} {y.min():.0f}%")
            ax.plot(xx, y, color=color, linewidth=2, label=label, solid_capstyle="round", marker="o", markersize=4)
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
        ax.set_title(f"S18 at traded prices: {title}, booked in the month of the result", loc="left", fontsize=11, color=INK)
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.14 if dd else 0.02), frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m, cal, tt = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "calibration.csv"), pd.read_csv(R / "prints_tests.csv")
    pm, entries = pd.read_csv(R / "prints_markets.csv"), pd.read_csv(R / "entries.csv")
    meta, pmeta = json.loads((R / "run_meta.json").read_text()), json.loads((R / "prints_meta.json").read_text())

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    def t(test, scope):
        return tt[(tt.test == test) & (tt.scope == scope)].iloc[0]

    s_all, s_is, s_oos, s_2x = t(SELL, "all markets"), t(SELL, "in-sample events"), t(SELL, "out-of-sample events"), t(SELL + ", fee doubled", "all markets")
    b_all, b_is, b_oos = t(BUY, "all markets"), t(BUY, "in-sample events"), t(BUY, "out-of-sample events")
    s_mid, b_mid = t(SELL, "traded price 50 to 75%"), t(BUY, "traded price 50 to 75%")
    sell_m, sb = book(pm, entries, "sell")
    buy_m, bb = book(pm, entries, "buy")
    charts(sell_m, buy_m, sb["ALL"]["capital_base"], bb["ALL"]["capital_base"], meta["oos_from"])
    write_csv(R / "prints_book.csv", [{"book": name, "segment": seg, **vals} for name, d in (("sellers", sb), ("buyers", bb)) for seg, vals in d.items()])
    reading = [("Sellers' mean P&L above zero, interval excluding zero (whole sample)", s_all.mean_pnl_points > 0 and s_all.ci_lo > 0,
                f"{pts(s_all.mean_pnl_points)} points {ci(s_all.ci_lo, s_all.ci_hi)}"),
               ("Above zero in-sample", s_is.mean_pnl_points > 0, f"{pts(s_is.mean_pnl_points)} {ci(s_is.ci_lo, s_is.ci_hi)}"),
               ("Above zero out-of-sample", s_oos.mean_pnl_points > 0, f"{pts(s_oos.mean_pnl_points)} {ci(s_oos.ci_lo, s_oos.ci_hi)} on {int(s_oos.markets)} markets, {int(s_oos.events)} events"),
               ("Above zero with the fee doubled", s_2x.mean_pnl_points > 0, f"{pts(s_2x.mean_pnl_points)} {ci(s_2x.ci_lo, s_2x.ci_hi)}")]
    traded_pass = all(bool(r[1]) for r in reading)
    a1, a2, i1, o1, o2 = row("ALL", "V0", 1.0), row("ALL", "V0", 2.0), row("IS", "V0", 1.0), row("OOS", "V0", 1.0), row("OOS", "V0", 2.0)
    v4 = row("ALL", "V4", 1.0)
    c1 = cal[(cal.scope == "all markets") & (cal.price_range == "C1: 2 to 25%")].iloc[0]
    crit = [(f"At least {cfg.MIN_OOS_TRADES} OOS trades in at least {cfg.MIN_OOS_EVENTS} OOS events",
             o1.trades >= cfg.MIN_OOS_TRADES and o1.events >= cfg.MIN_OOS_EVENTS, f"{int(o1.trades)} trades in {int(o1.events)} events"),
            ("OOS mean net P&L per trade above zero, event-bootstrap interval excluding zero (1× costs)", o1.mean_net_points > 0 and o1.ci_lo > 0,
             f"{pts(o1.mean_net_points)} points {ci(o1.ci_lo, o1.ci_hi)}"),
            ("OOS above zero at 2× costs", o2.mean_net_points > 0, f"{pts(o2.mean_net_points)} points"),
            ("In-sample above zero at 1× costs", i1.mean_net_points > 0, f"{pts(i1.mean_net_points)} points {ci(i1.ci_lo, i1.ci_hi)}"),
            ("C1 over the whole sample: markets priced 2 to 25% resolve YES less often than priced", c1.diff_points < 0 and c1.ci_hi < 0,
             f"{pts(c1.diff_points)} points {ci(c1.ci_lo, c1.ci_hi)}")]
    verdict = "pass" if all(bool(c[1]) for c in crit) else "not a pass"
    e = entries
    near, exact = int(e.p.between(0.495, 0.505).sum()), int((e.p == 0.5).sum())
    ttab = md_table(tt.assign(T=tt.test, S=tt.scope, N=tt.markets.astype(int), E=tt.events.astype(int), P=tt.mean_traded_price.map(lambda x: num(x, 1)),
                              Y=tt.share_yes.map(lambda x: num(x, 1)), L=tt.mean_pnl_points.map(pts), CI=tt.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1),
                              Z=tt.median_size.map(lambda x: "n/a" if x != x else f"{x:,.0f}")),
                    {"T": "Test", "S": "Markets", "N": "Markets with such prints", "E": "Events", "P": "Mean traded price, %", "Y": "Resolved YES, %",
                     "L": "P&L per contract, points", "CI": "95% interval", "Z": "Median printed size"})
    ctab = md_table(cal.assign(S=cal.scope, R=cal.price_range, N=cal.markets.astype(int), E=cal.events.astype(int), P=cal.mean_price.map(lambda x: num(x, 1)),
                               Y=cal.share_yes.map(lambda x: num(x, 1)), D=cal.diff_points.map(pts), CI=cal.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1)),
                    {"S": "Markets", "R": "Entry price (history mid)", "N": "Markets", "E": "Events", "P": "Mean price, %", "Y": "Resolved YES, %",
                     "D": "Difference, points", "CI": "95% interval"})
    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == "V0", " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"), T=m.trades.astype(int),
                  E=m.events.astype(int), N=m.mean_net_points.map(pts), CI=m.apply(lambda r: ci(r.ci_lo, r.ci_hi), axis=1), G=m.mean_gross_points.map(pts),
                  K=m.mean_cost_points.map(num), Y=m.share_yes.map(lambda x: pct(x, 0)), H=m.hit_rate.map(lambda x: pct(x, 0)),
                  RC=m.mean_return_on_capital.map(pct), SH=m.sharpe.map(num), DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(pct),
                  WM=m.worst_month.map(pct), TO=m.turnover_ann.map(lambda x: "n/a" if x != x else f"{x:.1f}×"))
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "E": "Events", "N": "Net, points per trade", "CI": "95% interval",
             "G": "Before costs", "K": "Costs, points", "Y": "Resolved YES", "H": "Winners", "RC": "Return on capital locked", "SH": "Sharpe (monthly)",
             "DS": "Deflated Sharpe prob.", "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr"}
    bk = pd.DataFrame([{"B": name, "S": seg, "T": int(v["trades"]), "P": f"{'-' if v['pnl'] < 0 else '+'}${abs(v['pnl']):,.0f}", "K": f"${v['capital_base']:,.0f}",
                        "SH": num(v["sharpe"]), "MD": pct(v["max_drawdown"]), "WM": pct(v["worst_month"]), "TO": f"{v['turnover_ann']:.1f}×",
                        "W": pct(v["winners"], 0), "WE": f"-${abs(v['worst_event']):,.0f}" if v["worst_event"] < 0 else f"+${v['worst_event']:,.0f}",
                        "DL": num(v["median_days_locked"], 0)}
                       for name, d in (("Sold YES at traded bids", sb), ("Bought YES at traded asks", bb)) for seg, v in d.items()])
    S = ["# S18: are Polymarket's price markets fairly priced against how they resolve?", "",
         "Method, pre-registered before any entry price was matched to a result: "
         "[`research/s18_price_market_calibration/METHOD.md`](../../s18_price_market_calibration/METHOD.md) (commit `93d38c1`; amendment 1, "
         "the bug hunt and the test at traded prices, commit `37c9a0c`, before any print was pulled). "
         f"Data: {meta['markets_with_an_entry']:,} price markets with a result, in {meta['events']} events, first weekends from {meta['first_entry']} to "
         f"{meta['last_entry']}. Files: [`prints_tests.csv`](prints_tests.csv), [`prints_markets.csv`](prints_markets.csv), "
         "[`calibration.csv`](calibration.csv), [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`capacity.md`](capacity.md), "
         "[`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**What holds up, at prices that actually traded: people who bought YES in these markets overpaid.** Over {int(b_all.markets)} markets "
         f"in {int(b_all.events)} events, takers who bought YES on a market's first weekend paid {num(b_all.mean_traded_price, 1)}% on average and "
         f"{num(b_all.share_yes, 1)}% of those markets resolved YES. Held to the result they lost {num(-b_all.mean_pnl_points)} points per contract "
         f"after the fee, event-bootstrap 95% interval {ci(b_all.ci_lo, b_all.ci_hi)}. Where it is largest: contracts bought between 50% and 75% "
         f"lost {num(-b_mid.mean_pnl_points)} points {ci(b_mid.ci_lo, b_mid.ci_hi)}.", "",
         f"**The other side of those tickets earned a premium over the year, and nothing in the most recent events.** Takers who sold YES into a "
         f"bid received {num(s_all.mean_traded_price, 1)}% on average ({int(s_all.markets)} markets, {int(s_all.events)} events). Held to the "
         f"result they earned {pts(s_all.mean_pnl_points)} points per contract after the fee {ci(s_all.ci_lo, s_all.ci_hi)}, and "
         f"{pts(s_2x.mean_pnl_points)} with the fee doubled. In-sample {pts(s_is.mean_pnl_points)} {ci(s_is.ci_lo, s_is.ci_hi)}; out-of-sample (the "
         f"most recent 20% of events, from {meta['oos_from']}) {pts(s_oos.mean_pnl_points)} {ci(s_oos.ci_lo, s_oos.ci_hi)} on {int(s_oos.markets)} "
         f"markets in {int(s_oos.events)} events.", "",
         f"**By the rule fixed before the prints were pulled this is {'a pass at traded prices' if traded_pass else 'not a pass'}:** it needed the "
         "sellers' P&L above zero in-sample and out-of-sample, and out-of-sample it is not. It is the closest thing to an edge in the project, and "
         "it is not an arbitrage: selling \"will it hit\" tickets is selling insurance against large moves. "
         f"As a book of up to 100 contracts per market (never more than the printed size) it made {bk.iloc[2].P} on a capital base of "
         f"{bk.iloc[2].K} over the year, with a monthly Sharpe of {bk.iloc[2].SH}, a maximum drawdown of {bk.iloc[2].MD} and a worst event of "
         f"{bk.iloc[2].WE}.", "",
         f"**The modelled run is not evidence (the bug hunt).** Priced at Polymarket's history mid, YES looks overpriced by 10 to 20 points in "
         f"every bucket and \"sell every market\" (V4) earns {pts(v4.mean_net_points)} points per trade with a Sharpe near 3. The entry prices "
         f"explain it: {near} of the {len(e):,} are within half a point of 50% ({exact} are exactly 0.500), on markets a median of "
         f"{num(meta_age(e), 1)} days old. That is the midpoint of a book that has not formed. Nobody could sell there.", "",
         f"**Verdict on the pre-registered primary (V0, sell YES at 5 to 25% at the history mid): {verdict}.** {pts(a1.mean_net_points)} points per "
         f"trade {ci(a1.ci_lo, a1.ci_hi)} on {int(a1.trades)} trades; in-sample {pts(i1.mean_net_points)} {ci(i1.ci_lo, i1.ci_hi)}, out-of-sample "
         f"{pts(o1.mean_net_points)} {ci(o1.ci_lo, o1.ci_hi)}.", "",
         "## At traded prices (amendment 1)", "",
         "One observation per market: the size-weighted mean price of the prints of one taker side during the market's first weekend (48 hours "
         "from the entry instant), then held to the result. P&L after the market's own taker fee. Intervals resample events.", "",
         ttab, "",
         f"Of the {pmeta['entries']:,} markets, " + "; ".join(f"{n} are left out because: {k}" for k, n in pmeta["left_out"].items()) + ". "
         f"Of the {pmeta['markets_checked']} checked, {pmeta['with_a_taker_sell']} have a taker sale of YES in the window and "
         f"{pmeta['with_a_taker_buy']} a taker purchase.", "",
         "### The reading fixed before the prints were pulled", "", "| Needed | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'met' if b else '**not met**'} | {e_} |" for a, b, e_ in reading]
    S += ["", "### The two sides as books", "",
          md_table(bk, {"B": "Book", "S": "Segment", "T": "Markets", "P": "Net P&L", "K": "Capital base", "SH": "Sharpe (monthly)", "MD": "Max DD",
                        "WM": "Worst month", "TO": "Turnover / yr", "W": "Winners", "WE": "Worst event", "DL": "Median days locked"}), "",
          "Up to 100 contracts per market, never more than the printed size. P&L is booked in the month of the result. The capital base is the "
          "largest capital locked at one time. In the charts each point is a calendar month; a market that entered in-sample and resolved "
          "late is booked after the out-of-sample line.", "", "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
          "## The pre-registered run, at history mids (not evidence, see the bug hunt)", "",
          "### Pre-registered success criterion (V0)", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e_} |" for a, b, e_ in crit]
    S += ["", f"**Verdict: {verdict}.**", "", "### Every variant tried", "", md_table(vt, vcols), "",
          "V1: buy YES at 75 to 95%. V2: V0 on S9's markets. V3: V0 on crude oil. V4: sell YES on every market between 5% and 95%. The deflated "
          "Sharpe probability uses 5 trials. Sharpe is on monthly P&L.", "", "### Calibration at history mids", "", ctab, "",
          "## Costs", "",
          "- **At traded prices:** the price is the print, so no spread is assumed. The fee is the market's own taker fee, 0.04 × P × (1 − P) where "
          "the market charges one; nothing is paid at the result.",
          "- **At history mids:** the half-spread of the asset class (S9 and S15) and the fee, once.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## What didn't work", "",
          f"- **The primary at history mids** (sell YES at 5 to 25%): {pts(a1.mean_net_points)} points per trade, {pts(o1.mean_net_points)} "
          "out-of-sample.",
          f"- **Selling at traded bids out-of-sample:** {pts(s_oos.mean_pnl_points)} {ci(s_oos.ci_lo, s_oos.ci_hi)}. The premium of the first "
          "eleven months is not there in the most recent events, or the 20 events are too few to see it; the interval allows both.",
          f"- **Cheap tickets are not where the premium is.** Sold between 2% and 10%: {pts(t(SELL, 'traded price 2 to 10%').mean_pnl_points)} "
          f"points; the gap sits between 50% and 75% ({pts(s_mid.mean_pnl_points)} {ci(s_mid.ci_lo, s_mid.ci_hi)}).", "",
          "## Caveats", "",
          "- **One year with one oil shock in it.** Selling these markets is selling insurance. Events in the same months share the same "
          "weather, and resampling events does not cure that.",
          "- **The loss on one contract can be many times the gain.**",
          "- **A taker's sale needs a bid.** The prints show that bids were hit at these prices; they do not show how much more could have "
          "been sold.",
          "- **The buyers' loss is not our gain** unless our resting offer is the one they lift. P3 (S12) found that resting orders in these "
          "markets were adversely selected out-of-sample.",
          "- Markets that did not trade on their first weekend are not in the test.",
          "- The test at traded prices was added after the first run, in a dated amendment committed before any print was pulled.", "",
          "## Reproduce", "", "```", "cd research", "python -m s18_price_market_calibration.run", "python -m s18_price_market_calibration.prints --pull",
          "python -m s18_price_market_calibration.prints", "python -m s18_price_market_calibration.report",
          "python -m pytest s18_price_market_calibration/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    ss = pm[pm.sell_prints > 0]
    cap = ["# S18 capacity", "",
           f"- **Printed size behind the sellers' test:** a median of {ss.sell_size.median():,.0f} contracts sold into bids per market over its first "
           f"weekend (quartiles {ss.sell_size.quantile(.25):,.0f} to {ss.sell_size.quantile(.75):,.0f}); in dollars of premium, a median of "
           f"${(ss.sell_size * ss.sell_price).median():,.0f} per market.",
           f"- **The book as run:** up to 100 contracts per market, {int(sb['ALL']['trades'])} markets over the year, ${sb['ALL']['mean_capital']:,.0f} of "
           f"capital per market on average, a capital base of ${sb['ALL']['capital_base']:,.0f}, locked a median of {sb['ALL']['median_days_locked']:.0f} days.",
           "- This is a trade of tens of dollars per market, a few thousand dollars in all. The prints show what did trade, not what else could have.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:14]))
    return 0


def meta_age(e: pd.DataFrame) -> float:
    from .run import SOURCES
    starts = {str(m["id"]): pd.Timestamp(m["start"]).timestamp() for _, root in SOURCES for m in json.loads((root / "universe.json").read_text())["markets"]}
    return float(((e.entry_epoch - e.market.astype(str).map(starts)) / 86400).median())


if __name__ == "__main__":
    sys.exit(main())
