"""Closed-market evidence for the scored notebook, rebuilt from the COMMITTED result files only.

No network, no API key. Every statistic is recomputed from the committed CSVs with the same functions, parameters and
seeds the studies used, then checked against the committed JSON. Sources:

- results/leadlag_closed       380-closure panel (placebo arm of the closed-market study; exploratory re-read)
- results/leadlag_replication  10 rule-selected new markets (pre-registered replication)
- results/gap_model            R2 expected-gap model, walk-forward per market
- results/closed_hedge         R1 closed-market hedge (hedge A: PM contract; hedge B: staged equity order at 09:30)
- results/open_options         R3 options catch-up at the Monday open

The study packages' stats modules are numpy-only and never fetch data; they are imported here so the rules are the
studies' own, not a re-implementation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from closed_hedge import hedge as H  # noqa: E402
from closed_hedge.config import PARAMS as HEDGE_PARAMS  # noqa: E402
from gap_model.model import sign_accuracy as gap_sign, slope_test as gap_slope  # noqa: E402
from leadlag_closed.config import PARAMS as CLOSED_PARAMS  # noqa: E402
from leadlag_closed.stats import sign_agreement, slope_test  # noqa: E402
from leadlag_replication.analysis import verdict as replication_verdict  # noqa: E402
from leadlag_replication.config import PARAMS as REP_PARAMS  # noqa: E402
from leadlag_replication.stats import date_perm_slope  # noqa: E402
from open_options.stats import cluster_bootstrap, mean_ci  # noqa: E402

FILES = {
    "closures": "leadlag_closed/closures_all.csv",
    "closed_tests": "leadlag_closed/tests.json",
    "replication": "leadlag_replication/results.csv",
    "replication_tests": "leadlag_replication/tests.json",
    "gap_pred": "gap_model/predictions.csv",
    "gap_tests": "gap_model/tests.json",
    "hedge": "closed_hedge/closures_hedged.csv",
    "hedge_tests": "closed_hedge/results.json",
    "options": "open_options/events.csv",
    "options_tests": "open_options/stats.json",
}


def load(results_dir: Path | str = RESULTS) -> dict:
    """Read the committed CSV and JSON outputs. Raises FileNotFoundError naming any missing file."""
    root = Path(results_dir)
    missing = [p for p in FILES.values() if not (root / p).exists()]
    if missing:
        raise FileNotFoundError(f"committed result files missing under {root}: {missing}")
    out = {}
    for k, p in FILES.items():
        f = root / p
        out[k] = json.loads(f.read_text()) if f.suffix == ".json" else pd.read_csv(f, low_memory=False)
    return out


def _gap_eval(pr: pd.DataFrame, n_perm: int, groups: str | None = None) -> dict:
    g1 = gap_sign(pr["pred_bp"], pr["gap_bp"])
    g2 = gap_slope(pr["pred_bp"], pr["gap_bp"], n_perm=n_perm, groups=None if groups is None else pr[groups].to_numpy())
    ok = bool(g1["n"] and g1["rate"] > 0.5 and g1["p"] < 0.05 and np.isfinite(g2["c"]) and g2["c"] > 0 and g2["p_perm"] < 0.05)
    return {"g1": g1, "g2": g2, "verdict": "Accurate out of sample" if ok else "Not accurate out of sample"}


def recompute(data: dict, n_perm: int = 10_000, n_boot: int = 10_000) -> dict:
    """Headline statistics of the five studies, recomputed from the CSVs (defaults = the studies' own draw counts)."""
    res: dict = {}

    # 1. 380-closure panel: closures with no flagged news, slope with HC3 t and a permutation p, sign test at 1 pp
    c = data["closures"]
    news = c["news"].astype(str).str.lower().eq("true")
    pl = c[~news]
    pl = pl[np.isfinite(pl["dpm_o_pp"]) & np.isfinite(pl["gap_bp"])]
    res["panel380"] = {"slope": slope_test(pl["dpm_o_pp"], pl["gap_bp"], n_perm, CLOSED_PARAMS.seed),
                       "sign": sign_agreement(pl["dpm_o_pp"], pl["gap_bp"], CLOSED_PARAMS.theta_pp),
                       "by_market": {m: sign_agreement(s["dpm_o_pp"], s["gap_bp"], CLOSED_PARAMS.theta_pp)
                                     for m, s in pl.groupby("market")}}

    # 2. replication: pooled slope, HC3 t, date-permutation p (one shuffle of the date -> gap map for all markets)
    r = data["replication"]
    r = r[np.isfinite(r["x_pp"].astype(float)) & np.isfinite(r["gap_spy_bp"].astype(float))]
    s1 = date_perm_slope(r["x_pp"], r["gap_spy_bp"], r["closure"], n_perm, REP_PARAMS.seed)
    res["replication"] = {"slope": s1, "sign": sign_agreement(r["x_pp"], r["gap_spy_bp"], REP_PARAMS.theta_pp),
                          "verdict": replication_verdict(s1)[0]}

    # 3. R2: walk-forward predictions; sign accuracy and slope of realized on predicted, per market and pooled
    p = data["gap_pred"]
    a = p[(p["set"] == "A_placebo") & (p["etf"] == "SPY")]
    res["r2"] = {"pooled": _gap_eval(a, n_perm),
                 "by_market": {m: _gap_eval(s, n_perm) for m, s in a.groupby("market")},
                 "replication_panel": _gap_eval(p[p["set"] == "B_replication"], n_perm, groups="closure")}

    # 4. R1: variance tests on the 09:30-10:00 P&L of a long SPY holder (iid bootstrap = the rule; block = check)
    h = data["hedge"]
    ev = h[h["excluded"].fillna("").astype(str) == ""]
    r1 = {}
    for name, (c0, ch, cs) in {"A": ("Y0_A", "Y_A", "Y_SA"), "B": ("Y0_B", "Y_B", "Y_SB")}.items():
        m = ev[[c0, ch, cs]].notna().all(axis=1).to_numpy()
        y0, yh, ys = (ev[col].to_numpy(float)[m] for col in (c0, ch, cs))
        t = H.variance_test(y0, yh, ys, H.iid_indices(int(m.sum()), n_boot, HEDGE_PARAMS.seed))
        t["verdict"] = H.verdict(t)
        tb = H.variance_test(y0, yh, ys, H.block_indices(int(m.sum()), n_boot, HEDGE_PARAMS.block_len, HEDGE_PARAMS.seed))
        t["block"] = {k: tb[k] for k in ("VR0_lo", "VR0_hi", "VRS_lo", "VRS_hi")} | {"verdict": H.verdict(tb)}
        r1[name] = t
    res["r1"] = r1

    # 5. R3: catch-up slope and net residual gap, cluster bootstrap over closures
    o = data["options"]
    o = o[o["status"] == "event"]
    cb = cluster_bootstrap(o["d_pm"], o["d_opt"], o["G"], o["closure"], draws=n_boot)
    net = mean_ci(o["G_net"], o["closure"], draws=n_boot)
    res["r3"] = {"n": cb["n"], "clusters": cb["clusters"], "beta": cb["beta"], "beta_ci": cb["beta_ci"],
                 "g": {"mean": cb["mean"], "mean_ci": cb["mean_ci"]}, "g_net": net,
                 "verdict": "PASS" if net["mean_ci"][0] > 0 else "NULL"}
    return res


def comparison(rec: dict, data: dict) -> pd.DataFrame:
    """Recomputed value next to the committed JSON value for every headline number."""
    ct, rt, gt, ht, ot = (data[k] for k in ("closed_tests", "replication_tests", "gap_tests", "hedge_tests", "options_tests"))
    g = gt["primary"]["SPY"]
    rows = [
        ("380 panel", "slope (bp per pp)", rec["panel380"]["slope"]["b"], ct["p1_t2"]["b"]),
        ("380 panel", "HC3 t", rec["panel380"]["slope"]["t"], ct["p1_t2"]["t"]),
        ("380 panel", "permutation p", rec["panel380"]["slope"]["p_perm"], ct["p1_t2"]["p_perm"]),
        ("380 panel", "sign agree at 1 pp (k)", rec["panel380"]["sign"]["k"], ct["p1_t1"]["1.0"]["k"]),
        ("replication", "pooled slope (bp per pp)", rec["replication"]["slope"]["b"], rt["s1"]["b"]),
        ("replication", "HC3 t", rec["replication"]["slope"]["t"], rt["s1"]["t"]),
        ("replication", "date-permutation p", rec["replication"]["slope"]["p_perm"], rt["s1"]["p_perm"]),
        ("R2", "pooled sign right (k)", rec["r2"]["pooled"]["g1"]["k"], g["g1"]["k"]),
        ("R2", "pooled slope", rec["r2"]["pooled"]["g2"]["c"], g["g2"]["c"]),
        ("R2", "pooled permutation p", rec["r2"]["pooled"]["g2"]["p_perm"], g["g2"]["p_perm"]),
        ("R2", "recession sign right (k)", rec["r2"]["by_market"]["recession"]["g1"]["k"], g["by_market"]["recession"]["g1"]["k"]),
        ("R2", "replication panel slope", rec["r2"]["replication_panel"]["g2"]["c"], gt["panel_b"]["g2"]["c"]),
        ("R1", "hedge B VR0", rec["r1"]["B"]["VR0"], ht["primary"]["tests"]["B"]["VR0"]),
        ("R1", "hedge B VR0 CI low", rec["r1"]["B"]["VR0_lo"], ht["primary"]["tests"]["B"]["VR0_lo"]),
        ("R1", "hedge B VRS", rec["r1"]["B"]["VRS"], ht["primary"]["tests"]["B"]["VRS"]),
        ("R1", "hedge B VRS CI low", rec["r1"]["B"]["VRS_lo"], ht["primary"]["tests"]["B"]["VRS_lo"]),
        ("R1", "hedge B VRS CI low, block", rec["r1"]["B"]["block"]["VRS_lo"], ht["block"]["B"]["VRS_lo"]),
        ("R1", "hedge A VR0", rec["r1"]["A"]["VR0"], ht["primary"]["tests"]["A"]["VR0"]),
        ("R3", "catch-up slope", rec["r3"]["beta"], ot["primary"]["beta"]),
        ("R3", "catch-up slope CI low", rec["r3"]["beta_ci"][0], ot["primary"]["beta_ci"][0]),
        ("R3", "net residual gap (prob.)", rec["r3"]["g_net"]["mean"], ot["primary"]["g_net"]["mean"]),
        ("R3", "net residual gap CI low", rec["r3"]["g_net"]["mean_ci"][0], ot["primary"]["g_net"]["mean_ci"][0]),
    ]
    df = pd.DataFrame(rows, columns=["study", "statistic", "recomputed", "committed"])
    df["match"] = np.isclose(df["recomputed"].astype(float), df["committed"].astype(float), rtol=1e-9, atol=1e-12)
    return df


def _ci_pct(lo, hi):
    return f"[{lo * 100:+.2f}, {hi * 100:+.2f}]"


def _p(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def summary(rec: dict) -> pd.DataFrame:
    """One row per finding: what was tested, on what data, the kind of evidence, the numbers, the verdict and its scope."""
    p3, rp, r2, r1, r3 = rec["panel380"], rec["replication"], rec["r2"], rec["r1"], rec["r3"]
    s, sg = p3["slope"], p3["sign"]
    bm = p3["by_market"]
    rs = rp["slope"]
    pooled, rec_m, ele, rpan = r2["pooled"], r2["by_market"]["recession"], r2["by_market"]["election"], r2["replication_panel"]
    a, b = r1["A"], r1["B"]
    rows = [
        ("380-closure relation: PM move over the closure vs next SPY opening gap",
         "380 unselected closures, 2 markets (already seen)",
         "exploratory (re-read of the placebo arm; the study's pre-set verdict was 'mixed')",
         f"slope {s['b']:+.2f} bp per pp, HC3 t {s['t']:+.2f}, permutation p {_p(s['p_perm'])}; "
         f"same sign {sg['k']} of {sg['n']} at 1 pp (p {_p(sg['p'])})",
         "co-movement, not replicated",
         f"same-window co-movement, not a lead; carried by the recession market ({bm['recession']['k']} of {bm['recession']['n']}; "
         f"election {bm['election']['k']} of {bm['election']['n']}); futures not observed"),
        ("Replication of that relation",
         "new PM series, 10 rule-selected markets", "confirmatory (pre-registered, new data)",
         f"pooled slope {rs['b']:+.2f} bp per pp, HC3 t {rs['t']:+.2f}, date-permutation p {_p(rs['p_perm'])}, n {rs['n']}",
         rp["verdict"], "markets mostly geopolitical, so a null does not rule out US macro markets"),
        ("R2 expected-gap model, walk-forward per market",
         "already-seen 380 panel; replication panel secondary", "pre-registered analysis of a known panel (not confirmatory)",
         f"pooled sign right {pooled['g1']['k']} of {pooled['g1']['n']} (p {_p(pooled['g1']['p'])}), slope {pooled['g2']['c']:+.2f} "
         f"(permutation p {_p(pooled['g2']['p_perm'])}); recession {rec_m['g1']['k']} of {rec_m['g1']['n']}; "
         f"election {ele['g1']['k']} of {ele['g1']['n']} (p {_p(ele['g1']['p'])}); replication panel "
         f"{rpan['g1']['k']} of {rpan['g1']['n']}, slope {rpan['g2']['c']:+.2f}",
         f"pooled: {pooled['verdict'].lower()}; recession: {rec_m['verdict'].lower()}; election: {ele['verdict'].lower()}; "
         f"replication panel: {rpan['verdict'].lower()}",
         "one market (US recession); this is why PolyBridge gates each market on its own out-of-sample result"),
        ("R1 hedge B: equity hedge staged for 09:30",
         "already-seen 380 panel (346 evaluated)", "pre-registered analysis of a known panel (not confirmatory)",
         f"variance cut vs no hedge {b['VR0'] * 100:+.2f}% {_ci_pct(b['VR0_lo'], b['VR0_hi'])}; vs static same size "
         f"{b['VRS'] * 100:+.2f}% {_ci_pct(b['VRS_lo'], b['VRS_hi'])}; block bootstrap vs static "
         f"{_ci_pct(b['block']['VRS_lo'], b['block']['VRS_hi'])}",
         f"{b['verdict']} (fragile: {b['block']['verdict']} under block bootstrap)",
         "post-open risk 09:30 to 10:00 ET only; works by timing, not direction; does not reduce the gap"),
        ("R1 hedge A: hold the adverse PM contract over the closure",
         "already-seen 380 panel (346 evaluated)", "pre-registered analysis of a known panel (not confirmatory)",
         f"variance cut vs no hedge {a['VR0'] * 100:+.2f}% {_ci_pct(a['VR0_lo'], a['VR0_hi'])}; vs static "
         f"{a['VRS'] * 100:+.2f}% {_ci_pct(a['VRS_lo'], a['VRS_hi'])}",
         a["verdict"], "opt-in in the product and labelled an unvalidated estimate"),
        ("R3 options catch-up at the Monday open",
         f"new: {r3['n']:,} events over {r3['clusters']} closures reopening 2025-10-01 to 2026-09-28",
         "confirmatory (pre-registered, new data)",
         f"catch-up slope {r3['beta']:.2f} [{r3['beta_ci'][0]:.2f}, {r3['beta_ci'][1]:.2f}]; net residual gap "
         f"{r3['g_net']['mean'] * 100:+.2f} pt [{r3['g_net']['mean_ci'][0] * 100:+.2f}, {r3['g_net']['mean_ci'][1] * 100:+.2f}] "
         f"(before costs {r3['g']['mean'] * 100:+.2f} pt)",
         r3["verdict"], "the 0.44 slope is the reported measure, not the pass test; after costs no tradable gap"),
    ]
    return pd.DataFrame(rows, columns=["finding", "data", "evidence type", "numbers", "verdict", "scope"])


def chart(data: dict, rec: dict, ax=None, xlim: float = 15.0, ylim: float = 250.0):
    """Small multiples, shared axes: PM move vs SPY opening gap on the 380 panel (left) and the replication (right)."""
    import matplotlib.pyplot as plt

    c = data["closures"]
    pl = c[~c["news"].astype(str).str.lower().eq("true")]
    r = data["replication"]
    panels = [("Original panel: 380 closures, 2 markets", pl["dpm_o_pp"], pl["gap_bp"], rec["panel380"]["slope"], "#2a78d6"),
              ("Replication: 1,211 rows, 10 new markets", r["x_pp"], r["gap_spy_bp"], rec["replication"]["slope"], "#eb6834")]
    if ax is None:
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.4), sharex=True, sharey=True)
    else:
        fig = ax[0].figure
    for a, (title, x, y, st, colr) in zip(ax, panels):
        x, y = np.asarray(x, float), np.asarray(y, float)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        clipped = int(((np.abs(x) > xlim) | (np.abs(y) > ylim)).sum())
        a.scatter(np.clip(x, -xlim, xlim), np.clip(y, -ylim, ylim), s=14, color=colr, alpha=0.35, edgecolors="none")
        xs = np.linspace(max(x.min(), -xlim), min(x.max(), xlim), 50)  # fit drawn over the data range only
        intercept = float(np.mean(y) - st["b"] * np.mean(x))
        a.plot(xs, intercept + st["b"] * xs, color="#222222", lw=2)
        a.axhline(0, color="#999999", lw=0.6)
        a.axvline(0, color="#999999", lw=0.6)
        a.set_title(title, fontsize=10, loc="left")
        a.text(0.02, 0.96, f"slope {st['b']:+.2f} bp per pp, permutation p {_p(st['p_perm'])}\n"
                           f"{clipped} points beyond the axes drawn at the edge (fit uses all)",
               transform=a.transAxes, va="top", fontsize=8, color="#333333")
        a.set_xlabel("PM move over the closure (pp, oriented equity-bullish)")
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
    ax[0].set_ylabel("Next SPY opening gap (bp)")
    a.set_xlim(-xlim, xlim)
    a.set_ylim(-ylim, ylim)
    fig.suptitle("PM move over the closure vs next SPY opening gap: exploratory on 2 markets (left), not replicated on 10 new markets (right)",
                 fontsize=11)
    fig.tight_layout()
    return fig
