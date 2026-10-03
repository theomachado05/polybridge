"""Write protection for a backend that may be reachable through a public tunnel (the voice-agent setup runs
``ngrok http 8000`` / ``cloudflared``, which exposes the whole app).

A request is *local* when it comes from the loopback interface with a local Host header and no proxy-forwarding
header (a tunnel forwards from 127.0.0.1 but always adds X-Forwarded-For / Forwarded / Cf-Connecting-Ip and keeps
its public Host). The browser UI on localhost and every test client are local.

Any non-local request that can change state (anything but GET / HEAD / OPTIONS: POST /orders, DELETE /orders/{id},
POST /account/reset, POST /proposals/{id}/approve, POST /bridges, POST /agent/tool/*, ...) must carry
``X-Agent-Secret`` equal to ``AGENT_TOOL_SECRET``; with the variable unset every such request is refused (401). A
non-local POST /orders never chooses its own fill price (``request.state.remote`` lets the route drop ref_px)."""
from __future__ import annotations

import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}  # "testclient": Starlette's TestClient
LOCAL_HOSTS = {"127.0.0.1", "::1", "[::1]", "localhost", "testserver"}
FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip", "cf-connecting-ip",
                   "true-client-ip", "ngrok-trace-id")


def _host_name(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):  # [::1]:8000
        return h[: h.find("]") + 1] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def is_local(request: Request) -> bool:
    client = request.client.host if request.client else ""
    if client not in LOCAL_CLIENTS:
        return False
    if any(h in request.headers for h in FORWARD_HEADERS):
        return False
    return _host_name(request.headers.get("host", "")) in LOCAL_HOSTS


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
