"""results.csv companions: tests.json, chart.png and SUMMARY.md. Every number in SUMMARY.md is generated from `res`."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .analysis import usable  # noqa: E402
from .config import PARAMS, RESULTS_DIR  # noqa: E402

# reference categorical palette (dataviz skill, light mode), slots 1-2; ink and grid recessive
CLS_COLOR = {"geopolitics": "#2a78d6", "US macro/policy": "#eb6834"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _f(x, nd=2, plus=True):
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{x:+.{nd}f}" if plus else f"{x:.{nd}f}"


def _p(x):
    if x is None or not np.isfinite(x):
        return "n/a"
    return "<0.001" if x < 0.001 else f"{x:.3f}"


def _s2(t) -> str:
    if not t["n"]:
        return "no rows pass the threshold"
    return f"{t['k']} of {t['n']} agree ({100 * t['rate']:.0f}%), p = {_p(t['p'])}"


def _s1(t, perm_label="date-permutation p") -> str:
    return f"b = {_f(t['b'])} bp per pp (HC3 t = {_f(t['t'])}, {perm_label} = {_p(t['p_perm'])}, n = {t['n']})"


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def chart(rows: pd.DataFrame, res: dict, path) -> None:
    u = usable(rows)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})
    for cls in ("geopolitics", "US macro/policy"):   # the smaller class drawn last so it stays visible
        sub = u[u["cls"] == cls]
        if sub.empty:
            continue
        a1.scatter(sub["x_pp"], sub["gap_spy_bp"], s=22, color=CLS_COLOR.get(cls, MUTED), alpha=0.75,
                   edgecolor="white", lw=0.6, label=f"{cls} ({sub['market'].nunique()} markets, {len(sub)} rows)")
    s1 = res["s1"]
    if np.isfinite(s1["b"]) and len(u):
        xs = np.linspace(u["x_pp"].min(), u["x_pp"].max(), 50)
        a1.plot(xs, s1["a"] + s1["b"] * xs, color=INK, lw=2, label=f"pooled fit: {_f(s1['b'])} bp per pp")
        xo = np.linspace(max(u["x_pp"].min(), -15), min(u["x_pp"].max(), 15), 50)
        a1.plot(xo, res["original"]["b"] * xo, color=MUTED, lw=1.5, ls="--", label=f"original study: +{res['original']['b']:.2f} bp per pp")
    a1.axhline(0, color=MUTED, lw=0.8)
    a1.axvline(0, color=MUTED, lw=0.8)
    a1.set_xlabel("Oriented PM change over the closure (pp; + = equity-bullish)", fontsize=9, color=INK)
    a1.set_ylabel("SPY opening gap (bp)", fontsize=9, color=INK)
    a1.set_title("Pooled market x closure rows", fontsize=10, color=INK, loc="left")
    a1.legend(fontsize=7.5, frameon=False, loc="upper left")
    _style(a1)
    pm = res["per_market"]
    names = sorted(pm, key=lambda m: pm[m]["rank"] or 0)
    ys = np.arange(len(names))[::-1]
    for y, m in zip(ys, names):
        t = pm[m]["s1"]
        col = CLS_COLOR.get(pm[m]["cls"], MUTED)
        if np.isfinite(t["b"]) and np.isfinite(t["se"]):
            a2.plot([t["b"] - 1.96 * t["se"], t["b"] + 1.96 * t["se"]], [y, y], color=col, lw=2, solid_capstyle="round")
        if np.isfinite(t["b"]):
            a2.scatter([t["b"]], [y], s=64, color=col, edgecolor="white", lw=2, zorder=3)
    a2.axvline(0, color=MUTED, lw=0.8)
    a2.axvline(res["original"]["b"], color=MUTED, lw=1.2, ls="--")
    a2.set_yticks(ys)
    a2.set_yticklabels([f"#{pm[m]['rank']} {m[:38]} (n={pm[m]['s1']['n']})" for m in names], fontsize=7.5, color=INK)
    a2.set_xlabel("Slope, bp of SPY gap per pp (dot; bar = 95% HC3 interval)", fontsize=9, color=INK)
    a2.set_title("Per-market slope (dashed = original +7.52)", fontsize=10, color=INK, loc="left")
    _style(a2)
    lim = np.nanmax([abs(pm[m]["s1"]["b"]) + 1.96 * pm[m]["s1"]["se"] for m in names if np.isfinite(pm[m]["s1"]["se"])] or [20])
    a2.set_xlim(-min(lim, 200), min(lim, 200))
    fig.suptitle(f"Overnight-gap replication on {res['n_markets']} new Polymarket markets: verdict \"{res['verdict']}\"",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def write_summary(rows: pd.DataFrame, res: dict, cov: pd.DataFrame, path) -> None:
    s1, s2, o = res["s1"], res["s2"], res["original"]
    vd = res["verdict_detail"]
    yes = lambda b: "met" if b else "not met"  # noqa: E731
    L = []
    L.append("# Overnight-gap replication: does the closed-market PM move predict the SPY gap on new markets?\n")
    L.append("Confirmatory test of the closed-market finding. The original result: on 380 unselected closures of two markets, the Polymarket "
             f"move while equities were closed went with the SPY opening gap, +{o['b']:.2f} bp per pp, HC3 t +{o['t']:.2f}, permutation "
             f"p {o['p_perm']:.3f}. Market selection, sign rule, measures, tests and the success criterion were fixed in "
             "[METHOD.md](../../leadlag_replication/METHOD.md), committed at `7a780b5` before any price series was fetched. "
             "This is the single run.\n")
    L.append("## Headline\n")
    L.append(f"- **Verdict under the pre-set criterion: {res['verdict']}.** It requires slope > 0 ({yes(vd['slope_positive'])}), "
             f"date-permutation p < 0.05 ({yes(vd['perm_p_below_0.05'])}) and HC3 t > 2 ({yes(vd['hc3_t_above_2'])}).")
    L.append(f"- **Pooled slope (S1):** {_s1(s1)}, R-squared {_f(s1['r2'], 3, False)}. Pooled over {res['n_markets']} markets and "
             f"{s1['n_dates']} distinct closure dates. The original study found +{o['b']:.2f} (t +{o['t']:.2f}, p {o['p_perm']:.3f}, n {o['n_rows']}).")
    L.append(f"- **Sign test at 1 pp (S2):** {_s2(s2)}. The original: {o['k']} of {o['n']} ({100 * o['k'] / o['n']:.0f}%), p {o['p_sign']:.3f}. "
             f"S2 {'agrees with' if res['sign_test_agrees'] else 'does not confirm'} a positive relation (rate above 50% with p < 0.05).")
    c, col = res["cluster"], res["collapsed"]
    L.append(f"- **Dependence checks:** with errors clustered by closure date, t = {_f(c['t'])} ({c['G']} dates). "
             f"With one observation per date (mean oriented PM change across markets), b = {_f(col['b'])}, HC3 t = {_f(col['t'])}, "
             f"permutation p = {_p(col['p_perm'])}, n = {col['n']}.")
    L.append(f"- Rows: {res['n_rows_usable']} usable of {res['n_rows_total']} market x closure rows. Excluded: "
             + (", ".join(f"{k} {v}" for k, v in res["excluded"].items()) or "none") + ".\n")
    L.append("![chart](chart.png)\n")
    L.append("## Markets (selected by the frozen rule)\n")
    L.append("The frozen ranking was walked in order. A market was taken if at least 40 of its closures had a PM quote at both ends (PM data only, "
             "before any equity bar was fetched).\n")
    L.append("| Rank | Market | Class | Sign | Closures | Quoted both ends | Selected |")
    L.append("|---|---|---|---|---|---|---|")
    pm = res["per_market"]
    cls_by = {m: pm[m]["cls"] for m in pm}
    sign_by = {m: pm[m]["sign"] for m in pm}
    for _, r in cov.iterrows():
        L.append(f"| {r['rank']} | `{r['market']}` | {cls_by.get(r['market'], '')} | "
                 f"{'+1' if sign_by.get(r['market']) == 1 else ('-1' if sign_by.get(r['market']) == -1 else '')} | {r['closures']} | "
                 f"{r['pm_both_ends']} | {'yes' if r['qualifies'] else 'no (coverage)'} |")
    L.append("")
    L.append("## Per market (SPY)\n")
    L.append("| Rank | Market | Median PM level (pp) | Rows | Slope (bp/pp) | HC3 t | Date-perm p | Sign test at 1 pp | Slope without this market |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for m in sorted(pm, key=lambda k: pm[k]["rank"] or 0):
        t = pm[m]["s1"]
        L.append(f"| {pm[m]['rank']} | `{m}` | {_f(pm[m]['median_pm'], 1, False)} | {t['n']} | {_f(t['b'])} | {_f(t['t'])} | {_p(t['p_perm'])} | "
                 f"{_s2(pm[m]['s2'])} | {_f(res['loo'].get(m))} |")
    L.append("")
    L.append("## Secondary (not part of the verdict)\n")
    for tk, d in res["secondary_tickers"].items():
        L.append(f"- **{tk} gap:** {_s1(d['s1'])}; sign test {_s2(d['s2'])}.")
    for th, t in res["s2_sens"].items():
        L.append(f"- Sign test at {th} pp: {_s2(t)}.")
    sp = res["s2_date_perm"]
    L.append(f"- Sign test at 1 pp with a one-sided date-permutation p (agreement at least as high): p = {_p(sp['p_perm'])}.")
    rp = res["row_perm"]
    L.append(f"- Row-level permutation of the pooled slope (ignores shared dates): p = {_p(rp['p_perm'])}; Spearman rho {_f(rp['rho'])} (p = {_p(rp['p_rho'])}).")
    for cname, d in res["by_class"].items():
        L.append(f"- **{cname}** ({d['n_markets']} markets): {_s1(d['s1'])}; sign test {_s2(d['s2'])}.")
    for k, d in res["by_kind"].items():
        L.append(f"- {k.replace('_', ' and ')} closures: {_s1(d['s1'])}; sign test {_s2(d['s2'])}.")
    fr = res["fresh"]
    L.append(f"- **Fresh-date subset** (closure dates outside both original panels, so the SPY gap is new too; {fr['n_dates']} dates): "
             f"{_s1(fr['s1'])}; sign test {_s2(fr['s2'])}.")
    L.append("")
    L.append("## How to read this\n")
    L.append(reading(res))
    L.append("")
    L.append("## Caveats\n")
    L.append("- **Futures proxy.** E-mini S&P 500 and Nasdaq futures trade almost around the clock, and SPY trades pre-market. By 09:30 the equity "
             "side has already priced overnight news through futures, which this study does not observe (Massive equity bars only). A PM-gap relation is "
             "co-movement over the closure, both prices reacting to the same news. It is not a tradeable lead: the gap cannot be captured once futures have moved. "
             "A lead claim would need the PM move up to time t against the futures move after t.")
    L.append("- **Same calendar as the original.** Most closure dates lie inside the original panels' date ranges. The PM series are new, but the SPY gaps on "
             "those dates are the numbers the original used. The fresh-date subset is the only part where both are new, and it is small.")
    L.append("- **The rule picks mostly geopolitical markets.** By volume, ceasefire, invasion and military markets dominate the eligible pool. Few are US "
             "macro/policy markets. The original relation came mainly from a US recession market, and Fed markets are excluded because their sign is "
             "ambiguous. A null on this pool would not rule out the relation for US macro markets.")
    L.append("- **Low-probability markets.** Many markets trade at a few percent, so 1 pp moves are rare and the sign test has few rows.")
    L.append("- **Shared dates.** Rows on one date share a gap. The binomial test and HC3 t treat rows as independent and are optimistic. The date "
             "permutation (primary), the date-clustered t and the date-collapsed regression address this.")
    L.append("- **Rule revisions before data.** The selection rule was revised three times after reading candidate question texts (metadata only, "
             "no prices). METHOD.md section 0 lists each revision.\n")
    L.append("## Files\n")
    L.append("`results.csv` (every market x closure row: PM at close and open, oriented change, SPY/QQQ/IWM gaps, flags). "
             "`coverage.csv` (the coverage check for every candidate examined). `tests.json` (every statistic). `chart.png`. `RUN_LOG.md`. "
             "Code: `research/leadlag_replication/`. Synthetic tests: `research/leadlag_replication/tests/`.")
    path.write_text("\n".join(L) + "\n")


def reading(res: dict) -> str:
    s1, s2 = res["s1"], res["s2"]
    v = res["verdict"]
    if v == "replicates":
        head = (f"On {res['n_markets']} markets that the original study never used, chosen by a fixed rule, the PM move during the closure again goes "
                f"with the SPY opening gap ({_f(s1['b'])} bp per pp, date-permutation p = {_p(s1['p_perm'])}). ")
    elif v == "partial":
        head = (f"The slope is positive ({_f(s1['b'])} bp per pp), but only one of the two significance conditions holds "
                f"(date-permutation p = {_p(s1['p_perm'])}, HC3 t = {_f(s1['t'])}). The new markets lean the same way as the original, but the evidence falls short of the pre-set bar. ")
    else:
        head = (f"On these {res['n_markets']} markets the pooled slope is {_f(s1['b'])} bp per pp (date-permutation p = {_p(s1['p_perm'])}, "
                f"HC3 t = {_f(s1['t'])}). The original relation does not carry over to this rule-selected set of mostly geopolitical markets. ")
    col = res["collapsed"]
    if np.isfinite(col["p_perm"]) and col["p_perm"] < PARAMS.alpha and v != "replicates":
        head += (f"One secondary check leans positive: with one observation per closure date, the slope is {_f(col['b'])} with permutation "
                 f"p = {_p(col['p_perm'])} but HC3 t = {_f(col['t'])}. It is outside the pre-set criterion and does not change the verdict. ")
    tail = ("In every case this is co-movement over the closure, not a demonstrated lead (see the futures caveat).")
    return head + tail


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return [_jsonable(v) for v in o.tolist()]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def write_all(rows: pd.DataFrame, res: dict, cov: pd.DataFrame, charts: bool = True, out_dir=None) -> None:
    out = out_dir or RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "tests.json").write_text(json.dumps(_jsonable(res), indent=1))
    if charts:
        chart(rows, res, out / "chart.png")
    write_summary(rows, res, cov, out / "SUMMARY.md")
