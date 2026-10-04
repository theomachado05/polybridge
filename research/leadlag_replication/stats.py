from __future__ import annotations

import numpy as np

from leadlag_closed.stats import THETA_TOL, binom_two_sided, ols_hc3, sign_agreement, slope_test  # noqa: F401


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    xc = x - x.mean()
    d = float((xc ** 2).sum())
    return float((xc * (y - y.mean())).sum() / d) if d > 0 else float("nan")


def _clean(x, y, dates):
    x, y, dates = np.asarray(x, float), np.asarray(y, float), np.asarray(dates)
    m = np.isfinite(x) & np.isfinite(y)
    return x[m], y[m], dates[m]


def date_gap_index(y: np.ndarray, dates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    uniq, inv = np.unique(dates, return_inverse=True)
    g = np.full(len(uniq), np.nan)
    for i, v in zip(inv, y):
        if np.isnan(g[i]):
            g[i] = v
        elif abs(g[i] - v) > 1e-9:
            raise ValueError("rows on the same closure date carry different gaps")
    return g, inv


def date_perm_slope(x, y, dates, n_perm: int, seed: int) -> dict:
    x, y, dates = _clean(x, y, dates)
    n = len(x)
    out = {"n": n, "n_dates": int(len(np.unique(dates))) if n else 0}
    if n < 4 or np.ptp(x) == 0:
        return {**out, "b": float("nan"), "t": float("nan"), "se": float("nan"), "r2": float("nan"), "p_perm": float("nan")}
    fit = ols_hc3(y, np.column_stack([np.ones(n), x]))
    g, inv = date_gap_index(y, dates)
    rng = np.random.default_rng(seed)
    b_obs = abs(_slope(x, y))
    xc = x - x.mean()
    d = float((xc ** 2).sum())
    cnt = 0
    for _ in range(n_perm):
        yp = rng.permutation(g)[inv]
        cnt += abs(float((xc * (yp - yp.mean())).sum() / d)) >= b_obs - 1e-12
    return {**out, "b": float(fit["beta"][1]), "a": float(fit["beta"][0]), "t": float(fit["t"][1]),
            "se": float(fit["se"][1]), "r2": fit["r2"], "p_perm": (cnt + 1) / (n_perm + 1)}


def date_perm_sign(x, y, dates, theta: float, n_perm: int, seed: int) -> dict:
    x, y, dates = _clean(x, y, dates)
    base = sign_agreement(x, y, theta)
    if base["n"] == 0:
        return {**base, "p_perm": float("nan")}
    g, inv = date_gap_index(y, dates)
    m = np.abs(x) >= theta - THETA_TOL
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(n_perm):
        yp = rng.permutation(g)[inv]
        ok = m & (yp != 0)
        cnt += int((np.sign(x[ok]) == np.sign(yp[ok])).sum()) / max(int(ok.sum()), 1) >= base["rate"] - 1e-12
    return {**base, "p_perm": (cnt + 1) / (n_perm + 1)}


def cluster_t(x, y, dates) -> dict:
    x, y, dates = _clean(x, y, dates)
    n = len(x)
    uniq, inv = np.unique(dates, return_inverse=True)
    G = len(uniq)
    if n < 4 or G < 3 or np.ptp(x) == 0:
        return {"n": n, "G": G, "b": float("nan"), "t": float("nan"), "se": float("nan")}
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    S = np.zeros((G, 2))
    np.add.at(S, inv, X * e[:, None])
    meat = S.T @ S
    c = G / (G - 1) * (n - 1) / (n - 2)
    cov = c * XtX_inv @ meat @ XtX_inv
    se = float(np.sqrt(max(cov[1, 1], 0)))
    return {"n": n, "G": G, "b": float(beta[1]), "se": se, "t": float(beta[1] / se) if se > 0 else float("nan")}


def collapse_by_date(x, y, dates) -> tuple[np.ndarray, np.ndarray]:
    x, y, dates = _clean(x, y, dates)
    g, inv = date_gap_index(y, dates)
    sx = np.bincount(inv, weights=x)
    cnt = np.bincount(inv)
    return sx / cnt, g
