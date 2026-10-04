"""Stale-quote decision on one book touch. Uses the C++ hedgecore_stale binding when it is built
(engine/hedgecore/scripts/build_stale.sh), else the pure-Python twin below. IMPL says which one ran."""
from __future__ import annotations

NONE, BUY_YES, BUY_NO = 0, 1, 2
SIDES = {NONE: "none", BUY_YES: "buy_yes", BUY_NO: "buy_no"}
P_MIN, P_MAX = 0.03, 0.97


def fee_py(px: float, rate: float, exp: float, enabled: bool) -> float:
    if not enabled or not (0.0 < px < 1.0):
        return 0.0
    return rate * (px * (1.0 - px)) ** exp


def decide_py(bid, bid_size, ask, ask_size, p_ref, tau=0.05, fee_rate=0.04, fee_exp=1.0, fees_enabled=True):
    nan = float("nan")
    if not (P_MIN - 1e-12 <= p_ref <= P_MAX + 1e-12):
        return NONE, 0.0, 0.0, nan, 0.0
    e_yes = p_ref - ask if 0.0 < ask < 1.0 and ask_size > 0.0 else -1.0
    e_no = bid - p_ref if 0.0 < bid < 1.0 and bid_size > 0.0 else -1.0
    cut = tau - 1e-12
    if e_yes >= cut and e_yes >= e_no:
        return BUY_YES, 100.0 * e_yes, 100.0 * (e_yes - fee_py(ask, fee_rate, fee_exp, fees_enabled)), ask, ask_size
    if e_no >= cut:
        px = 1.0 - bid
        return BUY_NO, 100.0 * e_no, 100.0 * (e_no - fee_py(px, fee_rate, fee_exp, fees_enabled)), px, bid_size
    return NONE, 0.0, 0.0, nan, 0.0


try:
    from .hedgecore_stale import decide as decide_cpp
    decide, IMPL = decide_cpp, "cpp"
except ImportError:
    decide_cpp = None
    decide, IMPL = decide_py, "python"
