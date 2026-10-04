"""Gemini 429/503 are retried with backoff (Retry-After honoured, capped); a persistent error still falls back."""
import asyncio

import httpx
import pytest

from app.pipeline import llm


def _client(statuses):
    calls = []

    def handler(req):
        calls.append(req)
        code = statuses[min(len(calls) - 1, len(statuses) - 1)]
        if code == 200:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"event_class": "macro_fed"}'}]}}]})
        return httpx.Response(code, headers={"retry-after": "0"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def test_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm, "RETRY_ATTEMPTS", 3)
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    http, calls = _client([429, 503, 200])
    p = llm.GeminiProvider("k", model="gemini-2.5-flash", http=http)
    assert asyncio.run(p.classify("Will the Fed cut?", ["macro_fed", "unsupported"])) == "macro_fed"
    assert len(calls) == 3 and len(slept) == 2 and all(0.5 <= s <= llm.RETRY_MAX_WAIT_S for s in slept)


def test_persistent_503_raises_llm_error(monkeypatch):
    monkeypatch.setattr(llm, "RETRY_ATTEMPTS", 3)

    async def fake_sleep(s):
        return None

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    http, calls = _client([503])
    p = llm.GeminiProvider("k", model="gemini-2.5-flash", http=http)
    with pytest.raises(llm.LLMError, match="503"):
        asyncio.run(p.classify("Will the Fed cut?", ["macro_fed", "unsupported"]))
    assert len(calls) == 3
