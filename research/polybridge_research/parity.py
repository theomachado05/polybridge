from __future__ import annotations

import math


def implied_move(call_atm: float, put_atm: float, spot: float) -> float:
    if not math.isfinite(spot) or spot <= 0:
        return math.nan
    return (call_atm + put_atm) / spot


def implied_scaled(implied: float, sessions_held: int, dte_sessions: int) -> float:
    if not dte_sessions or dte_sessions <= 0:
        return math.nan
    return implied * math.sqrt(sessions_held / dte_sessions)


def realized_move(S_entry: float, S_exit: float) -> float:
    if not math.isfinite(S_entry) or S_entry <= 0:
        return math.nan
    return S_exit / S_entry - 1


def parity_ratio(realized: float, implied_h: float) -> float:
    if math.isnan(realized) or math.isnan(implied_h) or implied_h <= 0:
        return math.nan
    return abs(realized) / implied_h
