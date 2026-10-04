from __future__ import annotations

import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WEB_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "[::1]", "localhost", "testserver"}
FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip", "cf-connecting-ip",
                   "true-client-ip", "ngrok-trace-id")


def _host_name(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[: h.find("]") + 1] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def is_local(request: Request) -> bool:
    client = request.client.host if request.client else ""
    if client not in LOCAL_CLIENTS:
        return False
    if any(h in request.headers for h in FORWARD_HEADERS):
        return False
    return _host_name(request.headers.get("host", "")) in LOCAL_HOSTS


def is_local_web_app(request: Request) -> bool:
    return is_local(request) and request.headers.get("origin", "") in WEB_ORIGINS


async def guard_remote_writes(request: Request, call_next):
    remote = not is_local(request)
    request.state.remote = remote
    if remote and request.method.upper() not in SAFE_METHODS:
        secret = os.environ.get("AGENT_TOOL_SECRET") or ""
        given = request.headers.get("x-agent-secret") or ""
        if not secret:
            return JSONResponse(status_code=401, content={"detail": (
                "Remote write refused: this backend is reachable from outside localhost (a tunnel). Set "
                "AGENT_TOOL_SECRET and send it as X-Agent-Secret on each voice-agent tool.")})
        if not hmac.compare_digest(given, secret):
            return JSONResponse(status_code=401, content={"detail": "Missing or wrong X-Agent-Secret."})
    return await call_next(request)
