"""Apply METHOD.md sections 4-5 to a table of closure rows. Pure pandas/numpy, testable on synthetic data.

Input columns: closure, kind, market, news (bool), dpm_o_pp, dpm_early_o_pp, gap_bp, ret30_bp, resid_bp, reason.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PARAMS
from .stats import interaction, pairing_placebo, sign_agreement, slope_test


def usable(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with a PM change and a gap (usability rules 1 and 2)."""
    return df[np.isfinite(df["dpm_o_pp"]) & np.isfinite(df["gap_bp"])]


def _t1(df: pd.DataFrame, y: str, x: str = "dpm_o_pp") -> dict:
    out = {}
    for th in (PARAMS.theta_pp, *PARAMS.theta_sens):
        out[th] = sign_agreement(df[x], df[y], th)
    return out


def _t2(df: pd.DataFrame, y: str, x: str = "dpm_o_pp") -> dict:
    return slope_test(df[x], df[y], PARAMS.n_perm, PARAMS.seed)


def analyse(rows: pd.DataFrame) -> dict:
    """Return every number in METHOD.md sections 4-5 plus the verdict."""
    ev = usable(rows[rows["news"]])
    pl = usable(rows[~rows["news"]])
    res: dict = {"n_events_total": int(rows["news"].sum()), "n_events_usable": len(ev), "n_placebo_total": int((~rows["news"]).sum()),
                 "n_placebo_usable": len(pl)}
    res["t1_events"] = _t1(ev, "gap_bp")
    res["t2_events"] = _t2(ev, "gap_bp")
    res["t3_events_t1"] = _t1(ev[np.isfinite(ev["ret30_bp"])], "ret30_bp")
    res["t3_events_t2"] = _t2(ev[np.isfinite(ev["ret30_bp"])], "ret30_bp")
    e4 = ev[np.isfinite(ev["dpm_early_o_pp"]) & np.isfinite(ev["resid_bp"])]
    res["t4_events_t1"] = sign_agreement(e4["dpm_early_o_pp"], e4["resid_bp"], PARAMS.theta_pp)
    res["t4_events_t2"] = slope_test(e4["dpm_early_o_pp"], e4["resid_bp"], PARAMS.n_perm, PARAMS.seed)
    # gap -> first-30-minute relation (description): reversal vs continuation
    g = ev[np.isfinite(ev["ret30_bp"]) & (ev["gap_bp"] != 0) & (ev["ret30_bp"] != 0)]
    res["gap_vs_ret30"] = {"n": len(g), "continue": int((np.sign(g["gap_bp"]) == np.sign(g["ret30_bp"])).sum())}
    # subsets
    for name, sub in (("overnight", ev[ev["kind"] == "overnight"]), ("weekend_holiday", ev[ev["kind"] != "overnight"])):
        res[f"t1_{name}"] = sign_agreement(sub["dpm_o_pp"], sub["gap_bp"], PARAMS.theta_pp)
        res[f"t2_{name}"] = slope_test(sub["dpm_o_pp"], sub["gap_bp"], PARAMS.n_perm, PARAMS.seed)
    for name, sub in (("election", ev[ev["market"] == "election"]), ("recession", ev[ev["market"] == "recession"])):
        res[f"t1_{name}"] = sign_agreement(sub["dpm_o_pp"], sub["gap_bp"], PARAMS.theta_pp)
    # placebo
    res["p1_t1"] = _t1(pl, "gap_bp")
    res["p1_t2"] = _t2(pl, "gap_bp")
    res["p1_by_panel"] = {m: {"t1": sign_agreement(s["dpm_o_pp"], s["gap_bp"], PARAMS.theta_pp), "n": len(s)}
                          for m, s in pl.groupby("market")}
    pools = {m: s["gap_bp"].to_numpy() for m, s in pl.groupby("market")}
    ok_panels = [m for m in ev["market"].unique() if m in pools and len(pools[m]) >= 5]
    ev_p = ev[ev["market"].isin(ok_panels)]
    res["p2"] = pairing_placebo(ev_p["dpm_o_pp"], ev_p["market"], ev_p["gap_bp"], pools, PARAMS.theta_pp, PARAMS.n_perm, PARAMS.seed)
    both = pd.concat([ev.assign(_n=1.0), pl.assign(_n=0.0)])
    res["p3"] = interaction(both["dpm_o_pp"], both["gap_bp"], both["_n"])
    # closure-type mix
    res["mix_events"] = ev["kind"].value_counts().to_dict()
    res["mix_placebo"] = pl["kind"].value_counts().to_dict()
    res["median_abs_gap_events"] = float(ev["gap_bp"].abs().median()) if len(ev) else float("nan")
    res["median_abs_gap_placebo"] = float(pl["gap_bp"].abs().median()) if len(pl) else float("nan")
    res["verdict"], res["verdict_detail"] = verdict(res)
    return res


def verdict(res: dict) -> tuple[str, dict]:
    """Decision rule of METHOD.md section 4, applied literally."""
    a = PARAMS.alpha
    t1 = res["t1_events"][PARAMS.theta_pp]
    c1 = bool(t1["n"] and t1["p"] < a and t1["rate"] > 0.5)
    t2 = res["t2_events"]
    c2 = bool(np.isfinite(t2["b"]) and t2["b"] > 0 and t2["p_perm"] < a)
    p2 = res["p2"]
    c3 = bool(p2["k_obs"] is not None and p2["p_k"] < a)
    n = c1 + c2 + c3
    label = "supports the closed-market claim" if n == 3 else ("no evidence" if n == 0 else "mixed")
    return label, {"c1_sign_test": c1, "c2_slope_perm": c2, "c3_pairing_placebo": c3}
