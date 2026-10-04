from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from ..broker import get_broker
from . import budget
from .service import snapshot

router = APIRouter()
ROUTE_TIMEOUT_S = 20.0


@router.get("/capital")
async def get_capital(request: Request) -> dict:
    try:
        broker = get_broker(request.app)
    except Exception as e:
        return {"broker": None, "account_read": False, "account_error": f"broker unavailable ({type(e).__name__})",
                "limits": budget.limits(request.app), "breaches": [{"kind": "account_unreadable"}]}
    try:
        return await asyncio.wait_for(snapshot(request.app, broker), ROUTE_TIMEOUT_S)
    except Exception as e:
        return {"broker": getattr(broker, "name", None), "account_read": False,
                "account_error": f"capital snapshot failed ({type(e).__name__})", "limits": budget.limits(request.app),
                "breaches": [{"kind": "account_unreadable"}]}
