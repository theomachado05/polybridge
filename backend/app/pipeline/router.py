"""Routes: POST /pipeline/fit, GET /library, GET /pipeline/fits (the precomputed batch)."""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Request

from .engine_adapter import EngineAdapter
from .llm import LLMProvider, default_provider
from .service import Deps, FitRequest, FitResponse, fit

router = APIRouter()
FITS = Path(__file__).resolve().parents[1] / "data" / "fits.json"
FIT_TTL_S = 300.0
FIT_CACHE_MAX = 256


class FitCache:
    """TTL + size-capped LRU, so a stream of distinct free-text questions cannot grow memory without bound."""

    def __init__(self, ttl_s: float = FIT_TTL_S, max_entries: int = FIT_CACHE_MAX,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.max_entries, self._clock = ttl_s, max_entries, clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        if self._clock() - hit[0] >= self.ttl_s:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return hit[1]

    def put(self, key: str, value: Any) -> None:
        self._data[key] = (self._clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


def get_adapter(request: Request) -> EngineAdapter:
    """Tests set app.state.pipeline_adapter (e.g. an adapter around a fake hedgecore)."""
    if not hasattr(request.app.state, "pipeline_adapter"):
        request.app.state.pipeline_adapter = EngineAdapter()
    return request.app.state.pipeline_adapter


def get_provider(request: Request, http) -> LLMProvider:
    """Tests set app.state.pipeline_provider; otherwise the provider factory (OpenAI -> Gemini -> rules, LLM_PROVIDER)."""
    p = getattr(request.app.state, "pipeline_provider", None)
    return p if p is not None else default_provider(http)


def _deps(request: Request) -> Deps:
    from ..markets import _http
    from ..equities import get_client
    http = _http(request)
    return Deps(adapter=get_adapter(request), provider=get_provider(request, http), http=http,
                massive=lambda: get_client(request),
                offline=bool(getattr(request.app.state, "pipeline_offline", False)))


@router.post("/pipeline/fit", response_model=FitResponse)
async def pipeline_fit(req: FitRequest, request: Request) -> FitResponse:
    if not isinstance(getattr(request.app.state, "cache_fit", None), FitCache):
        request.app.state.cache_fit = FitCache()
    cache: FitCache = request.app.state.cache_fit
    key = req.model_dump_json()
    hit = cache.get(key)
    if hit is not None:  # say so: any Gemini call behind it happened earlier
        return hit.model_copy(update={"ai": hit.ai.model_copy(update={"cached": True})})
    try:
        deps = _deps(request)
    except Exception:
        deps = Deps(adapter=EngineAdapter(module=None))
    value = await fit(req, deps)
    # Never cache a degraded answer, nor one where a Gemini call failed and rules/template stood in: that failure
    # may be transient (503, timeout), and caching it would pin the fallback for the whole TTL, so Retry could not
    # reach Gemini. A cached answer whose Gemini calls succeeded, or a rules-only answer with no key, stays cached.
    if not value.rationale.startswith("The fit pipeline hit an internal error") and not value.gemini_failed:
        cache.put(key, value)
    return value


@router.get("/library")
async def library(request: Request) -> dict:
    try:
        adapter = get_adapter(request)
        manifest, source = adapter.library()
        return {**manifest, "source": source, "can_score": adapter.can_score}
    except Exception:
        return {"families": [], "event_classes": [], "total_presets": 0, "source": "fallback", "can_score": False}


@router.get("/pipeline/fits")
async def precomputed_fits() -> dict:
    try:
        return json.loads(FITS.read_text())
    except (OSError, ValueError):
        return {"generated_at": None, "fits": {}}
