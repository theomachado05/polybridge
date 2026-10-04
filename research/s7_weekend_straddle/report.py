"""S7 report: SUMMARY.md, equity_curve.png, drawdown.png and capacity.md from the result CSVs.

Run from `research/`:  python -m s7_weekend_straddle.report
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
BLUE, ORANGE = "#2a78d6", "#eb6834"


def pct(x: float, d: int = 1) -> str:
    return "n/a" if x != x else f"{100 * x:+.{d}f}%"


def num(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def md_table(df: pd.DataFrame, cols: dict) -> str:
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[k]) for k in cols) + " |")
    return "\n".join(out)


def books(tr: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Mean 1x return per Friday of the primary's flagged straddles and of their controls."""
    ok = tr[tr.status == "ok"]
    f = ok[(ok.group == "flagged") & (ok[f"flag_{cfg.PRIMARY}"])]
    keys = set(zip(f.ticker, f.friday))
    c = ok[(ok.group == "control") & np.array([(t, d) in keys for t, d in zip(ok.ticker, ok.controls_for)])]
    return f.groupby("friday").ret_1x.mean(), c.groupby("friday").ret_1x.mean()


def charts(tr: pd.DataFrame, oos_from: str) -> None:
    fb, cb = books(tr)
    for name, title, dd in (("equity_curve.png", "cumulative weekend returns", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        deepest = []
        for s, label, color in ((fb, "Flagged Fridays (the prediction market shows a live event)", BLUE), (cb, "Control Fridays, same tickers", ORANGE)):
            x, y = pd.to_datetime(s.index), np.cumsum(s.to_numpy()) * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
                deepest.append(f"{label.split(' Fridays')[0].lower()} {y.min():.0f}%")
            ax.plot(x, y, color=color, linewidth=2, label=label, solid_capstyle="round")
            if not dd and len(y):
                ax.plot([x[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
                ax.annotate(f"{y[-1]:+.0f}%", (x[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(oos_from)
        ax.axvline(split, color=INK2, linewidth=1)
        ax.annotate("out-of-sample starts ▸", (split, 0.0 if dd else 1.0), xycoords=("data", "axes fraction"), xytext=(-5, 5 if dd else -4),
                    textcoords="offset points", va="bottom" if dd else "top", ha="right", fontsize=8.5, color=INK2)
        if deepest:
            ax.annotate("Deepest: " + ", ".join(deepest), (0.0, 0.0), xycoords="axes fraction", xytext=(12, 30), textcoords="offset points",
                        ha="left", va="bottom", fontsize=8.5, color=INK)
        ax.grid(True, axis="y", color=GRID, linewidth=1)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.margins(x=0.08)
        ax.set_ylabel("Sum of weekend returns, % of the premium paid", fontsize=9, color=INK2)
        ax.set_title(f"S7 weekend straddles, 1× costs: {title}", loc="left", fontsize=11, color=INK)
        ax.legend(loc="lower left" if not dd else "upper right", frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m, tr = pd.read_csv(R / "metrics.csv"), pd.read_csv(R / "trades.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    charts(tr, meta["oos_from"])

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    a1, a2, i1, o1, o2 = row("ALL", cfg.PRIMARY, 1.0), row("ALL", cfg.PRIMARY, 2.0), row("IS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 1.0), row("OOS", cfg.PRIMARY, 2.0)
    crit = [
        (f"At least {cfg.MIN_OOS_TRADES} OOS flagged trades on at least {cfg.MIN_OOS_WEEKENDS} OOS weekends",
         o1.flagged_trades >= cfg.MIN_OOS_TRADES and o1.flagged_weekends >= cfg.MIN_OOS_WEEKENDS, f"{int(o1.flagged_trades)} trades, {int(o1.flagged_weekends)} weekends"),
        ("OOS mean net return per flagged trade above zero, weekend-bootstrap interval excluding zero (1× costs)", o1.mean_ret_flagged > 0 and o1.ci_lo > 0,
         f"{pct(o1.mean_ret_flagged)} [{pct(o1.ci_lo)}, {pct(o1.ci_hi)}]"),
        ("OOS above zero at 2× costs", o2.mean_ret_flagged > 0, pct(o2.mean_ret_flagged)),
        ("In-sample above zero", i1.mean_ret_flagged > 0, f"{pct(i1.mean_ret_flagged)} on {int(i1.flagged_trades)} trades"),
        ("Whole sample: flagged minus control above zero, interval excluding zero", a1.diff_flagged_minus_control > 0 and a1.diff_ci_lo > 0,
         f"{pct(a1.diff_flagged_minus_control)} [{pct(a1.diff_ci_lo)}, {pct(a1.diff_ci_hi)}]"),
    ]
    few = not bool(crit[0][1])
    verdict = "pass" if all(bool(c[1]) for c in crit) else ("too few observations" if few else "not a pass")
    ok = tr[tr.status == "ok"]
    f0 = ok[(ok.group == "flagged") & (ok[f"flag_{cfg.PRIMARY}"])]
    vt = m.assign(V=m.variant + np.where(m.variant == cfg.PRIMARY, " (primary)", ""), C=m.cost_mult.map(lambda x: f"{x:.0f}×"), S=m.segment,
                  N=m.flagged_trades.astype(int), W=m.flagged_weekends.astype(int), RF=m.mean_ret_flagged.map(pct),
                  CI=m.apply(lambda r: f"[{pct(r.ci_lo)}, {pct(r.ci_hi)}]", axis=1), MF=m.mean_mid_ret_flagged.map(pct),
                  AF=m.abs_move_bp_flagged.map(lambda x: "n/a" if x != x else f"{x:.0f} bp"), NC=m.control_trades.astype(int), RC=m.mean_ret_control.map(pct),
                  MC=m.mean_mid_ret_control.map(pct), AC=m.abs_move_bp_control.map(lambda x: "n/a" if x != x else f"{x:.0f} bp"),
                  D=m.apply(lambda r: f"{pct(r.diff_flagged_minus_control)} [{pct(r.diff_ci_lo)}, {pct(r.diff_ci_hi)}]", axis=1),
                  SH=m.sharpe.map(num), MD=m.max_drawdown.map(lambda x: "n/a" if x != x else f"{100 * x:.0f}%"),
                  WM=m.worst_month.map(lambda x: "n/a" if x != x else f"{100 * x:.0f}%"), H=m.hit_rate_flagged.map(lambda x: "n/a" if x != x else f"{100 * x:.0f}%"))
    vcols = {"V": "Variant", "C": "Costs", "S": "Segment", "N": "Flagged trades", "W": "Weekends", "RF": "Net return, flagged", "CI": "95% interval",
             "H": "Winners", "MF": "Mid-to-mid, flagged", "AF": "Underlying move, flagged", "NC": "Control trades", "RC": "Net return, control",
             "MC": "Mid-to-mid, control", "AC": "Underlying move, control", "D": "Flagged minus control", "SH": "Sharpe", "MD": "Max DD", "WM": "Worst month"}
    bt = f0.groupby("ticker").agg(n=("ret_1x", "size"), ret=("ret_1x", "mean"), mid=("mid_ret_1x", "mean"), mv=("underlying_move_bp", lambda s: s.abs().mean()),
                                  cost=("cost_share_of_premium_1x", "mean"), prem=("premium_mid_1x", "median"), size=("ask_size_call_fri", "median")).reset_index().sort_values("n", ascending=False)
    bt = bt.assign(T=bt.ticker, N=bt.n, R=bt.ret.map(pct), M=bt.mid.map(pct), MV=bt.mv.map(lambda x: f"{x:.0f} bp"), CS=bt.cost.map(lambda x: pct(x).lstrip("+")),
                   P=bt.prem.map(lambda x: f"${x:,.0f}"), Z=bt["size"].map(lambda x: "n/a" if x != x else f"{x:,.0f}"))
    st = meta["status"]
    dropped = {k: v for k, v in st.items() if k != "ok"}

    S = ["# S7: are options too cheap on Friday when the prediction market shows a live event?", "",
         "Method, pre-registered before any option price was pulled: [`research/s7_weekend_straddle/METHOD.md`](../../s7_weekend_straddle/METHOD.md) "
         f"(commit `8b4e914`). {meta['weekends']} weekend and holiday closures, Fridays {meta['first_friday']} to {meta['last_friday']}; out-of-sample is the "
         f"last {meta['oos_weekends']} (from {meta['oos_from']}). Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), "
         "[`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**Verdict on the pre-registered criterion: {verdict}.** Out-of-sample has {int(o1.flagged_trades)} flagged trades on "
         f"{int(o1.flagged_weekends)} weekend: the events that made the odds active had ended by then. Over the whole year the answer is a clear "
         "no: Friday straddles lose, and flagged Fridays do no better than ordinary ones.", "",
         f"- **Does the flag find the weekends that move?** On flagged Fridays the underlying moved {a1.abs_move_bp_flagged:.0f} bp on average by "
         f"Monday's open; on control Fridays, {a1.abs_move_bp_control:.0f} bp.",
         f"- **Did the straddle pay?** Flagged, net of every spread and commission: {pct(a1.mean_ret_flagged)} of the premium per trade "
         f"(95% interval {pct(a1.ci_lo)} to {pct(a1.ci_hi)}; {int(a1.flagged_trades)} trades on {int(a1.flagged_weekends)} weekends). Before costs, mid to "
         f"mid: {pct(a1.mean_mid_ret_flagged)}. At 2× costs: {pct(a2.mean_ret_flagged)}.",
         f"- **Against ordinary weekends:** control straddles returned {pct(a1.mean_ret_control)} net ({pct(a1.mean_mid_ret_control)} mid to mid). "
         f"Flagged minus control: {pct(a1.diff_flagged_minus_control)} [{pct(a1.diff_ci_lo)}, {pct(a1.diff_ci_hi)}].", "",
         "## Headline numbers (primary V0: activity of 4 points, odds between 10% and 90%)", "",
         md_table(vt[m.variant == cfg.PRIMARY], vcols), "",
         "Each trade buys one at-the-money straddle at Friday 15:55 at the ask and sells it at Monday 09:45 at the bid, expiry at least a week "
         f"out. Returns are a share of the premium paid. Sharpe is on weekend returns, {meta['weekends_per_year']:.0f} weekends a year.", "",
         "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {a} | {'pass' if b else '**fail**'} | {e} |" for a, b, e in crit]
    S += ["", f"**Verdict: {verdict}.**", "",
          "## By ticker (primary, flagged, 1× costs)", "",
          md_table(bt, {"T": "Ticker", "N": "Trades", "R": "Net return", "M": "Mid-to-mid", "MV": "Underlying move", "CS": "Costs, share of premium",
                        "P": "Median premium per straddle", "Z": "Median contracts at the ask"}), "",
          "## Costs", "",
          f"Real NBBO quotes on every leg: bought at the ask on Friday, sold at the bid on Monday, plus $0.65 per contract per leg each way. On the "
          f"primary's trades that is {100 * a1.cost_share_of_premium:.1f}% of the premium at 1× and {100 * a2.cost_share_of_premium:.1f}% at 2×. "
          "Source: Massive `/v3/quotes`; commission as in R3.", "",
          "## Every variant tried", "", md_table(vt, vcols), "",
          "The deflated Sharpe ratio is not shown: no variant has a positive Sharpe to deflate." if not (m.sharpe > 0).any() else
          "The deflated Sharpe ratio uses 3 trials.", "",
          "## Trades dropped", "",
          f"{meta['planned_trades']} trades were planned (flagged under the loosest rule, and their controls). Kept: {st.get('ok', 0)}. Dropped: "
          + "; ".join(f"{k} {v}" for k, v in dropped.items()) + ".", "",
          "## Caveats", "",
          "- A weekend straddle pays three days of time decay and two spreads; it needs a move well above the usual to break even.",
          "- Most active weekends are one theme (Iran and oil), so the result leans on USO, XLE and XOP.",
          "- The links are model judgements made after most of these markets resolved (S5 amendment 1). The flag itself uses only odds.",
          "- One year of weekends.", "",
          "## Reproduce", "", "```", "cd research", "python -m s7_weekend_straddle.run", "python -m s7_weekend_straddle.report",
          "python -m pytest s7_weekend_straddle/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    cap = ["# S7 capacity", "",
           f"Primary variant, flagged trades ({len(f0)}). The call's size at the ask at Friday 15:55: median {f0.ask_size_call_fri.median():,.0f} contracts "
           f"(quartiles {f0.ask_size_call_fri.quantile(0.25):,.0f} to {f0.ask_size_call_fri.quantile(0.75):,.0f}). Median premium per straddle "
           f"${f0.premium_mid_1x.median():,.0f}, so the quoted size is about ${f0.ask_size_call_fri.median() * f0.premium_mid_1x.median():,.0f} of "
           "premium per ticker at the touch. Liquidity is not the limit here; the result is.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
