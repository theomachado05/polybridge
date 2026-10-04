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
SERIES = (("V0", "V0 primary and V1: no trades", "#2a78d6"), ("V2", "V2: lock without the outlier filter", "#eb6834"),
          ("V3", "V3: unhedged fade of the outlier", "#1baf7a"))


def money(x: float) -> str:
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.2f}"


def num(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def md_table(df: pd.DataFrame, cols: dict) -> str:
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[k]) for k in cols) + " |")
    return "\n".join(out)


def charts(tr: pd.DataFrame, dates: list[str]) -> None:
    x = pd.to_datetime(dates)
    for name, title, dd in (("equity_curve.png", "cumulative net P&L", False), ("drawdown.png", "drawdown from peak", True)):
        fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=SURFACE)
        ax.set_facecolor(SURFACE)
        for vid, label, color in SERIES:
            t = tr[(tr.variant == vid) & (tr.cost_mult == 1.0)] if len(tr) else tr
            daily = np.array([t[t.date == d].pnl.sum() if len(t) else 0.0 for d in dates])
            y = np.cumsum(daily)
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
            ax.plot(x, y, color=color, linewidth=2, label=label, solid_capstyle="round")
            ax.plot([x[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
            ax.annotate(f"{y[-1]:+.0f}", (x[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        ax.grid(True, axis="y", color=GRID, linewidth=1)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.margins(x=0.07)
        ax.set_ylabel("Dollars, 100 contract pairs per entry", fontsize=9, color=INK2)
        ax.set_title(f"S3 three-way consistency, history at 1× costs: {title} by resolution date", loc="left", fontsize=11, color=INK)
        ax.legend(loc="lower left", frameon=False, fontsize=9, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def main() -> int:
    m = pd.read_csv(R / "metrics_history.csv")
    sets = pd.read_csv(R / "sets.csv")
    tr = pd.read_csv(R / "trades.csv") if (R / "trades.csv").stat().st_size > 5 else pd.DataFrame()
    meta = json.loads((R / "run_meta.json").read_text())
    fwd = pd.read_csv(R / "metrics_forward.csv") if (R / "metrics_forward.csv").exists() else None
    fsets = pd.read_csv(R / "sets_forward.csv") if (R / "sets_forward.csv").exists() else None
    charts(tr, meta["dates"])
    pd.concat([m] + ([fwd] if fwd is not None else []), ignore_index=True).to_csv(R / "metrics.csv", index=False)

    def row(seg, vid, c):
        return m[(m.segment == seg) & (m.variant == vid) & (m.cost_mult == c)].iloc[0]

    a1, a2 = row("ALL", cfg.PRIMARY, 1.0), row("ALL", cfg.PRIMARY, 2.0)
    d = meta["drops"]
    gap_pk = 100 * (sets.pm_mid - sets.k_mid).abs().mean()
    gap_ko = 100 * (sets.k_mid - sets.opt_mid).abs().mean()
    gap_po = 100 * (sets.pm_mid - sets.opt_mid).abs().mean()
    vt = m[m.segment.isin(["IS", "OOS", "ALL"])].assign(
        S=lambda x: x.segment, V=lambda x: x.variant + np.where(x.variant == cfg.PRIMARY, " (primary)", ""),
        C=lambda x: x.cost_mult.map(lambda c: f"{c:.0f}×"), N=lambda x: x.sets.astype(int), E=lambda x: x.entries.astype(int),
        D=lambda x: x.entry_dates.astype(int), P=lambda x: x.pnl.map(money), W=lambda x: x.wins.astype(int),
        VE=lambda x: x.verified_entries.astype(int), VP=lambda x: x.pnl_verified.map(money), SH=lambda x: x.sharpe.map(num))

    S = ["# S3: three-way consistency on \"S&P 500 closes above K\"", "",
         "Method, pre-registered before any S3 data was pulled: [`research/s3_three_way/METHOD.md`](../../s3_three_way/METHOD.md) "
         "(commit `83ce137`; amendment 1 before any result). Files: [`metrics.csv`](metrics.csv), [`sets.csv`](sets.csv), "
         "[`trades.csv`](trades.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", "",
         "## Answer", "",
         f"**No trade. Too few observations.** On {sets.date.nunique()} resolution dates ({meta['dates'][0]} to {meta['dates'][-1]}) "
         f"there are {len(sets)} matched sets: a Polymarket SPY strike, the Kalshi S&P 500 strike at the same level, and the options "
         f"band, all at 12:00 ET. The primary rule (V0: one prediction venue outside the options band, the other inside, and a "
         f"cross-venue lock worth at least 2¢ after costs) fired **{int(a1.entries)} times at 1× costs and {int(a2.entries)} at 2×**. "
         "At noon on the resolution day the three prices agreed to within costs.", "",
         f"The pre-registered pass needed {cfg.MIN_VERIFIED_ENTRIES} print-verified entries on {cfg.MIN_VERIFIED_DATES} dates. "
         "There are none. This is a null and is reported as one.", "",
         "## How close the three prices are (all matched sets)", "",
         "| Pair of prices | Mean absolute gap |", "|---|---|",
         f"| Polymarket mid against Kalshi mid | {gap_pk:.1f} points |",
         f"| Kalshi mid against the options band mid | {gap_ko:.1f} points |",
         f"| Polymarket mid against the options band mid | {gap_po:.1f} points |", "",
         f"Median Kalshi spread {100 * (sets.ka - sets.kb).median():.0f} points; the Polymarket spread in history is the arb scan's "
         f"assumed ±5 points. Split resolutions (the two venues settling differently): {int(sets.split_resolution.sum())} of {len(sets)} sets. "
         f"Strike rounding: at most {sets.strike_gap_pts.abs().max():.1f} index points.", "",
         "## Every variant tried (history)", "",
         md_table(vt, {"S": "Segment", "V": "Variant", "C": "Costs", "N": "Sets", "E": "Entries", "D": "Dates with an entry",
                       "P": "Net P&L", "W": "Winners", "VE": "Print-verified", "VP": "Verified P&L", "SH": "Sharpe"}), "",
         "P&L is per 100 contract pairs (about $100 of capital per entry); each leg is paid by its own venue's result. "
         "OOS is the most recent 20% of dates "
         f"({meta['oos_dates'][0]} to {meta['oos_dates'][-1]}, {len(meta['oos_dates'])} dates). With one to two entries a Sharpe ratio means nothing; "
         "it is printed only because the table has the column.", "",
         "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
         "## Costs, in bp of capital", "",
         f"Kalshi `{meta['kalshi_fee_type']}` fee, multiplier {meta['kalshi_fee_multiplier']:.0f}: `ceil(0.07 × C × P × (1 − P))`, up to 175 bp at "
         "P = 0.5. Polymarket 0.04 × P × (1 − P), up to 100 bp. Half-spreads: Kalshi's real quote (median "
         f"{100 * (sets.ka - sets.kb).median() / 2:.1f} points a side), Polymarket assumed 5 points a side. Carry to a same-day resolution is "
         "under 1 bp. A round lock near P = 0.5 therefore needs a gap of about 9 points between the venues' mids before it "
         f"clears 2¢; the mean gap is {gap_pk:.1f}.", "",
         "## Forward: this weekend's recorded books (Monday 2026-10-05 markets)", ""]
    if fwd is None:
        S += ["Pending. Window Sat 20:00 ET to Sun 07:00 ET, six matched strikes (SPY 750 to 775 against S&P 7525 to 7775), real "
              "books every 30 s. Options are closed, so their Friday band is reported, not used.", ""]
    else:
        f1 = fwd[(fwd.variant == cfg.PRIMARY) & (fwd.cost_mult == 1.0)].iloc[0]
        f2 = fwd[(fwd.variant == cfg.PRIMARY) & (fwd.cost_mult == 2.0)].iloc[0]
        S += [f"Six matched strikes, real books every 30 s. Primary (θ = 2¢): **{int(f1.entries)} fills at 1× costs**, "
              f"{f1.contracts:,.0f} contract pairs, ${f1.capital:,.2f} of capital, {money(f1.pnl_locked_if_resolved_alike)} locked if both "
              f"venues resolve alike on Monday; {int(f2.entries)} fills at 2×. The markets resolve after the deadline, so no realised P&L.", ""]
        if fsets is not None:
            S += [md_table(fsets.assign(A=fsets.pm_strike.map(lambda v: f"{v:.0f}"), B=fsets.kalshi_strike.map(lambda v: f"{v:.0f}"),
                                        N=fsets.snapshots.astype(int), PM=fsets.pm_mid_median.map(lambda v: num(v, 3)),
                                        PS=fsets.pm_spread_median.map(lambda v: num(v, 3)), K=fsets.kalshi_mid_median.map(lambda v: num(v, 3)),
                                        KS=fsets.kalshi_spread_median.map(lambda v: num(v, 3)), G=fsets.mid_gap_median.map(lambda v: num(v, 3)),
                                        O=fsets.apply(lambda r: f"{num(r.get('options_lo_friday', np.nan))} to {num(r.get('options_hi_friday', np.nan))}", axis=1)),
                           {"A": "SPY strike", "B": "S&P strike", "N": "Snapshots", "PM": "Polymarket mid (median)", "PS": "Polymarket spread",
                            "K": "Kalshi mid (median)", "KS": "Kalshi spread", "G": "Mid gap (PM − Kalshi)", "O": "Options band, Friday close (stale)"}), ""]
    S += ["## What didn't work", "",
          f"- **The primary rule never fired** ({len(sets)} sets, {sets.date.nunique()} dates, 1× and 2× costs).",
          "- **Loosening it did not help.** V1 (θ = 1¢) also has no entry. V2 (no outlier filter) has one entry, not print-verified. "
          "V3 (unhedged fade) has two entries at 1× costs, both losers, and one at 2×, a winner: noise.",
          f"- **Coverage is thin.** Of {len(sets) + d['no_strike_in_tolerance'] + d['no_kalshi_quote'] + d['ex_dividend']} Polymarket rows, "
          f"{d['no_kalshi_quote']} had no two-sided Kalshi quote at noon, {d['no_strike_in_tolerance']} had no Kalshi strike within 2.5 points, "
          f"and {d['ex_dividend']} fell on the SPY ex-dividend date.", "",
          "## Caveats", "",
          "- One snapshot a day in history, so no two-observation latency rule there.",
          "- The contracts are near-twins (SPY against the index, a rounded strike, two closing prints).",
          "- The historical Polymarket spread is assumed; nothing here rests on it because nothing traded.", "",
          "## Reproduce", "", "```", "cd research", f"python -m s3_three_way.run --rate {meta['rate']}",
          f"python -m s3_three_way.forward --rate {meta['rate']}     # after the forward window closes", "python -m s3_three_way.report",
          "python -m pytest s3_three_way/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))

    cap = ["# S3 capacity", "", "## History", "",
           "No capacity claim: the history has no sizes, and the primary rule produced no trade.", ""]
    if (R / "capacity_forward.csv").exists():
        cf = pd.read_csv(R / "capacity_forward.csv")
        c0 = cf[(cf.variant == cfg.PRIMARY) & (cf.cost_mult == 1.0)]
        live = c0[c0.max_fillable_qty > 0]
        cap += ["## Forward recording (sizes that were on the book)", "",
                f"Primary variant, 1× costs: {len(live)} of {len(c0)} strikes showed a fillable edge at some snapshot; "
                f"largest fillable amount per strike, summed, ${live.max_fillable_dollars.sum():,.0f}.", ""]
    else:
        cap += ["## Forward recording", "", "Pending: the forward window closes Sun 2026-10-04 07:00 ET.", ""]
    (R / "capacity.md").write_text("\n".join(cap))
    print("\n".join(S[4:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
