from __future__ import annotations

import math
import os
from typing import Any

MAX_GROSS_HEDGE_PCT = 0.50
MAX_EVENT_PCT = 0.20
REG_T_INITIAL = 0.50
REG_T_MAINTENANCE = 0.30
NAKED_PUT_UNDERLYING_PCT = 0.20
NAKED_PUT_MIN_STRIKE_PCT = 0.10
OPTION_MULT = 100
CAPITAL_BUDGET = "capital_budget"


def _env_pct(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return v if math.isfinite(v) and 0 < v <= 10 else default


def limits(app=None) -> dict:
    out = {"max_gross_hedge_pct": _env_pct("CAPITAL_MAX_GROSS_PCT", MAX_GROSS_HEDGE_PCT),
           "max_event_pct": _env_pct("CAPITAL_MAX_EVENT_PCT", MAX_EVENT_PCT),
           "reg_t_initial": REG_T_INITIAL, "reg_t_maintenance": REG_T_MAINTENANCE,
           "short_put_mode": "margin" if os.environ.get("CAPITAL_SHORT_PUT_MODE", "").lower() == "margin"
           else "cash_secured"}
    over = getattr(getattr(app, "state", None), "capital_limits", None) if app is not None else None
    if isinstance(over, dict):
        out.update({k: v for k, v in over.items() if k in out})
    return out


def short_equity_margin(notional: float, lim: dict | None = None) -> dict:
    lim = lim or limits()
    n = max(0.0, float(notional))
    return {"initial": lim["reg_t_initial"] * n, "maintenance": lim["reg_t_maintenance"] * n}


def naked_put_margin(spot: float, strike: float, premium: float) -> float:
    otm = max(0.0, spot - strike)
    return (max(NAKED_PUT_UNDERLYING_PCT * spot - otm, NAKED_PUT_MIN_STRIKE_PCT * strike) + max(0.0, premium)) * OPTION_MULT


def option_requirement(kind: str, side: int, qty: float, net_mid: float | None, net_half: float | None,
                       width: float | None = None, strike: float | None = None, spot: float | None = None,
                       mode: str = "cash_secured") -> float | None:
    if net_mid is None or not math.isfinite(net_mid) or qty <= 0:
        return None
    half = net_half or 0.0
    if side > 0:
        return max(0.0, net_mid + half) * OPTION_MULT * qty
    credit = max(0.0, net_mid - half)
    if width is not None:
        return max(0.0, width - credit) * OPTION_MULT * qty
    if kind == "cash_secured_put" and mode == "margin" and strike and spot:
        return naked_put_margin(spot, strike, credit) * qty
    return max(0.0, float(strike or 0.0) - credit) * OPTION_MULT * qty


def evaluate(*, equity: float | None, buying_power: float | None, gross_now: float, event_now: float,
             add_notional: float, add_margin: float, bp_basis: str, lim: dict, event: str | None = None) -> dict:
    if equity is None or not math.isfinite(equity):
        return {"ok": False, "breaches": [{"kind": "account_unreadable",
                                           "detail": "the account could not be read, so the budget cannot be checked; "
                                                     "exposure-increasing orders are refused until it can"}]}
    breaches = []
    g_lim, e_lim = lim["max_gross_hedge_pct"] * equity, lim["max_event_pct"] * equity
    g_after, e_after = gross_now + add_notional, event_now + add_notional
    if g_after > g_lim + 1e-6:
        breaches.append({"kind": "gross_hedge_notional", "limit_usd": g_lim, "after_usd": g_after,
                         "detail": f"gross hedge notional would be ${g_after:,.0f} > {lim['max_gross_hedge_pct']:.0%} of "
                                   f"equity (${g_lim:,.0f})"})
    if e_after > e_lim + 1e-6:
        breaches.append({"kind": "event_exposure", "event": event, "limit_usd": e_lim, "after_usd": e_after,
                         "detail": f"exposure to {event or 'this event'} would be ${e_after:,.0f} > "
                                   f"{lim['max_event_pct']:.0%} of equity (${e_lim:,.0f})"})
    need = add_margin if bp_basis == "margin" else add_notional
    bp = {"basis": bp_basis, "required": need, "available": buying_power}
    if buying_power is not None and math.isfinite(buying_power) and need > buying_power + 1e-6:
        breaches.append({"kind": "buying_power", "limit_usd": buying_power, "after_usd": need,
                         "detail": f"the order needs ${need:,.0f} of buying power ({'initial margin' if bp_basis == 'margin' else 'notional'}); "
                                   f"the broker reports ${buying_power:,.0f}"})
    return {"ok": not breaches, "breaches": breaches,
            "gross": {"now": gross_now, "after": g_after, "limit_usd": g_lim},
            "event": {"key": event, "now": event_now, "after": e_after, "limit_usd": e_lim},
            "buying_power": bp, "add_notional": add_notional, "add_margin": add_margin}


def max_room(equity: float | None, gross_now: float, event_now: float, lim: dict) -> float | None:
    if equity is None:
        return None
    return max(0.0, min(lim["max_gross_hedge_pct"] * equity - gross_now, lim["max_event_pct"] * equity - event_now))


def fin(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
