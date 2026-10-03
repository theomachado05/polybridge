"""Liquidity routes: GET /liquidity/{ticker}, /liquidity/option, /liquidity/pm. Bounded, cached, never a 500."""
from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import APIRouter, HTTPException, Query, Request

from . import model as m
from .service import service_for

router = APIRouter()
ROUTE_TIMEOUT_S = 12.0  # above one bounded Massive round (8 s); the route answers unavailable past it


async def _bounded(coro, base: dict) -> dict:
    try:
        return m.clean(await asyncio.wait_for(coro, ROUTE_TIMEOUT_S))
    except asyncio.TimeoutError:
        return {**base, "available": False, "reason": f"timed out after {ROUTE_TIMEOUT_S:g} s"}
    except Exception as e:  # never a 500
        return {**base, "available": False, "reason": f"liquidity unavailable ({type(e).__name__})"}


@router.get("/liquidity/option")
async def liquidity_option(request: Request, underlying: str = Query(min_length=1, max_length=10),
                           strike: float = Query(gt=0, allow_inf_nan=False), expiry: str = Query(min_length=10,
                                                                                                  max_length=10),
                           right: str = Query(pattern="^(call|put)$"),
                           coverage: float = Query(default=0.5, gt=0, le=1, allow_inf_nan=False)) -> dict:
    try:
        dt.date.fromisoformat(expiry)
    except ValueError:
        raise HTTPException(422, "expiry must be YYYY-MM-DD.")
    base = {"kind": "option", "underlying": underlying.upper(), "strike": strike, "expiry": expiry, "right": right,
            "caps": m.CAPS["option"]}
    return await _bounded(service_for(request.app).option(underlying, strike, expiry, right, coverage), base)


@router.get("/liquidity/pm")
async def liquidity_pm(request: Request, source: str = Query(pattern="^(polymarket|kalshi)$"),
                       id: str = Query(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.\-]+$"),
                       token_id: str | None = Query(default=None, max_length=100, pattern=r"^[0-9]+$")) -> dict:
    base = {"kind": "pm", "source": source, "id": id, "caps": m.CAPS["pm"]}
    return await _bounded(service_for(request.app).pm(source, id, token_id), base)


@router.get("/liquidity/{ticker}")
async def liquidity_equity(ticker: str, request: Request,
                           coverage: float = Query(default=0.5, gt=0, le=1, allow_inf_nan=False),
                           qty: float | None = Query(default=None, ge=0, le=1e9, allow_inf_nan=False),
                           refresh: bool = False) -> dict:
    t = ticker.strip().upper()
    base = {"kind": "equity", "ticker": t, "caps": m.CAPS["equity"], "cost_model": m.COST_MODEL}
    if not t or len(t) > 10:
        raise HTTPException(422, "ticker must be 1-10 characters.")
    return await _bounded(service_for(request.app).equity(t, coverage, qty, refresh), base)
