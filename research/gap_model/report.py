from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import PARAMS  # noqa: E402

BLUE, ORANGE, GREY, INK = "#0072B2", "#D55E00", "#9AA0A6", "#222222"
COLOR = {"recession": BLUE, "election": ORANGE}
LABEL = {"recession": "US recession 2025 (Yes = bearish)", "election": "Trump 2024 election (Yes = bullish)"}


def _f(x, nd=1, plus=False):
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{x:+.{nd}f}" if plus else f"{x:.{nd}f}"


def _p(x):
    if x is None or not np.isfinite(x):
        return "n/a"
    return "<0.001" if x < 0.001 else f"{x:.3f}"


def _pe(x):
    s = _p(x)
    return f"p {s[0]} {s[1:]}" if s.startswith("<") else f"p = {s}"


def _pct(r):
    return "n/a" if r is None or not np.isfinite(r) else f"{100 * r:.1f}%"


def g1s(g):
    return f"{g['k']} of {g['n']} ({_pct(g['rate'])}), binomial {_pe(g['p'])}" if g["n"] else "n/a (no rows)"


def g2s(g):
    return (f"{_f(g['c'], 2, True)} (HC3 t {_f(g['t'], 2, True)}, permutation {_pe(g['p_perm'])}, "
            f"R² {_f(g['r2'], 3)}, n {g['n']})")


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GREY)
    ax.tick_params(colors=INK, labelsize=8)
    ax.grid(True, color="#E6E6E6", lw=0.6)
    ax.set_axisbelow(True)


def chart(pred: pd.DataFrame, res: dict, path: Path) -> None:
    pr = pred[(pred["set"] == "A_placebo") & (pred["etf"] == "SPY")]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), dpi=150, gridspec_kw={"width_ratios": [1.15, 1]})
    for m in ("election", "recession"):
        s = pr[pr["market"] == m]
        ax1.scatter(s["pred_bp"], s["gap_bp"], s=14, color=COLOR[m], alpha=0.6, lw=0.5, edgecolor="white",
                    label=f"{LABEL[m]}, n {len(s)}")
    g2 = res["primary"]["SPY"]["g2"]
    if np.isfinite(g2["c"]):
        xs = np.linspace(pr["pred_bp"].min(), pr["pred_bp"].max(), 50)
        ax1.plot(xs, g2["a"] + g2["c"] * xs, color=INK, lw=2, label=f"fit: slope {g2['c']:+.2f}")
        ax1.plot(xs, xs, color=GREY, lw=1, ls="--", label="perfect calibration (slope 1)")
    cal = pd.DataFrame(res["calibration"])
    cal = cal[cal["n"] > 0]
    ax1.scatter(cal["mean_pred_bp"], cal["mean_realized_bp"], marker="D", s=46, color="white", edgecolor=INK, lw=1.5,
                zorder=5, label="bucket mean")
    ax1.axhline(0, color=GREY, lw=0.8)
    ax1.axvline(0, color=GREY, lw=0.8)
    ax1.set_xlabel("Predicted SPY open gap, out of sample (bp)", fontsize=9, color=INK)
    ax1.set_ylabel("Realized SPY open gap (bp)", fontsize=9, color=INK)
    ax1.set_title("Predicted vs realized gap (380-closure panel)", fontsize=10, color=INK, loc="left")
    ax1.legend(fontsize=7, frameon=False, loc="upper left")
    _style(ax1)

    for m in ("election", "recession"):
        s = pr[pr["market"] == m].copy()
        s["d"] = pd.to_datetime(s["closure"])
        own = s["source"] == "own"
        ax2.plot(s["d"], s["rate"], color=COLOR[m], lw=2, label=LABEL[m])
        ax2.fill_between(s["d"], s["rate"] - 1.96 * s["se_eff"], s["rate"] + 1.96 * s["se_eff"], color=COLOR[m],
                         alpha=0.15, lw=0)
        if (~own).any():
            ax2.plot(s.loc[~own, "d"], s.loc[~own, "rate"], color=COLOR[m], lw=0, marker="o", ms=3, mfc="white",
                     label=f"{m}: pooled fallback")
    ax2.axhline(0, color=GREY, lw=0.8)
    ax2.set_ylabel("Rate used for the prediction (bp per pp)", fontsize=9, color=INK)
    ax2.set_title("Expanding-window rate (±1.96 effective SE)", fontsize=10, color=INK, loc="left")
    ax2.legend(fontsize=7, frameon=False)
    _style(ax2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _cal_table(rows) -> list[str]:
    out = ["| Predicted gap (bp) | n | Mean predicted | Mean realized | Median realized | Sign hit rate (n) |",
           "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {r['bucket']} | {r['n']} | {_f(r['mean_pred_bp'], 1, True)} | {_f(r['mean_realized_bp'], 1, True)} | "
                   f"{_f(r['median_realized_bp'], 1, True)} | {_pct(r['hit_rate'])} ({r['n_hit_eligible']}) |")
    return out


def _split_table(d: dict, label: str) -> list[str]:
    out = [f"| {label} | Test n | Sign accuracy | Slope (HC3 t, perm p) | Verdict rule |", "|---|---:|---|---|---|"]
    for k, r in d.items():
        out.append(f"| {k} | {r['n_test']} | {g1s(r['g1'])} | {_f(r['g2']['c'], 2, True)} "
                   f"({_f(r['g2']['t'], 2, True)}, {_p(r['g2']['p_perm'])}) | {r['verdict']} |")
    return out


def write_summary(res: dict, info: dict, path: Path) -> None:
    p = res["primary"]["SPY"]
    q = res["primary"]["QQQ"]
    g1, g2 = p["g1"], p["g2"]
    ex = res["export"]
    L = ["# Expected-gap model: out-of-sample accuracy (R2)", "",
         "Pre-registered in `research/gap_model/METHOD.md` (committed before any statistic was computed). "
         "Generated by `python -m gap_model.run` from saved closure tables; no data was fetched.", "",
         "## Bottom line", "",
         f"**Verdict (pre-set rule): {p['verdict']}.** Fitting each market's rate only on closures that ended before the "
         f"test closure began, the predicted SPY open gap had the right sign in {g1s(g1)}. The slope of realized on "
         f"predicted gap was {g2s(g2)}.", "",
         f"- Criterion (i), sign accuracy > 50% with p < 0.05: **{'met' if g1['n'] and g1['rate'] > 0.5 and g1['p'] < PARAMS.alpha else 'not met'}**.",
         f"- Criterion (ii), slope > 0 with permutation p < 0.05: **{'met' if np.isfinite(g2['c']) and g2['c'] > 0 and g2['p_perm'] < PARAMS.alpha else 'not met'}**.",
         f"- Calibration: a perfectly calibrated model has slope 1; HC3 t of (slope − 1) = {_f(g2['t_c_minus_1'], 2, True)}.",
         f"- Error size: out-of-sample R² vs a zero forecast {_f(p['oos_r2_zero'], 3, True)}, vs the expanding mean gap "
         f"{_f(p['oos_r2_mean'], 3, True)}. Most of the open gap is not explained by the PM move; the expected gap is a "
         f"direction-and-size hint with a wide band, not a point forecast.",
         f"- Nominal 80% band: realized gap inside the band in {_pct(p['band']['all']['coverage'])} of "
         f"{p['band']['all']['n']} test closures (own rate {_pct(p['band']['own']['coverage'])}, n {p['band']['own']['n']}; "
         f"pooled fallback {_pct(p['band']['pooled']['coverage'])}, n {p['band']['pooled']['n']}).",
         "- Where the skill comes from (same tests, per subset; not in the verdict): "
         + "; ".join(f"{k}: sign {_pct(r['g1']['rate'])} of {r['g1']['n']} ({_pe(r['g1']['p'])}), slope "
                     f"{_f(r['g2']['c'], 2, True)} (permutation {_pe(r['g2']['p_perm'])}) -> {r['verdict'].lower()}"
                     for k, r in {**{f"{m} market": v for m, v in p['by_market'].items()},
                                  **{f"{s} rate": v for s, v in p['by_source'].items()}}.items()) + "."]
    if res.get("panel_b"):
        b = res["panel_b"]
        n_pass = sum(r["verdict"] == "Accurate out of sample" for r in b["by_market"].values())
        L += [f"- **Replication panel ({b['n_markets']} new rule-selected markets): {b['verdict'].lower()}** — sign "
              f"{_pct(b['g1']['rate'])} of {b['g1']['n']} ({_pe(b['g1']['p'])}), slope {_f(b['g2']['c'], 2, True)} "
              f"(date permutation {_pe(b['g2']['p_perm'])}); {n_pass} of {b['n_markets']} markets pass the rule on their own."]
    pl = ex["pooled"]
    L += [f"- Product reading: the pooled rate over all {pl['n_markets']} markets is {_f(pl['rate_bp_per_pp'], 2, True)} bp/pp "
          f"(SE {_f(pl['se'], 2)}) with a between-market SD of {_f(ex['tau_bp_per_pp'], 2)} bp/pp"
          + (", so for a market without its own rate the rate band spans both signs."
             if ex["tau_bp_per_pp"] is not None and ex["tau_bp_per_pp"] > abs(pl["rate_bp_per_pp"]) else ".")
          + f" The expected gap is informative only where a market's own rate is "
          f"well determined; the UI must show the band and the closure count.", "",
          "## Design", ""]
    L += [
         f"- Panel: the 380 unselected closures of `leadlag_closed` (Trump 2024 market, 149 closures; US recession 2025 "
         f"market, 231). Rate = least squares through the origin (bp of SPY gap per pp of oriented PM move), HC3 SE.",
         f"- Expanding window: a closure's training set is every closure whose open was on or before its close day. "
         f"Per-market rate once the market has ≥ {PARAMS.n_min} non-zero-move training closures; pooled rate before that; "
         f"no prediction until the pooled set has {PARAMS.n_min} (burn-in).",
         f"- Test closures: {p['n_test']} (rate source: {', '.join(f'{k} {v}' for k, v in p['sources'].items())}).", "",
         "## Primary result (SPY, the mapped ETF of both markets)", "",
         f"- G1 sign accuracy (pred ≠ 0, gap ≠ 0): {g1s(g1)}.",
         f"- G2 slope of realized on predicted: {g2s(g2)}.",
         f"- G1 at |PM move| ≥ {PARAMS.theta_pp:g} pp: {g1s(p['g1_theta'])}.", "",
         "### Calibration by predicted-gap bucket", "", *_cal_table(res["calibration"]), "",
         "### By market and by rate source", "", *_split_table(p["by_market"], "Market"), "",
         *_split_table(p["by_source"], "Rate source"), "",
         "## Secondary", "",
         f"- **QQQ** (rates refitted on QQQ gaps): sign {g1s(q['g1'])}; slope {g2s(q['g2'])}; rule would read: {q['verdict']}.",
         f"- **All 397 closures** (17 hand-picked news closures added back): sign {g1s(res['all397']['g1'])}; slope "
         f"{g2s(res['all397']['g2'])}; rule would read: {res['all397']['verdict']}.",
         ]
    if res.get("panel_b"):
        b = res["panel_b"]
        L += [f"- **Replication panel** ({b['n_markets']} rule-selected markets, own rates from their own closures, pooled "
              f"fallback over panels A and B, slope permutation over closure dates): sign {g1s(b['g1'])}; slope {g2s(b['g2'])}; "
              f"rule would read: {b['verdict']}. Band coverage {_pct(b['band']['all']['coverage'])}.", "",
              *_split_table(b["by_market"], "Replication market"), ""]
    else:
        L += ["- **Replication panel:** not available at run time (`research/results/leadlag_replication/results.csv` did "
              "not exist), so it is not in this run and not in the product export.", ""]
    L += ["## Product export (`backend/app/data/gap_rates.json`)", "",
          f"Full-sample rates (no holdout), {ex['sample']}.", "",
          "| Market | Use | Rate (bp/pp) | SE | n | n with move |", "|---|---|---:|---:|---:|---:|"]
    for k, v in ex["markets"].items():
        L.append(f"| `{k}` | {v['use']} | {_f(v['rate_bp_per_pp'], 2, True)} | {_f(v['se'], 2)} | {v['n']} | {v['n_nonzero']} |")
    pl = ex["pooled"]
    L += [f"| pooled | fallback | {_f(pl['rate_bp_per_pp'], 2, True)} | {_f(pl['se'], 2)} | {pl['n']} | {pl['n_nonzero']} |", "",
          f"Between-market SD of rates (tau, widens the pooled-fallback band): {_f(ex['tau_bp_per_pp'], 2)} bp/pp.", "",
          "## Caveats", "",
          "- **Known panel.** The full-sample relation on this panel (+7.52 bp/pp with intercept) was known before this "
          "test was designed. The expanding window never uses future closures, but the model form was chosen knowing it.",
          "- **Two markets, two regimes.** The recession market's first closures are predicted with the election market's "
          "rate (a different market in a different year), which is exactly the product's situation for a new market.",
          "- **Co-movement, not lead.** The PM move and the gap span the same closure; futures and pre-market SPY are not "
          "observed. An accurate expected gap does not mean the gap is capturable.",
          "- **Serial dependence.** Consecutive closures of one market are not independent; binomial and HC3 inference "
          "are somewhat optimistic. The permutation p is the primary slope inference.",
          "- **Many zero moves.** Closures with no PM move get a predicted gap of 0 and are outside the sign test.", ""]
    path.write_text("\n".join(L))


def write_all(pred: pd.DataFrame, res: dict, info: dict, out_dir: Path) -> None:
    pred.to_csv(out_dir / "predictions.csv", index=False)
    (out_dir / "tests.json").write_text(json.dumps(jsonable(res), indent=1) + "\n")
    chart(pred, res, out_dir / "chart.png")
    write_summary(res, info, out_dir / "SUMMARY.md")


def append_run_log(out_dir: Path, entry: str) -> None:
    path = out_dir / "RUN_LOG.md"
    if not path.exists():
        path.write_text("# Expected-gap OOS run log\n\nOne entry per run of `python -m gap_model.run`: code commit, wall "
                        "time, network requests, exit status.\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)
