"""Massive REST client: key loading that never hangs a non-interactive kernel, on-disk cache, retries, paging.

The cache key is sha1(full URL), the same as the Massive starter notebook's, so both share `.massive_cache/`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from getpass import getpass
from pathlib import Path

import requests

BASE_URL = "https://api.massive.com"
_PLACEHOLDERS = {"", "your-key-here"}
_RETRY_STATUS = {429, 500, 502, 503, 504}


class MissingApiKey(RuntimeError):
    pass


def _read_dotenv(path: Path, name: str) -> str:
    for line in path.read_text().splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_api_key(name: str = "MASSIVE_API_KEY", search_from: Path | None = None,
                 interactive: bool | None = None) -> str:
    """Environment first, then `.env` in `search_from` and up to three parent folders, then a prompt only
    when a human is at the terminal. Judges run non-interactively, so they get an error, never a hang."""
    key = (os.environ.get(name) or "").strip()
    if key in _PLACEHOLDERS:
        start = (search_from or Path.cwd()).resolve()
        for folder in [start, *list(start.parents)[:3]]:
            env_file = folder / ".env"
            if env_file.exists():
                key = _read_dotenv(env_file, name)
                if key not in _PLACEHOLDERS:
                    break
    if key not in _PLACEHOLDERS:
        return key
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    if interactive:
        key = getpass(f"{name}: ").strip()
        if key not in _PLACEHOLDERS:
            return key
    raise MissingApiKey(
        f"{name} not found. Set it in the environment or in a .env file next to the notebook "
        f"(a line '{name}=<your key>'), then rerun."
    )


class MassiveClient:
    def __init__(self, api_key: str, cache_dir: Path = Path(".massive_cache"), session=None, sleep=time.sleep,
                 max_attempts: int = 10):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session if session is not None else requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        self._sleep = sleep
        self._max_attempts = max_attempts

    def get(self, path_or_url: str, params: dict | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
        full_url = requests.Request("GET", url, params=params).prepare().url
        cache_file = self.cache_dir / (hashlib.sha1(full_url.encode()).hexdigest() + ".json")
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        for attempt in range(self._max_attempts):
            resp = self.session.get(full_url, timeout=60)
            if resp.status_code not in _RETRY_STATUS:
                break
            retry_after = str(resp.headers.get("Retry-After", ""))
            self._sleep(float(retry_after) if retry_after.isdigit() else min(2 ** attempt, 20))
        resp.raise_for_status()
        payload = resp.json()
        cache_file.write_text(json.dumps(payload))
        return payload

    def get_all(self, path: str, params: dict | None = None, max_pages: int = 500) -> list[dict]:
        payload = self.get(path, params)
        rows = list(payload.get("results") or [])
        pages = 1
        while payload.get("next_url") and pages < max_pages:
            payload = self.get(payload["next_url"])
            rows.extend(payload.get("results") or [])
            pages += 1
        return rows
