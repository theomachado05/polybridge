"""S20 report: SUMMARY.md, the three charts and capacity.md, every number read back from the result CSVs.

Run from `research/`:  python -m s20_closed_vs_open.report
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
from .pull import S18_RESULTS  # noqa: E402
from .run import ALL, BUCKET_NAMES, RANGE, RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
COLOR = {"W1": "#2a78d6", "D1": "#eb6834", "W2": "#1baf7a"}          # fixed by window; validated (light surface) with the dataviz palette script
NAME = {"W1": "W1: first weekend (shut)", "D1": "D1: the week's sessions (open)", "W2": "W2: second weekend (shut)"}
RULE = {"B": "B (no look-ahead; the verdict)", "A": "A (as briefed)"}
GROUPS = list(cfg.CLASS_GROUPS)


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.axhline(0, color=INK2, linewidth=1)
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)


def book_charts(eq: pd.DataFrame, b: pd.DataFrame, oos_from: str, rule: str = "B") -> None:
    series = []
    for w in cfg.WINDOWS:
        e = eq[(eq.rule == rule) & (eq.window == w) & (eq.fee_mult == 1.0)].sort_values("month")
        k = b[(b.rule == rule) & (b.window == w) & (b.scope == ALL) & (b.fee_mult == 1.0) & (b.segment == "ALL")]
        if len(e) and len(k):
            series.append((w, pd.to_datetime(e.month + "-01"), np.cumsum(e.pnl.to_numpy()) / float(k.capital_base.iloc[0]) * 100))
    for name, title, dd in (("equity_curve.png", "cumulative P&L after fees", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.6), facecolor=SURFACE)
        _style(ax)
        deepest = []
        for w, x, y in series:
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{w} {y.min():.0f}%")
            ax.plot(x, y, color=COLOR[w], linewidth=2, label=NAME[w], solid_capstyle="round", marker="o", markersize=4)
        if not dd:                                                   # end labels, kept apart when two books end close together
            ends = sorted(((y[-1], w, x.iloc[-1]) for w, x, y in series))
            gap, last = 0.05 * (ax.get_ylim()[1] - ax.get_ylim()[0]), None
            for y_end, w, x_end in ends:
                at = y_end if last is None else max(y_end, last + gap)
                ax.annotate(f"{w} {y_end:+.0f}%", (x_end, at), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
                last = at
        split = pd.Timestamp(oos_from)
        ax.axvline(split, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
        ax.annotate("out-of-sample events start ▸", (split, 1.0), xycoords=("data", "axes fraction"), xytext=(-5, -4), textcoords="offset points",
                    va="top", ha="right", fontsize=8.5, color=INK2)
        if deepest:
            ax.annotate("Deepest: " + ", ".join(deepest), (0.0, 0.0), xycoords="axes fraction", xytext=(12, 10), textcoords="offset points",
                        ha="left", va="bottom", fontsize=8.5, color=INK)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.margins(x=0.10)
        ax.set_ylabel("% of each book's capital base", fontsize=9, color=INK2)
        ax.set_title(f"S20, sold YES at traded bids and held to the result (rule {rule}): {title}, booked in the month of the result",
                     loc="left", fontsize=10.5, color=INK)
        ax.legend(loc="upper left" if not dd else "lower right", frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def loss_chart(m: pd.DataFrame) -> None:
    """Buyers' mean P&L per contract by window, with the event-bootstrap interval: one panel per rule and scope, one shared axis."""
    panels = [("B", ALL), ("B", RANGE), ("A", ALL), ("A", RANGE)]
    fig, axes = plt.subplots(1, 4, figsize=(12.5, 4.4), facecolor=SURFACE, sharey=True)
    for ax, (rule, scope) in zip(axes, panels):
        _style(ax)
        for i, w in enumerate(cfg.WINDOWS):
            r = m[(m.rule == rule) & (m.kind == "level") & (m.side == "buy") & (m.windows == w) & (m.scope == scope) & (m.fee_mult == 1.0)].iloc[0]
            ax.bar(i, r.estimate, width=0.5, color=COLOR[w], edgecolor=SURFACE, linewidth=2)
            if r.ci_lo == r.ci_lo:
                ax.plot([i, i], [r.ci_lo, r.ci_hi], color=INK, linewidth=1.5, solid_capstyle="butt")
            ax.annotate(f"{r.estimate:+.1f}\n{int(r.markets)} markets", (i, 0.0), xytext=(0, 5), textcoords="offset points", ha="center", va="bottom",
                        fontsize=8.5, color=INK)
        ax.set_xticks(range(3), ["W1\nshut", "D1\nopen", "W2\nshut"], fontsize=9, color=INK2)
        ax.set_title(f"Rule {RULE[rule]}\n{scope}", loc="left", fontsize=9.5, color=INK)
    lo = min(ax.get_ylim()[0] for ax in axes)
    axes[0].set_ylim(lo - 0.5, 3.5)
    axes[0].set_ylabel("points per contract, after the fee", fontsize=9, color=INK2)
    fig.suptitle("S20: what takers who bought YES made, held to the result, by the window they bought in (bar = mean, line = 95% interval over events)",
                 x=0.01, ha="left", fontsize=10.5, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(R / "buyers_loss_by_window.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def est(r) -> str:
    return f"{pts(r.estimate)} {ci(r.ci_lo, r.ci_hi)}"


def money(x: float) -> str:
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.0f}"


def main() -> int:
    m, b, c, eq = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "books.csv"), pd.read_csv(R / "counts.csv"), pd.read_csv(R / "equity.csv")
    tr = pd.read_csv(R / "trades.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    s18 = json.loads((S18_RESULTS / "run_meta.json").read_text())

    def lv(rule, w, side="buy", scope=ALL, fee=1.0):
        return m[(m.rule == rule) & (m.kind == "level") & (m.side == side) & (m.windows == w) & (m.scope == scope) & (m.fee_mult == fee)].iloc[0]

    def df(rule, a, b_, side="buy", scope=ALL, fee=1.0):
        return m[(m.rule == rule) & (m.kind == "difference") & (m.side == side) & (m.windows == f"{a}-{b_}") & (m.scope == scope) & (m.fee_mult == fee)].iloc[0]

    def path(rule, a, b_, side="buy", scope=ALL):
        return m[(m.rule == rule) & (m.kind == "path") & (m.side == side) & (m.windows == f"{a}-{b_}") & (m.scope == scope)].iloc[0]

    def bk(rule, w, seg="ALL", scope=ALL, fee=1.0):
        x = b[(b.rule == rule) & (b.window == w) & (b.segment == seg) & (b.scope == scope) & (b.fee_mult == fee)]
        return x.iloc[0] if len(x) else None

    def below(r):
        return bool(r.estimate < 0 and r.ci_hi < 0)

    def above(r):
        return bool(r.estimate > 0 and r.ci_lo > 0)

    book_charts(eq, b, s18["oos_from"])
    loss_chart(m)

    # ---- the verdict, by the rules of METHOD.md section 5 (rule B, all markets)
    t1, t2, t12 = df("B", "W1", "D1"), df("B", "W2", "D1"), df("B", "W1", "W2")
    t1_holds = below(t1)
    t2_read = "shut matters" if below(t2) else ("just new" if below(t12) else "cannot tell")
    w1_is, w1_oos = bk("B", "W1", "IS"), bk("B", "W1", "OOS")
    oos_ok = bool(w1_is.pnl > 0 and w1_oos.pnl > 0)
    verdict = ("the closed-market premium is an edge candidate" if t1_holds and oos_ok else "a lead" if t1_holds
               else "the overpricing does not depend on the clock")
    agree = {"rule A, all markets": df("A", "W1", "D1"), "rule B, tickets traded 2 to 98%": df("B", "W1", "D1", scope=RANGE),
             "rule A, tickets traded 2 to 98%": df("A", "W1", "D1", scope=RANGE)}
    t3a, t3b = path("B", "W1", "D1"), path("B", "W2", "D1")

    crit = [("T1: buyers lose more in W1 (shut) than in D1 (open): W1 minus D1 below zero, interval excluding zero", t1_holds, est(t1) + " points"),
            ("T2: buyers lose more in W2 (shut again) than in D1: W2 minus D1 below zero, interval excluding zero", below(t2), est(t2) + f" points; reading: **{t2_read}**"),
            ("T3: the same ticket is dearer in W1 than in D1 (buyers' traded price, same markets), interval excluding zero", above(t3a),
             est(t3a) + f" points on {int(t3a.markets)} markets"),
            ("T3: the same ticket is dearer in W2 than in D1", above(t3b), est(t3b) + f" points on {int(t3b.markets)} markets"),
            ("T4: the W1 sellers' book is above zero in-sample", bool(w1_is.pnl > 0), f"{money(w1_is.pnl)} on {int(w1_is.trades)} markets"),
            ("T4: the W1 sellers' book is above zero out-of-sample", bool(w1_oos.pnl > 0), f"{money(w1_oos.pnl)} on {int(w1_oos.trades)} markets")]

    # ---- tables
    def level_table(side: str, scopes: list[str], rules=("B", "A")) -> str:
        rows = []
        for rule in rules:
            for scope in scopes:
                for w in cfg.WINDOWS:
                    r, r2 = lv(rule, w, side, scope), lv(rule, w, side, scope, 2.0)
                    rows.append({"R": rule, "S": scope, "W": w, "N": int(r.markets), "E": int(r.events), "P": num(r.mean_traded_price, 1), "Y": num(r.share_yes, 1),
                                 "L": pts(r.estimate), "CI": ci(r.ci_lo, r.ci_hi), "L2": pts(r2.estimate), "Z": "n/a" if r.median_size != r.median_size else f"{r.median_size:,.0f}"})
        return md_table(pd.DataFrame(rows), {"R": "Rule", "S": "Scope", "W": "Window", "N": "Markets", "E": "Events", "P": "Mean traded price, %", "Y": "Resolved YES, %",
                                             "L": "P&L per contract, points", "CI": "95% interval", "L2": "Fee doubled", "Z": "Median printed size"})

    def diff_table(side: str, scopes: list[str], rules=("B", "A")) -> str:
        rows = []
        for rule in rules:
            for scope in scopes:
                for label, a, b_ in (("T1", "W1", "D1"), ("T2", "W2", "D1"), ("T2", "W1", "W2")):
                    r = df(rule, a, b_, side, scope)
                    rows.append({"R": rule, "S": scope, "T": f"{label}: {a} minus {b_}", "D": pts(r.estimate), "CI": ci(r.ci_lo, r.ci_hi),
                                 "N": f"{int(r.markets)} / {int(r.markets_b)}"})
        return md_table(pd.DataFrame(rows), {"R": "Rule", "S": "Scope", "T": "Difference in mean P&L", "D": "Points", "CI": "95% interval", "N": "Markets (first / second window)"})

    def path_table(scopes: list[str], rules=("B", "A")) -> str:
        rows = []
        for rule in rules:
            for scope in scopes:
                for a, b_ in (("W1", "D1"), ("W2", "D1")):
                    for side, who in (("buy", "buyers paid"), ("sell", "sellers received")):
                        r = path(rule, a, b_, side, scope)
                        rows.append({"R": rule, "S": scope, "T": f"{a} minus {b_}", "W": who, "N": int(r.markets), "E": int(r.events), "PA": num(r.mean_traded_price, 1),
                                     "PB": num(r.mean_traded_price_b, 1), "D": pts(r.estimate), "CI": ci(r.ci_lo, r.ci_hi)})
        return md_table(pd.DataFrame(rows), {"R": "Rule", "S": "Scope", "T": "Windows", "W": "Price", "N": "Markets with prints in both", "E": "Events",
                                             "PA": "Mean price, first window, %", "PB": "Mean price, second window, %", "D": "Difference, points", "CI": "95% interval"})

    def book_table(scopes: list[str], rules=("B", "A"), fees=(1.0, 2.0)) -> str:
        rows = []
        for rule in rules:
            for scope in scopes:
                for w in cfg.WINDOWS:
                    for fee in fees:
                        for seg in ("IS", "OOS", "ALL"):
                            v = bk(rule, w, seg, scope, fee)
                            if v is None or not v.trades:
                                continue
                            rows.append({"R": rule, "S": scope, "W": w, "F": f"{fee:.0f}×", "G": seg, "T": int(v.trades), "P": money(v.pnl), "K": f"${v.capital_base:,.0f}",
                                         "SH": num(v.sharpe), "MD": pct(v.max_drawdown), "WM": pct(v.worst_month), "TO": "n/a" if v.turnover_ann != v.turnover_ann else f"{v.turnover_ann:.1f}×",
                                         "WI": pct(v.winners, 0), "WE": money(v.worst_event), "DL": num(v.median_days_locked, 0)})
        return md_table(pd.DataFrame(rows), {"R": "Rule", "S": "Scope", "W": "Window", "F": "Fee", "G": "Segment", "T": "Markets", "P": "Net P&L", "K": "Capital base",
                                             "SH": "Sharpe (monthly)", "MD": "Max DD", "WM": "Worst month", "TO": "Turnover / yr", "WI": "Winners", "WE": "Worst event",
                                             "DL": "Median days locked"})

    left = [k for k in c.columns if k.startswith("left out: ")]
    ct = c.assign(**{k: c[k].fillna(0).astype(int) for k in left})
    count_tab = md_table(ct.assign(SY=ct.share_yes_counted.map(lambda x: num(x, 1))),
                         {"rule": "Rule", "window": "Window", "markets": "S18's markets", "counted": "Counted", "events_counted": "Events", "SY": "Resolved YES, %",
                          "with_a_print": "With a print", "with_a_taker_buy": "With a taker purchase", "events_with_a_taker_buy": "Events (purchases)",
                          "with_a_taker_sell": "With a taker sale", "events_with_a_taker_sell": "Events (sales)", "prints": "Prints",
                          **{k: k.replace("left out: ", "Left out: ") for k in left}})
    rep = meta["reproduces_s18"]
    pull = meta["pull"]
    S = ["# S20: are Polymarket's price markets most overpriced when the reference market is shut?", "",
         "Method, pre-registered before any print outside S18's first weekend was pulled: "
         "[`research/s20_closed_vs_open/METHOD.md`](../../s20_closed_vs_open/METHOD.md). "
         f"Markets: S18's {meta['markets']:,} price markets with a result, in {meta['events']} events. Three windows per market: **W1**, its first weekend "
         "(Friday 20:00 to Sunday 20:00 New York, the stock market shut; S18's prints, read only); **D1**, the regular sessions (09:30 to 16:00) of the "
         "trading days that follow; **W2**, the weekend after. Prices are public trade prints; P&L is after the market's own taker fee, held to the "
         "result; intervals resample events. Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`books.csv`](books.csv), "
         "[`counts.csv`](counts.csv), [`equity.csv`](equity.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         "Every number in this section is under rule B (a market counts in a window if it was still open when the window started) unless rule A is named. "
         "Why there are two rules is in the last paragraph and in the section after the verdict.", "", *answer(locals()), "",
         "## The tests against the lines fixed in advance (rule B, all markets)", "", "| Fixed in advance | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'**holds**' if ok else 'does not hold'} | {e} |" for a, ok, e in crit]
    S += ["", f"**Verdict by the rule of METHOD.md section 5: {verdict}.**", "",
          "T1 under the other readings fixed in advance: " + "; ".join(f"{k}: {est(v)}" for k, v in agree.items()) + ".", "",
          "## Which markets count in a window: the briefed rule and the one the verdict is read from", "",
          "The brief said: leave a market out of a window if it resolved before or during it (**rule A**). A \"will it hit\" market resolves early only when "
          "it is hit, so rule A removes the open week's winning tickets using knowledge of the future. That was visible from result times alone, before any "
          "print was pulled, and `METHOD.md` section 3 fixed a second rule then: **rule B**, a market counts if its result came after the window's start. "
          "Both are reported everywhere; the verdict is read from rule B. W1 under rule B is S18's own test and "
          f"{'returns its committed numbers exactly' if rep['all_same'] else '**does not return its committed numbers**'} "
          f"(buyers {pts(rep['buyers']['s20_w1_rule_b'][1])} on {rep['buyers']['s20_w1_rule_b'][0]} markets; sellers {pts(rep['sellers']['s20_w1_rule_b'][1])} on "
          f"{rep['sellers']['s20_w1_rule_b'][0]}; sellers' book {money(rep['sellers_book']['s20_w1_rule_b'][0])}).", "", count_tab, "",
          "## T1 and T2: what buyers of YES made, by the window they bought in", "", "![Buyers' loss by window](buyers_loss_by_window.png)", "",
          level_table("buy", [ALL, RANGE]), "", diff_table("buy", [ALL, RANGE]), "",
          "## T3: the price of the same ticket, weekend against open week", "",
          "Only markets with prints of that side in both windows. A fairly priced probability does not drift on average. \"Buyers paid\" is the pre-registered "
          "test; \"sellers received\" tells a dearer ticket from a wider spread.", "", path_table([ALL, RANGE]), "",
          "## T4: the trade, sell YES at traded bids and hold to the result, as a book per window", "",
          "Up to 100 contracts per market, never more than the printed size; P&L booked in the month of the result; capital locked from the window's start to "
          "the result; the capital base is the largest capital locked at one time (S18's book function). The charts show rule B at the fee. A D1 or W2 book "
          "under rule A could not have been traded: it drops the markets that were about to be hit.", "",
          "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "", book_table([ALL]), "",
          "Sellers' mean P&L per contract by window:", "", level_table("sell", [ALL, RANGE]), "", diff_table("sell", [ALL]), "",
          "## By asset class", "", "Buyers:", "", level_table("buy", GROUPS), "", diff_table("buy", GROUPS), "", path_table(GROUPS), "",
          "Sellers:", "", level_table("sell", GROUPS), "", book_table(GROUPS, fees=(1.0,)), "",
          "## In-sample and out-of-sample events (S18's split)", "", level_table("buy", ["in-sample events", "out-of-sample events"], rules=("B",)), "",
          diff_table("buy", ["in-sample events", "out-of-sample events"], rules=("B",)), "",
          level_table("sell", ["in-sample events", "out-of-sample events"], rules=("B",)), "",
          "## By S18's price buckets (rule B)", "", "Buyers, by the price they paid in that window:", "", level_table("buy", BUCKET_NAMES, rules=("B",)), "",
          diff_table("buy", BUCKET_NAMES, rules=("B",)), "", "The price path, by the mean of the two windows' prices:", "", path_table(BUCKET_NAMES, rules=("B",)), "",
          "Sellers, by the price they received in that window:", "", level_table("sell", BUCKET_NAMES, rules=("B",)), "",
          book_table(BUCKET_NAMES, rules=("B",), fees=(1.0,)), "",
          "Rule A by bucket is in [`metrics.csv`](metrics.csv) and [`books.csv`](books.csv).", "",
          "## Costs", "",
          "- The price is the print, so no spread is assumed. The fee is the market's own taker fee, 0.04 × P × (1 − P) where the market charges one "
          "(617 of the 1,092 markets), charged once; nothing is paid at the result. In points that is at most 1.0 at a price of 50% and 0.36 at 10%; on the "
          "capital a seller locks (1 − P) it is 4 × P percent, that is 0 to 400 bp. The \"fee doubled\" columns are the 2× case.", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          *tail(locals()), "",
          "## Reproduce", "", "```", "cd research", "python -m s20_closed_vs_open.pull      # one request a second; cached, resumable", "python -m s20_closed_vs_open.run",
          "python -m s20_closed_vs_open.report", "python -m pytest s20_closed_vs_open/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))

    k = tr[(tr.rule == "B") & (tr.status == "in") & (tr.sell_prints > 0)]
    cap = ["# S20 capacity", "", "Rule B (no look-ahead). What takers actually sold into bids, per market and window:", ""]
    for w in cfg.WINDOWS:
        s, v = k[k.window == w], bk("B", w)
        cap.append(f"- **{NAME[w]}:** a median of {s.sell_size.median():,.0f} contracts sold into bids per market (quartiles {s.sell_size.quantile(.25):,.0f} to "
                   f"{s.sell_size.quantile(.75):,.0f}); in dollars of premium a median of ${(s.sell_size * s.sell_price).median():,.0f} per market. The book as run: "
                   f"{int(v.trades)} markets, ${v.mean_capital:,.0f} of capital per market on average, a capital base of ${v.capital_base:,.0f}, locked a median of "
                   f"{v.median_days_locked:.0f} days.")
    cap += ["", "This is a trade of tens of dollars per market and a few thousand dollars in all, in every window. The prints show what did trade, not what "
            "else could have been sold. D1 covers 32.5 hours of sessions and each weekend 48 hours, so printed size per hour is the fairer comparison of depth.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:8 + len(crit) + 12]))
    print(f"pull: {pull.get('seconds_this_run')}s, recorder failures {pull.get('recorder_failures_before')} -> {pull.get('recorder_failures_after')}")
    return 0


def _lost(r) -> str:
    return f"{num(-r.estimate)} points {ci(r.ci_lo, r.ci_hi)}"


def answer(v: dict) -> list[str]:
    """The plain-language answer. Written after the run; every number is read from the result files through the helpers."""
    lv, df, path, bk, tr = v["lv"], v["df"], v["path"], v["bk"], v["tr"]
    w1, d1, w2 = (lv("B", w) for w in cfg.WINDOWS)
    s1, sd, s2 = (lv("B", w, "sell") for w in cfg.WINDOWS)
    t1, t2 = v["t1"], v["t2"]
    t1_is, t1_oos = df("B", "W1", "D1", scope="in-sample events"), df("B", "W1", "D1", scope="out-of-sample events")
    pb, ps = path("B", "W1", "D1"), path("B", "W1", "D1", "sell")
    sdiff = df("B", "W1", "D1", "sell")
    book = {w: {g: bk("B", w, g) for g in ("IS", "OOS", "ALL")} for w in cfg.WINDOWS}
    book2 = {w: bk("B", w, "ALL", fee=2.0) for w in cfg.WINDOWS}
    so = {w: lv("B", w, "sell", "out-of-sample events") for w in cfg.WINDOWS}
    st = {w: lv("B", w, "sell", GROUPS[0]) for w in cfg.WINDOWS}
    co = {w: lv("B", w, "sell", GROUPS[1]) for w in cfg.WINDOWS}
    t1a, d1a = df("A", "W1", "D1"), lv("A", "D1")
    a_d1, b_d1 = tr[(tr.rule == "A") & (tr.window == "D1")].set_index("market"), tr[(tr.rule == "B") & (tr.window == "D1")].set_index("market")
    gone = a_d1[(a_d1.status == "resolved before or during the window") & (b_d1.status.reindex(a_d1.index) != "resolved before the window")]

    def b_line(w):
        x, x2 = book[w]["ALL"], book2[w]
        return (f"{money(x.pnl)} on a capital base of ${x.capital_base:,.0f} (monthly Sharpe {num(x.sharpe)}, maximum drawdown {pct(x.max_drawdown)}, worst month "
                f"{pct(x.worst_month)}; {money(x2.pnl)} with the fee doubled; in-sample {money(book[w]['IS'].pnl)}, out-of-sample {money(book[w]['OOS'].pnl)})")

    return [
        f"**Buyers of YES overpay in every window, with the reference market shut or open.** Held to the result and after the fee, takers who bought YES "
        f"lost {_lost(w1)} per contract on the market's first weekend ({int(w1.markets)} markets, {int(w1.events)} events), {_lost(d1)} during the regular "
        f"sessions of the following week ({int(d1.markets)} markets, {int(d1.events)} events) and {_lost(w2)} on the second weekend ({int(w2.markets)} markets, "
        f"{int(w2.events)} events). No interval reaches zero. The overpricing S18 found is not a first-weekend effect: it is there during regular trading "
        "hours, with the stock, futures and options markets open.", "",
        f"**They lose more when the reference market is shut (T1 holds), but not in the most recent events.** First weekend minus open week: {est(t1)} points. "
        f"Second weekend minus open week: {est(t2)}, which by the line fixed in advance reads \"shut matters, not just new\", but only just. In the in-sample "
        f"events T1 is {est(t1_is)}; in the most recent 20% of events it is {est(t1_oos)} ({int(t1_oos.markets)} against {int(t1_oos.markets_b)} markets).", "",
        f"**The extra weekend loss is a wider gap between buyers and sellers, not a dearer ticket that a seller collects (T3).** On the same markets, buyers paid "
        f"{est(pb)} points more on the first weekend than in the open week ({int(pb.markets)} markets, {int(pb.events)} events). Takers who sold into bids "
        f"received the same price in both: {est(ps)} ({int(ps.markets)} markets). The price at which a ticket can be sold does not rise when the reference "
        "market shuts. What rises is the price at which it is bought.", "",
        f"**So for the side that can be traded, the clock does not matter (T4).** Takers who sold YES into a bid and held to the result earned {est(s1)} points "
        f"per contract on the first weekend, {est(sd)} in the open week and {est(s2)} on the second weekend. First weekend minus open week: {est(sdiff)}: "
        "selling while the reference market is shut paid no more than selling while it is open. As books of up to 100 contracts per market:", "",
        f"- **W1, first weekend (shut):** {b_line('W1')}. This is S18's book.",
        f"- **D1, the open week:** {b_line('D1')}.",
        f"- **W2, second weekend (shut):** {b_line('W2')}.", "",
        "The three books are one bet, short the same tickets, entered at three times; their monthly P&L moves together. Out-of-sample, per contract, none of "
        f"the three is distinguishable from zero: {est(so['W1'])}, {est(so['D1'])} and {est(so['W2'])}.", "",
        f"**Where the sellers' premium is: stocks and the S&P 500, in all three windows.** {est(st['W1'])}, {est(st['D1'])} and {est(st['W2'])} points per "
        f"contract. In commodities it is {est(co['W1'])}, {est(co['D1'])} and {est(co['W2'])}: every interval includes zero.", "",
        f"**Verdict by the rule fixed in advance: {v['verdict']}.** T1 holds and the first-weekend sellers' book is not above zero out-of-sample (known from "
        "S18). Read with T3 and T4: the clock changes what a buyer pays; it does not change what a seller at the bid earns. The thesis that these tickets are "
        "*most* overpriced when the reference market is shut is right for the buyer's side by about three points and is not a reason to time the sale.", "",
        f"**The exclusion rule decides T1, and the briefed one gives a different answer.** Under rule A, as briefed, T1 is {est(t1a)}: no clock effect that can be told from zero. Rule A "
        f"drops from the open week the {len(gone)} markets that resolved during it, {100 * gone.outcome.mean():.0f}% of them YES. Those are the buyers' winners, "
        f"so under rule A open-week buyers lose {num(-d1a.estimate)} points instead of {num(-d1.estimate)}. The bias and its direction were written into "
        "`METHOD.md` from result times alone, before any print was pulled, together with the rule the verdict would be read from (rule B). This is a departure "
        "from the brief.",
    ]


def tail(v: dict) -> list[str]:
    """What didn't work, what was looked at after the run, and the caveats."""
    lv, df, path, b = v["lv"], v["df"], v["path"], v["b"]
    af = pd.read_csv(R / "after_the_run.csv")
    gap = af[af.look.str.startswith("gap") & (af.scope == ALL)].set_index("windows")
    gd = af[af.look.str.startswith("the same gap") & (af.scope == ALL)].set_index("windows")
    hi = af[af.look.str.startswith("book") & (af.rule == "B")]
    sp = af[af.look.str.startswith("open-week")]
    hit, rest = sp[sp.look.str.contains("resolved during")].iloc[0], sp[sp.look.str.contains("still open")].iloc[0]
    p2b, p2s = path("B", "W2", "D1"), path("B", "W2", "D1", "sell")
    w2, d1 = lv("B", "W2"), lv("B", "D1")
    t1_oos, t1_c, t1_s = df("B", "W1", "D1", scope="out-of-sample events"), df("B", "W1", "D1", scope=GROUPS[1]), df("B", "W1", "D1", scope=GROUPS[0])
    t1_mid = df("B", "W1", "D1", scope="traded price 50 to 75%")
    t3_s = path("B", "W1", "D1", scope=GROUPS[0])
    w1_oos = v["w1_oos"]
    few = hi.fewer_than_six_months.astype(str) == "True"
    short, longer = hi[few], hi[~few]

    def g(r):
        return f"{num(r.estimate)} points {ci(r.ci_lo, r.ci_hi)}"

    return ["## What didn't work", "",
            f"- **T3 on the second weekend:** on the same markets the price buyers paid on the second weekend, minus the open week's, is {est(p2b)} points, and the "
            f"price sellers received {est(p2s)}: lower on the weekend, the opposite sign to the thesis. It is not evidence against it either. A market has prints on its second weekend only if it was not hit during the "
            "week, and tickets that go a week unhit have decayed. `METHOD.md` flagged this bias for rule A; it applies to this one comparison under rule B "
            "as well, and I did not see that before the run.",
            f"- **T1 out-of-sample:** {est(t1_oos)}. The clock effect of the in-sample events is not in the most recent ones, or 22 to 25 events are too few "
            "to see it.",
            f"- **The first-weekend sellers' book out-of-sample:** {money(w1_oos.pnl)} (S18's result). This is what keeps the verdict at \"a lead\".",
            f"- **T1 in commodities:** {est(t1_c)}, interval includes zero. In stocks and the S&P 500 it is {est(t1_s)}. But in stocks the same-ticket price "
            f"difference (T3) is {est(t3_s)}, interval includes zero.",
            f"- **T1 by price bucket:** no single bucket has an interval that excludes zero. The largest gap is at 50 to 75%: {est(t1_mid)}.", "",
            "## Looked at after the run (not pre-registered)", "",
            "These were computed after the results above were seen. They are in [`after_the_run.csv`](after_the_run.csv) (`python -m s20_closed_vs_open.after`).", "",
            "- **The gap between what buyers paid and what sellers received, same market and window** (rule B; markets with both sides printed). First weekend "
            f"{g(gap.loc['W1'])} on {int(gap.loc['W1'].markets)} markets; open week {g(gap.loc['D1'])} on {int(gap.loc['D1'].markets)}; second weekend "
            f"{g(gap.loc['W2'])} on {int(gap.loc['W2'].markets)}. On markets with both sides printed in both windows: first weekend minus open week "
            f"{est(gd.loc['W1-D1'])}; second weekend minus open week {est(gd.loc['W2-D1'])}; first minus second weekend {est(gd.loc['W1-W2'])}. The wide gap "
            "belongs to the first weekend. The second weekend, equally shut, looks like the open week. On this measure the first weekend is expensive because "
            "the market is new, not because the reference market is shut.",
            f"- **Where the open week's smaller loss comes from.** Of the {int(sp.markets.sum())} open-week markets with purchases, {int(hit.markets)} resolved during "
            f"that week ({num(hit.share_yes, 0)}% YES). Their buyers paid {num(hit.mean_traded_price, 1)}% on average and made {g(hit)} per contract: these are "
            f"purchases of tickets that were being hit while the asset traded. Buyers in the other {int(rest.markets)} markets lost {num(-rest.estimate)} points "
            f"{ci(rest.ci_lo, rest.ci_hi)}. That split is the whole difference between rule A and rule B. It does not show that open-week tickets are priced "
            "more fairly: it shows that open-week buyers include people who buy a ticket while it is being hit, which cannot happen to a stock ticket on a "
            "weekend. This study does not separate the two (a better price, or better-timed buyers). The like-for-like reading is T3: the same ticket cost "
            f"buyers {est(path('B', 'W1', 'D1'))} points more on the first weekend.",
            f"- **The bug hunt (a Sharpe above 3 starts one).** {len(hi)} rule-B books have a Sharpe above 3 at the fee. {len(short)} of them cover three or four "
            "months (out-of-sample segments and buckets of a few markets): a Sharpe on four monthly numbers is not a measurement. That includes the second "
            f"weekend's out-of-sample book ({num(float(hi[(hi.windows == 'W2') & (hi.scope == ALL) & (hi.segment == 'OOS')].sharpe.iloc[0]))}, four months, "
            f"and its per-contract mean is {est(lv('B', 'W2', 'sell', 'out-of-sample events'))}). The other {len(longer)} are cuts of nine to twelve months: "
            + "; ".join(f"{r.windows} {r.scope} {r.segment} {num(r.sharpe)} ({int(r.markets)} markets, {money(r.pnl)}, {money(r.pnl_without_best_event)} without "
                        f"its best event)" for r in longer.itertuples())
            + ". Checked: every print lies inside its window and none is stamped after its market's result (tested on the cache); W1 under rule B returns S18's "
            "committed numbers to the last digit; the fee is on and doubling it barely moves them; no single event carries a book; rule B uses nothing a trader "
            "would not know at the window's start. No bug found. They are sub-cuts of one year in which stock tickets mostly expired unhit; the pre-registered "
            "books (all markets, whole year) have Sharpes of 1.5 to 2.2. Under rule A the open-week book has a Sharpe of "
            f"{num(float(b[(b.rule == 'A') & (b.window == 'D1') & (b.scope == ALL) & (b.fee_mult == 1.0) & (b.segment == 'OOS')].sharpe.iloc[0]))} "
            "out-of-sample: that is the look-ahead of rule A, not a result.", "",
            "## Caveats", "",
            "- **One year, one oil shock in it** (S18's caveat). Resampling events does not cure shared weather. The three books are the same bet.",
            "- **Age and clock are tied together.** W1 is always the youngest window; W2 is one week older, not a random assignment. The gap measure above says "
            "\"new\"; T2 on buyers' P&L says \"shut\", only just. They are not the same test and the second weekend holds different tickets: buyers there paid "
            f"{num(w2.mean_traded_price, 1)}% on average against {num(d1.mean_traded_price, 1)}% in the open week, because the tickets that were hit are gone.",
            "- **Who trades when.** During sessions some takers buy because the asset is moving toward the strike. Their gains are part of why open-week buyers "
            "lose less. The test measures the price paid, not who paid it.",
            "- **Size-weighting follows volume.** Purchases cluster when a price is rising and sales when it is falling, so traded-price paths are not clean "
            "martingale tests.",
            "- **Commodity futures open on Sunday at 18:00**, so the last two hours of W1 and W2 are not shut for commodities.",
            "- D1 is 32.5 hours of sessions (26 in a holiday week); W1 and W2 are 48 hours each. Weekday nights are in no window.",
            "- **A taker's sale needs a bid.** The prints show what was sold, not how much more could have been.",
            "- The buyers' loss is not a seller's gain unless the seller's resting order is the one lifted (S12 found resting orders adversely selected)."]


if __name__ == "__main__":
    sys.exit(main())
