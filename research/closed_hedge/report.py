"""SUMMARY.md and chart.png for the R1 run. Every number comes from results.json."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
NAMES = {"A": "Hedge A: PM contract over the closure", "B": "Hedge B: equity hedge at the 09:30 open",
         "B08": "Hedge B variant: equity hedge at 08:00 ET"}
WINDOW = {"A": "close to open (the gap)", "B": "09:30 to 10:00 ET", "B08": "08:00 to 10:00 ET"}


def pct(x: float, nd: int = 1) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{100 * x:+.{nd}f}%"


def ci(t: dict, k: str, nd: int = 1) -> str:
    return f"{pct(t[k], nd)} [{pct(t[k + '_lo'], nd)}, {pct(t[k + '_hi'], nd)}]"


def headline(res: dict) -> str:
    t = res["primary"]["tests"]
    a, b = t["A"], t["B"]
    return (f"Over {res['n_eval']} unselected closures, holding the adverse prediction-market contract through the closure "
            f"(hedge A) gave a variance reduction of the open-gap P&L of {pct(a['VR0'], 2)} vs no hedge "
            f"(95% CI {pct(a['VR0_lo'], 2)} to {pct(a['VR0_hi'], 2)}) and {pct(a['VRS'], 2)} vs a static hedge of the same "
            f"average size (CI {pct(a['VRS_lo'], 2)} to {pct(a['VRS_hi'], 2)}): **{a['verdict']}**. The equity hedge staged "
            f"for the 09:30 open (hedge B) gave {pct(b['VR0'], 2)} on the post-open P&L (CI {pct(b['VR0_lo'], 2)} to "
            f"{pct(b['VR0_hi'], 2)}) and {pct(b['VRS'], 2)} vs static (CI {pct(b['VRS_lo'], 2)} to {pct(b['VRS_hi'], 2)}): "
            f"**{b['verdict']}**. Positive = less variance.")


def write_chart(res: dict, d: pd.DataFrame, path: Path) -> None:
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.titlecolor": INK, "axes.titlesize": 10})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.1, 1]})
    t = res["primary"]["tests"]
    keys = ["A", "B", "B08"]
    labels = ["A: PM contract\n(close to open)", "B: equity at 09:30\n(09:30 to 10:00)", "B: equity at 08:00\n(08:00 to 10:00)"]
    y = np.arange(len(keys))[::-1]
    for off, (k, col, lab) in zip((0.14, -0.14), (("VR0", BLUE, "vs no hedge"), ("VRS", ORANGE, "vs static hedge, same size"))):
        v = np.array([100 * t[h][k] for h in keys])
        lo = np.array([100 * t[h][k + "_lo"] for h in keys])
        hi = np.array([100 * t[h][k + "_hi"] for h in keys])
        ax1.errorbar(v, y + off, xerr=[v - lo, hi - v], fmt="o", color=col, ms=8, lw=2, capsize=0, label=lab,
                     markeredgecolor="white", markeredgewidth=2)
    ax1.axvline(0, color=INK2, lw=1)
    ax1.set_yticks(y, labels)
    ax1.set_xlabel("variance reduction, % of unhedged variance (95% bootstrap CI)")
    ax1.set_title("Variance removed by each hedge (positive = less risk)", loc="left")
    ax1.grid(axis="x", color=GRID, lw=0.8)
    ax1.set_axisbelow(True)
    ax1.legend(frameon=False, loc="upper right")
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    ev = d[d["excluded"] == ""].copy()
    ev["t"] = pd.to_datetime(ev["open_day"])
    for m, col in (("election", BLUE), ("recession", ORANGE)):
        g = ev[ev["market"] == m]
        if len(g):
            ax2.plot(g["t"], g["rate"], color=col, lw=2, label=f"{m} market")
    ax2.set_title("Hedge A size: rate fitted on earlier closures only", loc="left")
    ax2.set_ylabel("rate, bp of gap per pp of PM move")
    ax2.grid(axis="y", color=GRID, lw=0.8)
    ax2.set_axisbelow(True)
    ax2.legend(frameon=False)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    for lab in ax2.get_xticklabels():
        lab.set_rotation(30)
        lab.set_ha("right")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def _desc_rows(res_part: dict, h: str) -> list[str]:
    ds = res_part["describe"][h]
    rows = []
    for k, name in (("none", "no hedge"), ("hedge", "hedge"), ("static", "static, same average size")):
        x = ds[k]
        rows.append(f"| {name} | {x['mean']:+.2f} | {x['sd']:.2f} | {x['p5']:+.1f} | {x['worst']:+.1f} | "
                    f"{x['bad_mean']:+.1f} ({x['bad_n']}) |")
    return rows


def write_summary(res: dict, path: Path) -> None:
    p = res["primary"]
    t = p["tests"]
    hs = res["hs"]
    L = []
    L.append("# R1: does closed-market hedging reduce the loss at the open?\n")
    L.append("Rules fixed in [METHOD.md](../../closed_hedge/METHOD.md) and committed before the run "
             "(pre-registered analysis of an already-seen closure panel; the only new data are today's live Polymarket "
             "books for the cost assumption). A long SPY holder at the close; two hedges from the product spec; each "
             "judged on the variance of its P&L against no hedge and against a static hedge of the same average size.\n")
    L.append("## Headline\n")
    L.append("- " + headline(res))
    L.append(f"- Sample: {res['n_eval']} of {res['n_panel']} placebo closures (the first {res['n_panel'] - res['n_eval']} "
             f"have no rate yet: fewer than {res['params']['min_prior']} earlier closures). Rate source: "
             f"{res['rate_src']}.")
    L.append(f"- Pre-set criterion (both bootstrap CIs above 0): hedge A **{t['A']['verdict']}**, hedge B (09:30) "
             f"**{t['B']['verdict']}**; secondary 08:00 variant: **{t['B08']['verdict']}**.")
    L.append(f"- In-sample ceiling (look-ahead, full-panel slope per market {', '.join(f'{k} {v:.2f}' for k, v in res['in_sample']['rates'].items())} bp/pp): "
             f"a PM-sized gap hedge could have removed at most {pct(res['in_sample']['VR0'])} of the gap variance on these closures.")
    L.append(f"- Cost: PM half-spread {hs['hs_pp']:.2f} pp (median of {hs['n']} usable live books out of the "
             f"{hs.get('n_markets')} top markets by lifetime volume; the rest were one-sided or priced outside [2%, 98%]; "
             f"fetched {hs.get('fetched_utc')}{'; FALLBACK value' if hs['fallback'] else ''}). "
             f"Hedge A costs {p['mean_cost_A_bp']:.2f} bp per closure on average; hedge B hedges {100 * p['mean_f_B']:.1f}% of the "
             f"position on average and is active in {100 * p['share_f_B_pos']:.0f}% of closures.")
    L.append(f"- Replication panel: {res['replication_status']}.")
    L.append("\n![chart](chart.png)\n")

    L.append("## Primary tests (METHOD.md section 4)\n")
    L.append("Variance reduction `VR0 = 1 - Var(hedged)/Var(unhedged)`; gain over static `VRS = (Var(static) - Var(hedged))/Var(unhedged)`. "
             "Point estimate [95% iid bootstrap CI, 10,000 paired resamples].\n")
    L.append("| Hedge | Window | n | sd unhedged (bp) | sd hedged (bp) | sd static (bp) | VR0 | VRS | static vs none | verdict |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for h in ("A", "B", "B08"):
        x = t[h]
        L.append(f"| {NAMES[h]} | {WINDOW[h]} | {x['n']} | {x['sd0']:.2f} | {x['sdH']:.2f} | {x['sdS']:.2f} | "
                 f"{ci(x, 'VR0', 2)} | {ci(x, 'VRS', 2)} | {pct(x['VRstatic0'], 2)} | {x['verdict']} |")
    s = p["sizes"]
    L.append(f"\nStatic sizes: hedge A {s['rbar']:.2f} bp/pp (= {s['rbar'] / 100:.4f} adverse contracts per $ of SPY); "
             f"hedge B fraction {s['fbar']:.4f}; 08:00 variant {s['fbar08']:.4f}.\n")

    L.append("## P&L per $ of position (bp)\n")
    for h in ("A", "B", "B08"):
        L.append(f"**{NAMES[h]}** ({WINDOW[h]})\n")
        L.append("| strategy | mean | sd | 5th pct | worst | mean on bad opens (n) |")
        L.append("|---|---|---|---|---|---|")
        L.extend(_desc_rows(p, h))
        L.append("")
    L.append("\"Bad opens\" = closures where the unhedged P&L in that window was worse than -50 bp.\n")

    L.append("## Secondary (METHOD.md section 5; not part of the verdict)\n")
    L.append("**Block bootstrap** (moving blocks of 10 consecutive closures):\n")
    L.append("| Hedge | VR0 | VRS | verdict under block CIs |")
    L.append("|---|---|---|---|")
    from .hedge import verdict
    for h in ("A", "B", "B08"):
        x = res["block"][h]
        L.append(f"| {h} | {ci(x, 'VR0', 2)} | {ci(x, 'VRS', 2)} | {verdict(x)} |")
    L.append("\n**Costs:**\n")
    L.append("| Variant | VR0 | VRS | mean hedged P&L (bp) |")
    L.append("|---|---|---|---|")
    for k, x in res["cost_sens"].items():
        mean = res["cost_sens_desc"].get(k, {}).get("hedge", {}).get("mean")
        L.append(f"| {k} | {ci(x, 'VR0', 2)} | {ci(x, 'VRS', 2)} | {'n/a' if mean is None else f'{mean:+.2f}'} |")
    arb = res.get("arb_half_spread_pp")
    if arb:
        L.append(f"\nThe {res['params']['hs_thin_pp']:.1f} pp case is the median half-spread of thin live equity-threshold books in the arb run "
                 f"({arb:.1f} pp). Hedge A's cost is 2 x hs x rate bp per closure, so at a wide spread it varies with the fitted "
                 "rate from closure to closure: it then adds variance as well as lowering the mean.\n")
    L.append("**Hedge B scale K** (expected loss that hedges the whole position):\n")
    L.append("| K (bp) | B at 09:30 VR0 | VRS | B at 08:00 VR0 | VRS |")
    L.append("|---|---|---|---|---|")
    for k, x in res["k_sens"].items():
        L.append(f"| {float(k):.0f} | {ci(x['B'], 'VR0', 2)} | {ci(x['B'], 'VRS', 2)} | {ci(x['B08'], 'VR0', 2)} | {ci(x['B08'], 'VRS', 2)} |")
    L.append("\n**Hedge A per market** (static size = that market's mean rate):\n")
    L.append("| Market | n | mean rate (bp/pp) | VR0 | VRS |")
    L.append("|---|---|---|---|---|")
    for m, x in res["per_market"].items():
        L.append(f"| {m} | {x['n']} | {x['mean_rate']:.2f} | {ci(x, 'VR0', 2)} | {ci(x, 'VRS', 2)} |")
    w = res["whole_path"]
    L.append(f"\n**Whole path, close to 10:00 ET** (unhedged sd {w['sd0']:.1f} bp): VR0 hedge A alone {pct(w['W_A'], 2)}, "
             f"hedge B alone {pct(w['W_B'], 2)}, A then B (the product's handoff) {pct(w['W_AB'], 2)}.\n")
    a3 = res["all397"]["tests"]
    L.append(f"**All 397 closures** (17 hindsight-selected news closures added; n evaluated {res['all397']['n_eval']}): "
             f"hedge A VR0 {ci(a3['A'], 'VR0', 2)}, VRS {ci(a3['A'], 'VRS', 2)} ({a3['A']['verdict']}); hedge B VR0 "
             f"{ci(a3['B'], 'VR0', 2)}, VRS {ci(a3['B'], 'VRS', 2)} ({a3['B']['verdict']}).\n")
    r = res.get("replication")
    if r:
        L.append(f"**Replication panel** (hedge A only; {r['n']} market x closure rows on {r['n_dates']} dates, "
                 f"{r['n_markets']} markets; bootstrap by closure date): VR0 {ci(r, 'VR0', 2)}, VRS {ci(r, 'VRS', 2)} "
                 f"({r['verdict']}).\n")
    else:
        L.append(f"**Replication panel:** {res['replication_status']}.\n")

    conc = res.get("exploratory", {}).get("concentration", {})
    if conc:
        L.append("**Concentration check, exploratory** (METHOD.md Amendment 1, added after the run): the gain over the "
                 "static hedge after dropping the k closures that contribute most to it.\n")
        L.append("| Hedge | all | drop 1 | drop 3 | drop 5 | top contributors (closure day) |")
        L.append("|---|---|---|---|---|---|")
        for h in ("A", "B", "B08"):
            c = conc.get(h)
            if c:
                L.append(f"| {h} | VRS {pct(t[h]['VRS'], 2)} | {pct(c['1']['VRS'], 2)} | {pct(c['3']['VRS'], 2)} | "
                         f"{pct(c['5']['VRS'], 2)} | {', '.join(c.get('top', []))} |")
        L.append("")

    L.append("## What this means for the product\n")
    a_ok, b_ok = t["A"]["verdict"], t["B"]["verdict"]
    bt = res.get("exploratory", {}).get("b_timing", {})
    L.append(f"- **Hedge A ({a_ok}).** It is the only hedge that can touch the gap itself, because it is on while equities "
             f"are shut. Its ceiling is how much of the gap the PM move explains: {pct(res['in_sample']['VR0'])} with "
             f"hindsight on these closures; the rate fitted without hindsight got {pct(t['A']['VR0'], 2)} "
             f"(CI {pct(t['A']['VR0_lo'], 2)} to {pct(t['A']['VR0_hi'], 2)}). In the app it should be labelled as an estimate with a wide band, never as protection.")
    L.append(f"- **Hedge B at 09:30 ({b_ok}).** It cannot reduce the gap; it changes the risk after the open. Its "
             "measured gain comes from timing, not direction: it is active only after an adverse expected gap "
             f"({bt.get('n_active', 'n/a')} closures), and the first 30 minutes after those closures were more volatile "
             f"(sd {bt.get('sd_active', float('nan')):.1f} bp vs {bt.get('sd_inactive', float('nan')):.1f} bp otherwise) "
             f"while the hedge size did not predict the direction (correlation of size with the 30-minute return "
             f"{bt.get('corr_f_ret30', float('nan')):+.2f}). The concentration check above shows how "
             "much of that rests on a few closures, and the block bootstrap is weaker; treat it as a supporting signal "
             "for staging an order at the first tradable moment, not as a protection against the gap.")
    L.append(f"- **Costs.** At today's top-book spread hedge A costs {p['mean_cost_A_bp']:.2f} bp per closure on "
             f"average; at thin-book spreads ({res['params']['hs_thin_pp']:.1f} pp) it would cost far more than it saves.\n")

    L.append("## Caveats\n")
    L.append("- Pre-registered analysis of data already analysed in the closed-market study; not a fresh sample.")
    L.append("- Two markets, one per period, loosely tied to SPY; rates differ a lot between them.")
    L.append("- PM fills are simulated at mid plus or minus today's median half-spread; historical books are not published, "
             "and a large hedge would walk the book. No financing or capital charge for the cash paid for contracts.")
    L.append("- Closures are not independent; the block bootstrap is the check.")
    L.append("- Hedge B is measured to 10:00 ET only (the first-30-minute horizon of the panel).\n")
    L.append("## Files\n")
    L.append("`closures_hedged.csv` (every closure: inputs, rate, sizes, each strategy's P&L, exclusion reason), "
             "`results.json` (every statistic), `chart.png`, `books_live.json` (the live books behind the spread), "
             "`RUN_LOG.md`. Code in `research/closed_hedge/`, synthetic tests in `research/closed_hedge/tests/`.")
    path.write_text("\n".join(L) + "\n")
