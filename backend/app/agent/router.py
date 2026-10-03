"""GET /agent/tools and POST /agent/tool/{name} for the ElevenLabs voice agent."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Body, Header, HTTPException, Request

from ..security import is_local_web_app
from .tools import NAMES, catalogue, run_tool

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/tools")
def list_tools() -> dict:
    return {"tools": catalogue()}


@router.post("/tool/{name}")
async def call_tool(name: str, request: Request, body: dict | None = Body(default=None),
                    x_agent_secret: str | None = Header(default=None)) -> dict:
    # Set: required on every call except the web app's own page on localhost (the voice widget's client tools run
    # in the browser, which cannot hold a secret). Unset: open on localhost only; a call through a tunnel is refused
    # by app.security.guard_remote_writes (which also protects every other write route).
    secret = os.environ.get("AGENT_TOOL_SECRET")
    if secret and not is_local_web_app(request) and not hmac.compare_digest(x_agent_secret or "", secret):
        raise HTTPException(401, "Missing or wrong X-Agent-Secret.")
    if name not in NAMES:
        raise HTTPException(404, f"No tool {name}.")
    return await run_tool(name, request, body or {})
