"""Tests of METHOD.md section 4-5, implemented with numpy only (no scipy)."""
from __future__ import annotations

from math import comb

import numpy as np


def binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test against p = 0.5 (doubled tail, capped at 1)."""
    if n <= 0:
        return float("nan")
    hi = max(k, n - k)
    tail = sum(comb(n, i) for i in range(hi, n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def sign_agreement(x, y, theta: float) -> dict:
    """T1: among pairs with |x| >= theta and y != 0, count sign(x) == sign(y)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y) & (np.abs(x) >= theta) & (y != 0)
    n = int(m.sum())
    k = int((np.sign(x[m]) == np.sign(y[m])).sum())
    return {"n": n, "k": k, "rate": k / n if n else float("nan"), "p": binom_two_sided(k, n) if n else float("nan")}


def ols_hc3(y, X) -> dict:
    """OLS with HC3 standard errors. X must include the constant column. Returns beta, se, t, r2, n."""
    y, X = np.asarray(y, float), np.asarray(X, float)
    n, k = X.shape
    if n <= k:
        return {"beta": np.full(k, np.nan), "se": np.full(k, np.nan), "t": np.full(k, np.nan), "r2": float("nan"), "n": n}
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    h = np.einsum("ij,jk,ik->i", X, XtX_inv, X)
    w = (e / np.clip(1 - h, 1e-8, None)) ** 2
    cov = XtX_inv @ (X.T * w) @ X @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta / se
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float((e ** 2).sum()) / tss if tss > 0 else float("nan")
    return {"beta": beta, "se": se, "t": t, "r2": r2, "n": n}


def slope_test(x, y, n_perm: int, seed: int) -> dict:
    """T2: y = a + b x, HC3 t, and a two-sided permutation p-value on |b| (shuffle y)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 4 or np.ptp(x) == 0:
        return {"n": n, "b": float("nan"), "t": float("nan"), "r2": float("nan"), "p_perm": float("nan"),
                "rho": float("nan"), "p_rho": float("nan")}
    X = np.column_stack([np.ones(n), x])
    fit = ols_hc3(y, X)
    rng = np.random.default_rng(seed)
    b_obs = abs(_slope(x, y))
    rx, ry = _rank(x), _rank(y)
    rho_obs = abs(_corr(rx, ry))
    cnt_b = cnt_r = 0
    for _ in range(n_perm):
        yp = rng.permutation(y)
        cnt_b += abs(_slope(x, yp)) >= b_obs - 1e-12
        cnt_r += abs(_corr(rx, _rank(yp))) >= rho_obs - 1e-12
    return {"n": n, "b": float(fit["beta"][1]), "t": float(fit["t"][1]), "r2": fit["r2"],
            "p_perm": (cnt_b + 1) / (n_perm + 1), "rho": float(_corr(rx, ry)), "p_rho": (cnt_r + 1) / (n_perm + 1)}


def _slope(x, y):
    xc = x - x.mean()
    d = float((xc ** 2).sum())
    return float((xc * (y - y.mean())).sum() / d) if d > 0 else 0.0


def _rank(a):
    order = a.argsort(kind="mergesort")
    r = np.empty(len(a))
    r[order] = np.arange(len(a))
    # average ties
    _, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=r)
    return (sums / cnt)[inv]


def _corr(a, b):
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a ** 2).sum() * (b ** 2).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def pairing_placebo(ev_x, ev_panel, ev_y, pools: dict, theta: float, n_perm: int, seed: int) -> dict:
    """P2: pair each event's oriented PM change with the gap of a random placebo closure from the same panel.

    Observed statistics use events with |x| >= theta and a valid gap: agreement count k and OLS slope.
    Returns p-values = share of draws at least as large as observed (with +1 correction).
    """
    x, y = np.asarray(ev_x, float), np.asarray(ev_y, float)
    panel = np.asarray(ev_panel)
    m = np.isfinite(x) & np.isfinite(y) & (np.abs(x) >= theta)
    x, y, panel = x[m], y[m], panel[m]
    n = len(x)
    if n < 3:
        return {"n": n, "k_obs": None, "slope_obs": float("nan"), "p_k": float("nan"), "p_slope": float("nan"),
                "k_draws_mean": float("nan"), "slope_draws_mean": float("nan"), "k_draws": [], "slope_draws": []}
    k_obs = int(((np.sign(x) == np.sign(y)) & (y != 0)).sum())
    s_obs = _slope(x, y)
    rng = np.random.default_rng(seed)
    pool = {k: np.asarray(v, float)[np.isfinite(np.asarray(v, float))] for k, v in pools.items()}
    ks, ss = [], []
    for _ in range(n_perm):
        yd = np.array([rng.choice(pool[p]) for p in panel])
        ks.append(int(((np.sign(x) == np.sign(yd)) & (yd != 0)).sum()))
        ss.append(_slope(x, yd))
    ks, ss = np.asarray(ks), np.asarray(ss)
    return {"n": n, "k_obs": k_obs, "slope_obs": s_obs,
            "p_k": float((np.sum(ks >= k_obs) + 1) / (n_perm + 1)), "p_slope": float((np.sum(ss >= s_obs) + 1) / (n_perm + 1)),
            "k_draws_mean": float(ks.mean()), "slope_draws_mean": float(ss.mean()), "k_draws": ks, "slope_draws": ss}


def interaction(dpm_o, gap, news) -> dict:
    """P3: gap = a + b*dpm + c*news + d*dpm*news, HC3. Returns b, d with t."""
    x, y, z = (np.asarray(v, float) for v in (dpm_o, gap, news))
    m = np.isfinite(x) & np.isfinite(y)
    x, y, z = x[m], y[m], z[m]
    if len(x) < 8 or z.sum() < 2:
        return {"n": len(x), "b": float("nan"), "b_t": float("nan"), "d": float("nan"), "d_t": float("nan")}
    X = np.column_stack([np.ones(len(x)), x, z, x * z])
    f = ols_hc3(y, X)
    return {"n": len(x), "b": float(f["beta"][1]), "b_t": float(f["t"][1]), "d": float(f["beta"][3]), "d_t": float(f["t"][3])}
