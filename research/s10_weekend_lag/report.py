from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as cfg  # noqa: E402
from .run import RESULTS as R  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE, GREEN, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.axhline(0, color=GRID, linewidth=1)
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)


def charts(tr: pd.DataFrame, eq: pd.DataFrame, K: float, oos_from: str) -> None:
    v = cfg.PRIMARY
    e1 = eq[(eq.variant == v) & (eq.cost_mult == 1.0)].sort_values("weekend")
    e2 = eq[(eq.variant == v) & (eq.cost_mult == 2.0)].sort_values("weekend")
    g = tr[(tr.variant == v) & (tr.cost_mult == 1.0)].groupby("weekend").gross_points.sum() * cfg.CONTRACTS / 100.0
    gross = g.reindex(e1.weekend).fillna(0.0).cumsum().to_numpy()
    x = pd.to_datetime(e1.weekend)
    series = (("Before costs", GREEN, gross), ("After costs", BLUE, e1.pnl.to_numpy()), ("After doubled costs", ORANGE, e2.pnl.to_numpy()),
              ("After costs, print-verified entries only", GREY, e1.pnl_verified.to_numpy()))
    for name, dd in (("equity_curve.png", False), ("drawdown.png", True)):
        fig, ax = plt.subplots(figsize=(9.5, 4.4), facecolor=SURFACE)
        _style(ax)
        for label, color, cum in series:
            y = cum / K * 100
            if dd:
                full = np.concatenate([[0.0], y])
                y = (full - np.maximum.accumulate(full))[1:]
            ax.plot(x, y, color=color, linewidth=2, label=label)
            if not dd:
                ax.annotate(f"{y[-1]:+.0f}%", (x.iloc[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
        split = pd.Timestamp(oos_from)
        ax.axvline(split, color=INK2, linewidth=1)
        ax.annotate("out-of-sample starts ▸", (split, 1.0), xycoords=("data", "axes fraction"), xytext=(-5, -4), textcoords="offset points",
                    va="top", ha="right", fontsize=8.5, color=INK2)
        ax.set_ylabel("% of capital base" if not dd else "drawdown, % of capital base", color=INK2, fontsize=9)
        ax.set_title(f"S10 primary (crude, 30-minute exit): {'cumulative P&L' if not dd else 'drawdown from peak'}, capital base ${K:,.0f}",
                     loc="left", fontsize=11, color=INK)
        ax.legend(frameon=False, fontsize=8.5, loc="lower left")
        fig.tight_layout()
        fig.savefig(R / name, dpi=160, facecolor=SURFACE)
        plt.close(fig)


def leadlag_chart(ll: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), facecolor=SURFACE, sharey=True)
    for ax, c in zip(axes, ("crude", "gold")):
        _style(ax)
        for d, color, off in (("event first", BLUE, -0.6), ("price first", ORANGE, 0.6)):
            s = ll[(ll["class"] == c) & (ll.direction == d)].sort_values("horizon_min")
            xs = np.arange(len(s)) * 4 + off
            ax.errorbar(xs, s.slope, yerr=1.96 * s.se, fmt="o", color=color, capsize=3, label=f"{d}: {'event odds' if d == 'event first' else 'price markets'} lead")
        ax.set_xticks(np.arange(len(cfg.HORIZONS_S)) * 4, [f"{h // 60} min" for h in cfg.HORIZONS_S])
        ax.set_title("Crude oil price markets" if c == "crude" else "Gold price markets", loc="left", fontsize=10.5, color=INK)
    axes[0].set_ylabel("slope, points per point (95% interval)", color=INK2, fontsize=9)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(R / "leadlag.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


def capacity(tr: pd.DataFrame, m: pd.DataFrame) -> str:
    p = tr[(tr.variant == cfg.PRIMARY) & (tr.cost_mult == 1.0)]
    ver = p[p.verified]
    row = m[(m.variant == cfg.PRIMARY) & (m.cost_mult == 1.0) & (m.segment == "ALL")].iloc[0]
    return "\n".join([
        "# S10 capacity", "",
        "- **Size at the best price on a weekend:** S9 measured the live books of Sat 2026-10-03 22:13 New York time: crude oil a median "
        "of **$20** at the best price across 7 markets priced 10% to 90% (from $1 to $256), spread 1.0 point. Spring 2026's oil markets "
        "were much larger; their books are not published.",
        f"- **The trade as run:** 100 contracts per market, at most {cfg.MAX_MARKETS_PER_SIGNAL} markets per signal and "
        f"{cfg.MAX_SIGNALS_PER_WEEKEND} signals per weekend; {int(row.trades)} trades on {int(row.weekends_traded)} weekends; "
        f"${p.capital.mean():.0f} of capital per trade on average; capital base ${row.capital_base:,.0f}.",
        f"- **Prints behind the entries:** {len(ver)} of {len(p)} primary entries ({len(ver) / len(p):.0%}) have a public print within five "
        f"minutes after the signal at the assumed price or better, on the side that proves the fill"
        + (f"; median printed size {ver.verify_size.median():.0f} shares." if len(ver) else "."),
        f"- **Stale prices:** {p.flat_mid_15m.mean():.0%} of primary entries are in a market whose one-minute price did not change in the "
        "15 minutes before the entry.",
        "- The trade does not pay after costs, so capacity is not the binding question.", ""])


def main() -> int:
    tr, eq, m = pd.read_csv(R / "trades.csv"), pd.read_csv(R / "equity.csv"), pd.read_csv(R / "metrics.csv")
    ll = pd.read_csv(R / "leadlag.csv")
    meta = json.loads((R / "run_meta.json").read_text())
    K = float(m[(m.variant == cfg.PRIMARY) & (m.cost_mult == 1.0) & (m.segment == "ALL")].capital_base.iloc[0])
    charts(tr, eq, K, meta["oos_from"])
    leadlag_chart(ll)
    if (R / "mechanism" / "slopes.csv").exists():
        mechanism_chart()
    (R / "capacity.md").write_text(capacity(tr, m))
    print("charts and capacity.md written")
    return 0



def mechanism_chart() -> None:
    s = pd.read_csv(R / "mechanism" / "slopes.csv")
    s = s[(s.pairs == "B") & (s.group == "all")]
    fig, ax = plt.subplots(figsize=(9.5, 4.0), facecolor=SURFACE)
    _style(ax)
    lines = (("active->thin", "active", BLUE, "Active market leads, follower active"),
             ("active->thin", "stale", GREY, "Active market leads, follower stale (no change in 15 min)"),
             ("thin->active", "all", ORANGE, "Thin market leads, active follows"))
    for k, (d, f, color, label) in enumerate(lines):
        r = s[(s.direction == d) & (s.follower == f)].sort_values("horizon_min")
        xs = np.arange(len(r)) * 4 + (k - 1) * 0.8
        ax.errorbar(xs, r.slope, yerr=1.96 * r.se, fmt="o", color=color, capsize=3, label=label)
    ax.set_xticks(np.arange(3) * 4, ["next 5 min", "next 15 min", "next 30 min"])
    ax.set_ylabel("follower's move per point of leader's move", color=INK2, fontsize=9)
    ax.set_title("Linked Polymarket questions, 1,301 pairs, 373 days: stale prices do not catch up", loc="left", fontsize=11, color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(R / "mechanism" / "mechanism.png", dpi=160, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
