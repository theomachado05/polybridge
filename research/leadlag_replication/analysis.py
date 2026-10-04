from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PARAMS
from .stats import cluster_t, collapse_by_date, date_perm_sign, date_perm_slope, sign_agreement, slope_test

ORIGINAL = {"b": 7.52, "t": 2.58, "p_perm": 0.001, "k": 89, "n": 149, "p_sign": 0.021, "n_rows": 380}


def usable(df: pd.DataFrame, y: str = "gap_spy_bp") -> pd.DataFrame:
    return df[np.isfinite(df["x_pp"].astype(float)) & np.isfinite(df[y].astype(float))]


def _s1(df: pd.DataFrame, y: str, n_perm: int | None = None) -> dict:
    return date_perm_slope(df["x_pp"], df[y], df["closure"], n_perm or PARAMS.n_perm, PARAMS.seed)


def _s2(df: pd.DataFrame, y: str, theta: float | None = None) -> dict:
    return sign_agreement(df["x_pp"], df[y], PARAMS.theta_pp if theta is None else theta)


def verdict(s1: dict) -> tuple[str, dict]:
    pos = bool(np.isfinite(s1["b"]) and s1["b"] > 0)
    c_perm = bool(np.isfinite(s1["p_perm"]) and s1["p_perm"] < PARAMS.alpha)
    c_t = bool(np.isfinite(s1["t"]) and s1["t"] > PARAMS.t_min)
    if pos and c_perm and c_t:
        label = "replicates"
    elif pos and (c_perm or c_t):
        label = "partial"
    else:
        label = "does not replicate"
    return label, {"slope_positive": pos, "perm_p_below_0.05": c_perm, "hc3_t_above_2": c_t}


def analyse(rows: pd.DataFrame, secondary: tuple[str, ...] = ("QQQ", "IWM"), n_perm_secondary: int | None = None) -> dict:
    y = "gap_spy_bp"
    u = usable(rows, y)
    res: dict = {"n_rows_total": len(rows), "n_rows_usable": len(u), "n_markets": int(rows["market"].nunique()),
                 "n_dates_usable": int(u["closure"].nunique()),
                 "excluded": rows.loc[rows["reason"].astype(str) != "", "reason"].value_counts().to_dict()}
    res["s1"] = _s1(u, y)
    res["s2"] = _s2(u, y)
    res["verdict"], res["verdict_detail"] = verdict(res["s1"])
    s2 = res["s2"]
    res["sign_test_agrees"] = bool(s2["n"] and s2["rate"] > 0.5 and s2["p"] < PARAMS.alpha)
    nps = n_perm_secondary or PARAMS.n_perm
    res["s2_sens"] = {th: _s2(u, y, th) for th in PARAMS.theta_sens}
    res["s2_date_perm"] = date_perm_sign(u["x_pp"], u[y], u["closure"], PARAMS.theta_pp, nps, PARAMS.seed)
    res["cluster"] = cluster_t(u["x_pp"], u[y], u["closure"])
    res["row_perm"] = slope_test(u["x_pp"], u[y], nps, PARAMS.seed)
    if len(u):
        cx, cy = collapse_by_date(u["x_pp"], u[y], u["closure"])
        res["collapsed"] = slope_test(cx, cy, nps, PARAMS.seed)
    else:
        res["collapsed"] = slope_test([], [], nps, PARAMS.seed)
    res["secondary_tickers"] = {}
    for t in secondary:
        col = f"gap_{t.lower()}_bp"
        if col in rows:
            us = usable(rows, col)
            res["secondary_tickers"][t] = {"s1": _s1(us, col, nps), "s2": _s2(us, col)}
    res["per_market"] = {}
    for m, sub in u.groupby("market", sort=False):
        res["per_market"][m] = {"cls": sub["cls"].iloc[0], "rank": int(sub["rank"].iloc[0]) if "rank" in sub else None,
                                "sign": int(sub["sign"].iloc[0]) if "sign" in sub else None,
                                "s1": date_perm_slope(sub["x_pp"], sub[y], sub["closure"], nps, PARAMS.seed),
                                "s2": _s2(sub, y), "median_pm": float(np.nanmedian(sub["pm_close"])) if "pm_close" in sub else float("nan")}
    res["loo"] = {}
    for m in u["market"].unique():
        sub = u[u["market"] != m]
        res["loo"][m] = date_perm_slope(sub["x_pp"], sub[y], sub["closure"], 0, PARAMS.seed)["b"]
    res["by_class"] = {c: {"s1": _s1(sub, y, nps), "s2": _s2(sub, y), "n_markets": int(sub["market"].nunique())}
                       for c, sub in u.groupby("cls")}
    res["by_kind"] = {}
    for name, sub in (("overnight", u[u["kind"] == "overnight"]), ("weekend_holiday", u[u["kind"] != "overnight"])):
        res["by_kind"][name] = {"s1": _s1(sub, y, nps), "s2": _s2(sub, y)}
    fresh = u[u["fresh_date"].astype(bool)]
    res["fresh"] = {"s1": _s1(fresh, y, nps), "s2": _s2(fresh, y), "n_dates": int(fresh["closure"].nunique())}
    res["original"] = ORIGINAL
    return res
