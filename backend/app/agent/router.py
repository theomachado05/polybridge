"""GET /agent/tools and POST /agent/tool/{name} for the ElevenLabs voice agent."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from .tools import NAMES, catalogue, run_tool

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/tools")
def list_tools() -> dict:
    return {"tools": catalogue()}


@router.post("/tool/{name}")
async def call_tool(name: str, request: Request, body: dict | None = Body(default=None)) -> dict:
    if name not in NAMES:
        raise HTTPException(404, f"No tool {name}.")
    return await run_tool(name, request, body or {})
