"""Benchmark-controlled regression tests (METHOD.md section 3). numpy only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ols_cluster(y, X, groups) -> dict:
    """OLS with CR1 standard errors clustered by `groups`. X includes the constant."""
    y, X = np.asarray(y, float), np.asarray(X, float)
    g = pd.factorize(np.asarray(groups))[0]
    n, k = X.shape
    G = int(g.max()) + 1 if n else 0
    if n <= k or G < 2:
        nan = np.full(k, np.nan)
        return {"beta": nan, "se": nan, "t": nan, "r2": float("nan"), "n": n, "G": G}
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    S = np.zeros((G, k))
    np.add.at(S, g, X * e[:, None])
    meat = S.T @ S
    adj = G / (G - 1) * (n - 1) / (n - k)
    cov = adj * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta / se
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float((e ** 2).sum()) / tss if tss > 0 else float("nan")
    return {"beta": beta, "se": se, "t": t, "r2": r2, "n": n, "G": G}


def _r2(y, X) -> float:
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ beta
    tss = float(((y - y.mean()) ** 2).sum())
    return 1 - float((e ** 2).sum()) / tss if tss > 0 else float("nan")


def benchmark_test(g, b, x, dates, blocks, n_perm: int, n_boot: int, seed: int) -> dict:
    """g = a + beta*b + c*x, clustered by date; Freedman-Lane permutation of date residuals within blocks;
    month-block bootstrap CIs for c and dR2; PM-only slope d."""
    g, b, x = (np.asarray(v, float) for v in (g, b, x))
    dates, blocks = np.asarray(dates).astype(str), np.asarray(blocks).astype(str)
    m = np.isfinite(g) & np.isfinite(b) & np.isfinite(x)
    g, b, x, dates, blocks = g[m], b[m], x[m], dates[m], blocks[m]
    n = len(g)
    out = {"n": n, "n_dates": int(len(np.unique(dates))), "n_blocks": int(len(np.unique(blocks)))}
    if n < 8 or np.ptp(x) == 0 or np.ptp(b) == 0:
        out.update({k: float("nan") for k in ("c", "c_se", "c_t", "c_lo", "c_hi", "beta", "beta_t", "r2_full", "r2_reduced",
                                             "dr2", "dr2_lo", "dr2_hi", "p_perm", "d", "d_t", "absorbed", "c_boot_lo",
                                             "c_boot_hi", "corr_xb")})
        return out
    one = np.ones(n)
    Xf = np.column_stack([one, b, x])
    Xr = np.column_stack([one, b])
    full = ols_cluster(g, Xf, dates)
    red_beta = np.linalg.lstsq(Xr, g, rcond=None)[0]
    fit_r = Xr @ red_beta
    res_r = g - fit_r
    r2_red = _r2(g, Xr)
    only = ols_cluster(g, np.column_stack([one, x]), dates)

    udates, inv = np.unique(dates, return_inverse=True)
    date_res = np.zeros(len(udates))
    date_res[inv] = res_r
    date_block = np.empty(len(udates), dtype=object)
    date_block[inv] = blocks
    block_idx = [np.flatnonzero(date_block == bl) for bl in np.unique(date_block.astype(str))]
    rng = np.random.default_rng(seed)
    t_obs = abs(float(full["t"][2]))
    cnt = 0
    perm = np.arange(len(udates))
    for _ in range(n_perm):
        for idx in block_idx:
            perm[idx] = rng.permutation(idx)
        y_star = fit_r + date_res[perm][inv]
        t_star = ols_cluster(y_star, Xf, dates)["t"][2]
        cnt += abs(t_star) >= t_obs - 1e-12
    p_perm = (cnt + 1) / (n_perm + 1)

    ublocks = np.unique(blocks)
    rows_of = [np.flatnonzero(blocks == bl) for bl in ublocks]
    rng_b = np.random.default_rng(seed)
    cs, drs = [], []
    for _ in range(n_boot):
        pick = rng_b.integers(0, len(ublocks), len(ublocks))
        idx = np.concatenate([rows_of[i] for i in pick])
        if np.ptp(x[idx]) == 0 or np.ptp(b[idx]) == 0:
            continue
        Xf_b, Xr_b = Xf[idx], Xr[idx]
        cs.append(float(np.linalg.lstsq(Xf_b, g[idx], rcond=None)[0][2]))
        drs.append(_r2(g[idx], Xf_b) - _r2(g[idx], Xr_b))
    c = float(full["beta"][2])
    se = float(full["se"][2])
    d = float(only["beta"][1])
    out.update({
        "c": c, "c_se": se, "c_t": float(full["t"][2]), "c_lo": c - 1.96 * se, "c_hi": c + 1.96 * se,
        "beta": float(full["beta"][1]), "beta_t": float(full["t"][1]),
        "r2_full": full["r2"], "r2_reduced": r2_red, "dr2": full["r2"] - r2_red,
        "dr2_lo": float(np.percentile(drs, 2.5)) if drs else float("nan"),
        "dr2_hi": float(np.percentile(drs, 97.5)) if drs else float("nan"),
        "c_boot_lo": float(np.percentile(cs, 2.5)) if cs else float("nan"),
        "c_boot_hi": float(np.percentile(cs, 97.5)) if cs else float("nan"),
        "p_perm": float(p_perm), "d": d, "d_t": float(only["t"][1]),
        "absorbed": 1 - c / d if d != 0 else float("nan"),
        "corr_xb": float(np.corrcoef(x, b)[0, 1]),
    })
    return out


def verdict(res: dict, t_crit: float = 1.96, alpha: float = 0.05) -> str:
    c, t, p = res.get("c"), res.get("c_t"), res.get("p_perm")
    if c is None or not np.isfinite(c) or not np.isfinite(t) or not np.isfinite(p):
        return "not computable"
    if c > 0 and t > t_crit and p < alpha:
        return "adds information beyond the benchmark"
    if c < 0 and t < -t_crit and p < alpha:
        return "no evidence that the PM adds information beyond the benchmark (significant negative coefficient)"
    return "no evidence that the PM adds information beyond the benchmark"


def describe(g, b, x) -> dict:
    g, b, x = (np.asarray(v, float) for v in (g, b, x))
    m = np.isfinite(g) & np.isfinite(b) & np.isfinite(x)
    if m.sum() < 2:
        return {"n": int(m.sum())}
    r = g[m] - b[m]
    return {"n": int(m.sum()), "sd_g": float(np.std(g[m], ddof=1)), "sd_b": float(np.std(b[m], ddof=1)),
            "sd_r": float(np.std(r, ddof=1)), "sd_x": float(np.std(x[m], ddof=1)),
            "share_x_nonzero": float(np.mean(x[m] != 0))}
