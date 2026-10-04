"""Figures for note/NOTE.md, drawn from committed result files only. Offline. Run by `make reproduce`, or alone:

    cd research && python note_figures.py

Writes note/figures/: ladder_equity.png, ladder_drawdown.png, s21_buyers_by_gap.png, scoreboard.png.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
R = HERE / "results"
OUT = HERE.parent / "note" / "figures"
NY = ZoneInfo("America/New_York")
LADDER = R / "ladder_replay"
RULES = (("Rule as registered", LADDER / "trades_fresh.csv", "#eb6834"), ("Year-checked\n(fixed after the run)", LADDER / "order_check" / "trades_fresh.csv", "#2a78d6"))
OOS_START = "2026-07-22"                 # ladder_replay.config.S11_OOS_START (asserted in reproduce.py's table)
INK, INK2, GRID, AXIS, BLUE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#2a78d6"

plt.rcParams.update({"font.size": 7.5, "font.family": "DejaVu Sans", "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "text.color": INK, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
                     "savefig.dpi": 300, "legend.frameon": False, "axes.titlesize": 8.5, "axes.titleweight": "bold", "axes.titlelocation": "left"})


W = 3.7                                  # inches: drawn at about half a page width, so the type is readable there


def foot(ax, text: str, y: float) -> None:
    ax.text(0.0, y, text, transform=ax.transAxes, fontsize=6.2, color=INK2, ha="left", va="top", wrap=False)


def save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, metadata={"Software": None}, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return p


# ---------------------------------------------------------------- (a), (b): the ladder book

def curve(path: Path) -> tuple[pd.DataFrame, datetime]:
    """Cumulative net dollars by resolution time (lock_end), as `ladder_replay.replay.metrics` orders them for its drawdown."""
    with path.open(newline="") as f:
        rows = sorted(({"t": float(r["lock_end"]), "pnl": float(r["pnl_usd"]), "settled": r["settled"] == "True", "entry": float(r["t_entry"])}
                       for r in csv.DictReader(f)), key=lambda r: r["t"])
    d = pd.DataFrame(rows)
    d["when"] = [datetime.fromtimestamp(t, NY).replace(tzinfo=None) for t in d.t]
    d["cum"] = d.pnl.cumsum()
    d["dd"] = np.maximum.accumulate(np.concatenate([[0.0], d.cum.to_numpy()]))[1:] - d.cum
    last_entry = datetime.fromtimestamp(d.entry.max(), NY).replace(tzinfo=None)
    return d, last_entry


def ladder_axes(ax, run_end: datetime) -> None:
    oos = datetime.fromisoformat(OOS_START)
    ax.axvline(oos, color=INK2, lw=0.9, ls=(0, (2, 2)))
    ax.annotate("out-of-sample\nentries start\n22 Jul 2026", (oos, 0.03), xycoords=("data", "axes fraction"), xytext=(4, 0), textcoords="offset points",
                ha="left", va="bottom", fontsize=6.5, color=INK2)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.set_xlabel("Date the trade resolved")


def ladder_figures() -> list[Path]:
    curves = [(name, *curve(path), color) for name, path, color in RULES]
    run_end = max(c[2] for c in curves)
    out = []
    for kind, col, ylab, title, fname in (
            ("equity", "cum", "Cumulative profit after costs, dollars", "Date-ladder book: profit after costs", "ladder_equity.png"),
            ("drawdown", "dd", "Fall from the earlier peak, dollars", "Date-ladder book: drawdown", "ladder_drawdown.png")):
        fig, ax = plt.subplots(figsize=(W, 2.5))
        for name, d, _, color in curves:
            y = d[col] if kind == "equity" else -d[col]
            x0 = [d.when.iloc[0]] + list(d.when)
            y0 = [0.0] + list(y)
            n = 1 + int(d.settled.sum())                     # resolved trades come first in time; the rest end later
            assert bool(d.settled.iloc[:n - 1].all()) and not bool(d.settled.iloc[n - 1:].any())
            ax.step(x0[:n], y0[:n], where="post", color=color, lw=1.4, label=name)
            if n < len(x0):                                  # trades not yet resolved, at their guaranteed floor, at their end date
                ax.step(x0[n - 1:], y0[n - 1:], where="post", color=color, lw=1.0, ls=(0, (1, 1.5)))
            if kind == "equity":
                ax.annotate(f"${y0[-1]:,.0f}", (x0[-1], y0[-1]), xytext=(0, 3), textcoords="offset points", fontsize=6.8, color=INK, ha="right")
            elif min(y0) < 0:
                ax.annotate(f"largest fall\n-${-min(y0):,.0f}", (x0[int(np.argmin(y0))], min(y0)), xytext=(-4, 0), textcoords="offset points", fontsize=6.8,
                            color=INK, ha="right", va="bottom")
        ladder_axes(ax, run_end)
        ax.axhline(0, color=AXIS, lw=0.8)
        ax.set_ylabel(ylab)
        ax.set_title(title)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}" if v >= 0 else f"-${-v:,.0f}"))
        ax.legend(loc="upper left" if kind == "equity" else "center right", fontsize=6.5, handlelength=1.2, borderaxespad=0.2, labelspacing=0.6)
        n_open = int((~curves[1][1].settled).sum())
        foot(ax, f"Up to 100 contracts a leg, held to resolution. Dotted: {n_open} trades not yet\nresolved, valued at their guaranteed floor on the day their market ends.", -0.30)
        out.append(save(fig, fname))
    return out


# ---------------------------------------------------------------- (c): S21 buckets

def s21_figure() -> Path:
    t = pd.read_csv(R / "s21_options_anchor" / "t1_buckets.csv")
    t = t[(t.anchor == "central") & (t.gap_bucket != "every gap")].reset_index(drop=True)
    names = {"below -5": "5 or more\nbelow", "-5 to +0": "0 to 5\nbelow", "+0 to +5": "0 to 5\nabove", "+5 to +10": "5 to 10\nabove", "+10 or more": "10 or more\nabove"}
    assert list(t.gap_bucket) == list(names)
    x = np.arange(len(t))
    fig, ax = plt.subplots(figsize=(W, 2.6))
    ax.bar(x, t.buyers_pnl_points, width=0.62, color=BLUE)
    ax.errorbar(x, t.buyers_pnl_points, yerr=[t.buyers_pnl_points - t.ci_lo, t.ci_hi - t.buyers_pnl_points], fmt="none", ecolor=INK, elinewidth=0.9, capsize=2.5)
    for i, r in t.iterrows():
        ax.annotate(f"{r.buyers_pnl_points:+.1f}", (i, r.ci_lo), xytext=(0, -8), textcoords="offset points", ha="center", fontsize=6.8, color=INK)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(x, [f"{names[b]}\nn = {m}" for b, m in zip(t.gap_bucket, t.markets)])
    ax.tick_params(axis="x", labelsize=6.8)
    ax.grid(axis="x", visible=False)
    ax.set_ylim(min(t.ci_lo) - 7, max(t.ci_hi) + 3)
    ax.set_xlabel("Price paid minus the options reference, points")
    ax.set_ylabel("Buyers' profit, points per contract")
    ax.set_title("Buyers lose most far above the options reference")
    foot(ax, "S21, seen data, exploratory: stock \"will it hit\" tickets on their first weekend.\nBar: mean of n markets. Line: 95% interval, events resampled.", -0.36)
    return save(fig, "s21_buyers_by_gap.png")


# ---------------------------------------------------------------- (d): scoreboard

COLS = ("Passed", "Positive, not\nconfirmed", "Null or\nfailed", "Too few\ntrades")
PASSED, LEAD, NULL, FEW = range(4)
WORD = {"PASS": PASSED, "EQUIVALENT": PASSED, "NULL": NULL, "INSUFFICIENT": FEW, "does not replicate": NULL, "does not hold": NULL,
        "no evidence that the PM adds information beyond the benchmark": NULL}


def verdicts() -> list[tuple[str, int]]:
    """Each test's verdict, read from its committed result files. An unknown verdict word raises (never guessed)."""
    def js(*p):
        return json.loads(R.joinpath(*p).read_text())

    acc = js("fresh_accuracy", "stats.json")
    lad, lad_yc = js("ladder_replay", "summary_all.json")["fresh"], js("ladder_replay", "order_check", "summary_all.json")["fresh"]
    s11 = pd.read_csv(R / "s11_bundles" / "metrics.csv")
    s11 = s11[(s11.study == "violation, exit at gap close or result") & (s11.cost_mult == 1.0) & (s11.entries == "print-verified")].set_index("segment")
    s21 = pd.read_csv(R / "s21_options_anchor" / "improvement.csv").set_index("segment")
    tf = pd.read_csv(R / "touch_fresh" / "markets.csv")
    tf = tf[tf.strict.astype(str).str.lower() == "true"]
    k8 = {(R / "oos" / f"{k}_verdict.txt").read_text().strip() for k in ("hedge", "opportunity")}
    sb = pd.read_csv(R / "strategy_backtest" / "metrics.csv")
    sb = sb[(sb.segment == "OOS") & (sb.book == "primary") & (sb.cost == "1x")]
    card = [ln.split("|")[-2].strip().lower() for ln in (R / "WEEKEND_SCORECARD.md").read_text().splitlines() if ln.startswith("| **S")]
    card_fail = all(any(w in v for w in ("not a pass", "null", "too few", "no trade", "does not replicate")) for v in card)

    def lead_or(ci_lo: float, oos_n: int, need: int) -> int:        # positive on seen data, short of its out-of-sample minimum
        if ci_lo > 0 and oos_n < need:
            return LEAD
        raise ValueError("verdict rule does not apply")

    if len(k8) != 1 or not card or not card_fail or len(sb) != 1 or int(sb.hedge_days.iloc[0]) != 0 or lad_yc["verdict"] != "PASS":
        raise ValueError("a committed verdict changed; update note_figures.verdicts")
    return [
        ("Options beat the Polymarket price (fresh)", WORD[acc["verdict"]]),
        ("Kalshi index prices match options", WORD[acc["h3"]["verdict"]]),
        ("Date ladders, rule as registered", WORD[lad["verdict"]]),
        ("Date ladders, year-checked after the run", LEAD),
        ("Date ladders, seen data (S11)", lead_or(float(s11.loc["IS", "ci_lo"]), int(s11.loc["OOS", "trades"]), 30)),
        ("Tickets above options, seen data (S21)", lead_or(float(s21.loc["ALL", "ci_lo"]), int(s21.loc["OOS", "taken_markets"]), 30)),
        ("Tickets above options, fresh test", FEW if (len(tf) < 30 or tf.event.nunique() < 15) else NULL),
        ("8-K options mispricing", WORD[k8.pop()]),
        ("Overnight move and SPY open, new markets", WORD[js("leadlag_replication", "tests.json")["verdict"]]),
        ("Same, 36 macro markets", WORD[js("macro_panel", "tests.json")["verdict"]]),
        ("Polymarket adds to pre-market SPY", WORD[js("pm_vs_premarket", "tests.json")["verdict"]]),
        ("Trade toward options at reopenings", WORD[js("reopen_taker", "stats.json")["verdict"]]),
        ("Same, all weekdays, fresh 2026", WORD[js("pm_taker_v2", "stats.json")["verdict"]]),
        ("Closed-market overlay on a SPY book", NULL),
        (f"Weekend scorecard, {len(card)} rows", NULL),
    ]


def scoreboard_figure() -> Path:
    v = verdicts()
    n = len(v)
    fig, ax = plt.subplots(figsize=(2.3, 3.1))
    for i, (name, col) in enumerate(v):
        y = n - 1 - i
        ax.axhline(y, color=GRID, lw=0.6, zorder=0)
        ax.plot(col, y, "o", ms=5, color=INK, zorder=3)
    ax.set_yticks(range(n), [name for name, _ in reversed(v)])
    counts = [sum(c == k for _, c in v) for k in range(4)]
    ax.set_xticks(range(4), [f"{COLS[k]}\n({counts[k]})" for k in range(4)])
    ax.xaxis.tick_top()
    ax.tick_params(length=0, labelsize=6.5)
    ax.tick_params(axis="x", labelsize=5.8)
    for lab in ax.get_xticklabels():
        lab.set_va("bottom")
    ax.set_xlim(-0.5, 3.5)
    ax.set_ylim(-0.6, n - 0.4)
    ax.grid(False)
    for k in range(1, 4):
        ax.axvline(k - 0.5, color=GRID, lw=0.6)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.text(-1.05, 1.19, "Every test and its verdict", transform=ax.transAxes, ha="left", va="bottom", fontsize=8.5, fontweight="bold")
    ax.text(-1.05, -0.04, "Verdicts from each study's committed result files, grouped into\nfour kinds. Counts in brackets.", transform=ax.transAxes, fontsize=6.2,
            color=INK2, ha="left", va="top")
    return save(fig, "scoreboard.png")


def main() -> list[Path]:
    return ladder_figures() + [s21_figure(), scoreboard_figure()]


if __name__ == "__main__":
    for p in main():
        print(f"wrote {p}")
    sys.exit(0)
