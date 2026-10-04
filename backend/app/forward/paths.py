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

LADDER_FILES = ("research/ladder_replay/METHOD.md", "research/ladder_replay/live.py", "research/ladder_replay/replay.py",
                "research/ladder_replay/config.py")
TOUCH_FILES = ("research/touch_fresh/FORWARD.md", "research/touch_fresh/forward_config.py", "research/touch_fresh/forward.py")


def data_dir() -> Path:
    env = os.environ.get("POLYBRIDGE_FORWARD_DIR", "").strip()
    return Path(env) if env else DEFAULT_DIR


def ensure_research_path() -> None:
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
