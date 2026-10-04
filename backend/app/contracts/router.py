"""POST /contracts/classify, GET /ladders, GET /tickets. Never 500: failures come back as ``ok: false`` with a reason."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..pipeline.llm import default_provider
from . import live
from .classify import classify_contract

router = APIRouter(tags=["contracts"])


class ClassifyIn(BaseModel):
    question: str = Field(..., max_length=2000)
    rules: str | None = Field(None, max_length=20000)
    market: dict[str, Any] | None = None


def provider():
    """The text reader for the LLM cross-check (OpenAI -> Gemini via the provider factory; rules only without a
    key). Tests replace it."""
    return default_provider()


@router.post("/contracts/classify")
async def contracts_classify(body: ClassifyIn) -> dict:
    try:
        res = await classify_contract(body.question, body.rules, body.market, provider())
    except Exception as e:  # never 500
        return {"ok": False, "error": f"{type(e).__name__}", "type": "other", "fields": {}, "checks": [], "linkable": False}
    ev = live.evidence_for(live.contract_key(res))   # a 15-minute Bitcoin market reaches the watch-only entry
    if ev:
        res["evidence"] = ev
    return {"ok": True, **res}


@router.get("/ladders")
async def ladders() -> dict:
    return await live.ladders_board()


@router.get("/tickets")
async def tickets() -> dict:
    return await live.tickets_board()
