import asyncio
import json

import httpx2
import pytest

from app.pipeline import llm, openai_llm
from app.pipeline.openai_llm import ChainProvider, OpenAIProvider, pick_model

MODELS = [{"id": "gpt-9-mini", "object": "model", "created": 200, "owned_by": "openai"},
          {"id": "gpt-test", "object": "model", "created": 210, "owned_by": "openai"},
          {"id": "gpt-9-audio-preview", "object": "model", "created": 300, "owned_by": "openai"},
          {"id": "text-embedding-3-small", "object": "model", "created": 400, "owned_by": "openai"}]


def _response(payload: dict, model: str = "gpt-9-mini") -> dict:
    return {"id": "resp_1", "object": "response", "created_at": 1, "model": model, "status": "completed",
            "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps(payload), "annotations": []}]}],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": []}


def fake_openai(answers, statuses=(), models=MODELS):
    calls = {"responses": [], "models": 0}
    statuses = list(statuses)

    def handler(req: httpx2.Request):
        assert "test-key" not in str(req.url)
        if req.url.path.endswith("/models"):
            calls["models"] += 1
            return httpx2.Response(200, json={"object": "list", "data": models})
        calls["responses"].append(json.loads(req.content))
        if statuses:
            return httpx2.Response(statuses.pop(0), headers={"retry-after": "0"},
                                   json={"error": {"message": "slow down", "type": "rate_limit"}})
        i = min(len(calls["responses"]) - 1 - 0, len(answers) - 1)
        return httpx2.Response(200, json=_response(answers[min(i, len(answers) - 1)]))

    client = openai_llm.make_client("test-key", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    return client, calls


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(openai_llm.asyncio, "sleep", fake_sleep)
    return slept


def test_pick_model_configured_listed_unlisted_and_default():
    assert pick_model(MODELS, "gpt-test") == ("gpt-test", None)
    model, reason = pick_model(MODELS, "gpt-nope")
    assert model is None and "OPENAI_MODEL gpt-nope is not listed" in reason
    assert pick_model(MODELS, None) == ("gpt-9-mini", None)
    assert pick_model([{"id": "text-embedding-3-small", "created": 1}], None)[0] is None


def test_strict_schema_closes_every_object():
    _, schema = llm.map_request("Q?", [{"ticker": "SPY", "name": "S&P"}])
    s = llm.strict_json_schema(schema)
    assert s["type"] == "object" and s["additionalProperties"] is False and s["required"] == ["mappings"]
    item = s["properties"]["mappings"]["items"]
    assert item["additionalProperties"] is False and set(item["required"]) == {"ticker", "direction", "impact_pct",
                                                                               "rationale"}
    assert item["properties"]["impact_pct"]["type"] == "number"


def test_classify_sends_strict_json_schema_and_parses():
    client, calls = fake_openai([{"event_class": "macro_fed"}])
    p = OpenAIProvider("test-key", model="gpt-test", client=client)
    assert run(p.classify("Will the Fed cut?", ["macro_fed", "unsupported"])) == "macro_fed"
    body = calls["responses"][0]
    assert body["model"] == "gpt-test" and body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["properties"]["event_class"]["enum"] == ["macro_fed", "unsupported"]
    assert p.label == "openai:gpt-test" and p.info(True)["provider"] == "openai"


def test_class_outside_allowed_set_is_an_error():
    client, _ = fake_openai([{"event_class": "sports"}])
    p = OpenAIProvider("test-key", model="gpt-test", client=client)
    with pytest.raises(llm.LLMError, match="OpenAI returned a class outside"):
        run(p.classify("Q?", ["macro_fed", "unsupported"]))


def test_retries_429_then_succeeds(no_sleep, monkeypatch):
    monkeypatch.setattr(llm, "RETRY_ATTEMPTS", 3)
    client, calls = fake_openai([{"event_class": "macro_fed"}], statuses=[429, 503])
    p = OpenAIProvider("test-key", model="gpt-test", client=client)
    assert run(p.classify("Will the Fed cut?", ["macro_fed", "unsupported"])) == "macro_fed"
    assert len(calls["responses"]) == 3 and len(no_sleep) == 2
    assert all(0.5 <= s <= llm.RETRY_MAX_WAIT_S for s in no_sleep)


def test_persistent_429_raises_without_the_key(no_sleep, monkeypatch):
    monkeypatch.setattr(llm, "RETRY_ATTEMPTS", 3)
    client, calls = fake_openai([{"event_class": "macro_fed"}], statuses=[429] * 5)
    p = OpenAIProvider("test-key", model="gpt-test", client=client)
    with pytest.raises(llm.LLMError) as e:
        run(p.classify("Q?", ["macro_fed", "unsupported"]))
    assert "HTTP 429" in str(e.value) and "test-key" not in str(e.value)
    assert len(calls["responses"]) == llm.RETRY_ATTEMPTS


def test_model_not_listed_refuses():
    client, calls = fake_openai([{"event_class": "macro_fed"}])
    p = OpenAIProvider("test-key", model="gpt-nope", client=client)
    with pytest.raises(llm.LLMError, match="not listed"):
        run(p.classify("Q?", ["macro_fed", "unsupported"]))
    assert calls["responses"] == []


class FakeGemini(llm.JSONProvider):
    name, display, model = "gemini", "Gemini", "gemini-test"
    fell_back_reason = None

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    @property
    def label(self):
        return f"gemini:{self.model}"

    def info(self, live):
        return {"provider": "gemini", "model": self.model, "live": live, "fell_back_reason": None}

    async def _generate(self, prompt, schema):
        self.calls += 1
        return self.payload


def test_chain_model_not_listed_falls_back_to_gemini_and_says_so():
    client, calls = fake_openai([{"event_class": "elections"}])
    gem = FakeGemini({"event_class": "macro_fed"})
    chain = ChainProvider([OpenAIProvider("test-key", model="gpt-nope", client=client), gem])
    assert run(chain.classify("Q?", ["macro_fed", "elections", "unsupported"])) == "macro_fed"
    assert chain.label == "gemini:gemini-test" and chain.name == "gemini" and gem.calls == 1
    assert "OPENAI_MODEL gpt-nope is not listed" in chain.fell_back_reason and calls["responses"] == []
    assert chain.info(True)["provider"] == "gemini"


def test_chain_failed_openai_call_moves_to_gemini(no_sleep):
    client, _ = fake_openai([{}], statuses=[500] * 5)
    chain = ChainProvider([OpenAIProvider("test-key", model="gpt-test", client=client), FakeGemini({"rationale": "R."})])
    assert run(chain.explain({"family": "x"})) == "R."
    assert chain.name == "gemini" and "HTTP 500" in chain.fell_back_reason


def test_chain_openai_answers_first():
    client, _ = fake_openai([{"event_class": "elections"}])
    gem = FakeGemini({"event_class": "macro_fed"})
    chain = ChainProvider([OpenAIProvider("test-key", client=client), gem])
    assert run(chain.classify("Q?", ["macro_fed", "elections", "unsupported"])) == "elections"
    assert chain.label == "openai:gpt-9-mini" and gem.calls == 0 and chain.fell_back_reason is None


@pytest.mark.parametrize("choice,okey,gkey,expect", [
    ("auto", True, True, ["openai", "gemini"]),
    ("auto", True, False, ["openai"]),
    ("auto", False, True, "gemini"),
    ("auto", False, False, "rules"),
    ("openai", True, True, ["openai"]),
    ("openai", False, True, "rules"),
    ("gemini", True, True, "gemini"),
    ("rules", True, True, "rules"),
])
def test_factory_order(monkeypatch, choice, okey, gkey, expect):
    monkeypatch.setenv("LLM_PROVIDER", choice)
    monkeypatch.setattr(openai_llm, "openai_key", lambda: "test-key" if okey else None)
    monkeypatch.setattr(llm, "gemini_key", lambda: "g-key" if gkey else None)
    p = llm.default_provider()
    if isinstance(expect, list):
        assert isinstance(p, ChainProvider) and [x.name for x in p.providers] == expect
    else:
        assert p.name == expect
    if expect == "rules" and choice != "auto":
        assert "LLM_PROVIDER" in llm.no_llm_reason(p)


def test_contract_field_disagreement_rules_win_and_flagged(monkeypatch):
    from app.contracts import classify as cc

    rule = {"type": "touch_ticket", "mechanism": "touch", "linkable": True, "checks": [], "reasons": [],
            "fields": {"underlying": "NVDA", "level": 200.0, "direction": "up", "window_end": "2026-12-31"}}
    monkeypatch.setattr(cc, "rules_classify", lambda q, r=None, m=None: dict(rule))
    client, _ = fake_openai([{"type": "touch_ticket", "underlying": "NVDA", "level": 250, "direction": "up",
                              "date": "2026-12-31"}])
    p = ChainProvider([OpenAIProvider("test-key", model="gpt-test", client=client)])
    res = run(cc.classify_contract("Will NVDA hit $200 by Dec 31?", "rules", {}, p))
    assert res["fields"]["level"] == 200.0
    assert res["flagged"] is True
    ag = res["gemini_agreement"]
    assert ag["used"] and ag["provider"] == "openai:gpt-test" and ag["agree"] is False
    assert ag["disagreements"] == [{"field": "level", "rules": 200.0, "gemini": 250.0}]


def test_ai_block_labels():
    from app.pipeline.service import AIInfo, FitResponse, ai_block

    client, _ = fake_openai([{}])
    p = OpenAIProvider("test-key", model="gpt-test", client=client)
    block = ai_block(p, "openai:gpt-test", True, [])
    assert block["provider"] == "openai" and block["model"] == "gpt-test"
    assert block["steps"] == {"classify": "openai", "explain": "openai"} and block["live"] is True
    AIInfo(**block)
    assert FitResponse.model_fields["llm"].metadata
    import re
    pat = next(m.pattern for m in FitResponse.model_fields["llm"].metadata if hasattr(m, "pattern"))
    assert re.match(pat, "openai:gpt-test") and re.match(pat, "gemini:gemini-x") and not re.match(pat, "claude:x")


def test_live_map_labels_openai(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    client, _ = fake_openai([{"mappings": [{"ticker": "ABNB", "direction": "down_on_yes", "impact_pct": 8,
                                            "rationale": "A ban would cut bookings."}]}])
    app.state.pipeline_provider = ChainProvider([OpenAIProvider("test-key", model="gpt-test", client=client)])
    try:
        r = TestClient(app).post("/map", json={"question": "Will the US ban short-term rentals such as Airbnb "
                                                           "nationwide by 2027 under a new federal law?"}).json()
    finally:
        app.state.pipeline_provider = None
        app.state.map_live_cache = None
    if r["source"] == "ai_precomputed":
        pytest.skip("question matched the precomputed library")
    assert r["source"] == "ai_live:openai:gpt-test", r
    assert r["label"] == "AI estimate (live, OpenAI gpt-test)"
    assert r["ai"]["provider"] == "openai" and r["ai"]["model"] == "gpt-test"


def _check(monkeypatch, configured, answers):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import openai_check

    if configured:
        monkeypatch.setenv("OPENAI_MODEL", configured)
    client, calls = fake_openai(answers)
    lines: list[str] = []
    code = asyncio.run(openai_check.run("test-key", client=client, out=lines.append))
    return code, "\n".join(lines), calls


def test_openai_check_ok(monkeypatch):
    code, out, calls = _check(monkeypatch, "gpt-test", [
        {"event_class": "macro_fed"}, {"rationale": "Picked by replay."},
        {"mappings": [{"ticker": "ABNB", "direction": "down_on_yes", "impact_pct": 8, "rationale": "Fewer stays."}]}])
    assert code == 0, out
    assert "OPENAI_MODEL: gpt-test -> the app uses gpt-test" in out and "latency=" in out
    assert "classify  model=gpt-test" in out and "openai:gpt-test" in out and "test-key" not in out
    assert "text-embedding" not in out
    assert len(calls["responses"]) == 3


def test_openai_check_model_not_listed_fails_without_substitute(monkeypatch):
    code, out, calls = _check(monkeypatch, "gpt-nope", [{}])
    assert code == 1 and "OPENAI_MODEL gpt-nope is not listed" in out and calls["responses"] == []


def test_openai_check_missing_key(monkeypatch, capsys):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import openai_check

    monkeypatch.setattr(openai_check, "env_key", lambda name: None)
    assert openai_check.main() == 2 and "OPENAI_API_KEY is missing" in capsys.readouterr().out
