"""S1 report: metrics.csv, equity_curve.png, drawdown.png, capacity.md and SUMMARY.md, all from the committed CSVs.

Run from `research/`:  python -m s1_twin_spread.report
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as cfg  # noqa: E402

R = Path(__file__).resolve().parents[1] / "results" / "s1_twin_spread"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE = "#2a78d6", "#eb6834"      # categorical slots 1 and 2 (validated pair)
RULE, PRIMARY = "registered", cfg.PRIMARY


def money(x: float) -> str:
    return "n/a" if x != x else f"{'-' if x < 0 else '+'}${abs(x):,.2f}"


def num(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def pct(x: float, d: int = 1) -> str:
    return "n/a" if x != x else f"{100 * x:.{d}f}%"


def pick(m: pd.DataFrame, seg: str, cost: float, variant: str = PRIMARY, rule: str = RULE) -> pd.Series:
    q = m[(m.segment == seg) & (m.cost_mult == cost) & (m.variant == variant) & (m.quote_rule == rule)]
    return q.iloc[0]


def curve(eq: pd.DataFrame, cost: float, mark: str) -> pd.DataFrame:
    """IS then OOS on one time axis, in % of the capital base. The OOS run starts flat; it is stacked on the IS end."""
    parts, base = [], 0.0
    for seg in ("IS", "OOS"):
        e = eq[(eq.quote_rule == RULE) & (eq.variant == PRIMARY) & (eq.cost_mult == cost) & (eq.segment == seg) & (eq["mark"] == mark)]
        e = e.sort_values("t")
        parts.append(pd.DataFrame({"t": pd.to_datetime(e.t, unit="s"), "y": (base + e.pnl.values) / cfg.CAPITAL_HISTORY * 100,
                                   "seg": seg}))
        base += float(e.pnl.values[-1]) if len(e) else 0.0
    return pd.concat(parts, ignore_index=True)


def style(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=8)
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    ax.grid(False, axis="x")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))


def charts(eq: pd.DataFrame, split: pd.Timestamp) -> None:
    series = (("mid", "All modelled entries", BLUE), ("mid_verified", "Print-verified entries only", ORANGE))
    for name, ylabel, transform in (("equity_curve.png", "Cumulative net P&L, % of $3,300 capital", None),
                                    ("drawdown.png", "Drawdown from peak, % of capital", "dd")):
        fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.3), sharey=True, facecolor=SURFACE)
        for ax, cost in zip(axes, cfg.COST_MULTIPLIERS):
            style(ax, f"{cost:.0f}× costs")
            for mark, label, color in series:
                c = curve(eq, cost, mark)
                y = c.y.values
                if transform == "dd":
                    full = np.concatenate([[0.0], y])
                    y = (full - np.maximum.accumulate(full))[1:]
                ax.plot(c.t, y, color=color, linewidth=2, solid_capstyle="round", solid_joinstyle="round", label=label)
                ax.plot([c.t.iloc[-1]], [y[-1]], "o", color=color, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
                ax.annotate(f"{y[-1]:+.1f}%", (c.t.iloc[-1], y[-1]), xytext=(7, 0), textcoords="offset points",
                            va="center", fontsize=9, color=INK)
            ax.axvline(split, color=INK2, linewidth=1)
            ax.annotate("out-of-sample starts ▸", (split, 1.0), xycoords=("data", "axes fraction"), xytext=(-5, -4),
                        textcoords="offset points", va="top", ha="right", fontsize=8.5, color=INK2)
            ax.margins(x=0.09)
        axes[0].set_ylabel(ylabel, fontsize=9, color=INK2)
        axes[0].legend(loc="upper left", bbox_to_anchor=(0.0, 0.86) if transform is None else (0.0, 0.3), frameon=False,
                       fontsize=9, labelcolor=INK)
        what = "equity curve" if transform is None else "drawdown"
        fig.suptitle(f"S1 twin spread, primary variant V0: {what}, in-sample then out-of-sample (mid mark)",
                     x=0.01, ha="left", fontsize=12, color=INK)
        fig.text(0.01, 0.005, "Blue is the backtest with a modelled Polymarket spread. Orange keeps only entries a public "
                 "Polymarket trade print confirms, at the printed size.", fontsize=8.5, color=INK2)
        fig.tight_layout(rect=(0, 0.04, 1, 0.95))
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def table(df: pd.DataFrame, cols: dict) -> str:
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for k in cols:
            v = r[k]
            cells.append(v if isinstance(v, str) else ("yes" if v is True else "no" if v is False else num(float(v), 2)
                         if isinstance(v, (float, np.floating)) else str(v)))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main() -> int:
    m = pd.read_csv(R / "metrics_history.csv")
    tr = pd.read_csv(R / "trades.csv")
    eq = pd.read_csv(R / "equity_history.csv")
    pairs = pd.read_csv(R / "pairs.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    fwd = pd.read_csv(R / "metrics_forward.csv") if (R / "metrics_forward.csv").exists() else None
    fwd_final = pd.read_csv(R / "metrics_forward_final.csv") if (R / "metrics_forward_final.csv").exists() else None
    split = pd.Timestamp(meta["split"]).tz_localize(None)
    charts(eq, split)

    allm = pd.concat([m] + [x.assign(quote_rule="recorded books") for x in (fwd, fwd_final) if x is not None], ignore_index=True)
    allm.to_csv(R / "metrics.csv", index=False)

    o1, o2, i1, i2 = pick(m, "OOS", 1.0), pick(m, "OOS", 2.0), pick(m, "IS", 1.0), pick(m, "IS", 2.0)
    crit = [
        ("1. At least 30 OOS entries across at least 5 pairs", o1.entries >= cfg.MIN_OOS_ENTRIES and o1.pairs_traded >= cfg.MIN_OOS_PAIRS,
         f"{int(o1.entries)} entries, {int(o1.pairs_traded)} pairs"),
        ("2. OOS net P&L positive under the mid and locked marks, pair-bootstrap interval excludes zero",
         o1.pnl_mid > 0 and o1.pnl_locked > 0 and o1.ci_lo_mid > 0,
         f"mid {money(o1.pnl_mid)}, locked {money(o1.pnl_locked)}, per trade {money(o1.mean_pnl_per_trade_mid)} [{num(o1.ci_lo_mid)}, {num(o1.ci_hi_mid)}]"),
        ("3. Still positive at 2× costs", o2.pnl_mid > 0 and o2.pnl_locked > 0, f"mid {money(o2.pnl_mid)}, locked {money(o2.pnl_locked)}"),
        ("4. At least half of OOS entries print-verified, and the verified subset positive",
         o1.verified_share >= cfg.MIN_VERIFIED_SHARE and o1.pnl_mid_verified > 0,
         f"{int(o1.verified_entries)} of {int(o1.entries)} verified ({pct(o1.verified_share)}); verified subset {money(o1.pnl_mid_verified)}"),
    ]
    passed = all(c[1] for c in crit)
    x = tr[(tr.quote_rule == RULE) & (tr.variant == PRIMARY) & (tr.cost_mult == 1.0)]
    xo = x[x.segment == "OOS"]
    ver = xo[xo.verified]
    unv = xo[~xo.verified]
    days_oos = (pd.Timestamp(meta["t1"]) - pd.Timestamp(meta["split"])).days
    top2 = float(ver.edge_at_entry_verified.nlargest(2).sum())
    nom = tr[tr.pair.str.startswith("KXPRESNOM")]
    ver_cap = float((ver.verified_qty * ver.cost_in).sum())

    head = pd.DataFrame([{
        "Segment": seg, "Costs": f"{c:.0f}×", "Entries": int(r.entries), "Pairs": int(r.pairs_traded),
        "Net P&L (mid)": money(r.pnl_mid), "Return on $3,300": pct(r.total_return if "total_return" in r else r.pnl_mid / cfg.CAPITAL_HISTORY),
        "Sharpe": num(r.sharpe_mid), "Max drawdown": pct(r.max_drawdown, 2), "Worst month": pct(r.worst_month, 2),
        "Turnover / yr": f"{r.turnover_ann:.1f}×", "Print-verified": f"{int(r.verified_entries)} of {int(r.entries)}",
        "Verified P&L (mid)": money(r.pnl_mid_verified), "Verified edge locked at entry": money(r.edge_at_entry_verified),
    } for seg, c, r in (("In-sample", 1, i1), ("In-sample", 2, i2), ("Out-of-sample", 1, o1), ("Out-of-sample", 2, o2))])

    variants = m.assign(
        Rule=m.quote_rule, Segment=m.segment, Variant=m.variant + np.where(m.variant == PRIMARY, " (primary)", ""),
        Costs=m.cost_mult.map(lambda c: f"{c:.0f}×"), Entries=m.entries.astype(int), Pairs=m.pairs_traded.astype(int),
        Mid=m.pnl_mid.map(money), Liq=m.pnl_liq.map(money), Locked=m.pnl_locked.map(money), Sharpe=m.sharpe_mid.map(num),
        DSR=m.deflated_sharpe_prob.map(lambda v: num(v, 3)), MDD=m.max_drawdown.map(lambda v: pct(v, 2)),
        Verified=m.verified_entries.astype(int).astype(str) + " of " + m.entries.astype(int).astype(str),
        VerPnL=m.pnl_mid_verified.map(money), VerEdge=m.edge_at_entry_verified.map(money))
    vcols = {"Rule": "Quote rule", "Segment": "Segment", "Variant": "Variant", "Costs": "Costs", "Entries": "Entries",
             "Pairs": "Pairs", "Mid": "P&L mid", "Liq": "P&L liquidation", "Locked": "P&L locked", "Sharpe": "Sharpe",
             "DSR": "Deflated Sharpe prob.", "MDD": "Max DD", "Verified": "Print-verified", "VerPnL": "Verified P&L",
             "VerEdge": "Verified edge at entry"}

    ver_tbl = ver.assign(Pair=ver.pair, Dir=ver.dir, Entry=ver.entry_utc.str.slice(0, 16), PM=ver.pm_px.map(lambda v: num(v, 3)),
                         K=ver.kalshi_bid.map(lambda v: num(v, 2)) + " / " + ver.kalshi_ask.map(lambda v: num(v, 2)),
                         Edge=(ver.edge_in * 100).map(lambda v: num(v, 1) + "¢"), Prints=ver.verify_n.astype(int),
                         Size=ver.verify_size.map(lambda v: f"{v:,.0f}"), Qty=ver.verified_qty.map(lambda v: f"{v:.0f}"),
                         Locked=ver.edge_at_entry_verified.map(money))
    ver_cols = {"Pair": "Kalshi ticker", "Dir": "Trade", "Entry": "Entry (UTC)", "PM": "Polymarket price paid (YES terms)",
                "K": "Kalshi bid / ask", "Edge": "Net edge per pair", "Prints": "Prints", "Size": "Printed shares",
                "Qty": "Contracts counted", "Locked": "Edge locked"}

    used = pairs[pairs.used == True]  # noqa: E712
    dropped = pairs[pairs.used != True]  # noqa: E712

    # ---- capacity.md
    cap = ["# S1 capacity", "",
           "## History", "",
           "The historical backtest makes **no capacity claim**: Kalshi candles and Polymarket price history carry no sizes "
           f"(METHOD.md section 5). It trades a fixed {cfg.CLIP_HISTORY} contract pairs per entry, about $100.", "",
           "The only size evidence in history is the Polymarket trade prints behind the verified entries (primary variant, "
           f"out-of-sample, 1× costs): {len(ver)} entries, median printed size "
           f"{ver.verify_size.median():,.0f} shares, smallest {ver.verify_size.min():,.0f}, largest {ver.verify_size.max():,.0f}. "
           f"Counted at the printed size and capped at 100, they are {ver.verified_qty.sum():,.0f} contract pairs and "
           f"${ver_cap:,.0f} of capital over {days_oos} days. Kalshi's size at those quotes is unknown.", ""]
    if (R / "capacity_forward.csv").exists():
        cf = pd.read_csv(R / "capacity_forward.csv")
        c0 = cf[(cf.variant == PRIMARY) & (cf.cost_mult == 1.0)]
        live = c0[c0.max_fillable_qty > 0]
        cap += ["## Forward recording (real books, sizes that were on the book)", "",
                f"Primary variant, 1× costs. Pairs with a fillable edge at any snapshot: {len(live)} of {len(c0)}. "
                f"Largest fillable amount per pair, summed: ${live.max_fillable_dollars.sum():,.0f} "
                f"({live.max_fillable_qty.sum():,.0f} contract pairs), locking {money(live.max_fillable_edge_dollars.sum())}.", ""]
        if len(live):
            cap += [table(live.assign(P=live.pair, S=live.snapshots_with_edge.astype(int), Q=live.max_fillable_qty.map(lambda v: f"{v:,.0f}"),
                                      D=live.max_fillable_dollars.map(lambda v: f"${v:,.0f}"), E=live.max_fillable_edge_dollars.map(money),
                                      Sh=live.depth_share_at_max.map(pct)),
                          {"P": "Pair", "S": "Snapshots with an edge", "Q": "Max fillable pairs", "D": "Max fillable $",
                           "E": "Edge locked at that size", "Sh": "Share of visible top-5 depth"}), ""]
    else:
        cap += ["## Forward recording", "", "Pending: the forward window closes Sun 2026-10-04 07:00 ET.", ""]
    (R / "capacity.md").write_text("\n".join(cap))

    # ---- SUMMARY.md
    S = []
    S += ["# S1: Polymarket–Kalshi twin spread", "",
          f"Method, pre-registered before any S1 data was pulled: [`research/s1_twin_spread/METHOD.md`](../../s1_twin_spread/METHOD.md) "
          "(commit `8260548`; amendments 1 and 2 in `460ffca`, before any run; amendment 3 in `68b49ff`, before the forward window). "
          f"History {meta['t0'][:10]} to {meta['t1'][:10]}, {meta['pairs_used']} of {meta['pairs_in_universe']} verified pairs, 1-minute bars. "
          f"Out-of-sample is the most recent 20%: {meta['split'][:10]} to {meta['t1'][:10]} ({days_oos} days). "
          "Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", ""]
    S += ["## Answer", ""]
    S += [f"**Real cross-venue gaps exist, they are confirmed by trade prints, and they were profitable after every cost. "
          f"They are also rare and small.** Out of sample, {len(ver)} entries on {ver.pair.nunique()} pairs have a public Polymarket "
          f"trade print at the price the trade needs. Held to resolution they lock in {money(o1.edge_at_entry_verified)} on "
          f"{ver.verified_qty.sum():,.0f} contract pairs (${ver_cap:,.0f} of capital), a mean net edge of "
          f"{100 * o1.edge_at_entry_verified / max(ver.verified_qty.sum(), 1):.1f}¢ per $1 pair after Kalshi fees, Polymarket fees, both "
          f"spreads and carry. At 2× costs {int(o2.verified_entries)} verified entries still lock in {money(o2.edge_at_entry_verified)}. "
          f"Marked at mid, with exits at modelled prices, their mean net P&L per trade is {money(o1.mean_pnl_per_verified_trade)} "
          f"(pair-bootstrap 95% interval {num(o1.ci_lo_verified)} to {num(o1.ci_hi_verified)}) at 1× and "
          f"{money(o2.mean_pnl_per_verified_trade)} ({num(o2.ci_lo_verified)} to {num(o2.ci_hi_verified)}) at 2×. "
          f"The result is concentrated: the two largest entries carry {money(top2)} of the {money(o1.edge_at_entry_verified)}.", "",
          f"**The strategy as pre-registered does not pass.** Criterion 4 fails: only {int(o1.verified_entries)} of {int(o1.entries)} "
          f"out-of-sample entries ({pct(o1.verified_share)}) are print-verified, against the 50% required. The unverified "
          f"{len(unv)} entries carry {money(unv.pnl_mid.sum())} of the {money(o1.pnl_mid)} modelled P&L. That P&L, and the "
          f"Sharpe ratio of {num(o1.sharpe_mid)}, come from the modelled Polymarket spread, not from prices anyone could trade "
          "(see \"Sharpe above 3\" below).", ""]
    S += ["## Headline numbers (primary variant V0, registered quote rule)", "", table(head, {c: c for c in head.columns}), "",
          f"Capital base $3,300 (33 pairs × $100), fully funded. Returns are net of financing at {100 * meta['rate']:.2f}% on locked capital. "
          "The Sharpe ratio is on daily marks at venue mids, 365 days a year. \"Verified edge locked at entry\" needs no modelled exit: "
          "it is the edge of the verified entries if simply held to resolution.", "",
          "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", ""]
    S += ["## Pre-registered success criterion", "", "| Criterion | Result | Evidence |", "|---|---|---|"]
    S += [f"| {c[0]} | {'pass' if c[1] else '**fail**'} | {c[2]} |" for c in crit]
    S += ["", f"**Verdict: {'pass' if passed else 'not a pass'}.**", ""]
    S += ["## The print-verified out-of-sample entries (primary variant, 1× costs)", "", table(ver_tbl, ver_cols), "",
          "Trade A buys Polymarket YES and Kalshi NO; trade B buys Kalshi YES and Polymarket NO. A print confirms the Polymarket "
          "price within ±10 minutes; it does not prove both legs could be filled in the same second, and Kalshi's size at the "
          "quote is unknown.", ""]
    S += ["## Costs, in bp of the capital committed (mean at entry, out-of-sample)", "",
          "| Cost | 1× | 2× | Source |", "|---|---|---|---|",
          f"| Fees, both venues | {o1.fees_bp:.0f} bp | {o2.fees_bp:.0f} bp | Kalshi: `ceil(0.07 × C × P × (1 − P))` to the cent, fee schedule and the API's `fee_type` / `fee_multiplier` (1 for all 33 series). Polymarket: the market's `feeSchedule`, rate 0.04 or 0.05 × P × (1 − P). |",
          f"| Half-spreads, both venues | {o1.spread_bp:.0f} bp | {o2.spread_bp:.0f} bp | Kalshi: real bid / ask from 1-minute candles. Polymarket: modelled, median of this weekend's live books per pair, floor 0.5¢. |",
          f"| Carry to the deadline | {o1.carry_bp:.0f} bp | {o2.carry_bp:.0f} bp | 3-month Treasury yield {100 * meta['rate']:.2f}% ({meta.get('rate_date', '')}), Alpha Vantage `TREASURY_YIELD` (FRED DGS3MO), on capital locked until the later venue deadline. |",
          "", "Not charged: USDC on- and off-ramp and gas, Kalshi deposit fees, taxes. Kalshi's interest on collateral is ignored.", ""]
    S += ["## Capacity", "",
          "History has no sizes, so it supports no capacity claim. The verified entries rest on prints with a median of "
          f"{ver.verify_size.median():,.0f} shares. At that scale S1 is a few hundred dollars per opportunity. "
          "Real depth comes from the forward recording: [`capacity.md`](capacity.md).", ""]
    S += ["## Forward paper test (this weekend's recorded order books)", ""]
    if fwd is None:
        S += ["Pending. The window is Sat 2026-10-03 20:00 ET to Sun 2026-10-04 07:00 ET. The rules are frozen in METHOD.md.", ""]
    else:
        f1 = fwd[(fwd.variant == PRIMARY) & (fwd.cost_mult == 1.0)].iloc[0]
        f2 = fwd[(fwd.variant == PRIMARY) & (fwd.cost_mult == 2.0)].iloc[0]
        S += [f"Window {f1.start} to {f1.end}, real books on both venues, fills only from recorded levels. Primary variant: "
              f"**{int(f1.entries)} fills on {int(f1.pairs_traded)} pairs at 1× costs**, {f1.contracts:,.0f} contract pairs, "
              f"${f1.capital:,.2f} of capital, locked edge {money(f1.pnl_locked)}"
              + (f" ({f1.locked_edge_bp:.0f} bp of capital)" if f1.capital else "") + f"; at 2× costs {int(f2.entries)} fills, {money(f2.pnl_locked)}. "
              f"Marked at the end of the window: mid {money(f1.pnl_mid)}, liquidation {money(f1.pnl_liq)}.", "",
              table(fwd.assign(V=fwd.variant, C=fwd.cost_mult.map(lambda c: f"{c:.0f}×"), E=fwd.entries.astype(int), P=fwd.pairs_traded.astype(int),
                               X=fwd.exits.astype(int), Q=fwd.contracts.map(lambda v: f"{v:,.0f}"), K=fwd.capital.map(lambda v: f"${v:,.2f}"),
                               L=fwd.pnl_locked.map(money), M=fwd.pnl_mid.map(money), Li=fwd.pnl_liq.map(money)),
                    {"V": "Variant", "C": "Costs", "E": "Fills", "P": "Pairs", "X": "Exits", "Q": "Contract pairs", "K": "Capital",
                     "L": "Locked edge", "M": "P&L at mid", "Li": "P&L at liquidation"}), "",
              "The window is under a day, so no Sharpe ratio is computed for it (METHOD.md section 6).", ""]
    S += ["## Every variant tried", "", table(variants, vcols), "",
          "`kalshi_carry_6h` is the sensitivity of amendment 1 (a Kalshi quote stays valid up to 6 hours, because Kalshi only "
          "writes a candle when the top of the book changes). The deflated Sharpe probability uses 8 trials.", ""]
    young = int(o1.entries_pm_market_under_48h)
    S += ["## Sharpe above 3: the bug hunt", "",
          f"The modelled backtest shows Sharpe ratios up to {m.sharpe_mid.max():.1f}. The pre-registered checks, in order:", "",
          "| Check | Outcome |", "|---|---|",
          "| Fills at the second observation | Enforced in code and pinned by tests (`test_a_gap_of_one_minute_is_never_traded`, `test_entry_fills_at_the_second_observation`). |",
          f"| Quote ages at entry | Kalshi median {x.kalshi_quote_age_s.median():.0f} s, max {x.kalshi_quote_age_s.max():.0f} s; Polymarket median {x.pm_point_age_s.median():.0f} s. Within the 15-minute rule. |",
          f"| **Polymarket points that are the middle of an empty or wide book** | **This is the cause.** {len(unv)} of {len(xo)} out-of-sample entries have no trade print at the price the model assumes. {young} entries are inside the first 48 hours of a Polymarket market's life, and {int(o1.entries_pm_price_45_55)} have a Polymarket \"price\" between 0.45 and 0.55 while Kalshi quotes far away: an unquoted midpoint, not a price. The median gap at entry is {100 * o1.median_abs_gap_at_entry:.0f}¢. |",
          f"| Fees on every leg | Yes: {o1.fees_bp:.0f} bp of capital per entry on average. |",
          "| Empty Kalshi sides | Never used (amendment 2, `test_build_pair_drops_empty_kalshi_sides`). |",
          "| Both clocks in UTC | Yes. Kalshi candles matched the recorder's live book in 1,542 of 1,584 snapshots. |",
          "| Pair direction | All 33 pairs are `direction: same`. |", "",
          "So the high Sharpe is not a coding bug. It is the artifact the earlier options scan found: a tight spread assumed "
          "around a history point that was never a tradable price. The trade-print check exists to catch it, and it did.", ""]
    S += ["## What didn't work", "",
          f"- **The modelled backtest is not evidence of an edge.** {pct(1 - o1.verified_share)} of its out-of-sample entries have no supporting trade print.",
          f"- **In-sample, almost nothing verifies:** {int(i1.verified_entries)} of {int(i1.entries)} entries, verified P&L {money(i1.pnl_mid_verified)}. "
          "Part of that is reach: Polymarket's data API serves only the latest 20,000 prints per market, so early entries on the "
          f"two busiest markets cannot be checked ({pct(1 - i1.prints_reach_share)} of in-sample entries are out of reach and are counted as unverified).",
          "- **Hold-only (V3) is weaker than the primary** on the mid mark: most of the modelled P&L comes from exits at modelled Polymarket prices.",
          f"- **{len(dropped)} of 33 pairs are unusable in history:** " + "; ".join(f"`{r.ticker}` ({r.reason})" for r in dropped.itertuples()) + ".",
          f"- **The 2028 nomination pairs produced {len(nom)} entries in any variant.** They lock capital for two years, so carry "
          "alone costs about 9¢ per $1.", ""]
    S += ["## Caveats", "",
          "- **Resolution risk.** The twins were verified from their text. No pair has resolved, so a mismatch cannot be measured here.",
          "- **Legging risk.** Both legs are assumed to fill together. A print within ±10 minutes is not a simultaneous fill.",
          "- **Exits use modelled Polymarket prices.** \"Verified edge locked at entry\" avoids that; the mid-mark P&L does not.",
          f"- **Small sample.** {len(ver)} verified out-of-sample entries on {ver.pair.nunique()} pairs in {days_oos} days; "
          f"two of them carry {money(top2)} of the {money(o1.edge_at_entry_verified)} locked.",
          "- **Coverage.** Under the registered 15-minute rule the two venues are both fresh in "
          f"{pct(used.both_share.median())} of minutes for the median pair ({pct(used.both_share_kalshi_carry_6h.median())} under the 6-hour sensitivity).", ""]
    S += ["## Reproduce", "", "```", "cd research",
          "python -m s1_twin_spread.data                       # pull (not committed; about 7 minutes)",
          f"python -m s1_twin_spread.run --rate {meta['rate']} --rate-date {meta.get('rate_date', '')}",
          f"python -m s1_twin_spread.forward --rate {meta['rate']}       # after the forward window closes",
          "python -m s1_twin_spread.report", "python -m pytest s1_twin_spread/tests -q", "```", ""]
    (R / "SUMMARY.md").write_text("\n".join(S))
    print("\n".join(S[4:8]))
    print(f"criteria: {[bool(c[1]) for c in crit]} -> {'PASS' if passed else 'NOT A PASS'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
