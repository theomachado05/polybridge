from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import PARAMS, Params


@dataclass(frozen=True)
class Move:
    time: pd.Timestamp
    delta: float
    sigma: float
    z: float

    @property
    def direction(self) -> int:
        return 1 if self.delta > 0 else -1


def rolling_sigma(chg: pd.Series, p: Params, floor: float) -> pd.Series:
    v = chg.dropna()
    sig_v = v.rolling(p.sigma_window, min_periods=p.sigma_min_obs).std().shift(1)
    sig = sig_v.reindex(chg.index).ffill()
    return sig.clip(lower=floor)


def first_move(level: pd.Series, chg: pd.Series, in_window: pd.Series, floor: float, k: float | None = None,
               p: Params = PARAMS) -> Move | None:
    k = p.k if k is None else k
    sigma = rolling_sigma(chg, p, floor)
    base = level.shift(p.w)
    delta = level - base
    fut = level.shift(-p.persist_h) - base
    thr = k * sigma * np.sqrt(p.w)
    cand = (delta.abs() > thr) & in_window & fut.notna()
    cand &= np.sign(fut) == np.sign(delta)
    cand &= fut.abs() >= p.persist_frac * delta.abs()
    net = level - level.shift(2 * p.w)
    cand &= np.sign(net) == np.sign(delta)
    cand &= net.abs() >= p.persist_frac * delta.abs()
    if not cand.any():
        return None
    t = cand.idxmax()
    return Move(time=t, delta=float(delta[t]), sigma=float(sigma[t]), z=float(delta[t] / (sigma[t] * np.sqrt(p.w))))


def lead_class(lead_min: float | None, p: Params = PARAMS) -> str:
    if lead_min is None or np.isnan(lead_min):
        return "NA"
    if lead_min > p.sim_tol:
        return "PM first"
    if lead_min < -p.sim_tol:
        return "equity first"
    return "simultaneous"


def lead_minutes(pm_move: Move | None, eq_move: Move | None) -> float | None:
    if pm_move is None or eq_move is None:
        return None
    return (eq_move.time - pm_move.time).total_seconds() / 60.0
