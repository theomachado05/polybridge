"""Pure pieces of Study A (METHOD.md sections 1-4). No network."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np

from pm_taker.core import ET, cluster_boot, evaluable, fee_per_share, qualifies

from . import config as C


def window(open_day: str) -> tuple[int, int]:
    d = date.fromisoformat(open_day)
    w0 = datetime(d.year, d.month, d.day, *C.WINDOW_START_HMS, tzinfo=ET)
    w1 = datetime(d.year, d.month, d.day, *C.WINDOW_END_HMS, tzinfo=ET)
    return int(w0.timestamp()), int(w1.timestamp())


def usable(p_mid: float, p_lo: float, p_hi: float) -> bool:
    if any(np.isnan(v) for v in (p_mid, p_lo, p_hi)):
        return False
    return (p_hi - p_lo) <= C.BAND_MAX + 1e-12 and C.P_RANGE[0] - 1e-12 <= p_mid <= C.P_RANGE[1] + 1e-12


def first_trades(prints: list[dict], p: float, taus=(C.TAUS_SECONDARY[0], C.TAU, C.TAUS_SECONDARY[1])) -> dict[float, dict]:
    out = {}
    for pr in prints:
        if not evaluable(pr):
            continue
        for tau in taus:
            if tau not in out and qualifies(pr["side"], pr["px"], p, tau):
                out[tau] = pr
        if len(out) == len(taus):
            break
    return out


def net(side: str, px: float, y: int, tick: float, enabled: bool, rate: float, exp: float) -> float:
    q = px if side == "BUY" else 1.0 - px
    win = y if side == "BUY" else 1 - y
    return win - (q + tick) - fee_per_share(q, enabled, rate, exp)


def verdict(n: int, k: int, lo: float, hi: float) -> str:
    if n < C.MIN_TRADES or k < C.MIN_CLUSTERS:
        return "INSUFFICIENT"
    if lo > 0:
        return "PASS"
    if hi < 0:
        return "NEGATIVE"
    return "NULL"


def summarize(vals, clusters) -> dict:
    vals = np.asarray(vals, float)
    if len(vals) == 0:
        return {"n": 0, "clusters": 0, "mean": float("nan"), "lo": float("nan"), "hi": float("nan")}
    lo, hi = cluster_boot(vals, np.asarray(clusters), C.BOOT_DRAWS, C.SEED)
    return {"n": int(len(vals)), "clusters": int(len(set(clusters))), "mean": float(vals.mean()), "lo": lo, "hi": hi}
