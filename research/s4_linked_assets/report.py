"""S4 report: equity_curve.png, drawdown.png, capacity.md and SUMMARY.md from the result CSVs.

Run from `research/`:  python -m s4_linked_assets.report
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
SERIES = (("V0", "V0: trusted links (the link agent)", "#2a78d6"), ("V2", "V2: two models agree, no data gate", "#eb6834"),
          ("V4", "V4: every original link, unchecked", "#1baf7a"))


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


def charts(eq: pd.DataFrame, oos_start: str) -> None:
    for name, title, dd in (("equity_curve.png", "cumulative net P&L", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for vid, label, color in SERIES:
            e = eq[(eq.variant == vid) & (eq.cost_mult == 1.0)].copy()
            base = 0.0
            xs, ys = [], []
            for seg in ("IS", "OOS"):           # the two segments are one continuous book here: stack them
                s = e[e.segment == seg].sort_values("day")
                xs += list(pd.to_datetime(s.day))
                ys += list(base + s.pnl.to_numpy())
                base = ys[-1] if ys else 0.0
            y = np.array(ys) / cfg.CAPITAL * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{vid} {y.min():.2f}%")
            ax.plot(xs, y, color=color, linewidth=2, label=label, solid_capstyle="round")
            if not dd:
                ax.plot([xs[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
                ax.annotate(f"{y[-1]:+.2f}%", (xs[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(oos_start)
        ax.axvline(split, color=INK2, linewidth=1)
        ax.annotate("out-of-sample starts ▸", (split, 0.0 if dd else 1.0), xycoords=("data", "axes fraction"),
                    xytext=(-5, 5 if dd else -4), textcoords="offset points", va="bottom" if dd else "top", ha="right", fontsize=8.5, color=INK2)
        if deepest:
            ax.annotate("Deepest: " + ", ".join(deepest), (0.0, 0.0), xycoords="axes fraction", xytext=(12, 30),
                        textcoords="offset points", ha="left", va="bottom", fontsize=8.5, color=INK)
        ax.grid(True, axis="y", color=GRID, linewidth=1)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.margins(x=0.08)
        ax.set_ylabel("% of the $100,000 book", fontsize=9, color=INK2)
        ax.set_title(f"S4 linked assets, 1× costs: {title}", loc="left", fontsize=11, color=INK)
        ax.legend(loc="upper left" if not dd else "lower left", bbox_to_anchor=(0.0, 0.9) if not dd else (0.0, 0.14), frameon=False,
                  fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m = pd.read_csv(R / "metrics.csv")
    tr = pd.read_csv(R / "trades.csv") if (R / "trades.csv").stat().st_size > 5 else pd.DataFrame(columns=["variant", "cost_mult", "segment"])
    eq = pd.read_csv(R / "equity.csv")
    lk = pd.read_csv(R / "links.csv")
    rg = pd.read_csv(R / "regressions.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    charts(eq, meta["oos_start"])

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    o1, o2, i1 = row("OOS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 2.0), row("IS", cfg.PRIMARY, 1.0)
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} out-of-sample trades on at least {cfg.MIN_OOS_DATES} dates and {cfg.MIN_OOS_TICKERS} tickers",
         o1.trades >= cfg.MIN_OOS_TRADES and o1.trade_dates >= cfg.MIN_OOS_DATES and o1.tickers >= cfg.MIN_OOS_TICKERS,
         f"{int(o1.trades)} trades, {int(o1.trade_dates)} dates, {int(o1.tickers)} tickers"),
        ("Out-of-sample mean net return per trade above zero, date-bootstrap interval excluding zero (1× costs)",
         o1.mean_net_bp > 0 and o1.ci_lo > 0, f"{bp(o1.mean_net_bp)} [{num(o1.ci_lo, 1)}, {num(o1.ci_hi, 1)}]"),
        ("Still above zero at 2× costs", o2.mean_net_bp > 0, bp(o2.mean_net_bp)),
        ("In-sample mean net return per trade above zero", i1.mean_net_bp > 0, f"{bp(i1.mean_net_bp)} on {int(i1.trades)} trades"),
    ]
    passed = all(bool(c[1]) for c in crit)
    few = o1.trades < cfg.MIN_OOS_TRADES
    test = lk[~lk.motivating]
    c = meta["counts"]
    n_links, n_mk = c["proposer_links"], c["markets"]
    agreed = int((test.critic == "agreed").sum())
    opposite = int((test.critic == "opposite direction").sum())
    not_named = int((test.critic == "not named").sum())
    ev = test[test.family == "event"]
    trusted = test[test.status == "trusted"]
    trusted_ev = trusted[trusted.family == "event"]
    conf_only = int((test.status == "confirmed, not agreed").sum())

    vt = m.assign(S=m.segment, V=m.variant + np.where(m.variant == cfg.PRIMARY, " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"),
                  T=m.trades.astype(int), K=m.tickers.astype(int), D=m.trade_dates.astype(int), P=m.pnl.map(money),
                  N=m.mean_net_bp.map(bp), CI=m.apply(lambda r: f"[{num(r.ci_lo, 1)}, {num(r.ci_hi, 1)}]", axis=1), G=m.mean_gross_bp.map(bp),
                  H=m.hit_rate.map(lambda x: "n/a" if x != x else f"{100 * x:.0f}%"), SH=m.sharpe.map(num),
                  DS=m.deflated_sharpe_prob.map(lambda x: num(x, 3)), MD=m.max_drawdown.map(lambda x: f"{100 * x:.2f}%"),
                  WM=m.worst_month.map(lambda x: "n/a" if x != x else f"{100 * x:.2f}%"), TO=m.turnover_ann.map(lambda x: f"{x:.1f}×"))
    vcols = {"S": "Segment", "V": "Variant", "C": "Costs", "T": "Trades", "K": "Tickers", "D": "Dates", "P": "Net P&L", "N": "Net per trade",
             "CI": "95% interval", "G": "Gross per trade", "H": "Winners", "SH": "Sharpe", "DS": "Deflated Sharpe prob.", "MD": "Max DD",
             "WM": "Worst month", "TO": "Turnover / yr"}
    head = vt[(m.variant == cfg.PRIMARY)]

    top = trusted_ev.sort_values("gate_t", ascending=False).head(15)
    top_tbl = top.assign(Q=top.question.str.slice(0, 70), T=top.ticker, D=top.direction.str.replace("_", " "),
                         S=top.sensitivity_bp_per_pp.map(lambda x: f"{x:+.1f}"), TT=top.gate_t.map(lambda x: num(x, 1)),
                         B=top.gate_bins.astype(int), F=top.first_confirmed)

    def reg(setname, rel, seg="ALL"):
        q = rg[(rg["set"] == setname) & (rg.relation == rel) & (rg.segment == seg)]
        return q.iloc[0] if len(q) else None

    def reg_cell(r):
        return "n/a" if r is None or r.slope != r.slope else f"{r.slope:+.2f} (t {r.t:+.2f}, n {int(r.n)}, same sign {100 * r.sign_agree:.0f}%)"

    rels = ["gap on overnight odds move", "move after the open on overnight odds move",
            "next overnight odds move on the equity's session move", "next 24h odds move on the equity's session move"]
    sets = ["trusted, event (V0 set)", "agreed, event, no data gate", "every proposer link", "motivating example (Brazil)"]
    reg_tbl = pd.DataFrame([{"Relation": f"{rel} ({rg[rg.relation == rel].unit.iloc[0]})", **{s: reg_cell(reg(s, rel)) for s in sets}} for rel in rels])

    S = ["# S4: prediction-market odds against the equity they move", "",
         "Method, pre-registered before any test-sample price was pulled: [`research/s4_linked_assets/METHOD.md`](../../s4_linked_assets/METHOD.md) "
         "(commit `603f2e8`). Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`links.csv`](links.csv), "
         "[`regressions.csv`](regressions.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", ""]
    verdict = "pass" if passed else ("too few observations" if few else "not a pass")
    g_ag, a_ag = reg("agreed, event, no data gate", rels[0]), reg("agreed, event, no data gate", rels[1])
    b_ag = reg("agreed, event, no data gate", rels[2])
    g_is, g_oos = reg("agreed, event, no data gate", rels[0], "IS"), reg("agreed, event, no data gate", rels[0], "OOS")
    S += [f"**The link is real, and the open already prices it.** On event questions where two independent models agree on the "
          f"equity and the direction, a 1-point overnight move in odds comes with a {g_ag.slope:+.1f} bp excess gap in that equity at "
          f"the open (t = {g_ag.t:.1f}, {int(g_ag.n):,} link-days, {int(g_ag.clusters)} dates; in-sample {g_is.slope:+.1f}, t = {g_is.t:.1f}; "
          f"out-of-sample {g_oos.slope:+.1f}, t = {g_oos.t:.1f}). It comes from the larger moves: the two have the same sign on only "
          f"{100 * g_ag.sign_agree:.0f}% of days. After the open nothing follows: "
          f"{a_ag.slope:+.1f} bp per point (t = {a_ag.t:.1f}). The reverse does not hold either: the odds do not follow the equity's "
          f"session move ({b_ag.slope:+.2f} pp per 100 bp, t = {b_ag.t:.1f}). The information reaches the equity while it is closed; "
          "by 09:30 there is no lag left to trade.", "",
          f"**Verdict on the pre-registered criterion: {verdict}.** Out of sample ({meta['oos_start']} to {meta['last']}, "
          f"{meta['oos_sessions']} sessions), trading the equity at the open in the direction of the overnight move in odds, on links "
          f"the agent trusts, gave {int(o1.trades)} trades on {int(o1.tickers)} tickers: {bp(o1.mean_net_bp)} net per trade at 1× costs "
          f"(95% interval {num(o1.ci_lo, 1)} to {num(o1.ci_hi, 1)}), {bp(o1.mean_gross_bp)} before costs; {bp(o2.mean_net_bp)} net at 2× costs. "
          f"In-sample: {int(i1.trades)} trades, {bp(i1.mean_net_bp)} net.", "",
          f"**The link agent's result.** Of {n_links} links on {n_mk} markets written by the first model, the blind critic agreed on the "
          f"ticker and the direction for {agreed}, named the same ticker with the **opposite** direction for {opposite}, and did not name "
          f"the ticker for {not_named}. The data gate then confirmed {len(trusted)} of the agreed links at some point in the window "
          f"({len(trusted_ev)} of them on event questions). {conf_only} links pass the data gate without the critic's agreement.", ""]
    S += ["## The link agent", "",
          "| Stage | What it does | Result |", "|---|---|---|",
          f"| 1. Proposer | The links in `ai_map.json`, written from the question text | {n_links} links, {n_mk} Polymarket markets, {test.ticker.nunique()} tickers |",
          f"| 2. Blind critic | A second model, shown only the question and the ticker menu | agreed {agreed}; opposite direction {opposite}; ticker not named {not_named} |",
          f"| 3. Data gate | Walk-forward: equity and odds must have moved together in 30-minute bins, t ≥ {cfg.GATE_MIN_T:.0f}, earlier days only | "
          f"{len(trusted)} agreed links confirmed at some point ({len(trusted_ev)} event, {len(trusted) - len(trusted_ev)} spot proxy) |", "",
          f"Markets by family (critic): " + ", ".join(f"{k} {v}" for k, v in c["family_of_markets"].items()) + ". "
          "A spot proxy is a question about a traded price itself (\"Bitcoin above X\"); the primary test leaves those out.", ""]
    if len(top_tbl):
        S += ["Trusted event links, strongest first (sensitivity is measured, in bp of excess return per pp of odds):", "",
              md_table(top_tbl, {"Q": "Question", "T": "Ticker", "D": "Direction", "S": "Sensitivity", "TT": "t", "B": "Bins", "F": "First confirmed"}), ""]
    else:
        S += ["**No event link passed all three stages.**", ""]
    S += ["## Headline numbers (primary V0: trusted links, event questions, exit at the close)", "",
          md_table(head, vcols), "",
          "A $100,000 book; $10,000 per position against a beta-weighted SPY hedge; entry at the 09:30 open, exit at the close. "
          "The Sharpe ratio is on daily returns, 252 days.", "",
          "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
          "## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {verdict}.**", "",
          "## Who moves first (described, not traded)", "",
          md_table(reg_tbl, {"Relation": "Relation", **{s: s for s in sets}}), "",
          "Slopes are through the origin with errors clustered by date. Rows 1 and 2 ask whether the equity follows the odds: at the "
          "open (row 1, not tradable, the move is already in the opening price) and after it (row 2, the trade). Rows 3 and 4 ask "
          "the reverse: whether the odds follow the equity's session move. The Brazil column is the motivating example and is not "
          "part of any test.", "",
          "## Costs, in bp of the position", "",
          f"Round trip on the primary's trades: {num(o1.mean_cost_bp, 1)} bp at 1×, {num(o2.mean_cost_bp, 1)} bp at 2×. Per side: SPY hedge "
          f"{cfg.COST_SPY:.0f} bp, liquid ETFs and stocks above $50 billion {cfg.COST_LIQUID:.0f} bp, other tickers {cfg.COST_OTHER:.0f} bp "
          "(half the quoted spread plus Interactive Brokers tiered commission and SEC and FINRA fees, widened for fills at the open; "
          "`research/strategy_backtest/METHOD.md` section 5).", "",
          "## Capacity", "", "See [`capacity.md`](capacity.md).", "",
          "## Every variant tried", "", md_table(vt, vcols), "",
          "V4 is the same backtest on the original links with no checking. The deflated Sharpe probability uses 5 trials.", "",
          "## What didn't work", ""]
    v4o, v2o = row("OOS", "V4", 1.0), row("OOS", "V2", 1.0)
    S += [f"- **Unchecked links (V4):** {int(v4o.trades)} out-of-sample trades, {bp(v4o.mean_net_bp)} net per trade "
          f"[{num(v4o.ci_lo, 1)}, {num(v4o.ci_hi, 1)}].",
          f"- **Two models agreeing, without the data gate (V2):** {int(v2o.trades)} trades, {bp(v2o.mean_net_bp)} net per trade "
          f"[{num(v2o.ci_lo, 1)}, {num(v2o.ci_hi, 1)}].",
          f"- **The critic contradicted the first model's direction on {opposite} links** and did not name the ticker on {not_named}: "
          "a map written from text alone is not a reliable input to a backtest.", ""]
    S += ["## Caveats", "",
          "- The links come from language models; agreement is not truth. The data gate needs history that young markets lack.",
          "- Fills are at the first regular bar's open, standing in for the opening auction.",
          "- Several markets share a ticker and tickers move together, so the interval resamples dates.",
          "- The Brazil example was seen before the method was written and is excluded from every test figure.", "",
          "## Reproduce", "", "```", "cd research", "python -m s4_linked_assets.data      # pull (not committed)",
          "python -m s4_linked_assets.run", "python -m s4_linked_assets.report", "python -m pytest s4_linked_assets/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))

    cap = ["# S4 capacity", ""]
    p = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)] if len(tr) else tr
    if len(p):
        g = p.groupby("ticker").agg(trades=("pnl", "size"), vol5=("vol5", "median"), vol30=("vol30", "median")).reset_index()
        g["capacity"] = cfg.CAPACITY_SHARE * g.vol30
        cap += [f"Primary variant, all its trades ({len(p)}). The position is ${cfg.NOTIONAL:,.0f}. Capacity is "
                f"{100 * cfg.CAPACITY_SHARE:.0f}% of the median dollar volume in the first 30 minutes on the days traded.", "",
                md_table(g.assign(T=g.ticker, N=g.trades, A=g.vol5.map(lambda x: f"${x:,.0f}"), B=g.vol30.map(lambda x: f"${x:,.0f}"),
                                  C=g.capacity.map(lambda x: f"${x:,.0f}"), P=(cfg.NOTIONAL / g.vol30).map(lambda x: f"{100 * x:.3f}%")),
                         {"T": "Ticker", "N": "Trades", "A": "Median first 5 minutes", "B": "Median first 30 minutes",
                          "C": "Capacity per position", "P": "$10,000 as a share of 30-minute volume"}), "",
                f"Smallest capacity per position: ${g.capacity.min():,.0f}; median ${g.capacity.median():,.0f}. With at most "
                f"{cfg.MAX_POSITIONS} positions a day the book could hold about ${cfg.MAX_POSITIONS * g.capacity.median():,.0f} "
                "before its fills exceed that share. The limit is the edge, not the liquidity.", ""]
    else:
        cap += ["The primary variant made no trade, so there is no capacity figure.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
