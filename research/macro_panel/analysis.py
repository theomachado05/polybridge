from __future__ import annotations

import numpy as np
import pandas as pd

from leadlag_replication.stats import cluster_t, collapse_by_date, date_perm_sign, date_perm_slope, sign_agreement, slope_test

from .config import PARAMS

ORIGINAL = {"b": 7.52, "p_perm": 0.001, "n_rows": 380}
REPLICATION = {"b": 0.63, "p_perm": 0.126, "cluster_t": 1.09, "n_rows": 1211}


def usable(df: pd.DataFrame, y: str = "gap_spy_bp") -> pd.DataFrame:
    return df[np.isfinite(df["x_pp"].astype(float)) & np.isfinite(df[y].astype(float))]


def cluster_ols(y, X, groups) -> dict:
    y, X, groups = np.asarray(y, float), np.asarray(X, float), np.asarray(groups)
    n, k = X.shape
    uniq, inv = np.unique(groups, return_inverse=True)
    G = len(uniq)
    if n <= k or G < 3:
        return {"n": n, "G": G, "beta": np.full(k, np.nan), "se": np.full(k, np.nan)}
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    S = np.zeros((G, k))
    np.add.at(S, inv, X * e[:, None])
    c = G / (G - 1) * (n - 1) / (n - k)
    cov = c * XtX_inv @ (S.T @ S) @ XtX_inv
    return {"n": n, "G": G, "beta": beta, "se": np.sqrt(np.clip(np.diag(cov), 0, None))}


def primary(u: pd.DataFrame, n_perm: int | None = None) -> dict:
    s = date_perm_slope(u["x_pp"], u["gap_spy_bp"], u["closure"], PARAMS.n_perm if n_perm is None else n_perm, PARAMS.seed)
    c = cluster_t(u["x_pp"], u["gap_spy_bp"], u["closure"])
    z = PARAMS.z_ci
    return {**s, "hc3_t": s["t"], "cluster_t": c["t"], "cluster_se": c["se"], "G": c["G"],
            "ci": [s["b"] - z * c["se"], s["b"] + z * c["se"]] if np.isfinite(c["se"]) else [float("nan")] * 2}


def verdict(p: dict) -> tuple[str, dict]:
    pos = bool(np.isfinite(p["b"]) and p["b"] > 0)
    c_perm = bool(np.isfinite(p["p_perm"]) and p["p_perm"] < PARAMS.alpha)
    c_t = bool(np.isfinite(p["cluster_t"]) and p["cluster_t"] > PARAMS.t_min)
    if pos and c_perm and c_t:
        label = "holds"
    elif pos and (c_perm or c_t):
        label = "partial"
    else:
        label = "does not hold"
    return label, {"slope_positive": pos, "perm_p_below_0.05": c_perm, "cluster_t_above_2": c_t}


def contrast(macro: pd.DataFrame, geo: pd.DataFrame) -> dict:
    m = usable(macro)[["x_pp", "gap_spy_bp", "closure"]].assign(macro=1.0)
    g = usable(geo)[["x_pp", "gap_spy_bp", "closure"]].assign(macro=0.0)
    df = pd.concat([m, g], ignore_index=True)
    out = {"n_macro": len(m), "n_geo": len(g)}
    if len(m) < 4 or len(g) < 4:
        return {**out, "d": float("nan"), "se": float("nan"), "ci": [float("nan")] * 2, "label": "not computable"}
    x, mac = df["x_pp"].to_numpy(float), df["macro"].to_numpy(float)
    X = np.column_stack([np.ones(len(df)), mac, x, x * mac])
    f = cluster_ols(df["gap_spy_bp"], X, df["closure"])
    d, se = float(f["beta"][3]), float(f["se"][3])
    lo, hi = d - PARAMS.z_ci * se, d + PARAMS.z_ci * se
    label = "macro slope larger" if lo > 0 else "macro slope smaller" if hi < 0 else "no difference shown"
    return {**out, "G": f["G"], "b_geo": float(f["beta"][2]), "b_macro": float(f["beta"][2] + f["beta"][3]),
            "d": d, "se": se, "t": d / se if se > 0 else float("nan"), "ci": [lo, hi], "label": label}


def analyse(rows: pd.DataFrame, geo: pd.DataFrame | None = None, n_perm_secondary: int | None = None) -> dict:
    u = usable(rows)
    nps = n_perm_secondary or PARAMS.n_perm
    res: dict = {"n_rows_total": len(rows), "n_rows_usable": len(u), "n_markets": int(rows["market"].nunique()),
                 "n_markets_usable": int(u["market"].nunique()), "n_dates_usable": int(u["closure"].nunique()),
                 "excluded": rows.loc[rows["reason"].astype(str) != "", "reason"].value_counts().to_dict()}
    res["primary"] = primary(u)
    res["verdict"], res["verdict_detail"] = verdict(res["primary"])
    res["contrast"] = contrast(rows, geo) if geo is not None else None
    if len(u):
        cx, cy = collapse_by_date(u["x_pp"], u["gap_spy_bp"], u["closure"])
        res["collapsed"] = slope_test(cx, cy, nps, PARAMS.seed)
    else:
        res["collapsed"] = slope_test([], [], nps, PARAMS.seed)
    res["s2"] = sign_agreement(u["x_pp"], u["gap_spy_bp"], PARAMS.theta_pp)
    res["s2_date_perm"] = date_perm_sign(u["x_pp"], u["gap_spy_bp"], u["closure"], PARAMS.theta_pp, nps, PARAMS.seed)
    res["by_class"] = {c: {**primary(sub, nps), "n_markets": int(sub["market"].nunique())} for c, sub in u.groupby("cls")}
    res["loo_class"] = {c: primary(u[u["cls"] != c], 0)["b"] for c in u["cls"].unique()}
    res["per_market"] = {m: {"cls": sub["cls"].iloc[0], "rank": int(sub["rank"].iloc[0]), "sign": int(sub["sign"].iloc[0]),
                             **{k: v for k, v in primary(sub, 0).items() if k in ("b", "n", "cluster_t")}}
                         for m, sub in u.groupby("market", sort=False)}
    fresh = u[u["fresh_date"].astype(bool)]
    res["fresh"] = {**primary(fresh, nps), "n_dates": int(fresh["closure"].nunique())}
    res["by_kind"] = {"overnight": primary(u[u["kind"] == "overnight"], nps),
                      "weekend_holiday": primary(u[u["kind"] != "overnight"], nps)}
    res["original"], res["replication"] = ORIGINAL, REPLICATION
    return res
