from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
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


_MAX_RETRY_SLEEP = 60.0


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
        resp = None
        for attempt in range(self._max_attempts):
            try:
                resp = self.session.get(full_url, timeout=60)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt == self._max_attempts - 1:
                    raise
                self._sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code not in _RETRY_STATUS:
                break
            retry_after = str(resp.headers.get("Retry-After", ""))
            self._sleep(min(float(retry_after), _MAX_RETRY_SLEEP) if retry_after.isdigit() else min(2 ** attempt, 20))
        resp.raise_for_status()
        payload = resp.json()
        tmp_file = cache_file.with_name(f"{cache_file.stem}.{uuid.uuid4().hex}.tmp")
        tmp_file.write_text(json.dumps(payload))
        os.replace(tmp_file, cache_file)
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
