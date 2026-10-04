"""Which keys are configured (names only), and do the AI keys work?

    make keys-check

Prints present / missing for each key the app reads (never a value), and whether web/.env.local names a voice agent.
When GEMINI_API_KEY is present it runs the full Gemini check (scripts/gemini_check.py). When ELEVENLABS_API_KEY is
present it makes read-only ElevenLabs calls: GET /v1/user/subscription, and GET /v1/convai/agents/{id} when an agent
id is known (does it exist, how many tools does it have).

Exit code: 0 every check that could run passed (missing keys are reported, not failed), 1 a check failed."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agent import elevenlabs as el  # noqa: E402
from app.keys import KNOWN_KEYS, REPO, env_key, mask  # noqa: E402

ENV_LOCAL = REPO / "web" / ".env.local"


def main(transport=None, gemini_run=None, out=print, env_local: Path = ENV_LOCAL) -> int:
    present = {}
    for label, names in KNOWN_KEYS:
        present[label] = any(env_key(n) for n in names)
        out(f"{'present' if present[label] else 'MISSING':<8} {label}")
    agent_id = (os.environ.get("ELEVENLABS_AGENT_ID") or "").strip() or el.read_env_local(env_local)
    out(f"{'present' if agent_id else 'MISSING':<8} {el.ENV_VAR} (web/.env.local)"
        + (f" = {mask(agent_id)}" if agent_id else ": run make voice-agent once ELEVENLABS_API_KEY is set"))
    failed = 0

    out("")
    if present["GEMINI_API_KEY"]:
        out("== Gemini")
        if gemini_run is None:
            import gemini_check
            gemini_run = lambda: asyncio.run(gemini_check.run(env_key("GEMINI_API_KEY"), out=out))  # noqa: E731
        failed += gemini_run() != 0
    else:
        out("== Gemini: skipped (no GEMINI_API_KEY; fits use keyword rules and templates, /map serves precomputed only)")

    out("")
    key = env_key("ELEVENLABS_API_KEY")
    if key:
        out("== ElevenLabs (read-only)")
        with el.client(key, transport) as http:
            try:
                s = el.subscription(http)
                used, limit = s.get("character_count"), s.get("character_limit")
                out(f"OK    key accepted: tier {s.get('tier')}, status {s.get('status')}, characters {used} of {limit}")
            except el.ElevenLabsError as e:
                failed += 1
                out(f"FAIL  {e}")
            if agent_id:
                try:
                    a = el.get_agent(http, agent_id)
                    if a is None:
                        failed += 1
                        out(f"FAIL  agent {mask(agent_id)} does not exist in this workspace: rerun make voice-agent")
                    else:
                        prompt = ((a.get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
                        out(f"OK    agent {mask(agent_id)} exists: {a.get('name')!r}, "
                            f"{len(prompt.get('tool_ids') or [])} tools attached, llm {prompt.get('llm')}")
                except el.ElevenLabsError as e:
                    failed += 1
                    out(f"FAIL  {e}")
    else:
        out("== ElevenLabs: skipped (no ELEVENLABS_API_KEY; the voice button stays hidden until make voice-agent runs)")

    out("")
    out("FAIL  some checks failed" if failed else "OK    every check that could run passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
