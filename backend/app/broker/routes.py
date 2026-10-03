"""HTTP surface for the active broker. A broker failure is a clean 4xx/502, never a 500.

GET /positions lists the active broker's book (Webull paper equities + simulated legs, or the simulator), each row
labelled by ``account``; ``include_demo=true`` appends the seeded demo portfolio as separate rows (broker "demo",
account "demo holdings"), never mixed into the broker's numbers. GET /orders reads Webull order history (``days``,
bounded) + open orders. POST /orders (manual) passes the liquidity caps and the capital budget first
(``gate_manual_order``). /broker/capabilities, /broker/shortable/{symbol} and /broker/reconcile* expose the broker's
capabilities, short-sale readiness and the background order reconciliation."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import get_broker
from .models import Account, BrokerError, Order, OrderRequest, Position
from .reconcile import ensure_started, get_reconciler, stop_all
from .sim import SimBroker

router = APIRouter(on_shutdown=[stop_all])  # no reconciler outlives the app
log = logging.getLogger(__name__)
DEMO_LABEL = "demo holdings"


class ResetIn(BaseModel):
    starting_cash: float | None = Field(default=None, gt=0, allow_inf_nan=False)


async def _call(coro):
    try:
        return await coro
    except BrokerError as e:
        raise HTTPException(e.status_code, e.message)
    except Exception as e:  # the API never answers 500 for a broker problem
        log.warning("broker call failed: %s", type(e).__name__)
        raise HTTPException(502, f"Broker error ({type(e).__name__}).")


def market_session(app) -> dict:
    """The NYSE session now (``app.state.staged_clock`` pins it in tests): market_open is the regular session."""
    from ..closed.session import now_utc, session_at, to_utc

    clock = getattr(app.state, "staged_clock", None)
    s = session_at(to_utc(clock()) if clock else now_utc())
    return {"market_open": s.equities_open, "session": s.label,
            "next_open": s.next_open.isoformat().replace("+00:00", "Z")}


@router.get("/account", response_model=Account)
async def get_account(request: Request) -> Account:
    b = get_broker(request.app)
    ensure_started(request.app)
    acct = await _call(b.account())
    ext = getattr(b, "extended_hours", None)
    return acct.model_copy(update={**market_session(request.app),
                                   "extended_hours": acct.extended_hours if acct.extended_hours is not None else ext})


def demo_positions() -> list[Position]:
    """The seeded demo portfolio (app/data/portfolio.json) as positions labelled "demo holdings": never held at any
    broker, no cost basis (avg_px 0) and no marks."""
    from ..portfolio import load_holdings

    return [Position(symbol=h["ticker"], asset="equity", qty=h["shares"], avg_px=0.0, broker="demo",
                     account=DEMO_LABEL) for h in load_holdings()]


@router.get("/positions", response_model=list[Position])
async def get_positions(request: Request, refresh: bool = False, include_demo: bool = False) -> list[Position]:
    b = get_broker(request.app)
    ensure_started(request.app)
    if refresh:  # the sim itself, or the sim behind Webull that holds the option and prediction legs
        sim = b if isinstance(b, SimBroker) else getattr(b, "sim", None)
        if sim is not None:
            await sim.refresh_marks()
    rows = await _call(b.positions())
    return rows + (demo_positions() if include_demo else [])


@router.get("/orders", response_model=list[Order])
async def get_orders(request: Request, status: Literal["filled", "open", "cancelled", "rejected"] | None = None,
                     days: int = Query(7, ge=1, le=30)) -> list[Order]:
    b = get_broker(request.app)
    ensure_started(request.app)
    if hasattr(b, "order_history"):  # Webull: history over the last `days` (bounded windows) + open orders
        return await _call(b.orders(status, days=days))
    return await _call(b.orders(status))


async def _short(b, symbols: list[str]) -> dict[str, dict]:
    if hasattr(b, "short_status"):
        return await b.short_status(symbols)
    out = {}
    for s in symbols:
        v = await b.can_short(s) if hasattr(b, "can_short") else None
        out[s] = {"symbol": s, "can_short": v, "reason": "simulated: no borrow model" if v else "unknown"}
    return out


def _symbols(raw: str | None) -> list[str]:
    syms = [s.strip().upper() for s in (raw or "").split(",") if s.strip()]
    if len(syms) > 100 or any(len(s) > 12 or not s.replace(".", "").replace("-", "").isalnum() for s in syms):
        raise HTTPException(422, "symbols: up to 100 comma-separated tickers")
    return syms


@router.get("/broker/capabilities")
async def capabilities(request: Request, symbols: str | None = None) -> dict:
    """What the active broker can do now: option orders (options_supported / options_route), extended hours, order
    reconciliation, and short-sale readiness per symbol (can_short True / False / None with the reason)."""
    b = get_broker(request.app)
    ensure_started(request.app)
    opts = bool(getattr(b, "options_supported", False))
    try:
        shorts = await _short(b, _symbols(symbols)) if symbols else {}
    except HTTPException:
        raise
    except Exception as e:
        shorts = {"error": f"{type(e).__name__}"}
    return {"broker": b.name, "options_supported": opts,
            "options_route": b.name if opts else getattr(getattr(b, "sim", None), "name", b.name),
            "extended_hours": bool(getattr(b, "extended_hours", False)),
            "reconcile": hasattr(b, "reconcile"), "can_short": shorts,
            "note": ("Webull paper: options documented by the OpenAPI but unverified on the paper sandbox; they stay "
                     "simulated unless WEBULL_OPTIONS=1." if hasattr(b, "reconcile") and not opts else None)}


@router.get("/broker/shortable/{symbol}")
async def shortable(symbol: str, request: Request) -> dict:
    syms = _symbols(symbol)
    if len(syms) != 1:
        raise HTTPException(422, "one ticker")
    res = await _short(get_broker(request.app), syms)
    return res.get(syms[0]) or {"symbol": syms[0], "can_short": None, "reason": "unknown"}


@router.get("/broker/reconcile")
async def reconcile_status(request: Request) -> dict:
    return get_reconciler(request.app).status()


@router.post("/broker/reconcile/start")
async def reconcile_start(request: Request) -> dict:
    request.app.state.reconcile_stopped_by_user = False
    r = get_reconciler(request.app)
    started = r.start()
    return {"started": started, **r.status()}


@router.post("/broker/reconcile/stop")
async def reconcile_stop(request: Request) -> dict:
    request.app.state.reconcile_stopped_by_user = True  # no auto-start until started again
    r = get_reconciler(request.app)
    stopped = await r.stop()
    return {"stopped": stopped, **r.status()}


@router.post("/broker/reconcile/run")
async def reconcile_run(request: Request) -> dict:
    """One reconciliation pass now, even outside the session (read-only at the broker)."""
    res = await get_reconciler(request.app).run_once(force=True)
    return res


MANUAL_GATE_TIMEOUT_S = 12.0


def _refuse(code: str, detail: str) -> HTTPException:
    return HTTPException(409, f"{code}: {detail}")


async def _held(broker, symbol: str) -> float:
    """The signed position the broker reports in ``symbol`` (0 when it cannot be read: every order then counts as
    opening, the conservative reading)."""
    try:
        rows = await asyncio.wait_for(broker.positions(), 8.0)
    except Exception:
        return 0.0
    return sum(float(p.qty) for p in rows or [] if (p.symbol or "").upper() == symbol.upper())


async def _option_mid(broker, symbol: str, body: OrderRequest) -> tuple[float | None, float | None]:
    if body.ref_px:
        return float(body.ref_px), body.ref_half_spread
    sim = broker if isinstance(broker, SimBroker) else getattr(broker, "sim", None)
    quotes = getattr(sim, "quotes", None)
    try:
        q = await asyncio.wait_for(quotes.option(symbol), 8.0) if quotes is not None else None
    except Exception:
        q = None
    return (q.mid, q.half_spread) if q is not None and q.mid and q.mid > 0 else (None, None)


async def _equity_px(app, broker, symbol: str, body: OrderRequest) -> float | None:
    """The price the budget sizes a manual equity order at: the supplied reference, the cached Massive price, the
    broker's own mark, its quote provider (``capital.order_price``, the same order as the bridges and staged plans)."""
    from ..capital import service as cap

    px, _src = await cap.order_price(app, broker, symbol, body.ref_px)
    return px


async def _capital_gate(app, broker, notional: float, margin: float, what: str) -> dict:
    """The capital budget for one exposure-increasing manual order, failing closed (an unreadable account, a failed
    check or a broker with no account read refuses it)."""
    from ..capital import service as cap

    try:
        chk = await cap.check(app, broker=broker, event=None, add_notional=notional, add_margin=margin)
    except Exception as e:
        raise _refuse("CAPITAL_BUDGET", f"the capital check failed ({type(e).__name__}); {what} is refused (fail "
                                        "closed).")
    if not chk.get("checked"):
        raise _refuse("CAPITAL_BUDGET", f"capital not checked ({chk.get('note')}); {what} is refused (fail closed).")
    if cap.refused(chk):
        raise _refuse("CAPITAL_BUDGET", cap.refusal_text(chk).split(": ", 1)[-1])
    return chk


async def gate_manual_order(app, broker, body: OrderRequest) -> dict:
    """POST /orders is the manual route. It passes the same liquidity caps and capital budget as the bridges and the
    staged plans, but refuses (409) instead of cutting, because the caller named the size:

    - equity, both sides: <= 10% of the opening 5-minute volume and <= what is left of 1% of ADV today (account
      scope; no cached numbers: not capped, labelled ``unknown``);
    - option: <= 10% of the contract's volume and <= 5% of its open interest (Massive snapshot; none: ``unknown``);
    - capital: a sell that opens or adds to a short equity position, or an option order that opens or adds to a
      position, must fit the gross and per-event budget and buying power. Its price must be known and the account
      readable, else it is refused (fail closed). Equity buys that open a long and orders that only reduce a position
      are not budget-checked (the broker's own cash check still applies);
    - prediction legs: simulated, and not depth-capped here (a request carries no book).

    Returns the gate outcome; ``record`` is the equity participation to count once the order is sent."""
    from ..capital import budget as cb
    from ..liquidity import gate as liq

    out: dict = {"liquidity": None, "capital": None, "record": 0.0}
    sym, qty = body.symbol.upper(), float(body.qty)
    if body.asset == "prediction":
        out["liquidity"] = {"status": "unknown", "note": "prediction legs on the manual route are simulated and not "
                                                         "depth-capped (the request carries no book)"}
        return out
    held = await _held(broker, sym)
    if body.asset == "equity":
        lq = liq.equity_check(app, sym, qty)
        out["liquidity"] = {k: v for k, v in lq.items() if k != "allowed"}
        if lq["status"] == "capped":
            raise _refuse("LIQUIDITY_CAPPED", f"{lq['rule']}: at most {lq['allowed']:g} shares of {sym} now "
                                              f"(asked {qty:g}).")
        out["record"] = qty
        opening = max(0.0, qty - max(0.0, held)) if body.side == "sell" else 0.0
        if opening > 0:
            px = await _equity_px(app, broker, sym, body)
            if px is None:
                raise _refuse("CAPITAL_BUDGET", f"no price for {sym}: the short's notional is unknown, so the "
                                                "budget cannot be checked (fail closed). Send ref_px.")
            out["capital"] = await _capital_gate(app, broker, opening * px, cb.REG_T_INITIAL * opening * px,
                                                 f"this sell of {opening:g} {sym} short")
        return out
    from ..options.quotes import parse_occ

    occ = parse_occ(sym)
    if occ is not None:
        from ..liquidity.service import service_for
        try:
            view = await asyncio.wait_for(service_for(app).option(occ["underlying"], occ["strike"], occ["expiry"],
                                                                  occ["right"]), MANUAL_GATE_TIMEOUT_S)
        except Exception as e:
            view = {"available": False, "reason": f"option liquidity unavailable ({type(e).__name__})"}
        cap_n = view.get("max_order_contracts") if view.get("available") else None
        if cap_n is not None and qty > float(cap_n) + 1e-9:
            raise _refuse("LIQUIDITY_CAPPED", f"option participation: at most {float(cap_n):g} contracts of {sym} "
                                              f"per order (10% of volume, 5% of open interest; asked {qty:g}).")
        out["liquidity"] = ({"status": "within_caps", "max_order_contracts": cap_n} if cap_n is not None else
                            {"status": "unknown", "note": view.get("reason") or "no volume / open interest"})
    signed = qty if body.side == "buy" else -qty
    opening = max(0.0, abs(held + signed) - abs(held)) if held * signed >= 0 else max(0.0, qty - abs(held))
    if opening > 0:
        mid, half = await _option_mid(broker, sym, body)
        req = cb.option_requirement("cash_secured_put" if (occ or {}).get("right") == "put" else "single",
                                    1 if body.side == "buy" else -1, opening, mid, half,
                                    strike=(occ or {}).get("strike"))
        if req is None or (body.side == "sell" and occ is None):
            raise _refuse("CAPITAL_BUDGET", f"no option price for {sym}: its requirement is unknown, so the budget "
                                            "cannot be checked (fail closed).")
        # option legs settle where they are filled: Webull paper's simulator unless WEBULL_OPTIONS=1
        acct = broker if isinstance(broker, SimBroker) or getattr(broker, "options_supported", False) else \
            (getattr(broker, "sim", None) or broker)
        out["capital"] = await _capital_gate(app, acct, req, req, f"this option order ({opening:g} {sym})")
    return out


@router.post("/orders", response_model=Order, status_code=201)
async def post_order(body: OrderRequest, request: Request) -> Order:
    """The manual order route: gated by the liquidity caps and the capital budget (``gate_manual_order``)."""
    if getattr(request.state, "remote", False):  # a caller outside localhost never picks its own fill price
        body = body.model_copy(update={"ref_px": None, "ref_half_spread": None, "ref_source": None})
    broker = get_broker(request.app)
    g = await gate_manual_order(request.app, broker, body)
    order = await _call(broker.place_order(body))
    if g["record"] and order.status != "rejected":
        from ..liquidity import gate as liq
        liq.record_equity(request.app, body.symbol, g["record"])
    if order.status == "rejected":
        raise HTTPException(422, order.reject_reason or "order rejected")
    return order


@router.delete("/orders/{order_id}", response_model=Order)
async def delete_order(order_id: str, request: Request) -> Order:
    return await _call(get_broker(request.app).cancel(order_id))


@router.post("/account/reset", response_model=Account)
async def reset_account(request: Request, body: ResetIn | None = None) -> Account:
    b = get_broker(request.app)
    sim = b if isinstance(b, SimBroker) else getattr(b, "sim", None)
    if sim is None:
        raise HTTPException(409, "Only the simulated account can be reset.")
    if b is not sim:
        raise HTTPException(409, "Webull paper is the active broker; reset its paper account in the Webull app. "
                                 "Use the simulator only by unsetting BROKER=webull.")
    return await sim.reset(body.starting_cash if body else None)
