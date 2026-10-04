"""make voice-agent / keys-check / gemini-check: ElevenLabs provisioning (client tools), key reporting, the Gemini
check. Offline: every HTTP call goes to a MockTransport; no key from .env is ever read (env_key is patched)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import elevenlabs_agent  # noqa: E402
import gemini_check  # noqa: E402
import keys_check  # noqa: E402

from app.agent import elevenlabs as el  # noqa: E402
from app.agent.tools import TOOLS  # noqa: E402

EL_KEY = "el-sekrit-key-123"
GEM_KEY = "gem-sekrit-key-456"


class FakeEleven:
    """A tiny in-memory ElevenLabs: tools, agents, subscription. Records every request."""

    def __init__(self, tools=None, agents=None, reject_llm=False, status=None):
        self.tools: dict[str, dict] = dict(tools or {})
        self.agents: dict[str, dict] = dict(agents or {})
        self.reject_llm, self.status = reject_llm, status
        self.requests: list[httpx.Request] = []
        self.n = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "api.elevenlabs.io"
        if request.headers.get("xi-api-key") != EL_KEY:
            return httpx.Response(401, json={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
        if self.status:
            return httpx.Response(self.status, json={"detail": "boom"})
        m, path = request.method, request.url.path
        body = json.loads(request.content) if request.content else None
        if (m, path) == ("GET", "/v1/convai/tools"):
            return httpx.Response(200, json={"tools": [{"id": i, "tool_config": c} for i, c in self.tools.items()],
                                             "has_more": False})
        if (m, path) == ("POST", "/v1/convai/tools"):
            self.n += 1
            tid = f"tool_{self.n}"
            self.tools[tid] = body["tool_config"]
            return httpx.Response(200, json={"id": tid, "tool_config": body["tool_config"]})
        if m == "PATCH" and path.startswith("/v1/convai/tools/"):
            tid = path.rsplit("/", 1)[1]
            if tid not in self.tools:
                return httpx.Response(404)
            self.tools[tid] = body["tool_config"]
            return httpx.Response(200, json={"id": tid, "tool_config": body["tool_config"]})
        if (m, path) in (("POST", "/v1/convai/agents/create"),) or (m == "PATCH" and path.startswith("/v1/convai/agents/")):
            if self.reject_llm and "llm" in body["conversation_config"]["agent"]["prompt"]:
                return httpx.Response(422, json={"detail": [{"msg": "Input should be a valid llm enum value"}]})
            if m == "POST":
                aid = f"agent_new{len(self.agents) + 1:04d}"
            else:
                aid = path.rsplit("/", 1)[1]
            self.agents[aid] = body
            return httpx.Response(200, json={"agent_id": aid, **body})
        if m == "GET" and path.startswith("/v1/convai/agents/"):
            aid = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"agent_id": aid, **self.agents[aid]}) if aid in self.agents else \
                httpx.Response(404, json={"detail": "not found"})
        if (m, path) == ("GET", "/v1/user/subscription"):
            return httpx.Response(200, json={"tier": "creator", "status": "active", "character_count": 10,
                                             "character_limit": 100000})
        return httpx.Response(404)


@pytest.fixture
def env_local(tmp_path, monkeypatch):
    p = tmp_path / ".env.local"
    monkeypatch.setattr(elevenlabs_agent, "gitignored", lambda path, repo=None: True)
    monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_ELEVENLABS_AGENT_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_LLM", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    return p


def _keys(monkeypatch, **present):
    def fake(name):
        return present.get(name)
    for mod in (elevenlabs_agent, keys_check, gemini_check):
        monkeypatch.setattr(mod, "env_key", fake)


def _run(argv, fake, env_local, monkeypatch, **keys):
    _keys(monkeypatch, **keys)
    lines: list[str] = []
    monkeypatch.setattr(elevenlabs_agent, "REPO", env_local.parent)
    code = elevenlabs_agent.main(argv, transport=httpx.MockTransport(fake), env_local=env_local, out=lines.append)
    return code, "\n".join(lines)


# ---------------------------------------------------------------- what is sent

def test_client_tools_mirror_agent_tools_exactly():
    cfgs = el.client_tool_configs()
    assert [c["name"] for c in cfgs] == [t["name"] for t in TOOLS]
    for c, t in zip(cfgs, TOOLS):
        assert c["type"] == "client" and c["expects_response"] is True and 1 <= c["response_timeout_secs"] <= 120
        assert c["description"].startswith("PolyBridge: ") and t["description"] in c["description"]
        assert set(c["parameters"]["properties"]) == set(t["parameters"]["properties"])
        assert c["parameters"]["required"] == t["parameters"]["required"]
        assert all(p.get("description") for p in c["parameters"]["properties"].values())
        assert "additionalProperties" not in c["parameters"]
    by = {c["name"]: c for c in cfgs}
    for gated in ("approve", "start_bridge"):
        assert "confirm" in by[gated]["parameters"]["required"]
        assert by[gated]["parameters"]["properties"]["confirm"]["type"] == "boolean"
        assert "said yes" in by[gated]["description"]
    assert by["fit"]["response_timeout_secs"] == 90
    assert by["propose"]["parameters"]["properties"]["tags"]["items"]["type"] == "string"
    assert by["start_bridge"]["parameters"]["properties"]["source"]["enum"] == ["live", "replay"]


def test_prompt_and_first_message_come_from_the_doc():
    prompt, first = el.prompt_from_doc()
    assert prompt.startswith("You are PolyBridge") and "confirm true" in prompt and "ack_unvalidated" in prompt
    assert first.startswith("Hi, I'm PolyBridge")
    assert "```" not in prompt and "<!--" not in prompt


def test_prompt_from_doc_without_markers_is_a_clear_error(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("# nothing here\n")
    with pytest.raises(el.ElevenLabsError, match="agent-system-prompt"):
        el.prompt_from_doc(p)


# ---------------------------------------------------------------- make voice-agent

def test_create_writes_only_the_agent_id_and_masks_it(env_local, monkeypatch):
    env_local.write_text("NEXT_PUBLIC_API_URL=http://localhost:8000\n")
    fake = FakeEleven()
    code, out = _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)
    assert code == 0, out
    assert len(fake.tools) == 8 and all(c["type"] == "client" for c in fake.tools.values())
    (aid, body), = fake.agents.items()
    prompt = body["conversation_config"]["agent"]["prompt"]
    assert prompt["tool_ids"] == [f"tool_{i}" for i in range(1, 9)] and prompt["llm"] == "gemini-2.5-flash"
    assert prompt["prompt"].startswith("You are PolyBridge") and "tools" not in prompt
    assert body["platform_settings"]["auth"] == {"enable_auth": False, "allowlist": [
        {"hostname": "localhost:3000"}, {"hostname": "127.0.0.1:3000"}]}
    assert env_local.read_text() == f"NEXT_PUBLIC_API_URL=http://localhost:8000\nNEXT_PUBLIC_ELEVENLABS_AGENT_ID={aid}\n"
    assert "agent created: ***0001" in out and aid not in out
    assert EL_KEY not in out and EL_KEY not in env_local.read_text()
    assert all(r.headers["xi-api-key"] == EL_KEY and EL_KEY not in str(r.url) for r in fake.requests)


def test_rerun_is_idempotent_updates_in_place(env_local, monkeypatch):
    fake = FakeEleven()
    assert _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)[0] == 0
    tools_before, agents_before = dict(fake.tools), set(fake.agents)
    code, out = _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)
    assert code == 0, out
    assert set(fake.tools) == set(tools_before) and set(fake.agents) == agents_before  # nothing new
    assert "agent updated" in out and "0 created, 8 updated" in out
    methods = [(r.method, r.url.path.split("/")[3] if r.url.path.count("/") > 2 else r.url.path) for r in fake.requests]
    assert ("PATCH", "agents") in methods
    assert env_local.read_text().count("NEXT_PUBLIC_ELEVENLABS_AGENT_ID=") == 1


def test_foreign_client_tool_with_the_same_name_is_left_alone(env_local, monkeypatch):
    foreign = {"type": "client", "name": "account", "description": "Someone else's tool", "parameters": {}}
    fake = FakeEleven(tools={"theirs": foreign})
    assert _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)[0] == 0
    assert fake.tools["theirs"] == foreign and len(fake.tools) == 9


def test_stale_agent_id_gets_a_new_agent(env_local, monkeypatch):
    env_local.write_text("NEXT_PUBLIC_ELEVENLABS_AGENT_ID=agent_gone\n")
    fake = FakeEleven()
    code, out = _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)
    assert code == 0 and "no longer exists" in out and "agent created" in out
    assert "agent_gone" not in env_local.read_text()


def test_rejected_llm_falls_back_to_platform_default_with_a_note(env_local, monkeypatch):
    fake = FakeEleven(reject_llm=True)
    code, out = _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)
    assert code == 0 and "rejected llm 'gemini-2.5-flash'" in out
    (body,) = fake.agents.values()
    assert "llm" not in body["conversation_config"]["agent"]["prompt"]


def test_missing_key_exits_2_without_network(env_local, monkeypatch):
    fake = FakeEleven()
    code, out = _run([], fake, env_local, monkeypatch)
    assert code == 2 and "ELEVENLABS_API_KEY is missing" in out and fake.requests == [] and not env_local.exists()


def test_invalid_key_exits_1_with_a_clear_message(env_local, monkeypatch):
    code, out = _run([], FakeEleven(), env_local, monkeypatch, ELEVENLABS_API_KEY="wrong-key")
    assert code == 1 and "refused the key" in out and "HTTP 401" in out and "wrong-key" not in out
    assert not env_local.exists()


def test_refuses_when_env_local_is_not_gitignored(env_local, monkeypatch):
    monkeypatch.setattr(elevenlabs_agent, "gitignored", lambda path, repo=None: False)
    fake = FakeEleven()
    code, out = _run([], fake, env_local, monkeypatch, ELEVENLABS_API_KEY=EL_KEY)
    assert code == 3 and "not gitignored" in out and fake.requests == []


def test_dry_run_needs_no_key_and_sends_nothing(env_local, monkeypatch):
    fake = FakeEleven()
    code, out = _run(["--dry-run"], fake, env_local, monkeypatch)
    assert code == 0 and fake.requests == [] and "approve (confirm required)" in out and '"type": "client"' in out


def test_web_env_local_is_gitignored_in_this_repo():
    assert elevenlabs_agent.gitignored(elevenlabs_agent.ENV_LOCAL)


# ---------------------------------------------------------------- make keys-check

def test_keys_check_names_only_and_read_only_elevenlabs(env_local, monkeypatch):
    env_local.write_text("NEXT_PUBLIC_ELEVENLABS_AGENT_ID=agent_abcd1234\n")
    _keys(monkeypatch, ELEVENLABS_API_KEY=EL_KEY, MASSIVE_API_KEY="massive-sekrit", BROKER="broker-value-xyz")
    fake = FakeEleven(agents={"agent_abcd1234": el.agent_body("p", "f", ["t1", "t2"], "gemini-2.5-flash")})
    lines: list[str] = []
    code = keys_check.main(transport=httpx.MockTransport(fake), out=lines.append, env_local=env_local)
    out = "\n".join(lines)
    assert code == 0, out
    assert "present  MASSIVE_API_KEY" in out and "MISSING  GEMINI_API_KEY" in out and "present  BROKER" in out
    assert "massive-sekrit" not in out and EL_KEY not in out and "broker-value-xyz" not in out
    assert "tier creator" in out and "agent ***1234 exists" in out and "2 tools attached" in out
    assert {r.method for r in fake.requests} == {"GET"}


def test_keys_check_runs_gemini_check_when_present(env_local, monkeypatch):
    _keys(monkeypatch, GEMINI_API_KEY=GEM_KEY)
    lines: list[str] = []
    assert keys_check.main(gemini_run=lambda: 1, out=lines.append, env_local=env_local) == 1
    assert "== Gemini" in "\n".join(lines) and "skipped (no ELEVENLABS_API_KEY" in "\n".join(lines)


# ---------------------------------------------------------------- make gemini-check

def _gemini_http(models_status=200, generate=None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1beta/models":
            if models_status != 200:
                return httpx.Response(models_status)
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]}]})
        schema = json.dumps(json.loads(request.content)["generationConfig"]["responseSchema"])
        if generate is not None:
            return generate(request)
        if "event_class" in schema:
            obj = {"event_class": "macro_fed"}
        elif "rationale" in schema and "mappings" not in schema:
            obj = {"rationale": "Chosen on replay. It is not a forecast."}
        else:
            obj = {"mappings": [{"ticker": "ABNB", "direction": "down_on_yes", "impact_pct": 8,
                                 "rationale": "Its US listings would vanish."},
                                {"ticker": "FAKE", "direction": "down_on_yes", "impact_pct": 1, "rationale": "x"}]}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def test_gemini_check_lists_models_and_runs_the_configured_model_through_the_app_provider():
    http, seen = _gemini_http()
    lines: list[str] = []
    code = asyncio.run(gemini_check.run(GEM_KEY, http, out=lines.append))
    out = "\n".join(lines)
    assert code == 0, out
    assert "newest flash: gemini-3-flash" in out and "configured model: gemini-2.5-flash (listed)" in out
    assert "classify  model=gemini-2.5-flash" in out and "-> macro_fed" in out
    assert "explain   model=gemini-2.5-flash" in out and "Chosen on replay." in out
    assert "map       model=gemini-2.5-flash" in out and "ABNB" in out and "dropped: FAKE" in out
    assert GEM_KEY not in out
    gens = [r for r in seen if r.url.path.endswith(":generateContent")]
    assert len(gens) == 3 and all("gemini-2.5-flash:" in r.url.path for r in gens)
    assert all(r.headers["x-goog-api-key"] == GEM_KEY and GEM_KEY not in str(r.url) for r in seen)


def test_gemini_check_invalid_key_exits_1():
    http, _ = _gemini_http(models_status=400)
    lines: list[str] = []
    assert asyncio.run(gemini_check.run(GEM_KEY, http, out=lines.append)) == 1
    assert "GEMINI_API_KEY was rejected (Gemini model list failed: HTTP 400)" in "\n".join(lines)


def test_gemini_check_failed_call_exits_1():
    http, _ = _gemini_http(generate=lambda r: httpx.Response(429))
    lines: list[str] = []
    assert asyncio.run(gemini_check.run(GEM_KEY, http, out=lines.append)) == 1
    assert "3 of 3 Gemini calls failed" in "\n".join(lines) and "HTTP 429" in "\n".join(lines)


def test_gemini_check_missing_key_exits_2(monkeypatch, capsys):
    _keys(monkeypatch)
    assert gemini_check.main() == 2
    assert "GEMINI_API_KEY is missing" in capsys.readouterr().out
