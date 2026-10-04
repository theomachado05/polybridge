"""S16 (overnight options): charts, SUMMARY.md and capacity.md, every number read back from the result files.

Run from `research/`:  python -m s16_overnight_options.report
"""
from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config as cfg
from .run import RESULTS

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"          # the first three slots of the validated palette
HYP_COLOR = {"H-dir": BLUE, "H-slow": ORANGE, "H-rich": AQUA}
HYP_NAME = {"H-dir": "H-dir: buy the option in the direction of the odds move", "H-slow": "H-slow: buy the straddle",
            "H-rich": "H-rich: sell the straddle"}
MORNING = list(cfg.MORNING)


def pct(v, d=1) -> str:
    return "n/a" if v != v else f"{100 * v:+.{d}f}%"


def upct(v, d=1) -> str:
    return "n/a" if v != v else f"{100 * v:.{d}f}%"


def ci(lo, hi, d=1) -> str:
    return "[n/a]" if lo != lo or hi != hi else f"[{100 * lo:+.{d}f}%, {100 * hi:+.{d}f}%]"


def num(v, d=2) -> str:
    return "n/a" if v != v else f"{v:.{d}f}"


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def end_labels(ax, x, ends: list[tuple[float, str]]) -> None:
    """Direct labels at the line ends, pushed apart so they never sit on each other."""
    lo, hi = ax.get_ylim()
    gap = 0.07 * (hi - lo)
    placed: list[float] = []
    for y, lab in sorted(ends):
        yy = y if not placed else max(y, placed[-1] + gap)
        placed.append(yy)
        ax.annotate(lab, (x, y), xytext=(x, yy), textcoords="data", color=INK2, fontsize=9, va="center",
                    xycoords="data", annotation_clip=False)
        ax.texts[-1].set_x(x)
        ax.texts[-1].set_position((x, yy))
        ax.texts[-1].set_text("  " + lab)


def chart_speed(sc: pd.DataFrame) -> None:
    s = sc[(sc["sample"] == "main") & (sc.segment == "ALL") & (sc.to == cfg.CLOSE) & sc["from"].isin(MORNING)]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.2), sharex=True, facecolor=SURFACE)
    xs = np.arange(len(MORNING))
    for j, (inst, title) in enumerate((("straddle", "Straddle (call + put)"), ("directional", "Option in the direction of the odds move"))):
        d = s[s.instrument == inst].set_index("from").loc[MORNING]
        ax = axes[0, j]
        style(ax)
        ends = []
        for off, col, lab, m, lo, hi in ((-0.06, BLUE, "event mornings", d["mean"], d.ci_lo, d.ci_hi),
                                         (0.06, ORANGE, "control mornings", d.control_mean, d.control_ci_lo, d.control_ci_hi)):
            y = 100 * m.to_numpy()
            ax.errorbar(xs + off, y, yerr=[y - 100 * lo.to_numpy(), 100 * hi.to_numpy() - y], color=col, linewidth=2, marker="o", markersize=6,
                        elinewidth=1, capsize=0, label=lab)
            ends.append((y[-1], lab))
        end_labels(ax, xs[-1] + 0.06, ends)
        ax.axhline(0, color=INK2, linewidth=0.8)
        ax.set_title(title, color=INK, fontsize=11, loc="left", pad=22)
        ax.set_ylabel("return to 15:55, mid to mid (%)", color=INK2, fontsize=9)
        ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, borderaxespad=0.2)
        ax = axes[1, j]
        style(ax)
        y = 100 * d.diff_mean.to_numpy()
        ax.errorbar(xs, y, yerr=[y - 100 * d.diff_ci_lo.to_numpy(), 100 * d.diff_ci_hi.to_numpy() - y], color=INK, linewidth=2, marker="o",
                    markersize=6, elinewidth=1, capsize=0)
        for x_, v in zip(xs, y):
            ax.annotate(f"{v:+.1f}", (x_, v), xytext=(9, 9), textcoords="offset points", color=INK2, fontsize=9,
                        bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1.0})
        ax.axhline(0, color=INK2, linewidth=0.8)
        ax.set_ylabel("event minus control (points)", color=INK2, fontsize=9)
        ax.set_xticks(xs)
        ax.set_xticklabels(MORNING)
        ax.set_xlabel("bought at (New York time), held to 15:55", color=INK2, fontsize=9)
    for ax in axes.ravel():
        ax.set_xlim(-0.4, len(MORNING) + 0.6)
    fig.suptitle("If options were fully repriced at the open, event minus control would be zero from every instant\n"
                 "Overnight odds moves of 10+ points; bars are 95% intervals from resampling dates", color=INK, fontsize=12, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(RESULTS / "speed_curve.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_equity(eq: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), facecolor=SURFACE)
    for ax, costs, title in ((axes[0], "1x", "At real bid/ask, with commissions"),
                             (axes[1], "mid", "Mid to mid, no cost (not tradable; its own scale)")):
        style(ax)
        ends = []
        for hyp in cfg.HYPOTHESES:
            d = eq[(eq.hypothesis == hyp) & (eq.costs == costs)]
            x = pd.to_datetime(d.day)
            ax.plot(x, 100 * d.cumulative, color=HYP_COLOR[hyp], linewidth=2, label=HYP_NAME[hyp])
            ends.append((100 * d.cumulative.iloc[-1], hyp))
        end_labels(ax, x.iloc[-1], ends)
        ax.axvline(pd.Timestamp(cfg.OOS_FROM), color=INK2, linewidth=0.8, linestyle=(0, (4, 3)))
        ax.annotate("out-of-sample from here", (pd.Timestamp(cfg.OOS_FROM), 1.0), xycoords=("data", "axes fraction"), xytext=(4, -9),
                    textcoords="offset points", color=INK2, fontsize=8)
        ax.axhline(0, color=INK2, linewidth=0.8)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.margins(x=0.14)
        ax.set_ylabel("cumulative daily return, % of premium", color=INK2, fontsize=9)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=9, labelcolor=INK2, loc="lower left", ncol=3, bbox_to_anchor=(0.01, 0.0))
    fig.suptitle("The three pre-registered trades, 09:35 to 15:55, after overnight odds moves of 10+ points", color=INK, fontsize=12, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    fig.savefig(RESULTS / "equity_curve.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11.5, 4.8), facecolor=SURFACE)
    style(ax)
    ends = []
    for hyp in cfg.HYPOTHESES:
        d = eq[(eq.hypothesis == hyp) & (eq.costs == "1x")]
        x = pd.to_datetime(d.day)
        ax.plot(x, -100 * d.drawdown, color=HYP_COLOR[hyp], linewidth=2, label=HYP_NAME[hyp])
        ends.append((-100 * d.drawdown.iloc[-1], hyp))
    end_labels(ax, x.iloc[-1], ends)
    ax.axvline(pd.Timestamp(cfg.OOS_FROM), color=INK2, linewidth=0.8, linestyle=(0, (4, 3)))
    ax.annotate("out-of-sample from here", (pd.Timestamp(cfg.OOS_FROM), 1.0), xycoords=("data", "axes fraction"), xytext=(4, -9),
                textcoords="offset points", color=INK2, fontsize=8)
    ax.set_ylabel("drawdown from the peak, % of premium", color=INK2, fontsize=9)
    ax.set_title("Drawdown of the three trades at real bid/ask (09:35 to 15:55, moves of 10+ points)", color=INK, fontsize=12, loc="left")
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=9, labelcolor=INK2, loc="lower left", ncol=3, bbox_to_anchor=(0.01, 0.0))
    ax.margins(x=0.12)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(RESULTS / "drawdown.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


class R:
    """The result files, read back."""

    def __init__(self):
        self.m = pd.read_csv(RESULTS / "metrics.csv")
        self.sc = pd.read_csv(RESULTS / "speed_curve.csv")
        self.sp = pd.read_csv(RESULTS / "spreads.csv")
        self.v = pd.read_csv(RESULTS / "verdicts.csv")
        self.t = pd.read_csv(RESULTS / "trades.csv")
        self.top = pd.read_csv(RESULTS / "top_moves.csv")
        self.eq = pd.read_csv(RESULTS / "equity.csv")
        self.obs = pd.read_csv(RESULTS / "observations.csv", low_memory=False)
        self.meta = json.loads((RESULTS / "run_meta.json").read_text())

    def row(self, hyp, seg="ALL", costs="1x", variant="V0", scope="main"):
        x = self.m[(self.m.scope == scope) & (self.m.variant == variant) & (self.m.hypothesis == hyp) & (self.m.segment == seg) & (self.m.costs == costs)]
        return x.iloc[0] if len(x) else None

    def speed(self, inst, frm, to=cfg.CLOSE, seg="ALL", sample="main"):
        x = self.sc[(self.sc["sample"] == sample) & (self.sc.segment == seg) & (self.sc.instrument == inst) & (self.sc["from"] == frm) & (self.sc.to == to)]
        return x.iloc[0] if len(x) else None

    def spread(self, inst, instant, kind="event", sample="main"):
        x = self.sp[(self.sp["sample"] == sample) & (self.sp.instrument == inst) & (self.sp.instant == instant) & (self.sp.kind == kind)]
        return x.iloc[0] if len(x) else None


def trade_table(r: R, scope: str, variant: str, hyps, segs=("IS", "OOS", "ALL"), costs=("mid", "1x", "2x")) -> list[str]:
    out = ["| Trade | Segment | Costs | Trades | Dates | Mean return | 95% interval | Median | Winners | Control mean | Event minus control | Sharpe | Max DD | Worst month |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for hyp in hyps:
        for seg in segs:
            for c in costs:
                x = r.row(hyp, seg, c, variant, scope)
                if x is None:
                    continue
                out.append(f"| {hyp} | {seg} | {c} | {int(x.trades)} | {int(x.dates)} | {pct(x['mean'])} | {ci(x.ci_lo, x.ci_hi)} | {pct(x['median'])} | {upct(x.hit_rate, 0)} | "
                           f"{pct(x.control_mean)} (n {int(x.control_trades)}) | {pct(x.diff_mean)} {ci(x.diff_ci_lo, x.diff_ci_hi)} (pairs {int(x.pairs)}) | "
                           f"{num(x.sharpe)} | {upct(x.max_drawdown, 0)} | {pct(x.worst_month, 0)} |")
    return out


def status_line(st: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in st.items()) if st else "none"


def tier_state(meta: dict) -> tuple[list[int], str]:
    fin: list[int] = []
    stopped = ""
    for s in meta.get("pull_runs", []):
        fin += [t for t in s.get("finished_tiers", []) if t not in fin]
        stopped = s.get("stopped") or ""
    return fin, stopped


def summary(r: R, answer: list[str], after: list[str]) -> str:
    meta = r.meta
    st = meta["status"]
    fin, stopped = tier_state(meta)
    L: list[str] = []
    L += ["# S16 (overnight options): after a big overnight move in the odds, are options on the linked asset mispriced in the first minutes?",
          "",
          "Method, pre-registered before any option quote was pulled: [`research/s16_overnight_options/METHOD.md`](../../s16_overnight_options/METHOD.md) "
          "(commit `1185abb`; amendments in METHOD.md, the label is S16: amendment 3). "
          f"{meta['sessions']} sessions, {meta['first_session']} to {meta['last_session']}; out-of-sample is every session from {meta['oos_from']}. "
          "Files: [`metrics.csv`](metrics.csv), [`trades.csv`](trades.csv), [`observations.csv`](observations.csv), [`speed_curve.csv`](speed_curve.csv), "
          "[`spreads.csv`](spreads.csv), [`verdicts.csv`](verdicts.csv), [`top_moves.csv`](top_moves.csv), [`equity.csv`](equity.csv), "
          "[`capacity.md`](capacity.md), [`RUN_LOG.md`](RUN_LOG.md).", ""]
    if not meta.get("pull_runs"):
        L += ["> **INTERIM.** The pull is still running. The main sample (tier 1) is complete and its numbers below are final; the Brazil and "
              "Fed-and-banks case files, the day volumes and variant V3 are not pulled yet and will change.", ""]
    L += ["## Answer", ""]
    L += answer
    L += ["", "![Speed curve](speed_curve.png)", "", "## The pre-registered pass line, hypothesis by hypothesis", ""]
    for hyp in cfg.HYPOTHESES:
        v = r.v[r.v.hypothesis == hyp]
        a = r.row(hyp, "ALL", "1x")
        L += [f"**{HYP_NAME[hyp]}, 09:35 quote to 15:55 quote. Verdict: {v.verdict.iloc[0]}.**", "", "| Line | Met | Evidence |", "|---|---|---|"]
        L += [f"| {x.line} | {'yes' if x.met else '**no**'} | {x.evidence} |" for x in v.itertuples()]
        if hyp != "H-dir" and a is not None:
            ok = a.diff_ci_lo == a.diff_ci_lo and a.diff_ci_lo > 0
            L.append(f"| Supporting line (not part of the pass): event minus control above zero, interval excluding zero, whole sample | "
                     f"{'yes' if ok else '**no**'} | {pct(a.diff_mean)} {ci(a.diff_ci_lo, a.diff_ci_hi)}, {int(a.pairs)} pairs |")
        L.append("")
    L += ["## Headline numbers (primary V0: moves of 10+ points, in at 09:35, out at 15:55)", ""]
    L += trade_table(r, "main", "V0", cfg.HYPOTHESES)
    L += ["", "Returns are a share of the premium traded at entry (for H-rich the premium received, not the margin). `mid` is mid price to mid price with no "
          "cost and is not tradable. `1x` buys at the ask and sells at the bid, with $0.65 per contract per leg each way. `2x` doubles every half-spread and "
          "commission. Intervals resample dates. Sharpe is on the daily book over every session of the segment (a day with no trade is zero), times √252.",
          "", "![Equity curve](equity_curve.png)", "", "![Drawdown](drawdown.png)", "",
          "## The speed curve: mean mid-to-mid return from each instant to 15:55", "",
          "| Instrument | Bought at | Event mornings | 95% interval | n | Control mornings | n | Event minus control | 95% interval | Pairs |", "|---|---|---|---|---|---|---|---|---|---|"]
    for inst in ("straddle", "directional"):
        for k in MORNING:
            x = r.speed(inst, k)
            if x is not None:
                L.append(f"| {inst} | {k} | {pct(x['mean'])} | {ci(x.ci_lo, x.ci_hi)} | {int(x.trades)} | {pct(x.control_mean)} | {int(x.control_trades)} | "
                         f"{pct(x.diff_mean)} | {ci(x.diff_ci_lo, x.diff_ci_hi)} | {int(x.pairs)} |")
    L += ["", "The directional option on a control morning is the same side (call or put) as its event's. Mid prices at 09:31 sit inside wide quotes "
          "(next table), so the 09:31 row is a measurement, not a price anyone could trade.", ""]
    a, b = r.speed("straddle", cfg.PREV_CLOSE, cfg.T0931), r.speed("directional", cfg.PREV_CLOSE, cfg.T0931)
    if a is not None and b is not None:
        L += [f"While the market was shut (previous 15:55 to 09:31, events only, mid to mid): the straddle changed by {pct(a['mean'])} {ci(a.ci_lo, a.ci_hi)} "
              f"(n {int(a.trades)}); the option in the direction of the odds move by {pct(b['mean'])} {ci(b.ci_lo, b.ci_hi)} (n {int(b.trades)}).", ""]
    L += ["## How wide options are in the first minutes (quoted spread as a share of the mid premium)", "",
          "| Instant | Straddle, event (median) | Straddle, control (median) | Directional option, event (median) | Middle half of event straddles | n event |",
          "|---|---|---|---|---|---|"]
    for k in [cfg.PREV_CLOSE] + MORNING + [cfg.CLOSE]:
        e, c, d = r.spread("straddle", k), r.spread("straddle", k, "control"), r.spread("directional", k)
        if e is not None:
            L.append(f"| {k} | {upct(e.median_spread_share)} | {upct(c.median_spread_share) if c is not None else 'not pulled'} | "
                     f"{upct(d.median_spread_share) if d is not None else 'n/a'} | {upct(e.p25)} to {upct(e.p75)} | {int(e.n)} |")
    L += ["", "## Variants (all reported; none of them is the test)", ""]
    for v in cfg.VARIANTS[1:]:
        note = v.note
        if v.id == "V3":
            n5 = st["v3extra"]
            done = 5 in fin
            note += (" (tier 5 of the pull finished)" if done else
                     f" (**incomplete**: the pull stopped before tier 5 finished; extra events with quotes: {n5['event'].get('ok', 0)} of "
                     f"{sum(n5['event'].values())}, not pulled: {n5['event'].get('not pulled', 0)}; a seeded random subsample)")
        L += [f"**{v.id}: {note}.**", ""] + trade_table(r, "main", v.id, cfg.HYPOTHESES, segs=("OOS", "ALL"), costs=("mid", "1x")) + [""]

    L += ["## Named case files (exploratory; none of them is the test)", "", "### Brazil: first-round questions against EWZ options (moves of 5+ points)", ""]
    bz = st["brazil"]
    L += [f"Mornings: {sum(bz['event'].values())} ({status_line(bz['event'])}); controls: {sum(bz['control'].values())} ({status_line(bz['control'])}).", ""]
    L += trade_table(r, "case: brazil", "V0", cfg.HYPOTHESES, segs=("ALL",))
    x = r.speed("straddle", cfg.T0931, sample="brazil")
    y = r.speed("directional", cfg.T0931, sample="brazil")
    if x is not None and y is not None:
        L += ["", f"From 09:31 to 15:55, mid to mid: straddle {pct(x['mean'])} against control {pct(x.control_mean)}; directional option {pct(y['mean'])} against "
              f"control {pct(y.control_mean)}. With {int(x.trades)} mornings no interval means anything."]
    L += ["", "### Oil: USO, XLE and XOP ticker-days of the main sample", ""]
    L += trade_table(r, "case: oil", "V0", cfg.HYPOTHESES)
    L += ["", "Speed curve, oil only (event minus control, mid to mid, to 15:55):", "", "| Instrument | 09:31 | 09:35 | 09:45 | 10:00 | 10:30 |", "|---|---|---|---|---|---|"]
    for inst in ("straddle", "directional"):
        cells = []
        for k in MORNING:
            x = r.speed(inst, k, sample="main, oil only")
            cells.append(f"{pct(x.diff_mean)} {ci(x.diff_ci_lo, x.diff_ci_hi)}" if x is not None else "n/a")
        L.append(f"| {inst} | " + " | ".join(cells) + " |")
    L += ["", "### Fed and banks: straddles on TLT, KRE and XLF on mornings when a Fed question moved 5+ points", ""]
    fd = st["fed"]
    L += [f"Ticker-days: {sum(fd['event'].values())} ({status_line(fd['event'])}); controls: {sum(fd['control'].values())} ({status_line(fd['control'])}). "
          + ("Tier 4 of the pull finished." if 4 in fin else "**Incomplete:** the pull stopped before tier 4 finished; what is here is a seeded random subsample."), ""]
    L += trade_table(r, "case: fed", "V0", ("H-slow", "H-rich"), segs=("ALL",))
    L += ["", "By ticker (whole sample, 1x costs):", "", "| Ticker | Trade | Trades | Mean return | 95% interval | Control mean | Event minus control |", "|---|---|---|---|---|---|---|"]
    for tk in cfg.FED_TICKERS:
        for hyp in ("H-slow", "H-rich"):
            x = r.row(hyp, "ALL", "1x", "V0", f"case: fed, {tk}")
            if x is not None:
                L.append(f"| {tk} | {hyp} | {int(x.trades)} | {pct(x['mean'])} | {ci(x.ci_lo, x.ci_hi)} | {pct(x.control_mean)} (n {int(x.control_trades)}) | "
                         f"{pct(x.diff_mean)} {ci(x.diff_ci_lo, x.diff_ci_hi)} |")
    L += ["", f"### The 12 largest overnight moves since {cfg.SINCE_DAY} and what the options did", "",
          "| Day | Ticker | Question | Odds move | Asset should | Stock gap, signed | Option, prev 15:55 to 09:31 (mid) | Straddle spread 09:31 / 09:35 | "
          "Option 09:35 to 15:55, mid / net | Straddle 09:35 to 15:55, mid | Stock 09:35 to 15:55, signed |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in r.top.itertuples():
        q = str(x.question)[:70]
        if x.status != "ok":
            L.append(f"| {x.day} | {x.ticker} | {q} | {x.x:+.1f} | {'rise' if x.direction > 0 else 'fall'} | dropped: {x.status} | | | | | |")
            continue
        L.append(f"| {x.day} | {x.ticker} | {q} | {x.x:+.1f} | {'rise' if x.direction > 0 else 'fall'} | {x.gap_bp_signed:+.0f} bp | "
                 f"{pct(x.directional_prev_to_0931_mid, 0)} | {upct(x.straddle_spread_0931, 0)} / {upct(x.straddle_spread_0935, 0)} | "
                 f"{pct(x.directional_0935_to_close_mid, 0)} / {pct(x.directional_0935_to_close_net, 0)} | {pct(x.straddle_0935_to_close_mid, 0)} | "
                 f"{x.underlying_0935_to_close_bp_signed:+.0f} bp |")
    L += ["", "\"Signed\" means in the direction the odds pointed: a positive number is the asset moving the way the odds said.", "",
          "## Counts and drops", "",
          f"- Main sample: {sum(st['main']['event'].values())} event ticker-days on {meta['main_event_dates']} dates. Status: {status_line(st['main']['event'])}.",
          f"- Controls planned for {sum(st['main']['control'].values())} of them. Status: {status_line(st['main']['control'])}.",
          f"- Main events with valid primary quotes: in-sample {meta['main_events_ok_by_segment']['IS']}, out-of-sample {meta['main_events_ok_by_segment']['OOS']}.",
          "- Dropped main events by ticker: " + ("; ".join(f"{tk} ({', '.join(f'{k}: {v}' for k, v in d.items())})"
                                                           for tk, d in sorted(meta['main_event_drops_by_ticker'].items())) or "none") + ".",
          f"- Put-call parity check at 09:35 (call mid minus put mid, against the stock price minus the strike), as a share of the stock price: median "
          f"{upct(meta['parity_gap_share_abs']['median'], 2)}, 99th percentile {upct(meta['parity_gap_share_abs']['p99'], 2)}, largest "
          f"{upct(meta['parity_gap_share_abs']['max'], 2)}; {meta['parity_gap_share_abs']['over_2pct']} of {meta['parity_gap_share_abs']['n']} above 2%.",
          f"- Pull: tiers finished {fin}; " + (f"stopped: {stopped}." if stopped else "no stop.")]
    L += [""] + after
    L += ["", "## Forward test (rules fixed in METHOD.md section 11, not run)", "",
          "The three Brazil first-round questions carry an end date of 2026-10-05T03:59Z in the market metadata on disk (Sunday 2026-10-04 23:59 New York "
          "time). The same three trades on EWZ at the next session's 09:35 quote, with the rule for direction and contract, are written in METHOD.md "
          "section 11 for someone else to run. One morning is an anecdote and enters no significance statement.", ""]
    return "\n".join(L)


def capacity(r: R) -> str:
    t = r.t[(r.t.variant == "V0") & (r.t.kind == "event")]
    L = ["# S16 (overnight options): capacity and costs: what could be traded at the 09:35 quote", "",
         "Main-sample events (overnight odds move of 10+ points), primary timing. Sizes are the NBBO size at the entry price (the ask for a purchase, the "
         "bid for a sale; for a straddle the smaller of the two legs). Volume is the day's volume of the contract (for a straddle the smaller leg). "
         "Costs are measured from the quotes themselves: mid-to-mid P&L minus P&L at bid/ask with $0.65 per contract per leg each way.", "",
         "| Trade | Trades | Median premium per contract set | Median size at entry (contracts) | Median day volume (contracts) | Trades with volume data | "
         "Median entry spread, share of premium | Mean round-trip cost, share of premium | Mean round-trip cost, bp of the stock price | Premium at the quoted size (median) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for hyp in cfg.HYPOTHESES:
        d = t[t.hypothesis == hyp]
        if d.empty:
            continue
        cost_share = (d.ret_mid - d.ret_1x).mean()
        L.append(f"| {hyp} | {len(d)} | ${d.premium_1x.median():,.0f} | {d.size_at_entry_contracts.median():.0f} | "
                 f"{d.day_volume_contracts.median():.0f} | {int(d.day_volume_contracts.notna().sum())} | {upct(d.entry_spread_share.median())} | "
                 f"{upct(cost_share)} | {d.cost_bp_of_underlying_1x.mean():.1f} | ${(d.premium_1x * d.size_at_entry_contracts).median():,.0f} |")
    L += ["", "## By ticker (H-slow, the straddle bought at 09:35)", "",
          "| Ticker | Trades | Median premium | Median size at the ask | Median day volume | Median entry spread | Mean net return | Mean mid-to-mid return |", "|---|---|---|---|---|---|---|---|"]
    d = t[t.hypothesis == "H-slow"]
    for tk, g in sorted(d.groupby("ticker"), key=lambda kv: -len(kv[1])):
        L.append(f"| {tk} | {len(g)} | ${g.premium_1x.median():,.0f} | {g.size_at_entry_contracts.median():.0f} | {g.day_volume_contracts.median():.0f} | "
                 f"{upct(g.entry_spread_share.median())} | {pct(g.ret_1x.mean())} | {pct(g.ret_mid.mean())} |")
    L += ["", "The quoted size is what one order could take at the entry price at that instant; a larger order pays more. The day's volume in these "
          "contracts is the ceiling on what trades in them at all. No fill in this study is larger than one contract set.", ""]
    return "\n".join(L)


def run_log(r: R, notes: list[str]) -> str:
    import subprocess
    from .plan import CACHE, RESEARCH
    git = subprocess.run(["git", "log", "--date=format-local:%Y-%m-%d %H:%M", "--format=%h | %ad | %s", "--",
                          "research/s16_overnight_options", "research/results/s16_overnight_options"],
                         cwd=RESEARCH.parent, capture_output=True, text=True, env={"TZ": "America/New_York", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}).stdout.strip().splitlines()
    log = (CACHE / "pull.log").read_text().splitlines() if (CACHE / "pull.log").exists() else []
    keep = [x for x in log if any(k in x for k in ("pull start", "recorder", "finished", "hard stop", "pull end", "request failed", "in a row"))]
    fin, stopped = tier_state(r.meta)
    runs = r.meta.get("pull_runs", [])
    L = ["# S16 (overnight options): run log", "",
         "All times New York (EDT) unless marked Z (UTC). The label was S16, then S17 for a few minutes, then S16 again (METHOD.md amendments 2 and 3); "
         "the folder never changed.", "", "## Commits (read from `git log`, newest first; the commit that adds this file is the one after these)", "",
         "| Hash | Time | Message |", "|---|---|---|"]
    L += [f"| `{a.strip()}` | {b.strip()} | {c.strip()[:150]} |" for a, b, c in (x.split(" | ", 2) for x in git)]
    L += ["", "## Data sources", "",
          "- Odds: the one-minute Polymarket caches of S5 and S4 on disk and `results/s8_open_referee/mornings.csv`. **No call to Polymarket or Kalshi.**",
          "- Underlying prices: cached five-minute bars (`eq_<TICKER>.npz` of S5 and S4); KRE and XLF bars pulled from Massive (amendment 1).",
          "- Options: Massive `/v3/reference/options/contracts` (one listing request per ticker-day), `/v3/quotes/<contract>` (the last NBBO at or before "
          "each instant, one request per leg and instant), `/v2/aggs/ticker/<contract>/range/1/day` (day volume). No modelled price anywhere.",
          f"- Cache: `research/s16_overnight_options/.cache/cache.jsonl`, {r.meta['cache_lines']:,} lines (not committed).", "",
          "## The pull", ""]
    for i, st in enumerate(runs, 1):
        L.append(f"- Run {i}: {st.get('requests')} requests in {st.get('seconds')} s; tiers finished {st.get('finished_tiers')}; "
                 f"stopped: {st.get('stopped') or 'no (ran to the end)'}; failed requests {st.get('errors')}; final rate {st.get('final_rps')} a second; "
                 f"recorder `fetch failed` lines before {st.get('recorder_before')}, after {st.get('recorder_after')}; ended {st.get('ended_utc')}.")
    L += ["", "Lines of the pull's own log (UTC):", "", "```"] + keep + ["```", "", "## Notes, and anything that went wrong", ""]
    L += [f"- {n}" for n in notes]
    return "\n".join(L) + "\n"


def main(answer: list[str] | None = None, after: list[str] | None = None) -> int:
    r = R()
    chart_speed(r.sc)
    chart_equity(r.eq)
    notes: list[str] = []
    try:
        from .answer import answer as ans_fn
        answer, after, notes = ans_fn(r)
    except ModuleNotFoundError:
        answer, after = answer or ["(answer not written yet)"], after or []
    (RESULTS / "SUMMARY.md").write_text(summary(r, answer, after))
    (RESULTS / "capacity.md").write_text(capacity(r))
    (RESULTS / "RUN_LOG.md").write_text(run_log(r, notes))
    print("wrote SUMMARY.md, capacity.md, RUN_LOG.md, speed_curve.png, equity_curve.png, drawdown.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
