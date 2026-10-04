from __future__ import annotations

import asyncio
import math
from typing import Any

from . import model as m
from .service import equity_view, service_for

LIVE_TIMEOUT_S = 10.0
LABEL = ("Capacity before approval: participation caps and estimated cost from Massive (equity) and the venue book "
         "(PM); capital budget from the active broker's account. Estimates, not guarantees.")


def _hedge_shares(prop) -> int:
    return int(math.floor(float(prop.target_coverage) * float(prop.shares_held) + 1e-9))


def _equity_block(prop, view: dict) -> dict:
    hs = _hedge_shares(prop)
    if not view.get("available"):
        return {"ticker": prop.ticker, "hedge_shares": hs, "available": False, "reason": view.get("reason"),
                "inside_caps": None}
    px = view.get("price")
    mo, pd_ = view.get("max_order_shares"), view.get("per_day_shares")
    cost = m.equity_cost_bp(float(hs), (view.get("spread_bp") or 0.0) / 2.0 if view.get("spread_bp") is not None
                            else None, view.get("adv_shares"), view.get("sigma_daily"))
    sessions = math.ceil(hs / pd_) if pd_ else None
    return {"ticker": prop.ticker, "available": True, "hedge_shares": hs, "price": px,
            "hedge_notional_usd": hs * px if px else None, "max_order_shares": mo, "per_day_shares": pd_,
            "inside_caps": (hs <= mo) if mo is not None else None,
            "binding": view.get("binding"), "est_cost_bp": cost["total_bp"], "cost": cost,
            "orders_at_open_needed": math.ceil(hs / mo) if mo else None, "sessions_needed": sessions,
            "book_usd_capacity": (view.get("capacity") or {}).get("book_usd"),
            "book_usd_within_one_session": (view.get("capacity") or {}).get("book_usd_within_one_session"),
            "adv_shares": view.get("adv_shares"), "open5_median_shares": view.get("open5_median_shares"),
            "spread_bp": view.get("spread_bp"), "spread_source": view.get("spread_source"),
            "freshness": view.get("freshness"),
            "note": (None if mo is None or hs <= mo else
                     f"the hedge ({hs} sh) is above one order's cap ({mo} sh): orders are capped "
                     "(liquidity_capped) and the rest waits for later orders")}


def cached(app, prop) -> dict:
    out: dict[str, Any] = {"label": LABEL, "source": "cache", "caps": m.CAPS}
    if prop.family == "hedge":
        raw, age = service_for(app).cached_equity(prop.ticker)
        view = equity_view(prop.ticker, raw, age, False, float(prop.target_coverage)) if raw else {
            "available": False, "reason": "not fetched yet (POST /proposals fetches it; GET /liquidity/{ticker})"}
        out["equity"] = _equity_block(prop, view)
    else:
        out["options"] = _options_note(prop)
    out["capital"] = None
    return m.clean(out)


def _options_note(prop) -> dict:
    return {"max_notional": prop.max_notional, "max_contracts": prop.max_contracts,
            "note": "each option order is capped per structure at bridge time: every leg <= 10% of its daily volume "
                    "and <= 5% of its open interest (liquidity_capped)"}


async def live(app, prop) -> dict:
    from ..broker import get_broker
    from ..capital import service as cap
    out: dict[str, Any] = {"label": LABEL, "source": "live", "caps": m.CAPS}
    svc = service_for(app)

    async def equity():
        return await svc.equity(prop.ticker, float(prop.target_coverage) or 0.5)

    async def pm():
        if prop.market is None:
            return None
        return await svc.pm(prop.market.source, prop.market.id, prop.market.token_id)

    tasks = [equity() if prop.family == "hedge" else asyncio.sleep(0, None), pm()]
    try:
        eq_view, pm_view = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), LIVE_TIMEOUT_S)
    except asyncio.TimeoutError:
        eq_view = pm_view = None
    if isinstance(eq_view, BaseException):
        eq_view = None
    if isinstance(pm_view, BaseException):
        pm_view = None
    if prop.family == "hedge":
        out["equity"] = _equity_block(prop, eq_view or {"available": False, "reason": "timed out"})
    else:
        out["options"] = _options_note(prop)
    if pm_view is not None:
        out["pm"] = {k: pm_view.get(k) for k in ("available", "reason", "source", "depth", "max_order_contracts",
                                                 "est_cost_at_cap", "freshness")}
        if pm_view.get("twin"):
            tw = pm_view["twin"]
            out["pm"]["twin"] = {k: tw.get(k) for k in ("available", "reason", "source", "id", "depth",
                                                        "max_order_contracts")}
    try:
        broker = get_broker(app)
        if prop.family == "hedge":
            from ..capital.budget import REG_T_INITIAL
            notional = (out["equity"].get("hedge_notional_usd") or 0.0)
            margin = notional * REG_T_INITIAL
        else:
            notional = margin = float(prop.max_notional or 0.0)
        if notional > 0:
            chk = await asyncio.wait_for(cap.check(app, broker=broker, event=cap.event_key(prop.market),
                                                   add_notional=notional, add_margin=margin), LIVE_TIMEOUT_S)
            out["capital"] = {"fits": chk.get("ok"), "checked": chk.get("checked"), "breaches": chk.get("breaches"),
                              "note": chk.get("note"), "add_notional": notional, "gross": chk.get("gross"),
                              "event": chk.get("event"), "buying_power": chk.get("buying_power"),
                              "limits": chk.get("limits")}
        else:
            out["capital"] = {"fits": None, "checked": False, "note": "no hedge price yet: notional unknown"}
    except Exception as e:
        out["capital"] = {"fits": None, "checked": False, "note": f"capital check unavailable ({type(e).__name__})"}
    return m.clean(out)
