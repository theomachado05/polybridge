from __future__ import annotations

import numpy as np

from fresh_accuracy.config import PARAMS


def brier_diff(p_pm, p_opt, y) -> np.ndarray:
    p_pm, p_opt, y = (np.asarray(v, float) for v in (p_pm, p_opt, y))
    return (p_pm - y) ** 2 - (np.clip(p_opt, 0, 1) - y) ** 2


def log_score(p, y, clip=PARAMS.log_clip) -> np.ndarray:
    p = np.clip(np.asarray(p, float), *clip)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def log_diff(p_pm, p_opt, y) -> np.ndarray:
    return log_score(p_pm, y) - log_score(np.clip(np.asarray(p_opt, float), 0, 1), y)


def _weight_chunks(c: int, draws: int, seed: int, chunk: int = 1000):
    rng = np.random.default_rng(seed)
    left = draws
    while left > 0:
        k = min(chunk, left)
        yield rng.multinomial(c, np.full(c, 1.0 / c), size=k).astype(float)
        left -= k


def cluster_boot(series: dict[str, np.ndarray], clusters, draws: int = PARAMS.draws, seed: int = PARAMS.seed) -> dict:
    cl = np.asarray(clusters)
    keys, inv = np.unique(cl, return_inverse=True)
    c = len(keys)
    n = np.bincount(inv, minlength=c).astype(float)
    sums = {k: np.bincount(inv, np.asarray(v, float), c) for k, v in series.items()}
    rw = {k: [] for k in series}
    cw = {k: [] for k in series}
    for w in _weight_chunks(c, draws, seed):
        N = w @ n
        tot = w.sum(axis=1)
        for k in series:
            rw[k].append((w @ sums[k]) / N)
            cw[k].append((w @ (sums[k] / n)) / tot)
    out = {"n": int(len(cl)), "clusters": int(c), "draws": draws, "seed": seed}
    for k, v in series.items():
        a, b = np.concatenate(rw[k]), np.concatenate(cw[k])
        v = np.asarray(v, float)
        out[k] = dict(mean=float(v.mean()), ci95=_pct(a, 2.5, 97.5), ci90=_pct(a, 5, 95),
                      cw_mean=float((sums[k] / n).mean()), cw_ci95=_pct(b, 2.5, 97.5))
    return out


def _pct(a, lo, hi) -> list[float]:
    a = a[np.isfinite(a)]
    return [float(np.percentile(a, lo)), float(np.percentile(a, hi))] if len(a) else [float("nan")] * 2


def verdict(n_rows: int, n_dates: int, b: dict, l: dict, mean_key: str = "mean", ci_key: str = "ci95",
            p=PARAMS) -> str:
    if n_rows < p.min_rows or n_dates < p.min_dates:
        return "INSUFFICIENT"
    pos = [x[ci_key][0] > 0 for x in (b, l)]
    neg = [x[mean_key] < 0 and x[ci_key][1] < 0 for x in (b, l)]
    if any(neg):
        return "REVERSED"
    if all(pos):
        return "PASS"
    if any(pos):
        return "PARTIAL"
    return "NULL"


def h3_verdict(b: dict, margin: float = PARAMS.tost_margin) -> str:
    lo90, hi90 = b["ci90"]
    if -margin <= lo90 and hi90 <= margin:
        return "EQUIVALENT"
    lo, hi = b["ci95"]
    if lo > 0:
        return "OPTIONS-BETTER"
    if hi < 0:
        return "KALSHI-BETTER"
    return "INCONCLUSIVE"


def _cluster_meat(X, u, cl) -> np.ndarray:
    keys, inv = np.unique(np.asarray(cl), return_inverse=True)
    S = np.zeros((len(keys), X.shape[1]))
    np.add.at(S, inv, X * u[:, None])
    g = len(keys)
    return (S.T @ S) * (g / (g - 1) if g > 1 else 1.0)


def logit_cluster(X, y, cl, iters: int = 50) -> dict:
    X = np.column_stack([np.ones(len(y)), np.asarray(X, float)])
    y = np.asarray(y, float)
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ b)))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None])
        step = np.linalg.solve(H, X.T @ (y - p))
        b = b + step
        if np.max(np.abs(step)) < 1e-10:
            break
    p = 1 / (1 + np.exp(-(X @ b)))
    Hi = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    V = Hi @ _cluster_meat(X, y - p, cl) @ Hi
    se = np.sqrt(np.diag(V))
    return dict(coef=b.tolist(), se=se.tolist(), ci95=[[float(c - 1.96 * s), float(c + 1.96 * s)] for c, s in zip(b, se)])


def ols_cluster(x, y, cl) -> dict:
    X = np.column_stack([np.ones(len(y)), np.asarray(x, float)])
    y = np.asarray(y, float)
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    V = XtXi @ _cluster_meat(X, y - X @ b, cl) @ XtXi
    se = np.sqrt(np.diag(V))
    return dict(coef=b.tolist(), se=se.tolist(), ci95=[[float(c - 1.96 * s), float(c + 1.96 * s)] for c, s in zip(b, se)])


def logit(p, clip=PARAMS.log_clip) -> np.ndarray:
    p = np.clip(np.asarray(p, float), *clip)
    return np.log(p / (1 - p))
