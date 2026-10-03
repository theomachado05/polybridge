"""HTTP surface for the active broker. A broker failure is a clean 4xx/502, never a 500."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import get_broker
from .models import Account, BrokerError, Order, OrderRequest, Position
from .sim import SimBroker

router = APIRouter()
log = logging.getLogger(__name__)


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
    acct = await _call(b.account())
    ext = getattr(b, "extended_hours", None)
    return acct.model_copy(update={**market_session(request.app),
                                   "extended_hours": acct.extended_hours if acct.extended_hours is not None else ext})


@router.get("/positions", response_model=list[Position])
async def get_positions(request: Request, refresh: bool = False) -> list[Position]:
    b = get_broker(request.app)
    if refresh:  # the sim itself, or the sim behind Webull that holds the option and prediction legs
        sim = b if isinstance(b, SimBroker) else getattr(b, "sim", None)
        if sim is not None:
            await sim.refresh_marks()
    return await _call(b.positions())


@router.get("/orders", response_model=list[Order])
async def get_orders(request: Request, status: Literal["filled", "open", "cancelled", "rejected"] | None = None) -> list[Order]:
    return await _call(get_broker(request.app).orders(status))


@router.post("/orders", response_model=Order, status_code=201)
async def post_order(body: OrderRequest, request: Request) -> Order:
    if getattr(request.state, "remote", False):  # a caller outside localhost never picks its own fill price
        body = body.model_copy(update={"ref_px": None, "ref_half_spread": None, "ref_source": None})
    order = await _call(get_broker(request.app).place_order(body))
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
