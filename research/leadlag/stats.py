from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


def _betacf(a: float, b: float, x: float) -> float:
    tiny, eps = 1e-300, 1e-14
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def gammaq(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    if x < a + 1.0:
        ap, s, delta = a, 1.0 / a, 1.0 / a
        for _ in range(2000):
            ap += 1.0
            delta *= x / ap
            s += delta
            if abs(delta) < abs(s) * 1e-15:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 2000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = d if abs(d) > tiny else tiny
        c = b + an / c
        c = c if abs(c) > tiny else tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    return gammaq(df / 2.0, x / 2.0)


def f_sf(f: float, d1: float, d2: float) -> float:
    if f <= 0:
        return 1.0
    return betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


def binom_two_sided(k: int, n: int, p: float = 0.5) -> float:
    if n == 0:
        return float("nan")
    pm = [math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(n + 1)]
    return float(min(1.0, sum(v for v in pm if v <= pm[k] * (1 + 1e-12))))


@dataclass
class Block:
    event_id: str
    y: np.ndarray
    X: np.ndarray


def zscale(s: pd.Series) -> pd.Series:
    sd = s.std()
    return s / sd if sd and np.isfinite(sd) and sd > 0 else s * np.nan


def lagged(s: pd.Series, lags: range) -> list[np.ndarray]:
    return [s.shift(l).to_numpy() for l in lags]


def build_block(event_id: str, frame: pd.DataFrame, dep: str, own_lags: int, other: str | None, other_lags: int,
                min_rows: int = 40) -> Block | None:
    z = {c: zscale(frame[c]) for c in ("x", "ys")}
    cols = lagged(z[dep], range(1, own_lags + 1)) if own_lags else []
    if other and other_lags:
        cols += lagged(z[other], range(1, other_lags + 1))
    d = z[dep].to_numpy()
    X = np.column_stack(cols) if cols else np.zeros((len(frame), 0))
    ok = frame["in_window"].to_numpy() & np.isfinite(d) & np.isfinite(X).all(axis=1)
    if ok.sum() < min_rows:
        return None
    return Block(event_id, d[ok], X[ok])


@dataclass
class FitResult:
    beta: np.ndarray
    V: np.ndarray
    se: np.ndarray
    rss: float
    n: int
    n_events: int
    k: int

    @property
    def t(self) -> np.ndarray:
        return self.beta / self.se


def _demean(blocks: list[Block]) -> tuple[np.ndarray, np.ndarray, list[slice]]:
    ys, Xs, sl, i = [], [], [], 0
    for b in blocks:
        ys.append(b.y - b.y.mean())
        Xs.append(b.X - b.X.mean(axis=0, keepdims=True))
        sl.append(slice(i, i + len(b.y)))
        i += len(b.y)
    return np.concatenate(ys), np.vstack(Xs), sl


def fe_ols(blocks: list[Block], hac_lags: int) -> FitResult:
    y, X, sl = _demean(blocks)
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    u = y - X @ beta
    S = np.zeros((k, k))
    for s in sl:
        g = X[s] * u[s][:, None]
        T = g.shape[0]
        S += g.T @ g
        for l in range(1, min(hac_lags, T - 1) + 1):
            w = 1.0 - l / (hac_lags + 1.0)
            G = g[l:].T @ g[:-l]
            S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv * (n / max(n - k, 1))
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    return FitResult(beta, V, se, float(u @ u), n, len(blocks), k)


def wald(beta: np.ndarray, V: np.ndarray) -> tuple[float, float]:
    stat = float(beta @ np.linalg.pinv(V) @ beta)
    return stat, chi2_sf(stat, len(beta))


def cumulative(fit: FitResult, idx: slice | None = None) -> tuple[float, float, float]:
    idx = idx if idx is not None else slice(0, fit.k)
    c = np.zeros(fit.k)
    c[idx] = 1.0
    est = float(c @ fit.beta)
    se = float(np.sqrt(max(c @ fit.V @ c, 0.0)))
    return est, se, est / se if se > 0 else float("nan")


def distributed_lag(frames: dict[str, pd.DataFrame], dep: str, other: str, lags: int, hac_lags: int) -> tuple[FitResult, dict]:
    blocks = [b for eid, f in frames.items() if (b := build_block(eid, f, dep, 0, other, lags)) is not None]
    fit = fe_ols(blocks, hac_lags)
    w_stat, w_p = wald(fit.beta, fit.V)
    cum, cum_se, cum_t = cumulative(fit)
    return fit, dict(wald=w_stat, wald_p=w_p, cum=cum, cum_se=cum_se, cum_t=cum_t, n=fit.n, events=fit.n_events,
                     event_ids=[b.event_id for b in blocks])


def granger(frames: dict[str, pd.DataFrame], dep: str, other: str, p: int, hac_lags: int) -> dict:
    blocks_u = {}
    for eid, f in frames.items():
        b = build_block(eid, f, dep, p, other, p)
        if b is not None:
            blocks_u[eid] = b
    ul = list(blocks_u.values())
    blocks_r = [Block(b.event_id, b.y, b.X[:, :p]) for b in ul]
    fu, fr = fe_ols(ul, hac_lags), fe_ols(blocks_r, hac_lags)
    n, E = fu.n, fu.n_events
    df2 = n - 2 * p - E
    f = ((fr.rss - fu.rss) / p) / (fu.rss / df2)
    w_stat, w_p = wald(fu.beta[p:], fu.V[p:, p:])
    return dict(p=p, F=float(f), F_p=f_sf(f, p, df2), df2=int(df2), hac_wald=w_stat, hac_wald_p=w_p, n=n, events=E,
                other_sum=float(fu.beta[p:].sum()))
