from __future__ import annotations

import numpy as np

SEED = 20261003
DRAWS = 10_000


def ols(x, y) -> tuple[float, float]:
    x, y = np.asarray(x, float), np.asarray(y, float)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    b = float(((x - xm) * (y - ym)).sum() / sxx) if sxx > 0 else float("nan")
    return float(ym - b * xm), b


def _weights(n_clusters: int, draws: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=draws).astype(float)


def cluster_bootstrap(x, y, g, clusters, draws: int = DRAWS, seed: int = SEED) -> dict:
    x, y, g = (np.asarray(v, float) for v in (x, y, g))
    cl = np.asarray(clusters)
    keys, inv = np.unique(cl, return_inverse=True)
    c = len(keys)
    n = np.bincount(inv, minlength=c).astype(float)
    sx, sy = np.bincount(inv, x, c), np.bincount(inv, y, c)
    sxx, sxy = np.bincount(inv, x * x, c), np.bincount(inv, x * y, c)
    sg = np.bincount(inv, g, c)
    cm = sg / n
    w = _weights(c, draws, seed)
    N, SX, SY, SXX, SXY, SG = (w @ v for v in (n, sx, sy, sxx, sxy, sg))
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = (SXY - SX * SY / N) / (SXX - SX * SX / N)
        mean_g = SG / N
        cw = (w @ cm) / w.sum(axis=1)

    def ci(a):
        a = a[np.isfinite(a)]
        return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))] if len(a) else [float("nan")] * 2

    a0, b0 = ols(x, y)
    return dict(n=int(len(x)), clusters=int(c), alpha=a0, beta=b0, beta_ci=ci(beta), mean=float(g.mean()), mean_ci=ci(mean_g),
                cw_mean=float(cm.mean()), cw_mean_ci=ci(cw), draws=draws, seed=seed)


def mean_ci(v, clusters, draws: int = DRAWS, seed: int = SEED) -> dict:
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    if ok.sum() == 0:
        return dict(n=0, clusters=0, mean=float("nan"), mean_ci=[float("nan")] * 2)
    r = cluster_bootstrap(np.zeros(ok.sum()), np.zeros(ok.sum()), v[ok], np.asarray(clusters)[ok], draws, seed)
    return dict(n=r["n"], clusters=r["clusters"], mean=r["mean"], mean_ci=r["mean_ci"], cw_mean=r["cw_mean"], cw_mean_ci=r["cw_mean_ci"])
