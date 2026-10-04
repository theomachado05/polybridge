from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from . import model as m
from .service import service_for

LIQUIDITY_CAPPED = "liquidity_capped"
UNKNOWN_EQUITY = ("no cached liquidity numbers for this ticker (no Massive key, or not fetched yet): the order is not "
                  "capped by participation")
UNKNOWN_OPTION = "no open interest / volume for every leg: the order is not capped by option participation"
UNKNOWN_PM = "no book depth on this tick (mid-only or one-sided): the PM leg is not capped by depth"


def _ledger(app) -> dict:
    led = getattr(app.state, "liquidity_ledger", None)
    if led is None:
        led = app.state.liquidity_ledger = defaultdict(float)
    return led


def session_day(at: Any | None = None) -> str:
    from ..closed.session import ET, now_utc, to_utc
    t = to_utc(at) if at is not None else now_utc()
    return t.astimezone(ET).date().isoformat()


def _capped(qty: float, cap: float, limit: str, rule: str, **extra) -> dict:
    allowed = max(0.0, float(math.floor(cap + 1e-9)))
    return {"status": "capped", "reason": LIQUIDITY_CAPPED, "allowed": allowed, "capped_from": qty, "limit": limit,
            "limit_qty": cap, "rule": rule, **extra}


def equity_check(app, ticker: str, qty: float, *, scope: str = "account", day: str | None = None) -> dict:
    svc = service_for(app)
    raw, age = svc.cached_equity(ticker)
    if raw is None:
        return {"status": "unknown", "allowed": qty, "note": UNKNOWN_EQUITY}
    lim = m.equity_limits(raw.get("adv_shares"), raw.get("open5_median_shares"))
    day = day or session_day()
    used = _ledger(app).get((scope, ticker.upper(), day), 0.0)
    day_left = None if lim["per_day_shares"] is None else max(0.0, lim["per_day_shares"] - used)
    cands = [(v, n) for v, n in ((lim["per_order_shares"], "per_order_open5"), (day_left, "per_day_adv"))
             if v is not None]
    info = {"limits": {**lim, "used_today": used, "day_left": day_left, "day": day, "scope": scope},
            "data_age_s": None if age is None else round(age, 1)}
    if not cands:
        return {"status": "unknown", "allowed": qty, "note": UNKNOWN_EQUITY, **info}
    cap, which = min(cands)
    if qty <= cap + 1e-9:
        return {"status": "within_caps", "allowed": qty, **info}
    rule = m.CAPS["equity"]["per_order" if which == "per_order_open5" else "per_day"]
    return _capped(qty, cap, which, rule, **info)


def record_equity(app, ticker: str, qty: float, *, scope: str = "account", day: str | None = None) -> None:
    if qty and qty > 0:
        _ledger(app)[(scope, ticker.upper(), day or session_day())] += float(qty)


def option_check(quotes: Iterable[Any], qty: float) -> dict:
    caps = []
    for q in quotes:
        lim = m.option_limits(m.fin(getattr(q, "volume", None)), m.fin(getattr(q, "open_interest", None)))
        if lim["per_order_contracts"] is None:
            return {"status": "unknown", "allowed": qty, "note": UNKNOWN_OPTION}
        caps.append((lim["per_order_contracts"], lim["binding"], getattr(q, "ticker", None)))
    if not caps:
        return {"status": "unknown", "allowed": qty, "note": UNKNOWN_OPTION}
    cap, which, leg = min(caps, key=lambda c: c[0])
    if qty <= cap:
        return {"status": "within_caps", "allowed": qty, "legs": [{"ticker": t, "cap": c} for c, _, t in caps]}
    return _capped(qty, cap, f"option_{which}", m.CAPS["option"]["per_order"], leg=leg,
                   legs=[{"ticker": t, "cap": c} for c, _, t in caps])


def pm_check(fields: dict, side: str, qty: float) -> dict:
    bids, asks = m.book_levels(fields, "bid"), m.book_levels(fields, "ask")
    if not bids or not asks:
        return {"status": "unknown", "allowed": qty, "note": UNKNOWN_PM}
    depth = m.pm_depth(bids, asks)
    cap = m.pm_cap(depth, side)
    if cap is None:
        return {"status": "unknown", "allowed": qty, "note": UNKNOWN_PM}
    band = depth[side][f"{round(m.PM_DEPTH_BAND * 100)}c"]
    if qty <= cap:
        return {"status": "within_caps", "allowed": qty, "depth_2c": band}
    return _capped(qty, cap, "pm_depth_2c", m.CAPS["pm"]["per_order"], depth_2c=band)


def tag(rec: dict, check: dict) -> None:
    rec["liquidity"] = {k: v for k, v in check.items() if k not in ("allowed",)}
    if check.get("status") == "capped":
        rec.setdefault("gates", []).append({"reason": LIQUIDITY_CAPPED, "limit": check["limit"],
                                            "limit_qty": check["limit_qty"], "capped_from": check["capped_from"],
                                            "rule": check["rule"]})
