"""Where forward-test output lives, and the frozen rule files it is labelled with."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RESEARCH = REPO / "research"
DEFAULT_DIR = REPO / "backend" / "data_forward"

# The rule files each forward test is frozen on. Their sha256 and last commit are shown next to every result.
LADDER_FILES = ("research/ladder_replay/METHOD.md", "research/ladder_replay/live.py", "research/ladder_replay/replay.py",
                "research/ladder_replay/config.py")
TOUCH_FILES = ("research/touch_fresh/FORWARD.md", "research/touch_fresh/forward_config.py", "research/touch_fresh/forward.py")


def data_dir() -> Path:
    env = os.environ.get("POLYBRIDGE_FORWARD_DIR", "").strip()
    return Path(env) if env else DEFAULT_DIR


def ensure_research_path() -> None:
    """The research studies import each other as top-level packages (``python -m ladder_replay.live`` from research/)."""
    p = str(RESEARCH)
    if p not in sys.path:
        sys.path.insert(0, p)


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def frozen_info(files: tuple[str, ...]) -> list[dict]:
    """For each rule file: its sha256 (always, from the file), its last commit and whether it differs from that commit
    (``None`` when git is not available). The sha256 is what proves the rules did not change."""
    out = []
    for rel in files:
        f = REPO / rel
        sha = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
        commit = _git("log", "-1", "--format=%h", "--", rel) or None
        dirty = None
        if commit is not None:
            dirty = bool(_git("status", "--porcelain", "--", rel))
        out.append({"file": rel, "sha256": sha, "commit": commit, "modified_since_commit": dirty})
    return out
