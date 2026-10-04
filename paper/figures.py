from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "research" / "results"
OUT = Path(__file__).resolve().parent / "fig"
OUT.mkdir(exist_ok=True)

INK = "#111111"
ACCENT = "#0E6E6A"
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["STIXGeneral", "Times New Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 11,
    "axes.labelsize": 11,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 11,
    "axes.linewidth": 0.6,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.major.size": 3,
    "ytick.major.size": 3,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "lines.linewidth": 1.2,
    "legend.frameon": False,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
})
RNG = np.random.default_rng(20261004)


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def fig_reliability():
    r = pd.read_csv(RES / "fresh_accuracy" / "rows.csv", low_memory=False)
    s = r[r.status == "scored"]
    edges = np.linspace(0, 1, 11)
    fig, ax = plt.subplots(figsize=(3.6, 2.6))
    ax.plot([0, 1], [0, 1], color=INK, lw=0.6, ls=(0, (3, 3)))
    for col, color, marker, label, dx in (("p_mid", INK, "o", "Options", -0.008), ("pm_mid", ACCENT, "s", "Polymarket", 0.008)):
        b = np.clip(np.digitize(s[col], edges) - 1, 0, 9)
        g = s.groupby(b)
        x = g[col].mean().to_numpy()
        n = g.size().to_numpy()
        k = g["outcome"].sum().to_numpy()
        lo, hi = wilson(k, n)
        y = k / n
        ax.errorbar(x + dx, y, yerr=[y - lo, hi - y], color=color, marker=marker, ms=3.6, lw=1.0, elinewidth=0.7,
                    capsize=0, mfc=color if marker == "o" else "white", mew=0.9, label=label)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks(np.linspace(0, 1, 6))
    ax.set_yticks(np.linspace(0, 1, 6))
    ax.set_xlabel("Forecast probability")
    ax.set_ylabel("Share that resolved YES")
    ax.legend(loc="upper left", handlelength=1.4)
    fig.savefig(OUT / "reliability.pdf")
    plt.close(fig)


def fig_ladder():
    reg = pd.read_csv(RES / "ladder_replay" / "trades_fresh.csv").sort_values("t_entry")
    fix = pd.read_csv(RES / "ladder_replay" / "order_check" / "trades_fresh.csv").sort_values("t_entry")
    fig, ax = plt.subplots(figsize=(6.3, 2.3))
    for df, color, label in ((fix, INK, "Dates read correctly"), (reg, ACCENT, "Rule as registered")):
        t = pd.to_datetime(df.t_entry, unit="s")
        ax.step(t, df.pnl_usd.cumsum(), where="post", color=color, lw=1.1, label=label)
    ax.axvline(pd.Timestamp("2026-07-22"), color=INK, lw=0.6, ls=(0, (3, 3)))
    ax.axhline(0, color=INK, lw=0.5)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_ylabel("Cumulative net P&L ($)")
    ax.legend(loc="upper left", handlelength=1.6)
    fig.savefig(OUT / "ladder.pdf")
    plt.close(fig)


def boot_ci(x, groups, n=5000):
    keys = np.unique(groups)
    idx = {k: np.flatnonzero(groups == k) for k in keys}
    means = []
    for _ in range(n):
        pick = RNG.choice(keys, size=len(keys), replace=True)
        rows = np.concatenate([idx[k] for k in pick])
        means.append(x[rows].mean())
    return np.percentile(means, [2.5, 97.5])


def fig_touch():
    b = pd.read_csv(RES / "s21_options_anchor" / "t1_buckets.csv")
    b = b[(b.anchor == "central") & (b.gap_bucket != "every gap")]
    order = ["below -5", "-5 to +0", "+0 to +5", "+5 to +10", "+10 or more"]
    b = b.set_index("gap_bucket").loc[order]
    xs = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(4.2, 2.9))
    ax.axhline(0, color=INK, lw=0.5)
    y = -b.buyers_pnl_points.to_numpy()
    lo, hi = -b.ci_hi.to_numpy(), -b.ci_lo.to_numpy()
    ax.errorbar(xs - 0.1, y, yerr=[y - lo, hi - y], fmt="o", color=INK, ms=3.8, elinewidth=0.8, capsize=0, label="Earlier sample")
    m = pd.read_csv(RES / "touch_fresh" / "markets.csv")
    m = m[m.sell_pnl.notna() & m.gap.notna()]
    cuts = [-np.inf, -5, 0, 5, 10, np.inf]
    m["bucket"] = pd.cut(m.gap, cuts, right=False, labels=order)
    fy, flo, fhi, fx = [], [], [], []
    for i, lab in enumerate(order):
        g = m[m.bucket == lab]
        if g.event.nunique() < 3:
            continue
        fx.append(i + 0.1)
        fy.append(g.sell_pnl.mean())
        c = boot_ci(g.sell_pnl.to_numpy(), g.event.to_numpy())
        flo.append(c[0])
        fhi.append(c[1])
    fy, flo, fhi = map(np.array, (fy, flo, fhi))
    ax.errorbar(fx, fy, yerr=[fy - flo, fhi - fy], fmt="s", color=ACCENT, mfc="white", mew=0.9, ms=3.8, elinewidth=0.8,
                capsize=0, label="Fresh sample")
    ax.set_xticks(xs)
    ax.set_xticklabels(["< −5", "−5 to 0", "0 to 5", "5 to 10", "≥ 10"])
    ax.set_xlabel("Ticket price minus options reference (cents)")
    ax.set_ylabel("Seller P&L per contract (cents)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, handlelength=1.0)
    fig.savefig(OUT / "touch.pdf")
    plt.close(fig)


SEARCH = [
    ("Options vs Polymarket accuracy (Brier)", 0.0108, 0.0064, 0.0158, "pass"),
    ("Ladders, fresh, as registered", 2.47, -1.14, 6.26, "fail"),
    ("Ladders, fresh, dates corrected", 8.82, 6.73, 11.13, "post"),
    ("Touch tickets, fresh secondary", -15.38, -48.82, 21.82, "fail"),
    ("8-K H1, in sample, 21 sessions", 0.0007, -0.0270, 0.0291, "fail"),
    ("8-K H2, in sample, 21 sessions", 0.0009, -0.0068, 0.0089, "fail"),
    ("8-K H2, out of sample, 21 sessions", -0.0215, -0.0759, 0.0203, "fail"),
    ("Overnight PM move, US macro panel", 0.81, -0.14, 1.76, "fail"),
    ("PM beyond pre-market SPY, 08:00", -0.60, -2.64, 1.44, "fail"),
    ("PM beyond pre-market SPY, 09:25", 0.17, -0.23, 0.57, "fail"),
    ("Options catch-up at reopening, net", 0.79, -1.21, 2.78, "fail"),
    ("Staged 09:30 hedge vs static (seen panel)", 6.82, 0.50, 13.54, "post"),
    ("PM contract hedge, variance cut", 4.76, -0.80, 10.01, "fail"),
    ("Reopening taker at printed prices", -0.40, -4.68, 3.74, "fail"),
    ("Options-anchored taker, Apr to Aug", 29.79, 13.01, 44.58, "fail"),
    ("S1 twin spread, out of sample", 6.44, 4.92, 8.83, "fail"),
    ("S4 linked assets, out of sample", -47.1, -93.3, -7.4, "fail"),
    ("S5 big moves, in sample", -13.1, -53.3, 25.1, "fail"),
    ("S7 weekend straddles, in sample", -18.0, -21.0, -15.0, "fail"),
    ("S8 fade moves the open does not confirm, out of sample", -3.16, -5.28, -1.60, "fail"),
    ("S9 weekend price markets, out of sample", -3.77, -7.56, 1.87, "fail"),
    ("S10 weekend lag, in sample", -2.60, -2.80, -2.39, "fail"),
    ("S12 resting orders, out of sample", -8.07, -11.24, -5.36, "fail"),
    ("S15 weekend rises, out of sample", -1.92, -10.08, 6.05, "fail"),
    ("S16 Kalshi quotes, out of sample", -12.28, -15.43, -9.36, "fail"),
    ("S18 first-weekend sellers, out of sample", -0.99, -10.96, 9.28, "fail"),
    ("S19 crypto replication, out of sample", 2.84, -3.08, 7.80, "fail"),
    ("S21 options anchor, in sample", 22.27, 10.35, 33.14, "post"),
    ("S22 quoting outside the band", 24.51, 8.57, 37.52, "fail"),
    ("S23 Monday fade at printed prices", 9.77, 1.37, 20.29, "post"),
]


def fig_search():
    rows = [(n, e / ((h - l) / 3.92), k) for n, e, l, h, k in SEARCH]
    rows.sort(key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(5.3, 0.24 * len(rows) + 0.7))
    for lim in (-1.96, 1.96):
        ax.axvline(lim, color=INK, lw=0.6, ls=(0, (3, 3)))
    ax.axvline(0, color=INK, lw=0.5)
    for i, (n, z, k) in enumerate(rows):
        if k == "pass":
            ax.plot(z, i, "o", color=ACCENT, ms=5)
        elif k == "post":
            ax.plot(z, i, "o", color=INK, mfc="white", mew=0.9, ms=4.5)
        else:
            ax.plot(z, i, "o", color=INK, ms=4)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("Estimate divided by its standard error")
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    fig.savefig(OUT / "search.pdf")
    plt.close(fig)


if __name__ == "__main__":
    fig_reliability()
    fig_ladder()
    fig_touch()
    fig_search()


SUBSETS = [
    ("All contracts", 0.0108, 0.0064, 0.0158, True),
    ("Clustered by stock and date", 0.0108, 0.0082, 0.0133, False),
    ("First snapshot of the day", 0.0119, 0.0064, 0.0183, False),
    ("Second snapshot of the day", 0.0089, 0.0044, 0.0143, False),
    ("Contracts that resolve next day", 0.0107, 0.0068, 0.0155, False),
    ("Contracts that resolve that week", 0.0108, 0.0035, 0.0194, False),
    ("Latest fifth of dates", 0.0139, 0.0056, 0.0264, False),
    ("Without the five most influential dates", 0.0064, 0.0035, 0.0092, False),
    ("Both forecasts between 2% and 98%", 0.0077, 0.0038, 0.0126, False),
    ("No recent Polymarket trade", 0.0120, 0.0072, 0.0176, False),
    ("A Polymarket trade had printed", 0.0034, 0.0004, 0.0069, False),
    ("Polymarket price at most 30 s old", 0.0012, -0.0015, 0.0052, False),
    ("Polymarket price under 30 s old", 0.0002, -0.0019, 0.0032, False),
]


def fig_subsets():
    rows = SUBSETS[::-1]
    fig, ax = plt.subplots(figsize=(5.0, 5.4))
    ax.axvline(0, color=INK, lw=0.6, ls=(0, (3, 3)))
    for i, (name, est, lo, hi, primary) in enumerate(rows):
        color = ACCENT if primary else INK
        ax.plot([lo, hi], [i, i], color=color, lw=1.2, solid_capstyle="butt")
        ax.plot(est, i, "o", color=color, ms=4.5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("Polymarket Brier score minus options Brier score")
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    fig.savefig(OUT / "subsets.pdf")
    plt.close(fig)


fig_subsets()
