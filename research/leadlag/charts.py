from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .detect import Move
from .events import Event
from .xcorr import XCorr

PM_COLOR = "#1f5fd1"
EQ_COLOR = "#c4510a"
INK, MUTED, GRID = "#1f2328", "#6b7280", "#e5e7eb"


def normalise(s: pd.Series) -> pd.Series:
    s = s.dropna()
    if s.empty:
        return s
    d = s - s.iloc[0]
    m = d.abs().max()
    return d / m if m > 0 else d


def _fmt_t(t: pd.Timestamp | None) -> str:
    return "none" if t is None else t.strftime("%H:%M")


def plot_event(ev: Event, frame: pd.DataFrame, ticker: str, pm_move: Move | None, eq_move: Move | None,
               lead: float | None, lead_cls: str, xc: XCorr, out: Path) -> Path:
    win = frame[frame["in_window"]]
    pm_n = normalise(win["pm_lvl"] * ev.expected_sign)
    eq = win["eq_lvl"].where(win["eq_valid"])
    eq_n = normalise(eq)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9.6, 6.6), gridspec_kw={"height_ratios": [3.2, 1.3]}, constrained_layout=True)
    fig.patch.set_facecolor("white")
    for a in (ax, ax2):
        a.set_facecolor("white")
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color("#9ca3af")
        a.tick_params(colors=MUTED, labelsize=9)
        a.grid(True, color=GRID, lw=0.6)
        a.set_axisbelow(True)
    ax.plot(pm_n.index, pm_n.to_numpy(), color=PM_COLOR, lw=1.6, drawstyle="steps-post", label="Prediction market")
    ax.plot(eq_n.index, eq_n.to_numpy(), color=EQ_COLOR, lw=1.6, label=ticker)
    ax.axhline(0, color="#9ca3af", lw=0.8)
    if ev.anchor is not None and win.index.min() <= ev.anchor <= win.index.max():
        ax.axvline(ev.anchor, color=MUTED, lw=1, ls=":", ymax=0.93)
        ax.text(ev.anchor, 1.36, "scheduled " + _fmt_t(ev.anchor) + "Z", color=MUTED, fontsize=8, ha="center", va="bottom")
    ymax = 1.06
    for mv, col, lab, dy in ((pm_move, PM_COLOR, "PM first move", 0.0), (eq_move, EQ_COLOR, f"{ticker} first move", -0.12)):
        if mv is not None:
            ax.axvline(mv.time, color=col, lw=1.2, ls="--")
            ax.text(mv.time, -1.04 + (0.0 if dy == 0 else 0.1), f" {lab} {_fmt_t(mv.time)}Z", color=INK, fontsize=8.5,
                    ha="left", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=col, lw=0.8))
    if pm_move is not None and eq_move is not None:
        ax.annotate("", xy=(eq_move.time, 1.12), xytext=(pm_move.time, 1.12),
                    arrowprops=dict(arrowstyle="<->", color=INK, lw=1))
        mid = pm_move.time + (eq_move.time - pm_move.time) / 2
        word = {"PM first": "PM first", "equity first": "equity first", "simultaneous": "simultaneous"}.get(lead_cls, lead_cls)
        ax.text(mid, 1.15, f"lead {lead:+.0f} min ({word})", ha="center", va="bottom", fontsize=9, color=INK, weight="bold")
    ax.set_ylim(-1.15, 1.5)
    ax.set_ylabel("change since window start\n(each series scaled to max |move| = 1)", color=MUTED, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlim(win.index.min(), win.index.max())
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK, ncol=2, bbox_to_anchor=(1, 1.0))
    sign_word = "up = bullish" if ev.expected_sign == 1 else "oriented so that up = bullish (PM price inverted)"
    ax.set_title(f"{ev.name} ({ev.date})\n{ev.question}", fontsize=11, color=INK, loc="left")
    ax.text(1.0, -0.115, f"UTC. PM {sign_word}. First move = |3-min change| > 4 sigma, persisting 5 min. Positive lead = PM first.",
            transform=ax.transAxes, ha="right", fontsize=7.5, color=MUTED)

    tab = xc.table
    colors = [GRID] * len(tab)
    ax2.bar(tab["lag"], tab["rho"].fillna(0), color="#9ca3af", width=0.8, lw=0)
    if xc.peak_lag is not None:
        pk = tab.index[tab["lag"] == xc.peak_lag][0]
        ax2.bar([xc.peak_lag], [tab["rho"].iloc[pk]], color=PM_COLOR if xc.peak_lag > 0 else EQ_COLOR, width=0.8, lw=0)
        ax2.annotate(f"peak lag {xc.peak_lag:+d} min, rho {xc.peak_rho:+.2f}", xy=(xc.peak_lag, tab["rho"].iloc[pk]),
                     xytext=(0.99, 0.92), textcoords="axes fraction", ha="right", va="top", fontsize=8.5, color=INK)
        band = 2 / np.sqrt(xc.n)
        ax2.axhspan(-band, band, color=GRID, alpha=0.7, lw=0, zorder=0)
    ax2.axvline(0, color="#9ca3af", lw=0.8)
    ax2.set_xlabel("lag in minutes (positive = prediction market leads equity)", color=MUTED, fontsize=9)
    ax2.set_ylabel("correlation of\n1-min changes", color=MUTED, fontsize=9)
    ax2.set_xlim(-31, 31)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out
