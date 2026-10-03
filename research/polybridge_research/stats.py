"""Uncertainty and multiple-testing tools. Standard library + numpy only (judges' environment).

bootstrap_ci        percentile bootstrap of the mean (the Massive starter's method, with a level argument)
benjamini_hochberg  false-discovery-rate q-values across the exploratory atlas
deflated_sharpe     Bailey & Lopez de Prado (2014): P(true Sharpe > 0) after N trials
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def bootstrap_ci(x, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    arr = np.asarray(x, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(means, [tail, 100 - tail])
    return (float(lo), float(hi))


def benjamini_hochberg(pvalues) -> np.ndarray:
    """BH q-values over the finite p-values only; non-finite inputs stay NaN and do not count toward m."""
    p = np.asarray(pvalues, dtype=float)
    q = np.full(len(p), np.nan)
    idx = np.flatnonzero(np.isfinite(p))
    m = len(idx)
    if m == 0:
        return q
    order = idx[np.argsort(p[idx])]
    ranked = p[order] * m / np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q[order] = np.minimum(q_sorted, 1.0)
    return q


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum Sharpe among n_trials strategies with zero true Sharpe (the SR0 benchmark)."""
    if n_trials <= 1:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sharpe_variance) * ((1 - _EULER_GAMMA) * a + _EULER_GAMMA * b)


def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int, sharpe_variance: float,
                    skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Probability that the true (per-period) Sharpe exceeds the best expected by luck across n_trials."""
    if n_obs < 2:
        return math.nan
    sr0 = expected_max_sharpe(n_trials, sharpe_variance)
    denom = math.sqrt(max(1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe ** 2, 1e-12))
    z = (sharpe - sr0) * math.sqrt(n_obs - 1) / denom
    return _N.cdf(z)
