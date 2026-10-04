"""Create or update the PolyBridge ElevenLabs voice agent (client tools, no tunnel) and point the web app at it.

    make voice-agent                 # create, or update the agent whose id is already known
    make voice-agent ARGS=--dry-run  # print what would be sent; no network, no key needed

With ELEVENLABS_API_KEY (repo-root .env): creates or updates one CLIENT tool per GET /agent/tools entry
(search_markets, fit, propose, approve, start_bridge, bridge_status, account, positions; approve and start_bridge keep
the required confirm parameter), then creates the agent, or updates it when an id is known (ELEVENLABS_AGENT_ID,
else NEXT_PUBLIC_ELEVENLABS_AGENT_ID in the environment or in web/.env.local), with the system prompt and first message
from docs/voice-agent.md. Then writes ONLY NEXT_PUBLIC_ELEVENLABS_AGENT_ID=<id> into web/.env.local (created if
missing, other lines kept; refused unless git ignores the file) and prints the id masked. Running it again updates
the same tools and agent. Optional: ELEVENLABS_LLM (default gemini-2.5-flash; dropped with a note if ElevenLabs
rejects it), ELEVENLABS_VOICE_ID (else the platform default voice).

Exit code: 0 done, 1 ElevenLabs refused or failed, 2 ELEVENLABS_API_KEY missing, 3 web/.env.local not gitignored."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import elevenlabs as el  # noqa: E402
from app.keys import REPO, env_key, mask  # noqa: E402

ENV_LOCAL = REPO / "web" / ".env.local"


def known_agent_id(env_local: Path = ENV_LOCAL) -> str | None:
    for name in ("ELEVENLABS_AGENT_ID", el.ENV_VAR):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return el.read_env_local(env_local)


def gitignored(path: Path, repo: Path = REPO) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(path.relative_to(repo))],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return r.returncode == 0


def main(argv: list[str] | None = None, transport=None, env_local: Path = ENV_LOCAL, out=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print the tools and agent body; no network")
    ap.add_argument("--agent-id", default=None, help="update this agent instead of the known one")
    a = ap.parse_args(argv)

    try:
        system_prompt, first_message = el.prompt_from_doc()
    except el.ElevenLabsError as e:
        out(f"FAIL  {e}")
        return 1
    llm = (os.environ.get("ELEVENLABS_LLM") or el.DEFAULT_LLM).strip() or None
    voice = (os.environ.get("ELEVENLABS_VOICE_ID") or "").strip() or None
    agent_id = a.agent_id or known_agent_id(env_local)

    if a.dry_run:
        tools = el.client_tool_configs()
        out(f"dry run: {len(tools)} client tools: " + ", ".join(
            f"{t['name']}{' (confirm required)' if 'confirm' in t['parameters']['required'] else ''}" for t in tools))
        body = el.agent_body(system_prompt, first_message, [f"<{t['name']}-id>" for t in tools], llm, voice)
        body["conversation_config"]["agent"]["prompt"]["prompt"] = f"<{len(system_prompt)} chars from docs/voice-agent.md>"
        out(json.dumps({"agent": "update " + mask(agent_id) if agent_id else "create", "body": body,
                        "tools": tools}, indent=1))
        return 0

    key = env_key("ELEVENLABS_API_KEY")
    if not key:
        out("FAIL  ELEVENLABS_API_KEY is missing: add ELEVENLABS_API_KEY=<key> to the repo-root .env (never commit "
            "it), then rerun make voice-agent. Use make voice-agent ARGS=--dry-run to see what would be sent.")
        return 2
    if not gitignored(env_local):
        out(f"FAIL  {env_local.relative_to(REPO)} is not gitignored; refusing to write the agent id there.")
        return 3

    with el.client(key, transport) as http:
        try:
            res = el.provision(http, agent_id=agent_id, system_prompt=system_prompt, first_message=first_message,
                               llm=llm, voice_id=voice, log=lambda s: out(f"      {s}"))
        except el.ElevenLabsError as e:
            out(f"FAIL  {e}")
            return 1
    for n in res.notes:
        out(f"NOTE  {n}")
    el.write_env_local(env_local, res.agent_id)
    out(f"OK    agent {'created' if res.created else 'updated'}: {mask(res.agent_id)} with {len(res.tool_ids)} client "
        f"tools ({len(res.tools_created)} created, {len(res.tools_updated)} updated)")
    out("OK    widget allowlist: " + ", ".join(el.web_hosts())
        + ("" if os.environ.get("PUBLIC_WEB_HOST") else " (set PUBLIC_WEB_HOST=<tunnel host> for `make share`)"))
    out(f"OK    wrote {el.ENV_VAR} to {env_local.relative_to(REPO)} (gitignored). Restart `pnpm dev` so Next.js "
        "picks it up, then open http://localhost:3000.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
