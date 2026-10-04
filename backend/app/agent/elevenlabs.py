from __future__ import annotations

import os

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .tools import CONFIRM_TOOLS, TOOLS

API = "https://api.elevenlabs.io"
REPO = Path(__file__).resolve().parents[3]
VOICE_DOC = REPO / "docs" / "voice-agent.md"
DEFAULT_VOICE_ID = "cjVigY5qzO86Huf0OWal"
DEFAULT_TTS_MODEL = "eleven_turbo_v2"
AGENT_NAME = "PolyBridge"
DESC_PREFIX = "PolyBridge: "
DEFAULT_LLM = "gemini-2.5-flash"
WEB_HOSTS = ("localhost:3000", "127.0.0.1:3000")


def web_hosts() -> list[str]:
    hosts = list(WEB_HOSTS)
    for raw in (os.environ.get("PUBLIC_WEB_HOST") or "").split(","):
        extra = raw.strip().lower().split("://", 1)[-1].split("/", 1)[0]
        if extra and extra not in hosts:
            hosts.append(extra)
    return hosts
TIMEOUT_S = 20.0
TOOL_TIMEOUTS = {"fit": 90, "start_bridge": 30, "search_markets": 20, "propose": 20, "approve": 20,
                 "bridge_status": 15, "account": 15, "positions": 15, "navigate": 5,
                 "show_tickets": 45, "explain_ticket": 45, "show_ladders": 20, "explain_mechanism": 10,
                 "what_we_tested": 10}
CONFIRM_NOTE = (" Only set confirm true after the user has said yes, out loud, in their last message; never on your "
                "own initiative.")


class ElevenLabsError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _prop(name: str, spec: dict) -> dict:
    out: dict[str, Any] = {"type": spec.get("type", "string"),
                           "description": spec.get("description") or name.replace("_", " ").capitalize() + "."}
    if spec.get("enum"):
        out["enum"] = list(spec["enum"])
    if out["type"] == "array":
        item = spec.get("items") or {"type": "string"}
        out["items"] = {"type": item.get("type", "string"), "description": item.get("description") or f"One {name} value."}
    return out


def client_tool_configs() -> list[dict]:
    configs = []
    for t in TOOLS:
        params = t["parameters"]
        desc = DESC_PREFIX + t["description"] + (CONFIRM_NOTE if t["name"] in CONFIRM_TOOLS else "")
        configs.append({
            "type": "client",
            "name": t["name"],
            "description": desc,
            "parameters": {"type": "object",
                           "properties": {k: _prop(k, v) for k, v in params.get("properties", {}).items()},
                           "required": list(params.get("required") or [])},
            "expects_response": True,
            "response_timeout_secs": TOOL_TIMEOUTS.get(t["name"], 20),
        })
    return configs


def _fenced(doc: str, marker: str) -> str:
    m = re.search(rf"<!--\s*{marker}:start\s*-->\s*```[a-z]*\n(.*?)\n```\s*<!--\s*{marker}:end\s*-->", doc, re.S)
    if not m:
        raise ElevenLabsError(f"docs/voice-agent.md has no {marker} block (<!-- {marker}:start --> ... :end -->)")
    return m.group(1).strip()


def prompt_from_doc(path: Path = VOICE_DOC) -> tuple[str, str]:
    try:
        doc = path.read_text()
    except OSError as e:
        raise ElevenLabsError(f"cannot read {path}: {type(e).__name__}") from None
    return _fenced(doc, "agent-system-prompt"), _fenced(doc, "agent-first-message")


def agent_body(system_prompt: str, first_message: str, tool_ids: list[str], llm: str | None,
               voice_id: str | None = None) -> dict:
    prompt: dict[str, Any] = {"prompt": system_prompt, "temperature": 0.2, "tool_ids": tool_ids}
    if llm:
        prompt["llm"] = llm
    conv: dict[str, Any] = {"agent": {"first_message": first_message, "language": "en", "prompt": prompt}}
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
    conv["tts"] = {"voice_id": voice_id, "model_id": os.environ.get("ELEVENLABS_TTS_MODEL") or DEFAULT_TTS_MODEL,
                   "stability": 0.45, "similarity_boost": 0.8, "speed": 1.0}
    return {"name": AGENT_NAME, "conversation_config": conv,
            "platform_settings": {"auth": {"enable_auth": False,
                                           "allowlist": [{"hostname": h} for h in web_hosts()]}}}


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except Exception:
        return (r.text or "")[:200]
    if isinstance(d, dict):
        d = d.get("message") or d.get("status") or d
    if isinstance(d, list):
        d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d[:3])
    return str(d)[:300]


def _call(http: httpx.Client, method: str, path: str, **kw) -> httpx.Response:
    try:
        r = http.request(method, API + path, timeout=TIMEOUT_S, **kw)
    except httpx.HTTPError as e:
        raise ElevenLabsError(f"{method} {path} failed: {type(e).__name__}") from None
    if r.status_code in (401, 403):
        raise ElevenLabsError(f"ElevenLabs refused the key on {method} {path} (HTTP {r.status_code}): {_detail(r)}. "
                              "Check ELEVENLABS_API_KEY and that it has Conversational AI (agents) permissions.",
                              r.status_code)
    return r


def _ok(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        raise ElevenLabsError(f"{what} failed (HTTP {r.status_code}): {_detail(r)}", r.status_code)
    try:
        return r.json()
    except ValueError:
        return {}


def client(api_key: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(headers={"xi-api-key": api_key, "content-type": "application/json"}, transport=transport)


def list_tools(http: httpx.Client) -> list[dict]:
    tools: list[dict] = []
    cursor = None
    for _ in range(20):
        r = _call(http, "GET", "/v1/convai/tools", params={"cursor": cursor} if cursor else None)
        body = _ok(r, "listing tools")
        tools.extend(t for t in body.get("tools") or [] if isinstance(t, dict))
        cursor = body.get("next_cursor")
        if not body.get("has_more") or not cursor:
            break
    return tools


def _ours(t: dict, name: str) -> bool:
    cfg = t.get("tool_config") or {}
    return cfg.get("type") == "client" and cfg.get("name") == name and str(cfg.get("description", "")).startswith(
        DESC_PREFIX)


@dataclass
class Result:
    agent_id: str
    created: bool
    tool_ids: dict[str, str]
    tools_created: list[str] = field(default_factory=list)
    tools_updated: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def sync_tools(http: httpx.Client, res_notes: list[str] | None = None) -> tuple[dict[str, str], list[str], list[str]]:
    existing = list_tools(http)
    ids: dict[str, str] = {}
    created, updated = [], []
    for cfg in client_tool_configs():
        mine = next((t for t in existing if _ours(t, cfg["name"]) and t.get("id")), None)
        if mine:
            r = _call(http, "PATCH", f"/v1/convai/tools/{mine['id']}", json={"tool_config": cfg})
            if r.status_code < 400:
                ids[cfg["name"]] = mine["id"]
                updated.append(cfg["name"])
                continue
            if res_notes is not None:
                res_notes.append(f"updating tool {cfg['name']} failed (HTTP {r.status_code}: {_detail(r)}); "
                                 "created a new one")
        body = _ok(_call(http, "POST", "/v1/convai/tools", json={"tool_config": cfg}), f"creating tool {cfg['name']}")
        tid = body.get("id") or body.get("tool_id")
        if not tid:
            raise ElevenLabsError(f"creating tool {cfg['name']} returned no id")
        ids[cfg["name"]] = tid
        created.append(cfg["name"])
    return ids, created, updated


def _llm_rejected(r: httpx.Response) -> bool:
    return r.status_code in (400, 422) and "llm" in (r.text or "").lower()


def provision(http: httpx.Client, *, agent_id: str | None, system_prompt: str, first_message: str,
              llm: str | None = DEFAULT_LLM, voice_id: str | None = None,
              log: Callable[[str], None] = lambda s: None) -> Result:
    notes: list[str] = []
    ids, created, updated = sync_tools(http, notes)
    log(f"tools: {len(created)} created, {len(updated)} updated ({', '.join(ids)})")
    tool_ids = [ids[c["name"]] for c in client_tool_configs()]

    if agent_id:
        r = _call(http, "GET", f"/v1/convai/agents/{agent_id}")
        if r.status_code == 404:
            notes.append("the configured agent id no longer exists in this workspace; created a new agent")
            agent_id = None
        else:
            _ok(r, "reading the agent")

    def send(body: dict) -> httpx.Response:
        if agent_id:
            return _call(http, "PATCH", f"/v1/convai/agents/{agent_id}", json=body)
        return _call(http, "POST", "/v1/convai/agents/create", json=body)

    body = agent_body(system_prompt, first_message, tool_ids, llm, voice_id)
    r = send(body)
    if _llm_rejected(r) and llm:
        notes.append(f"ElevenLabs rejected llm {llm!r} ({_detail(r)}); used the platform default LLM instead")
        r = send(agent_body(system_prompt, first_message, tool_ids, None, voice_id))
    out = _ok(r, "updating the agent" if agent_id else "creating the agent")
    final_id = agent_id or out.get("agent_id")
    if not final_id:
        raise ElevenLabsError("creating the agent returned no agent_id")
    return Result(agent_id=final_id, created=agent_id is None, tool_ids=ids, tools_created=created,
                  tools_updated=updated, notes=notes)


def subscription(http: httpx.Client) -> dict:
    return _ok(_call(http, "GET", "/v1/user/subscription"), "reading the subscription")


def get_agent(http: httpx.Client, agent_id: str) -> dict | None:
    r = _call(http, "GET", f"/v1/convai/agents/{agent_id}")
    if r.status_code == 404:
        return None
    return _ok(r, "reading the agent")


ENV_VAR = "NEXT_PUBLIC_ELEVENLABS_AGENT_ID"


def read_env_local(path: Path) -> str | None:
    try:
        for line in path.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == ENV_VAR and v.strip():
                return v.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def write_env_local(path: Path, agent_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{4,128}", agent_id):
        raise ElevenLabsError("refusing to write an agent id with unexpected characters")
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = []
    kept = [ln for ln in lines if ln.partition("=")[0].strip() != ENV_VAR]
    kept.append(f"{ENV_VAR}={agent_id}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(kept) + "\n")
    tmp.replace(path)
