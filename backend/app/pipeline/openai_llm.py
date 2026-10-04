"""OpenAI as an LLM provider, in the same role as Gemini: it reads text into fields and writes rationales; it never
decides a trade. Every field it produces goes through the same checks as Gemini's (allowed class set, the rule
parser in ``app.contracts.classify``, ``app.mapping.validate_mappings``).

Official ``openai`` SDK, Responses API with strict structured outputs (``text.format`` = ``json_schema``), async
client, 8 s timeout, the SDK's own retries off: 429 / 5xx / timeouts are retried here with Gemini's capped backoff.

Model: ``OPENAI_MODEL`` when GET /v1/models lists it for this key. When it is set but not listed, the provider refuses
(``LLMError``, with a plain reason) so the chain moves on to the next provider; it never substitutes a model silently.
When it is unset, the newest general text model the key lists is used (``pick_model``). No model id is hard-coded.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Any

from . import llm as _llm  # retry policy read at call time: the same knobs (and test overrides) as Gemini
from .llm import MODELS_TTL_S, TIMEOUT_S, BACKEND, JSONProvider, LLMError, parse_json_text, strict_json_schema

log = logging.getLogger("polybridge.llm.openai")

_models_cache: dict[str, tuple[float, list[dict]]] = {}   # sha256(key)[:16] -> (fetched monotonic, models)
_clients: dict[tuple[str, int], Any] = {}                 # (key id, event loop id) -> AsyncOpenAI
_no_temperature: set[str] = set()                         # models that rejected `temperature` (reasoning models)

# Ids that are not general text models (audio, images, embeddings, moderation, realtime, search, ...).
_SPECIAL = re.compile(r"(audio|realtime|transcribe|tts|whisper|image|dall-e|embedding|moderation|search|"
                      r"instruct|computer-use|davinci|babbage|sora|codex|deep-research|chat-latest)")
_GENERAL = re.compile(r"^(gpt-\d|o\d)")
_DATED = re.compile(r"-\d{4}-\d{2}-\d{2}$|-\d{4}$")


def openai_key() -> str | None:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if key:
        return key
    try:
        from polybridge_research.massive import load_api_key
        return load_api_key("OPENAI_API_KEY", search_from=BACKEND, interactive=False)
    except Exception:
        return None


def _key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]  # never the key itself


def make_client(api_key: str, timeout_s: float = TIMEOUT_S, http_client: Any = None):
    from openai import AsyncOpenAI
    kw = {"http_client": http_client} if http_client is not None else {}
    return AsyncOpenAI(api_key=api_key, timeout=timeout_s, max_retries=0, **kw)


def _shared_client(api_key: str, timeout_s: float):
    """One AsyncOpenAI per key and event loop (a per-request provider must not open a connection pool per request)."""
    k = (_key_id(api_key), id(asyncio.get_running_loop()))
    c = _clients.get(k)
    if c is None:
        c = _clients[k] = make_client(api_key, timeout_s)
    return c


def _status(e: BaseException) -> int | None:
    s = getattr(e, "status_code", None)
    return s if isinstance(s, int) else None


async def list_models(api_key: str, client: Any = None, use_cache: bool = True) -> list[dict]:
    """GET /v1/models ([{id, created, owned_by}]), cached per key for an hour. Raises LLMError with the HTTP status
    (an invalid key is 401) and never the key."""
    kid = _key_id(api_key)
    hit = _models_cache.get(kid)
    if use_cache and hit and time.monotonic() - hit[0] < MODELS_TTL_S:
        return hit[1]
    c = client or _shared_client(api_key, TIMEOUT_S)
    try:
        models = [{"id": m.id, "created": getattr(m, "created", 0) or 0, "owned_by": getattr(m, "owned_by", None)}
                  async for m in c.models.list()]
    except Exception as e:
        s = _status(e)
        raise LLMError(f"OpenAI model list failed: {f'HTTP {s}' if s else type(e).__name__}") from None
    _models_cache[kid] = (time.monotonic(), models)
    return models


def general_models(models: list[dict]) -> list[dict]:
    return [m for m in models or [] if _GENERAL.match(str(m.get("id") or "")) and not _SPECIAL.search(str(m["id"]))]


def pick_model(models: list[dict], configured: str | None) -> tuple[str | None, str | None]:
    """(model, reason it cannot be used). Configured and listed: use it. Configured and not listed: (None, reason),
    never a substitute. Not configured: the newest general text model the key lists, preferring a "mini" variant
    (the app's calls are short JSON answers under an 8 s timeout) and an undated alias over a dated snapshot."""
    ids = {str(m.get("id")) for m in models or []}
    if configured:
        if configured in ids:
            return configured, None
        return None, f"OPENAI_MODEL {configured} is not listed by GET /v1/models for this key"
    cands = general_models(models)
    if not cands:
        return None, "no general text model is listed by GET /v1/models for this key"
    best = max(cands, key=lambda m: ("mini" in m["id"] and "nano" not in m["id"], not _DATED.search(m["id"]),
                                     int(m.get("created") or 0), m["id"]))
    return best["id"], None


class OpenAIProvider(JSONProvider):
    name = "openai"
    display = "OpenAI"

    def __init__(self, api_key: str, model: str | None = None, client: Any = None,
                 timeout_s: float = TIMEOUT_S) -> None:
        self.api_key = api_key
        self.configured_model = model or (os.environ.get("OPENAI_MODEL") or "").strip() or None
        self.model: str | None = self.configured_model
        self.fell_back_reason: str | None = None
        self._client, self.timeout_s = client, timeout_s
        self._ready = False

    @property
    def label(self) -> str:
        return f"openai:{self.model or 'unresolved'}"

    def info(self, live: bool) -> dict:
        return {"provider": "openai", "model": self.model, "live": live, "fell_back_reason": self.fell_back_reason}

    def client(self):
        return self._client or _shared_client(self.api_key, self.timeout_s)

    async def ensure_model(self) -> str:
        """Resolve the model against GET /v1/models once. Raises LLMError when it cannot be used."""
        if self._ready and self.model:
            return self.model
        model, reason = pick_model(await list_models(self.api_key, self.client()), self.configured_model)
        if not model:
            raise LLMError(reason or "no OpenAI model")
        self.model, self._ready = model, True
        return model

    async def _generate(self, prompt: str, schema: dict) -> dict:
        from openai import APIConnectionError, APITimeoutError
        model = await self.ensure_model()
        fmt = {"format": {"type": "json_schema", "name": "answer", "schema": strict_json_schema(schema),
                          "strict": True}}
        retries = 0
        while True:
            kw: dict = {"model": model, "input": prompt, "text": fmt}
            if model not in _no_temperature:
                kw["temperature"] = 0.0
            try:
                r = await self.client().responses.create(**kw)
            except (APITimeoutError, APIConnectionError):
                if retries + 1 < _llm.RETRY_ATTEMPTS:
                    retries += 1
                    await asyncio.sleep(_llm.RETRY_BASE_S * retries)
                    continue
                raise LLMError("OpenAI call failed: timeout or connection error") from None
            except Exception as e:
                s = _status(e)
                if s == 400 and "temperature" in str(e).lower() and "temperature" in kw:
                    _no_temperature.add(model)  # a reasoning model: ask again without it (not counted as a retry)
                    continue
                if s in _llm.RETRY_STATUS and retries + 1 < _llm.RETRY_ATTEMPTS:
                    retries += 1
                    try:
                        wait = float(getattr(getattr(e, "response", None), "headers", {}).get("retry-after", ""))
                    except (TypeError, ValueError):
                        wait = _llm.RETRY_BASE_S * retries
                    await asyncio.sleep(min(max(wait, 0.5), _llm.RETRY_MAX_WAIT_S))
                    continue
                raise LLMError(f"OpenAI call failed: {f'HTTP {s}' if s else type(e).__name__}") from None
            try:
                text = r.output_text
            except Exception:
                text = ""
            if not (text or "").strip():
                raise LLMError("OpenAI returned no text (refusal or incomplete answer)")
            return parse_json_text(text, vendor="OpenAI")


class ChainProvider:
    """OpenAI first, then the next provider (Gemini), then the caller's rules. Per request: the first provider that is
    ready (OpenAI: its model is listed for the key) answers; when one fails a call, the next one is asked for that call
    and the rest of the request. ``label`` / ``model`` / ``info`` / ``name`` describe the provider that answered last,
    so a response never claims a provider that did not answer it."""

    def __init__(self, providers: list) -> None:
        self.providers = list(providers)
        self._i = 0
        self._skipped: list[str] = []
        self._checked = False

    @property
    def active(self):
        return self.providers[min(self._i, len(self.providers) - 1)]

    @property
    def name(self) -> str:
        return self.active.name

    @property
    def display(self) -> str:
        return getattr(self.active, "display", self.active.name)

    @property
    def label(self) -> str:
        return self.active.label

    @property
    def model(self):
        return getattr(self.active, "model", None)

    @property
    def fell_back_reason(self) -> str | None:
        parts = [*self._skipped, getattr(self.active, "fell_back_reason", None)]
        return "; ".join(dict.fromkeys(p for p in parts if p)) or None

    def info(self, live: bool) -> dict:
        return {**self.active.info(live), "fell_back_reason": self.fell_back_reason}

    def _skip(self, reason: str) -> bool:
        """Move to the next provider; False when there is none."""
        if self._i + 1 >= len(self.providers):
            return False
        nxt = self.providers[self._i + 1]
        self._skipped.append(f"{getattr(self.active, 'display', self.active.name)}: {reason}; "
                             f"used {getattr(nxt, 'display', nxt.name)}")
        log.warning("LLM provider %s skipped (%s)", self.active.name, reason)
        self._i += 1
        return True

    async def _ensure(self) -> None:
        while not self._checked:
            p = self.active
            if hasattr(p, "ensure_model"):
                try:
                    await p.ensure_model()
                except LLMError as e:
                    if self._skip(str(e)):
                        continue
                    raise
            self._checked = True

    async def _call(self, method: str, *args):
        await self._ensure()
        while True:
            try:
                return await getattr(self.active, method)(*args)
            except LLMError as e:
                if not self._skip(str(e)):
                    raise
                self._checked = False
                await self._ensure()

    async def _generate(self, prompt: str, schema: dict) -> dict:
        return await self._call("_generate", prompt, schema)

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str:
        return await self._call("classify", question, allowed, ticker)

    async def explain(self, result: dict) -> str:
        return await self._call("explain", result)

    async def map_tickers(self, question: str, universe: list[dict], max_items: int = 6) -> list:
        return await self._call("map_tickers", question, universe, max_items)
