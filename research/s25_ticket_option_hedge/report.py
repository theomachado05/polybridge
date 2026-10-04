"""S25 report: SUMMARY.md, capacity.md, RUN_LOG.md and the three charts, every number read back from the result files.

Run from `research/`:  python -m s25_ticket_option_hedge.report
"""
from __future__ import annotations

import json
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as cfg  # noqa: E402
from . import engine as eg  # noqa: E402
from .pull import RESEARCH, S18  # noqa: E402
from .run import RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE = "#2a78d6", "#eb6834"                       # hedged, unhedged (the house palette of S18 and S21)
SET_NAME = {"rule": "rule subset (ticket 5+ points above the anchor)", "full": "full set", "left": "markets the rule leaves"}
STRAT = {"U": "unhedged", "P": "hedged, primary (2 spreads, Monday 09:35)", "A": "hedged, variant A (1 spread, Monday 09:35)",
         "B": "hedged, variant B (2 spreads, Friday 15:55 quotes; on paper)", "U2x": "unhedged, fee doubled", "P2x": "primary at 2× costs",
         "A2x": "variant A at 2× costs", "B2x": "variant B at 2× costs"}


def pts(x, d=2):
    return "n/a" if x != x else f"{x:+.{d}f}"


def num(x, d=2):
    return "n/a" if x != x else f"{x:.{d}f}"


def ci(lo, hi, d=2):
    return "n/a (under 5 events)" if lo != lo else f"[{lo:+.{d}f}, {hi:+.{d}f}]"


def ci0(lo, hi, d=2):
    return "n/a (under 5 events)" if lo != lo else f"[{lo:.{d}f}, {hi:.{d}f}]"


def money(x):
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.0f}"


def pc(x, d=1):
    return "n/a" if x != x else f"{100 * x:.{d}f}%"


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.axhline(0, color=INK2, linewidth=1)
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)


def chart_books(eq: pd.DataFrame, oos_from: str) -> None:
    for name, title, dd in (("equity_curve.png", "cumulative P&L after costs", False), ("drawdown.png", "drawdown from the peak", True)):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), facecolor=SURFACE)
        for ax, sname in zip(axes, ("rule", "full")):
            style(ax)
            for st, color, label in (("U", ORANGE, "Unhedged: ticket sold"), ("P", BLUE, "Hedged: ticket sold, 2 spreads bought")):
                e = eq[(eq.scope == "primary") & (eq.set == sname) & (eq.strategy == st)].sort_values("month")
                if not len(e):
                    continue
                xx = pd.to_datetime(e.month + "-01")
                y = np.cumsum(e.pnl.to_numpy())
                if dd:
                    full = np.concatenate([[0.0], y])
                    y = (full - np.maximum.accumulate(full))[1:]
                val = y.min() if dd else y[-1]
                ax.plot(xx, y, color=color, linewidth=2, label=f"{label} (deepest {money(val)})" if dd else label, solid_capstyle="round", marker="o", markersize=4)
                if not dd:
                    ax.annotate(money(val), (xx.iloc[-1], val), xytext=(8, -2 if st == "U" else 8), textcoords="offset points", va="center", fontsize=9, color=color)
            split = pd.Timestamp(oos_from)
            ax.axvline(split, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
            ax.annotate("out-of-sample events start ▸", (split, 0.0), xycoords=("data", "axes fraction"), xytext=(-5, 4), textcoords="offset points",
                        va="bottom", ha="right", fontsize=8.5, color=INK2)
            if dd:
                ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=INK, bbox_to_anchor=(0.0, -0.09))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
            ax.margins(x=0.16)
            ax.set_ylabel("dollars (up to 100 tickets per market)", fontsize=9, color=INK2)
            ax.set_title(SET_NAME[sname], loc="left", fontsize=10, color=INK)
        if not dd:
            axes[0].legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=INK)
        fig.suptitle(f"S25: {title}, hedged against unhedged, same markets and same tickets (2 option spreads per ticket, bought Monday 09:35)",
                     x=0.01, ha="left", fontsize=10.5, color=INK)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def chart_distribution(tr: pd.DataFrame) -> None:
    ok = tr[tr.status == "ok"]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), facecolor=SURFACE)
    step = 25.0
    for ax, sname in zip(axes, ("rule", "full")):
        t = ok[ok.rule] if sname == "rule" else ok
        style(ax)
        u, h = t.ticket_pnl_points.to_numpy(), t.hedged_pnl_points_P.to_numpy()
        lo = step * np.floor(min(u.min(), h.min()) / step)
        hi = step * np.ceil(max(u.max(), h.max()) / step + 1e-9)
        edges = np.arange(lo, hi + step, step)
        mid = (edges[:-1] + edges[1:]) / 2.0
        cu, ch = np.histogram(u, edges)[0], np.histogram(h, edges)[0]
        ax.bar(mid - step * 0.2, cu, width=step * 0.38, color=ORANGE, edgecolor=SURFACE, linewidth=1,
               label=f"unhedged: mean {u.mean():+.1f}, sd {np.std(u, ddof=1):.1f}, worst {u.min():+.0f}")
        ax.bar(mid + step * 0.2, ch, width=step * 0.38, color=BLUE, edgecolor=SURFACE, linewidth=1,
               label=f"hedged: mean {h.mean():+.1f}, sd {np.std(h, ddof=1):.1f}, worst {h.min():+.0f}")
        ax.set_xlabel("P&L per ticket contract, points (bins of 25 points)", fontsize=9, color=INK2)
        ax.set_ylabel("markets", fontsize=9, color=INK2)
        ax.set_title(f"{SET_NAME[sname]}: {len(t)} markets", loc="left", fontsize=10, color=INK)
        ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=INK)
        ax.margins(y=0.25)
    fig.suptitle("S25: P&L per market, ticket sold unhedged against ticket sold and 2 option spreads bought Monday 09:35", x=0.01, ha="left",
                 fontsize=10.5, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(R / "pnl_distribution.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def git_log() -> list[tuple[str, str, str]]:
    try:
        out = subprocess.run(["git", "log", "--format=%h|%ad|%s", "--date=format:%H:%M:%S", "--", "research/s25_ticket_option_hedge",
                              "research/results/s25_ticket_option_hedge"], capture_output=True, text=True, cwd=RESEARCH.parent, check=True).stdout
    except Exception:
        return []
    return [tuple(line.split("|", 2)) for line in out.splitlines() if line.count("|") >= 2][::-1]


def main() -> int:
    meta = json.loads((R / "run_meta.json").read_text())
    s18 = json.loads((S18 / "run_meta.json").read_text())
    m, hy, ce, eq = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "hypotheses.csv"), pd.read_csv(R / "cells.csv"), pd.read_csv(R / "equity.csv")
    tr = pd.read_csv(R / "trades.csv", dtype={"market": str, "event": str})
    ok = tr[tr.status == "ok"]
    chart_books(eq, s18["oos_from"])
    chart_distribution(tr)
    commits = git_log()
    prereg = commits[0][0] if commits else "n/a"

    def mr(set_, st, seg="ALL", scope="primary"):
        return m[(m.scope == scope) & (m.set == set_) & (m.strategy == st) & (m.segment == seg)].iloc[0]

    def hr(h, variant="P", seg="ALL", set_="rule"):
        return hy[(hy.hypothesis == h) & (hy.variant == variant) & (hy.segment == seg) & (hy.set == set_)].iloc[0]

    def stat(r):
        return f"{pts(r.mean_pnl_points)} points {ci(r.ci_lo, r.ci_hi)}"

    def nm(r):
        return f"{int(r.markets)} markets in {int(r.events)} events"

    n_plan, n_ok, n_rule_plan, n_rule = meta["markets_in_plan"], meta["hedged_primary"], meta["rule_subset_in_plan"], meta["hedged_primary_rule"]
    seg_all, seg_rule = meta["hedged_primary_by_segment"], meta["hedged_primary_rule_by_segment"]
    h1, h2a, h2b, h3 = hr("H1"), hr("H2a"), hr("H2b"), hr("H3", set_="rule minus left")
    h2a_f, h2b_f = hr("H2a", set_="full"), hr("H2b", set_="full")
    uR, pR, aR, bR = (mr("rule", s) for s in ("U", "P", "A", "B"))
    uF, pF, aF, bF = (mr("full", s) for s in ("U", "P", "A", "B"))
    uL, pL = mr("left", "U"), mr("left", "P")
    p2R, p2F, u2R, u2F = mr("rule", "P2x"), mr("full", "P2x"), mr("rule", "U2x"), mr("full", "U2x")
    verdict = lambda ok_: "**met**" if ok_ else "**not met**"
    vw = lambda ok_: "met" if ok_ else "not met"
    lead = bool(h1.passes and h2a.passes and h2b.passes)
    drops = {k: v for k, v in meta["status"].items() if k != "ok"}
    drops_rule = {k: v for k, v in meta["status_rule_subset"].items() if k != "ok"}

    # ------------------------------------------------------------------ the answer, built from the numbers
    af = pd.read_csv(R / "after_run.csv")

    def ar(look, set_, what):
        return af[af.look.str.startswith(look) & (af.set == set_) & af.what.str.startswith(what)].iloc[0]

    def cellv(set_, cell, col):
        r = ce[(ce.set == set_) & (ce.cell == cell)].iloc[0]
        return r[col] if r.markets else float("nan")

    def celln(set_, cell):
        return int(ce[(ce.set == set_) & (ce.cell == cell)].iloc[0].markets)

    l2F, l2R = ar("L2", "full", "hedged"), ar("L2", "rule", "hedged")
    hedge_adds = pR.mean_pnl_points - uR.mean_pnl_points
    hedge_adds_F = pF.mean_pnl_points - uF.mean_pnl_points
    h2 = bool(h2a.passes and h2b.passes)
    if lead:
        head = ("**The premium survives the hedge and the hedge cuts the risk, in this sample. By the rule fixed in advance that is a lead needing "
                "replication, not an edge: almost none of it is out-of-sample.**")
    else:
        worse = pF.ci_hi == pF.ci_hi and pF.ci_hi < 0 and h2a_f.ci_lo == h2a_f.ci_lo and h2a_f.ci_lo > 1
        head = ("**Buying the option spread at real Monday quotes "
                + ("made the trade worse, not safer: it cost more than it paid back and it raised the risk instead of cutting it. "
                   if worse else "did not make this a hedged trade by the rules fixed in advance. ")
                + f"H1 is {'met' if h1.passes else 'not met'} and H2 is {'met' if h2 else 'not met'}: not a lead. "
                + ("One thing holds: the options anchor still sorts the tickets after the hedge (H3 met).**" if h3.passes else "H3 is not met either.**"))
    NT, TB, TC = eg.CELLS[0], eg.CELLS[1], eg.CELLS[2]
    ans = [
        head, "",
        f"**On all {n_ok} hedged markets** the ticket sold at its traded bid made {stat(uF)} per ticket unhedged. With two option spreads per ticket bought "
        f"at Monday 09:35 quotes the same tickets made **{stat(pF)}**. The two spreads cost {num(pF.mean_hedge_cost_points)} points per ticket and paid back "
        f"{num(pF.mean_hedge_payoff_points)}. The standard deviation of P&L per market went from {num(h2a_f.unhedged)} to {num(h2a_f.hedged)} points: a ratio of "
        f"**{num(h2a_f.value)} {ci0(h2a_f.ci_lo, h2a_f.ci_hi)}**, above 1. The worst market went from {pts(uF.worst_market)} to {pts(pF.worst_market)} points, "
        f"the worst month of the book from {money(h2b_f.unhedged)} to {money(h2b_f.hedged)}.", "",
        f"**H3, the anchor still sorts: {vw(h3.passes)}.** Hedged P&L on the rule subset {pts(h3.rule_mean)} points minus hedged P&L on the "
        f"{int(h3.left_markets)} markets the rule leaves {pts(h3.left_mean)}: **{pts(h3.value)} points {ci(h3.ci_lo, h3.ci_hi)}**. The tickets the rule leaves "
        f"lose once hedged: {stat(pL)}.", "",
        f"**H1, the premium survives the hedge: {vw(h1.passes)}.** On the rule subset ({nm(pR)}) the hedged trade made **{stat(pR)}** per ticket, an interval "
        f"that {'excludes' if h1.passes else 'includes'} zero. The same tickets unhedged made {stat(uR)}. The hedge cost {num(pR.mean_hedge_cost_points)} points "
        f"per ticket and paid back {num(pR.mean_hedge_payoff_points)}: it {'added' if hedge_adds >= 0 else 'took'} {num(abs(hedge_adds))} points per ticket. "
        f"In-sample {stat(mr('rule', 'P', 'IS'))} on {int(mr('rule', 'P', 'IS').markets)} markets. Out-of-sample {pts(mr('rule', 'P', 'OOS').mean_pnl_points)} on "
        f"{int(mr('rule', 'P', 'OOS').markets)} markets, which is no evidence either way. At 2× costs {stat(p2R)}.", "",
        f"*Looked at after the run, not a test:* {int(ar('L1', 'full', 'markets left out').markets)} hedges ({int(ar('L1', 'rule', 'markets left out').markets)} in "
        f"the rule subset) were bought on opening quotes that had not been refreshed by 09:35, one of them at \"0 bid, 15.00 offered\". The registered rule buys "
        f"them at the offer. Without them the rule subset reads {pts(ar('L1', 'rule', 'hedged, primary').mean_pnl_points)} "
        f"{ci(ar('L1', 'rule', 'hedged, primary').ci_lo, ar('L1', 'rule', 'hedged, primary').ci_hi)} on {int(ar('L1', 'rule', 'hedged, primary').markets)} markets and "
        f"the full set {pts(ar('L1', 'full', 'hedged, primary').mean_pnl_points)} "
        f"{ci(ar('L1', 'full', 'hedged, primary').ci_lo, ar('L1', 'full', 'hedged, primary').ci_hi)}. No verdict changes.", "",
        f"**H2, the hedge cuts risk: {vw(h2)}.** (a) Standard deviation of P&L per market on the rule subset: hedged {num(h2a.hedged)} points against "
        f"unhedged {num(h2a.unhedged)}, a ratio of **{num(h2a.value)} {ci0(h2a.ci_lo, h2a.ci_hi)}**; it had to be below 1 with the interval below 1: "
        f"{verdict(h2a.passes)}. (b) Worst month of the book: hedged {money(h2b.hedged)} ({pc(h2b.hedged_pct_of_capital)} of its capital base) against unhedged "
        f"{money(h2b.unhedged)} ({pc(h2b.unhedged_pct_of_capital)}): {verdict(h2b.passes)}; difference {money(h2b.value)}, interval [{money(h2b.ci_lo)}, "
        f"{money(h2b.ci_hi)}]. Worst single market: hedged {pts(pR.worst_market)} points against unhedged {pts(uR.worst_market)}. Maximum drawdown: hedged "
        f"{pc(pR.max_drawdown)} against {pc(uR.max_drawdown)}. Monthly Sharpe: hedged {num(pR.sharpe)} against {num(uR.sharpe)}. Skew per market: hedged "
        f"{num(pR["skew"])} against {num(uR["skew"])}.", "",
        "**Why the hedge fails as specified.** Three things, all visible in the outcome table below.",
        f"1. *It does not cover the case that hurts.* The spread pays when the stock **finishes** beyond the level; the ticket loses when the stock **touches** it. "
        f"{celln('full', TC)} of the {n_ok} markets ({pc(celln('full', TC) / n_ok, 0)}) touched and came back: the ticket lost "
        f"{num(abs(cellv('full', TC, 'ticket_pnl_points')))} points, the hedge lost another {num(abs(cellv('full', TC, 'hedge_pnl_points_P')))}, "
        f"{pts(cellv('full', TC, 'hedged_pnl_points_P'))} in all.",
        f"2. *Two spreads per ticket is too many.* When the ticket never touched ({celln('full', NT)} markets, {pc(celln('full', NT) / n_ok, 0)}) the two spreads "
        f"cost {num(cellv('full', NT, 'hedge_cost_points_P'))} points and the ticket had earned {num(cellv('full', NT, 'ticket_pnl_points'))}: "
        f"{pts(cellv('full', NT, 'hedged_pnl_points_P'))}. When it touched and finished beyond ({celln('full', TB)} markets) the hedge paid twice the loss: "
        f"{pts(cellv('full', TB, 'hedged_pnl_points_P'))}. The hedge swaps one bet for a larger opposite one.",
        f"3. *The options are not cheap, and crossing their quotes at 09:35 is dear.* The two spreads cost {num(pF.mean_hedge_cost_points)} points and paid back "
        f"{num(pF.mean_hedge_payoff_points)}: the hedge leg lost {num(abs(pF.mean_hedge_pnl_points))} points per ticket, against a ticket premium of "
        f"{num(uF.mean_pnl_points)}. On the markets with fresh quotes about {num(l2F.mean_crossing_cost_points, 1)} points of the hedge leg's loss is the cost of "
        f"crossing the quotes and about {num(abs(l2F.mean_hedge_pnl_at_mid_points), 1)} is options priced above what happened (looked at after the run, L2).", "",
        f"**The variants, disclosed, none of them the test.** One spread per ticket (variant A) on the rule subset: {stat(aR)}, standard deviation "
        f"{num(aR.sd)} against {num(uR.sd)} unhedged (ratio {num(hr('H2a', 'A').value)} {ci0(hr('H2a', 'A').ci_lo, hr('H2a', 'A').ci_hi)}), worst month "
        f"{money(hr('H2b', 'A').hedged)} against {money(hr('H2b', 'A').unhedged)}; on the full set {stat(aF)}. Friday 15:55 quotes (variant B, the gap on paper, "
        f"not executable): rule subset {stat(bR)}, full set {stat(bF)}. Primary at 2× costs: rule subset {stat(p2R)}, full set {stat(p2F)}.", "",
        f"**Out-of-sample there is almost nothing:** {seg_all.get('OOS', 0)} of the {n_ok} hedged markets, {seg_rule.get('OOS', 0)} of the {n_rule} in the rule "
        f"subset. S21 already found this. Nothing here is confirmed out-of-sample.", "",
        f"**Markets.** {n_ok} of the {n_plan} could be hedged, {n_rule} of the {n_rule_plan} in the rule subset. Dropped: "
        + "; ".join(f"{v} ({k})" for k, v in drops.items()) + ". The 20 index (SPX) tickets are out because Massive does not serve the index close on this key.", "",
    ]

    # ------------------------------------------------------------------ tables
    def risk_row(set_, st, seg="ALL", scope="primary"):
        r = mr(set_, st, seg, scope)
        return [STRAT[st], int(r.markets), int(r.events), pts(r.mean_pnl_points), ci(r.ci_lo, r.ci_hi), num(r.sd), pts(r.worst_market), num(r["skew"]),
                money(r.book_pnl), money(r.capital_base).lstrip("+"), num(r.sharpe), pc(r.max_drawdown), f"{money(r.worst_month_dollars)} ({pc(r.worst_month)})",
                int(r.months)]

    risk_head = ["Trade", "Markets", "Events", "Mean P&L per ticket, points", "95% interval", "SD per market", "Worst market", "Skew", "Book P&L",
                 "Capital base", "Sharpe (monthly)", "Max drawdown", "Worst month", "Months"]

    def cells_table(set_):
        c = ce[ce.set == set_]
        rows = []
        for r in c.itertuples():
            if r.markets == 0:
                rows.append([r.cell, 0, "0.0%", "n/a", "n/a", "n/a", "n/a", "n/a"])
                continue
            rows.append([r.cell, int(r.markets), pc(r.share_of_markets), pts(r.ticket_pnl_points), num(r.hedge_cost_points_P), num(200 * r.payoff_unit),
                         pts(r.hedge_pnl_points_P), pts(r.hedged_pnl_points_P)])
        return table(["Outcome", "Markets", "Share", "Ticket P&L, points", "Hedge cost", "Hedge paid", "Hedge P&L", "Hedged P&L"], rows)

    fb = meta["finished_beyond_without_touch"]
    seg_rows = []
    for set_ in ("rule", "full", "left"):
        for seg in ("IS", "OOS"):
            for st in ("U", "P"):
                r = mr(set_, st, seg)
                seg_rows.append([SET_NAME[set_], "in-sample" if seg == "IS" else "out-of-sample", "unhedged" if st == "U" else "hedged (primary)", int(r.markets),
                                 int(r.events), pts(r.mean_pnl_points), ci(r.ci_lo, r.ci_hi), num(r.sd), pts(r.worst_market), money(r.book_pnl), num(r.sharpe)])

    var_rows = []
    for set_ in ("rule", "full"):
        for st in ("U", "P", "A", "B", "U2x", "P2x", "A2x", "B2x"):
            r = mr(set_, st)
            var_rows.append([SET_NAME[set_], STRAT[st], int(r.markets), pts(r.mean_pnl_points), ci(r.ci_lo, r.ci_hi), num(r.sd), pts(r.worst_market), num(r["skew"]),
                             "n/a" if st.startswith("U") else num(r.mean_hedge_cost_points), "n/a" if st.startswith("U") else num(r.mean_hedge_payoff_points),
                             money(r.book_pnl), num(r.sharpe), pc(r.max_drawdown), money(r.worst_month_dollars)])
    bown = [[SET_NAME[s], STRAT[st], int(mr(s, st, scope="B").markets), pts(mr(s, st, scope="B").mean_pnl_points), ci(mr(s, st, scope="B").ci_lo, mr(s, st, scope="B").ci_hi),
             num(mr(s, st, scope="B").sd), pts(mr(s, st, scope="B").worst_market)] for s in ("rule", "full") for st in ("U", "B", "B2x")]

    hyp_rows = []
    for vid in ("P", "A", "B", "P2x"):
        for seg in ("ALL", "IS", "OOS"):
            a, b1, b2, c = hr("H1", vid, seg), hr("H2a", vid, seg), hr("H2b", vid, seg), hr("H3", vid, seg, "rule minus left")
            hyp_rows.append([STRAT[vid], {"ALL": "whole sample", "IS": "in-sample", "OOS": "out-of-sample"}[seg], int(a.markets),
                             f"{pts(a.value)} {ci(a.ci_lo, a.ci_hi)}", f"{num(b1.value)} {ci0(b1.ci_lo, b1.ci_hi)}",
                             f"{money(b2.hedged)} vs {money(b2.unhedged)}", f"{pts(c.value)} {ci(c.ci_lo, c.ci_hi)}"])

    high = m[(m.sharpe.abs() > 3) & (m.scope == "primary")]
    high_txt = "; ".join(f"{STRAT[r.strategy]}, {SET_NAME[r.set]}, {r.segment}: {num(r.sharpe)} ({int(r.markets)} markets, {int(r.months)} months)" for r in high.itertuples())
    rc = meta["recheck"]
    age = meta["monday_quote_age_s"]
    okR = ok[ok.rule]
    med = lambda t, col: float((200 * t[col]).median())
    crossm = lambda t: float((t.hedge_cost_points_P - 200 * t.unit_mid_P).median())

    worst = ok.sort_values("hedged_pnl_points_P").iloc[0]
    L = [
        "# S25: sell the ticket on Polymarket, buy the matching option spread. What is left, and how much risk goes?", "",
        f"Method, pre-registered before any Monday option quote or any underlying close was pulled: [`research/s25_ticket_option_hedge/METHOD.md`]"
        f"(../../s25_ticket_option_hedge/METHOD.md) (commit `{prereg}`). Markets: S21's anchored stock and S&P 500 \"will it hit\" tickets with a first-weekend "
        f"taker sale, first weekends from 2025-10-31 to 2026-09-25. Ticket leg: S18's traded bids and held-to-result P&L. Hedge leg: real NBBO option quotes "
        f"from Massive at 09:35 New York on the first session after the weekend, the long leg at its ask and the short leg at its bid, held to expiry and "
        f"settled on the underlying's unadjusted close. Files: [`trades.csv`](trades.csv), [`metrics.csv`](metrics.csv), [`hypotheses.csv`](hypotheses.csv), "
        f"[`cells.csv`](cells.csv), [`equity.csv`](equity.csv), [`after_run.csv`](after_run.csv), [`run_meta.json`](run_meta.json), [`capacity.md`](capacity.md), "
        f"[`RUN_LOG.md`](RUN_LOG.md).", "",
        "Words used here. A *ticket* is one YES contract of a Polymarket \"will the stock hit this level this month\" market; it pays $1 if the level is "
        "touched. A *spread* is two options on the two listed strikes around that level, one bought and one sold; sized here so that one spread pays $1 "
        "when the stock finishes beyond the far strike at expiry. A *point* is one cent per ticket. *Hedged* means the ticket sold plus the spreads bought.", "",
        "## Answer", "", *ans,
        "## How many markets", "",
        f"- In the plan: {n_plan} markets in {meta['events_in_plan']} events; {n_rule_plan} in the rule subset.",
        f"- **Hedged: {n_ok}** in {meta['hedged_primary_events']} events ({seg_all.get('IS', 0)} in-sample, {seg_all.get('OOS', 0)} out-of-sample); "
        f"**{n_rule} in the rule subset** ({seg_rule.get('IS', 0)} in-sample, {seg_rule.get('OOS', 0)} out-of-sample).",
        f"- **Dropped: {meta['dropped']}** (" + "; ".join(f"{v}: {k}" for k, v in drops.items()) + "). The first reason is the 20 S&P 500 index (SPX) tickets: "
        "Massive answered HTTP 403, not entitled, for the index's daily closes on this key.",
        f"- Dropped from the rule subset: {n_rule_plan - n_rule}" + (" (" + "; ".join(f"{v}: {k}" for k, v in drops_rule.items()) + ")" if drops_rule else "") + ".",
        "- Dropped by ticker: " + ", ".join(f"{k} {v}" for k, v in meta["dropped_by_ticker"].items()) + ". Hedged by ticker: "
        + ", ".join(f"{k} {v}" for k, v in meta["hedged_by_ticker"].items()) + ".",
        f"- Monday quotes used are {num(age['min'], 1)} to {num(age['max'], 1)} seconds older than 09:35:00 (median {num(age['median'], 1)}). "
        f"{meta['zero_bid_short_leg_P']} hedges sold a short leg with a zero bid (sold for nothing); {meta['crossed_pairs_P']} pairs were crossed; "
        f"{meta['above_one_P']} cost more than the spread can pay.", "",
        "## Unhedged against hedged, same markets", "",
        "### Rule subset", "", table(risk_head, [risk_row("rule", s) for s in ("U", "P")]), "",
        "### Full set", "", table(risk_head, [risk_row("full", s) for s in ("U", "P")]), "",
        "### The markets the rule leaves", "", table(risk_head, [risk_row("left", s) for s in ("U", "P")]), "",
        "P&L per ticket weighs each market once. The book holds up to 100 tickets per market, never more than the printed size, and for the hedged book "
        "the matching number of spreads; the capital base is the largest capital locked at one time (ticket collateral plus option premium); Sharpe, drawdown "
        "and worst month are on monthly P&L over that base. Intervals resample events.", "",
        "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "", "![P&L distribution](pnl_distribution.png)", "",
        "## The four outcomes", "", "### Rule subset", "", cells_table("rule"), "", "### Full set", "", cells_table("full"), "",
        f"\"Touched\" is the ticket's result. \"Finished beyond\" is the close on the option's expiry date at or beyond the question's level. \"Hedge cost\" and "
        f"\"hedge paid\" are for the two spreads of the primary, in points per ticket. The hedge is built for the second row and does not cover the third: "
        f"on the full set the touched-and-came-back markets lost {pts(cellv('full', eg.CELLS[2], 'hedged_pnl_points_P'))} points hedged against "
        f"{pts(cellv('full', eg.CELLS[2], 'ticket_pnl_points'))} unhedged ({celln('full', eg.CELLS[2])} markets).",
        (f"**Finished beyond without a recorded touch: {len(fb)} market(s).** " + "; ".join(
            f"{x['ticker']} \"{x['question']}\" (close {x['close_expiry']:.2f} on {x['expiry']} against the level {x['level']:g}; the option expires "
            f"{x['days_expiry_after_end']:.0f} days after the question's last session)" for x in fb) + "."
         if fb else "**Finished beyond without a recorded touch: none**, as it should be."), "",
        "## What the hedge costs, and the capital each leg ties up", "",
        table(["", "Rule subset", "Full set"], [
            ["Hedge cost paid, mean, points per ticket (2 spreads, Monday 09:35, ask and bid, with commission)", num(pR.mean_hedge_cost_points), num(pF.mean_hedge_cost_points)],
            ["Hedge cost paid, median", num(float(okR.hedge_cost_points_P.median())), num(float(ok.hedge_cost_points_P.median()))],
            ["The same two spreads at Monday's mid quotes, median", num(med(okR, "unit_mid_P")), num(med(ok, "unit_mid_P"))],
            ["Cost of crossing the quotes plus commission, median, points per ticket", num(crossm(okR)), num(crossm(ok))],
            ["The same two spreads at Friday 15:55 mid quotes, median", num(med(okR, "unit_mid_B")), num(med(ok, "unit_mid_B"))],
            ["Hedge cost at Friday 15:55 quotes (variant B), mean", num(bR.mean_hedge_cost_points), num(bF.mean_hedge_cost_points)],
            ["What the hedge paid at expiry, points per ticket", num(pR.mean_hedge_payoff_points), num(pF.mean_hedge_payoff_points)],
            ["Hedge P&L, points per ticket", pts(pR.mean_hedge_pnl_points), pts(pF.mean_hedge_pnl_points)],
            ["Ticket price received, points", num(pR.mean_ticket_price), num(pF.mean_ticket_price)],
            ["Ticket leg capital per ticket (collateral, 100 minus the price), points", num(100 - pR.mean_ticket_price), num(100 - pF.mean_ticket_price)],
            ["Hedge leg capital per ticket (premium paid), points", num(pR.mean_hedge_cost_points), num(pF.mean_hedge_cost_points)],
            ["Book: capital base unhedged", money(uR.capital_base).lstrip("+"), money(uF.capital_base).lstrip("+")],
            ["Book: capital base hedged", money(pR.capital_base).lstrip("+"), money(pF.capital_base).lstrip("+")],
            ["Book: ticket collateral deployed / option premium deployed", f"{money(pR.ticket_capital_deployed).lstrip('+')} / {money(pR.hedge_capital_deployed).lstrip('+')}",
             f"{money(pF.ticket_capital_deployed).lstrip('+')} / {money(pF.hedge_capital_deployed).lstrip('+')}"],
        ]), "",
        "Commission: $0.65 per option contract per leg (an assumed retail figure, the project's existing cost model). No financing cost is charged on either leg.", "",
        "## Variants and 2× costs (all reported, none replaces the primary)", "",
        table(["Set", "Trade", "Markets", "Mean P&L per ticket, points", "95% interval", "SD per market", "Worst market", "Skew", "Hedge cost", "Hedge paid",
               "Book P&L", "Sharpe (monthly)", "Max drawdown", "Worst month"], var_rows), "",
        "Variant B uses Friday 15:55 option quotes. It is **not executable in that order**: the ticket is sold after Friday's close. It shows the gap as it "
        "stood on paper. At 2× costs each option leg is moved a further half-spread against us, the commission is doubled and the ticket's fee is doubled.", "",
        f"Variant B on every market with a verified close (its own set, {meta['variant_B_own_set']} markets, {meta['variant_B_own_rule']} in the rule subset):", "",
        table(["Set", "Trade", "Markets", "Mean P&L per ticket, points", "95% interval", "SD per market", "Worst market"], bown), "",
        "## The hypotheses by variant and segment", "",
        table(["Trade", "Segment", "Rule-subset markets", "H1: hedged mean on the rule subset", "H2a: SD ratio, rule subset", "H2b: worst month hedged vs unhedged",
               "H3: rule subset minus left"], hyp_rows), "",
        "Only the first row (primary, whole sample, 1× costs) is the test. The others are disclosure.", "",
        "## In-sample and out-of-sample (S18's split of events)", "",
        table(["Set", "Segment", "Trade", "Markets", "Events", "Mean P&L per ticket, points", "95% interval", "SD per market", "Worst market", "Book P&L",
               "Sharpe (monthly)"], seg_rows), "",
        f"**The out-of-sample part has almost no markets:** {seg_all.get('OOS', 0)} hedged markets, {seg_rule.get('OOS', 0)} in the rule subset. Nothing here is "
        f"confirmed out-of-sample. S21 found the same.", "",
        "## What a pass would and would not mean", "",
        "A pass on H1 and H2 is a **lead needing replication, not an edge**. The tickets' results were known before this study; only the Monday option quotes, "
        "the closes at expiry and the hedged P&L were new. The rule subset was chosen by S21 on the same markets, so its unhedged premium is in-sample by "
        "construction.", "",
        "## Looked at after the run (not pre-registered, not tests)", "",
        "These three looks were chosen after the result was read (METHOD.md, amendment 2). Each was run once. None replaces H1, H2 or H3.", "",
        f"**L1, fresh quotes only.** {int(ar('L1', 'full', 'markets left out').markets)} hedged markets ({int(ar('L1', 'rule', 'markets left out').markets)} in the "
        f"rule subset) had a Monday leg quote more than 60 seconds old at 09:35: an opening quote that was never refreshed. The clearest case is the worst market "
        f"of the study, {worst.ticker} \"{worst.question}\": both legs showed {num(worst.mon_lo_bid)} bid, {num(worst.mon_lo_ask)} offered, about "
        f"{num(max(worst.mon_lo_age_s, worst.mon_hi_age_s), 0)} seconds old; the registered rule buys at the offer, and the hedge of a far out-of-the-money spread "
        f"cost {num(worst.hedge_cost_points_P)} points ({pts(worst.hedged_pnl_points_P)} hedged). Nobody would lift that offer. Without those markets:", "",
        table(["Set", "Trade", "Markets", "Mean P&L per ticket, points", "95% interval", "SD per market", "SD ratio to unhedged", "Worst market"],
              [[SET_NAME[x], w, int(ar("L1", x, w).markets), pts(ar("L1", x, w).mean_pnl_points), ci(ar("L1", x, w).ci_lo, ar("L1", x, w).ci_hi), num(ar("L1", x, w).sd),
                "1" if w == "unhedged" else f"{num(ar('L1', x, w).sd_ratio)} {ci0(ar('L1', x, w).sd_ratio_lo, ar('L1', x, w).sd_ratio_hi)}", pts(ar("L1", x, w).worst_market)]
               for x in ("rule", "full", "left") for w in ("unhedged", "hedged, primary", "hedged, variant A")]), "",
        f"Rule subset minus left, hedged primary, fresh quotes: {pts(ar('L1', 'rule minus left', 'hedged').mean_pnl_points)} "
        f"{ci(ar('L1', 'rule minus left', 'hedged').ci_lo, ar('L1', 'rule minus left', 'hedged').ci_hi)}. The stale quotes made the primary look worse than a careful "
        f"trader would have done, and they do not change any verdict: the two-spread hedge still does not cut the standard deviation, and on the rule subset its "
        f"interval still includes zero.", "",
        f"**L2, the same two spreads at Monday's mid quotes plus commission (not executable), on the fresh quotes.** Rule subset "
        f"{pts(l2R.mean_pnl_points)} {ci(l2R.ci_lo, l2R.ci_hi)}; full set {pts(l2F.mean_pnl_points)} {ci(l2F.ci_lo, l2F.ci_hi)}. Bought at mid, the hedge leg "
        f"still loses {num(abs(l2F.mean_hedge_pnl_at_mid_points))} points per ticket on the full set ({num(abs(l2R.mean_hedge_pnl_at_mid_points))} on the rule "
        f"subset): in this sample the options were priced above what happened, as S21 noted of its anchor. Crossing the quotes costs a further mean of "
        f"{num(l2F.mean_crossing_cost_points)} points per ticket on the full set (median {num(l2F.median_crossing_cost_points)}; rule subset mean "
        f"{num(l2R.mean_crossing_cost_points)}). So about half of the hedge leg's loss is the options' own premium and about half is the cost of crossing at the "
        f"open. Even at mid the two-spread hedge raises the standard deviation on the full set: ratio {num(l2F.sd_ratio)} "
        f"{ci0(l2F.sd_ratio_lo, l2F.sd_ratio_hi)}.", "",
        f"**L3, how many spreads per ticket would have cut the risk most, found after the fact.** Rule subset: {num(ar('L3', 'rule', 'hedged').h)} spreads per ticket, "
        f"standard deviation ratio {num(ar('L3', 'rule', 'hedged').sd_ratio)} {ci0(ar('L3', 'rule', 'hedged').sd_ratio_lo, ar('L3', 'rule', 'hedged').sd_ratio_hi)}, mean "
        f"{pts(ar('L3', 'rule', 'hedged').mean_pnl_points)} {ci(ar('L3', 'rule', 'hedged').ci_lo, ar('L3', 'rule', 'hedged').ci_hi)}. Full set: "
        f"{num(ar('L3', 'full', 'hedged').h)} spreads, ratio {num(ar('L3', 'full', 'hedged').sd_ratio)} "
        f"{ci0(ar('L3', 'full', 'hedged').sd_ratio_lo, ar('L3', 'full', 'hedged').sd_ratio_hi)}, mean {pts(ar('L3', 'full', 'hedged').mean_pnl_points)} "
        f"{ci(ar('L3', 'full', 'hedged').ci_lo, ar('L3', 'full', 'hedged').ci_hi)}. The ticket's P&L and one spread's P&L move against each other with a correlation of "
        f"{num(ar('L3', 'rule', 'hedged').correlation_ticket_vs_one_spread)} (rule subset) and {num(ar('L3', 'full', 'hedged').correlation_ticket_vs_one_spread)} "
        f"(full set). These ratios were fitted on the same markets they are scored on, so they flatter the hedge; even so, the best ratio removes about "
        f"{num(100 * (1 - ar('L3', 'full', 'hedged').sd_ratio), 0)}% of the standard deviation on the full set and {num(100 * (1 - ar('L3', 'rule', 'hedged').sd_ratio), 0)}% "
        f"on the rule subset. A spread that pays on the finish is a weak hedge for a ticket that pays on the touch.", "",
        "## Checks", "",
        f"- Every primary hedged P&L was recomputed by a second route from the cached quotes, the cached close and S18's file: {rc['recomputed']} markets, "
        f"{rc['mismatches']} mismatches.",
        f"- The copied book function reproduces S18's own function on the ticket leg: {'yes' if meta['copied_book_equals_s18_book_on_ticket_leg'] else 'NO'}.",
        f"- Tickets whose result came before the hedge was bought: {meta['result_before_hedge']}.",
        ("- **A Sharpe beyond 3 in absolute value appears in:** " + high_txt + ". " + ("All of them are negative: hedged books that lose in most of "
         "their months. " if (high.sharpe < 0).all() else "") + "These are monthly numbers over at most a dozen months. The bug hunt: the recomputation above, the "
         "quote times (every quote used is from 09:30:00 to 09:35:00 of the hedge day), the close basis (no market finished beyond its level without a recorded "
         "touch, which ties Massive's closes to Polymarket's results), and the after-the-run look L1 at stale opening quotes."
         if len(high) else "- No book of the primary set shows a Sharpe beyond 3 in absolute value."), "",
    ]
    (R / "SUMMARY.md").write_text("\n".join(L) + "\n")

    # ------------------------------------------------------------------ capacity.md
    okr = ok[ok.rule]

    def leg_stats(t):
        up = t.direction > 0
        lb, la = np.where(up, t.mon_lo_bid, t.mon_hi_bid), np.where(up, t.mon_lo_ask, t.mon_hi_ask)
        sb, sa = np.where(up, t.mon_hi_bid, t.mon_lo_bid), np.where(up, t.mon_hi_ask, t.mon_lo_ask)
        l_asz, s_bsz = np.where(up, t.mon_lo_ask_size, t.mon_hi_ask_size), np.where(up, t.mon_hi_bid_size, t.mon_lo_bid_size)
        with np.errstate(divide="ignore", invalid="ignore"):
            lsp, ssp = 100 * (la - lb) / ((la + lb) / 2), 100 * (sa - sb) / ((sa + sb) / 2)
        per_spread = 100.0 * t.width / cfg.HEDGE_RATIO_PRIMARY                  # tickets one spread contract hedges at h = 2
        return {"long_spread_usd": float(np.median(la - lb)), "short_spread_usd": float(np.median(sa - sb)), "long_spread_pct": float(np.nanmedian(lsp)),
                "short_spread_pct": float(np.nanmedian(ssp)), "long_ask_size": float(np.median(l_asz)), "short_bid_size": float(np.median(s_bsz)),
                "long_vol": float(t.long_leg_volume_hedge_day.median()), "short_vol": float(t.short_leg_volume_hedge_day.median()),
                "zero_vol": float(((t.long_leg_volume_hedge_day == 0) | (t.short_leg_volume_hedge_day == 0)).mean()),
                "vol_known": int(t.long_leg_volume_hedge_day.notna().sum()),
                "cross_points": float((t.hedge_cost_points_P - 200 * t.unit_mid_P).median()), "width": float(t.width.median()),
                "tickets_per_spread": float(per_spread.median()), "printed": float(t.printed_size.median()),
                "printed_q1": float(t.printed_size.quantile(0.25)), "printed_q3": float(t.printed_size.quantile(0.75)),
                "share_one_spread": float((t.printed_size >= per_spread).mean()), "n": int(len(t)),
                "total_printed": float(t.printed_size.sum()), "total_premium": float((t.printed_size * t.sell_price).sum())}

    cap = []
    for name, t in (("Rule subset", okr), ("Full set", ok)):
        s = leg_stats(t)
        cap += [f"## {name} ({s['n']} hedged markets)", "",
                f"- **Option quotes at entry (Monday 09:35):** the long leg is quoted a median of ${s['long_spread_usd']:.2f} wide ({s['long_spread_pct']:.0f}% of its mid), "
                f"the short leg ${s['short_spread_usd']:.2f} ({s['short_spread_pct']:.0f}%). Crossing both, with commission, costs a median of "
                f"{s['cross_points']:.2f} points per ticket against the mid.",
                f"- **Size at the quote:** a median of {s['long_ask_size']:.0f} contracts offered on the long leg and {s['short_bid_size']:.0f} bid on the short leg.",
                f"- **Option volume on the hedge day:** a median of {s['long_vol']:.0f} contracts on the long leg and {s['short_vol']:.0f} on the short leg "
                f"({s['vol_known']} markets with volume pulled); {100 * s['zero_vol']:.0f}% of the hedges have a leg that did not trade that day.",
                f"- **The ticket's printed size:** a median of {s['printed']:.0f} tickets sold into bids per market over the first weekend (quartiles "
                f"{s['printed_q1']:.0f} to {s['printed_q3']:.0f}); {s['total_printed']:,.0f} tickets and ${s['total_premium']:,.0f} of premium in all.",
                f"- **Lot size is the binding limit.** One listed spread is 100 shares; with a median width of ${s['width']:.2f} it pays ${100 * s['width']:,.0f} at most, "
                f"which hedges {s['tickets_per_spread']:.0f} tickets at 2 spreads per ticket. Only {100 * s['share_one_spread']:.0f}% of these markets printed that many "
                f"tickets in their first weekend. The book in the summary holds up to 100 tickets per market and so holds a fraction of one option contract: "
                f"it is an accounting of the trade per ticket, not an order that could be sent.", ""]
    cap_text = ["# S25 capacity", "",
                "The Polymarket side limits this trade, and the option lot size makes the hedge lumpy; listed-option liquidity does not.", "", *cap,
                "Sources: option NBBO and daily option volume from Massive; printed ticket sizes from S18's `prints_markets.csv` (takers' sales, Friday 20:00 to "
                "Sunday 20:00 New York). The prints show what did trade; a newcomer hitting the same bids would have moved them."]
    (R / "capacity.md").write_text("\n".join(cap_text) + "\n")

    # ------------------------------------------------------------------ RUN_LOG.md
    log = meta.get("pull_log", [])
    st = meta["status"]
    K_CLOSE = "the underlying's closes or splits are not served"
    age_all = np.maximum(ok.mon_lo_age_s, ok.mon_hi_age_s)
    notes = [
        f"1. **The index close is not served.** `/v2/aggs/ticker/I:SPX/range/1/day/...` answered `HTTP 403 NOT_AUTHORIZED: You are not entitled to this data` "
        f"(both requests, see the pull's log). By METHOD.md section 5 the {st.get(K_CLOSE, 0)} index (SPX) markets are "
        f"dropped, {meta['status_rule_subset'].get(K_CLOSE, 0)} of them in the rule subset. Their Monday option quotes "
        f"were pulled and are not used. No other source was substituted.",
        f"2. **A listed split on Opendoor.** Massive lists a 30-for-31 split of OPEN executed 2025-11-18 (by its ratio, an adjustment for a distribution; what it "
        f"was is not verified here). {st.get('a split between the first weekend and the expiry', 0)} OPEN markets sold on the weekend of 2025-10-31 with a "
        f"2025-11-28 expiry are dropped by rule 1, {meta['status_rule_subset'].get('a split between the first weekend and the expiry', 0)} in the rule subset. "
        f"Netflix's 10-for-1 split (2025-11-17) dropped nothing here: the {meta['hedged_by_ticker'].get('NFLX', 0)} Netflix markets S21 kept were all sold after it.",
        f"3. **One market without a usable Monday quote** ({meta['markets_without_a_usable_monday_pair']}): a HOOD call whose last quote before Monday 09:35 was "
        f"from before the open. Dropped, as registered. No modelled price was used anywhere.",
        f"4. **Stale opening quotes were bought at the offer.** {int((age_all > 60).sum())} hedged markets ({int(((age_all > 60) & ok.rule).sum())} in the rule "
        f"subset) had a leg quote more than 60 seconds old at 09:35, some of them placeholders such as 0 bid, 15.00 offered. The registered rule accepts them, so "
        f"the primary includes them; {meta['above_one_P']} hedges cost more than the spread can pay and {meta['zero_bid_short_leg_P']} sold a short leg for a zero "
        f"bid. The after-the-run look L1 shows the primary without them. This was not foreseen in METHOD.md.",
        "5. **The unhedged benchmark moved with the drops.** S21's B0 book (60 markets) had no losing month. On the 52 markets that could be hedged the unhedged "
        "book has one (June 2026), because three winning S&P index tickets of that month were dropped. METHOD.md section 8 said the hedged book could at best tie "
        "the unhedged worst month; on these markets that no longer applied, and the hedged worst month is worse anyway.",
        "6. **The first run was on a cache without option volumes.** `run.py` was first run at 01:52 New York, after every Monday quote and close was in the cache "
        "and while the capacity-only pull of option volumes was still running. Volumes enter no P&L. Everything was rerun after the pull finished.",
        "7. **The book holds fractions of an option contract.** One listed spread is 100 shares; the book holds up to 100 tickets per market. The numbers are an "
        "accounting per ticket, not an order that could be sent as is (see capacity.md).",
        "8. **Not verified:** Massive's NBBO and daily closes against a second source (the closes are tied to Polymarket's results only by the fact that no market "
        "finished beyond its level without a recorded touch); early exercise of the short leg and dividends (the spread is read as European, as S21 read it); the "
        "$0.65 commission (an assumption); the taker side of S18's prints; whether a hedge could have been bought in the size of the weekend's ticket sales.",
        "9. **Clerical:** METHOD.md's header says \"about 02:00\"; the pre-registration commit was made at 01:47:44 (amendment 1).",
    ]
    rl = ["# S25 run log", "", "Sun 2026-10-04. Branch `r/weekend-options`. Commit hashes and times read from `git log` (New York time); pull times are UTC.", "",
          "## Commits", "", table(["Time", "Commit", "What"], [[c[1], f"`{c[0]}`", c[2][:150]] for c in commits]) if commits else "n/a", "",
          "The commit that carries this file is not listed in it; it is recorded by the next commit.", "",
          "## The pull (from the pull's own log)", "", *[f"- `{x}`" for x in log], "",
          "## Data sources", "",
          "- **Polymarket side: nothing pulled.** Traded bids, held-to-result P&L, results, sizes and segments are S18's `prints_markets.csv`; entry and result "
          "times are S18's `entries.csv`. No call to Polymarket or Kalshi.",
          "- **Option contracts, strikes, expiries and the Friday 15:55 quotes:** S21's `anchors.csv` (read only; S21's cache was not touched).",
          "- **Monday 09:35 quotes:** Massive `/v3/quotes/<option>` (`timestamp.lte` = 09:35:00 New York on the hedge day, newest first, limit 1).",
          "- **Closes:** Massive `/v2/aggs/ticker/<ticker>/range/1/day/2025-10-27/2026-10-02`, `adjusted=false` and `adjusted=true`. **Splits:** `/v3/reference/splits`.",
          "- **Option volume on the hedge day (capacity only):** Massive daily bar of each leg.",
          f"- Cache: `research/s25_ticket_option_hedge/.cache/cache.jsonl`, {meta['cache_lines']} lines. Not committed.",
          "- **The session clock:** SPY five-minute bars in `s5_big_moves/.cache/eq_SPY.npz`.", "",
          "## The recorder", "",
          f"`fetch failed` lines in `research/forward/recorder.log` (read only): see the first and last lines of the pull's log above; at the time of the run: "
          f"{meta['recorder_fetch_failed_now']}. The recorder was not touched.", "",
          "## Markets dropped", "",
          table(["Reason", "Markets"], [[k, v] for k, v in drops.items()]), "",
          "## What went wrong, and what could not be verified", "", *notes, ""]
    (R / "RUN_LOG.md").write_text("\n".join(rl) + "\n")
    print("\n".join(ans))
    return 0



if __name__ == "__main__":
    sys.exit(main())
