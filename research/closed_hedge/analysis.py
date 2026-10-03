"""Applies METHOD.md sections 2-5 to a closure panel. No I/O."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import hedge as H
from .config import PARAMS

PAIRS = {  # hedge -> (unhedged, hedged, static) columns
    "A": ("Y0_A", "Y_A", "Y_SA"),
    "B": ("Y0_B", "Y_B", "Y_SB"),
    "B08": ("Y0_B08", "Y_B08", "Y_SB08"),
}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, fit the expanding rate, mark the evaluation sample."""
    d = H.sort_panel(df)
    d = pd.concat([d, H.expanding_rates(d)], axis=1)
    d["excluded"] = np.where(d["rate"].isna(), "no rate yet", "")
    return d


def evaluate(d: pd.DataFrame, hs_pp: float, k_bp: float = PARAMS.k_bp, eq_pre_side_bp: float = PARAMS.eq_cost_bp,
             n_boot: int = PARAMS.n_boot, seed: int = PARAMS.seed, block: int | None = None) -> dict:
    """Variance tests for hedges A, B, B08 on the evaluation rows of a prepared panel."""
    ev = d[d["excluded"] == ""].copy()
    st = H.strategies(ev, hs_pp, k_bp=k_bp, eq_pre_side_bp=eq_pre_side_bp)
    out = {"sizes": dict(st.attrs), "tests": {}, "describe": {}}
    for h, (c0, ch, cs) in PAIRS.items():
        m = st[[c0, ch, cs]].notna().all(axis=1).to_numpy()
        n = int(m.sum())
        idx = (H.block_indices(n, n_boot, block, seed) if block else H.iid_indices(n, n_boot, seed))
        t = H.variance_test(st[c0].to_numpy()[m], st[ch].to_numpy()[m], st[cs].to_numpy()[m], idx)
        t["verdict"] = H.verdict(t)
        out["tests"][h] = t
        y0 = st[c0].to_numpy()[m]
        out["describe"][h] = {"none": H.describe(y0, y0), "hedge": H.describe(st[ch].to_numpy()[m], y0),
                              "static": H.describe(st[cs].to_numpy()[m], y0)}
    out["mean_cost_A_bp"] = float(st["cost_A"].mean())
    out["mean_f_B"] = float(st["f_B"].mean())
    out["share_f_B_pos"] = float((st["f_B"] > 0).mean())
    return out, st


def whole_path(st: pd.DataFrame) -> dict:
    v0 = st["W0"].var(ddof=1)
    return {k: float(1 - st[k].var(ddof=1) / v0) for k in ("W_A", "W_B", "W_AB")} | {"sd0": float(np.sqrt(v0))}


def in_sample_bound(d: pd.DataFrame, hs_pp: float) -> dict:
    """Hedge A with the full-panel per-market slope (look-ahead); VR0 on the evaluation rows."""
    ev = d[d["excluded"] == ""]
    rates = {m: max(H._slope(g["dpm_o_pp"], g["gap_bp"]), 0.0) for m, g in d.groupby("market")}
    r = ev["market"].map(rates).to_numpy(float)
    y = H.hedge_a(ev["gap_bp"], ev["dpm_o_pp"], r, hs_pp)
    return {"rates": rates, "VR0": float(1 - np.var(y, ddof=1) / ev["gap_bp"].var(ddof=1))}


def per_market(d: pd.DataFrame, hs_pp: float, n_boot: int = PARAMS.n_boot, seed: int = PARAMS.seed) -> dict:
    """Hedge A per market; the static size is that market's own mean rate."""
    out = {}
    for m, g in d[d["excluded"] == ""].groupby("market"):
        st = H.strategies(g, hs_pp)
        t = H.variance_test(st["Y0_A"], st["Y_A"], st["Y_SA"], H.iid_indices(len(g), n_boot, seed))
        out[m] = {"n": t["n"], "VR0": t["VR0"], "VR0_lo": t["VR0_lo"], "VR0_hi": t["VR0_hi"], "VRS": t["VRS"],
                  "VRS_lo": t["VRS_lo"], "VRS_hi": t["VRS_hi"], "mean_rate": float(g["rate"].mean())}
    return out


def replication(rep: pd.DataFrame, hs_pp: float, n_boot: int = PARAMS.n_boot, seed: int = PARAMS.seed) -> dict:
    """Section 7: hedge A on the replication panel, cluster bootstrap by closure date."""
    d = H.sort_panel(rep)
    d = pd.concat([d, H.expanding_rates(d)], axis=1)
    ev = d[d["rate"].notna()].reset_index(drop=True)
    st = H.strategies(ev.assign(ret30_bp=np.nan, resid_bp=np.nan, dpm_early_o_pp=np.nan), hs_pp)
    t = H.variance_test(st["Y0_A"], st["Y_A"], st["Y_SA"], H.cluster_indices(ev["closure"], n_boot, seed))
    t["verdict"] = H.verdict(t)
    t["n_rows_total"] = int(len(d))
    t["n_dates"] = int(ev["closure"].nunique())
    t["n_markets"] = int(ev["market"].nunique())
    return t


def concentration(st: pd.DataFrame, h: str, ks=(1, 3, 5)) -> dict:
    """Exploratory (Amendment 1): VR0 and VRS after dropping the k closures that add most to VRS."""
    c0, ch, cs = PAIRS[h]
    e = st[[c0, ch, cs]].dropna()
    v0 = e[c0].var(ddof=1)
    contrib = ((e[cs] - e[cs].mean()) ** 2 - (e[ch] - e[ch].mean()) ** 2) / (len(e) - 1) / v0
    order = contrib.sort_values(ascending=False).index
    out = {"top": [str(st.loc[i, "closure"]) for i in order[:max(ks)]] if "closure" in st else []}
    for k in ks:
        r = e.drop(order[:k])
        out[str(k)] = {"VR0": float(1 - r[ch].var(ddof=1) / r[c0].var(ddof=1)),
                       "VRS": float((r[cs].var(ddof=1) - r[ch].var(ddof=1)) / r[c0].var(ddof=1))}
    return out


def b_timing(ev: pd.DataFrame) -> dict:
    """Exploratory (Amendment 1): post-open sd when hedge B is active vs not, and corr(f_B, ret30)."""
    on = ev["f_B"] > 0
    return {"n_active": int(on.sum()), "sd_active": float(ev.loc[on, "ret30_bp"].std(ddof=1)),
            "sd_inactive": float(ev.loc[~on, "ret30_bp"].std(ddof=1)),
            "mean_active": float(ev.loc[on, "ret30_bp"].mean()), "mean_inactive": float(ev.loc[~on, "ret30_bp"].mean()),
            "corr_f_ret30": float(np.corrcoef(ev["f_B"], ev["ret30_bp"])[0, 1])}
