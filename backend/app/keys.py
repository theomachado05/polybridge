"""Key lookup for the CLI checks (make gemini-check / voice-agent / keys-check). Values are returned, never printed.

The environment wins (``make`` passes ``--env-file ../.env``), then ``.env`` in backend/ or up to three parents (the
repo-root ``.env``), the same rule the research client and ``app.pipeline.llm.gemini_key`` use."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# (label, accepted names): what keys-check reports, by name only.
KNOWN_KEYS: list[tuple[str, tuple[str, ...]]] = [
    ("MASSIVE_API_KEY", ("MASSIVE_API_KEY",)),
    ("GEMINI_API_KEY", ("GEMINI_API_KEY",)),
    ("ELEVENLABS_API_KEY", ("ELEVENLABS_API_KEY",)),
    ("WEBULL_APP_KEY", ("WEBULL_APP_KEY", "WEBULL_API_KEY")),
    ("WEBULL_APP_SECRET", ("WEBULL_APP_SECRET",)),
    ("WEBULL_ACCOUNT_ID", ("WEBULL_ACCOUNT_ID",)),
    ("BROKER", ("BROKER",)),
    ("AGENT_TOOL_SECRET", ("AGENT_TOOL_SECRET",)),
]


def env_key(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    try:
        from polybridge_research.massive import load_api_key
        return load_api_key(name, search_from=BACKEND, interactive=False) or None
    except Exception:
        return None


def mask(value: str | None, keep: int = 4) -> str:
    """'***' + the last ``keep`` characters (ids only; never call this on a key)."""
    s = str(value or "")
    return "***" + s[-keep:] if len(s) > keep else "***"
