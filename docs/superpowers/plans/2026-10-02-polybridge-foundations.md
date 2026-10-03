# PolyBridge Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (Foundations only; the 8-K event pipeline, atlas and overlay backtest get their own plans once this lands.) Lay the base layer of PolyBridge: a working, tested skeleton for every top-level folder, with fixed contracts between them, so two people can build in parallel on separate folders without merge conflicts.

**Architecture:** Five top-level folders, each owned by one lane: `research/` (scored Python package + notebook), `backend/` (FastAPI, imports the research package's schema), `engine/hedgecore/` (C++20 hedge algorithm + pybind11 binding), `web/` (Next.js), and `overlay/` (created later, when the Webull key arrives). The shared vocabulary lives in one Python module (`research/polybridge_research/schema.py`) and one doc (`docs/contracts.md`); both change only through a PR.

**Tech Stack:** Python 3.10+ (research floor), 3.12 (backend), uv, pytest, pandas/numpy/requests, FastAPI + pydantic v2, C++20 (Apple clang 17 / GCC 12+), CMake ≥ 3.24, GoogleTest 1.15.2, pybind11 ≥ 2.13, scikit-build-core, Next.js (create-next-app latest) + TypeScript + pnpm, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-02-polybridge-design.md` (v3), plus `research/HYPOTHESIS.md` and `research/HYPOTHESIS_TAGS.md`.

## Global Constraints

- The scored paths (`research/`, `overlay/`) never import `hedgecore` and never call Claude. Judges need only `MASSIVE_API_KEY`.
- The research package supports Python ≥ 3.10 and depends only on `pandas>=2.2`, `numpy>=2.0`, `requests>=2.31` and `matplotlib>=3.8` (the starter's floors).
- `.env`, `.massive_cache/`, `research/taxonomy/` and any raw API dump are never committed.
- H1 tags are exactly: `material_litigation`, `class_action_filing`, `regulatory_investigation`, `cybersecurity_incident`, `goodwill_impairment`, `asset_impairment`, `investment_impairment`.
- H2 tags are exactly: `restructuring_plan`, `workforce_reduction`, `facility_closure`, `business_line_exit`.
- A filing with tags from both families belongs to neither confirmatory test.
- Parity: `implied = (C_K + P_K) / S_entry`; `implied_scaled = implied * sqrt(sessions_held / dte_sessions)`; `ratio = |S_exit / S_entry − 1| / implied_scaled` (Massive starter, section 7).
- hedgecore executes only hedges that a user approved; the backend's approve step is the only path that creates an executable `HedgeSpec`.
- C++ standard is C++20. No heap allocation and no virtual calls inside `Engine::on_tick`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **Missing API key in a non-interactive run** (judges use `jupyter nbconvert --execute`): the starter's `getpass` prompt would hang forever. Expected: a clear `MissingApiKey` error naming the env var and the `.env` location. Pinned in Task 3.
- **A filing tagged in both families** (a restructuring that books an impairment): expected to land in neither test, never in both. Pinned in Task 2.
- **Stale or missing option marks** (NaN legs, the starter's `MAX_STALE_SESSIONS`): expected to give NaN P&L, never 0 and never an exception. Pinned in Task 4.
- **Approving a proposal twice, or approving an unknown id**: expected 409 and 404, never a second executable hedge. Pinned in Task 6.
- **A stale or out-of-range tick reaching hedgecore** (feed lag, p outside [0, 1]): expected Hold with a reason, never an order. Pinned in Task 7.

---

## File structure

```
.github/workflows/ci.yml            CI: research, backend, engine, web jobs
CONTRIBUTING.md                     lanes, branch rules, shared-file rules
Makefile                            setup / test entry points for every lane
docs/contracts.md                   Event, families, proposal, HedgeSpec/Tick/Decision, HTTP API
research/
  pyproject.toml                    package polybridge-research
  requirements.txt                  what judges install (starter floors + -e .)
  polybridge_research/__init__.py
  polybridge_research/schema.py     Family, H1_TAGS, H2_TAGS, assign_family, Event, normalize_ticker
  polybridge_research/massive.py    load_api_key, MissingApiKey, MassiveClient (cache, retry, paging)
  polybridge_research/strategies.py STRATEGIES, strategy_pnl
  polybridge_research/parity.py     implied_move, implied_scaled, realized_move, parity_ratio
  polybridge_research/stats.py      bootstrap_ci, benjamini_hochberg, deflated_sharpe
  tests/test_*.py
  starter/gqh-massive-8k-starter/   the Massive kit, committed as shipped
backend/
  pyproject.toml
  app/__init__.py  app/main.py  app/models.py  app/store.py  app/routes.py
  tests/test_api.py
engine/hedgecore/
  CMakeLists.txt  pyproject.toml
  include/hedgecore/types.hpp  include/hedgecore/engine.hpp
  src/engine.cpp  src/bindings.cpp
  tests/test_engine.cpp  tests/test_bindings.py
web/                                create-next-app output + src/lib/api.ts + src/app/page.tsx
```

---

### Task 1: Repo foundation and the research package shell

**Files:**
- Create: `research/pyproject.toml`, `research/requirements.txt`, `research/polybridge_research/__init__.py`, `research/tests/test_package.py`, `Makefile`, `CONTRIBUTING.md`
- Modify: `.gitignore` (append), `README.md` (replace the Workflow section)
- Commit as shipped: `research/starter/gqh-massive-8k-starter/` (already on disk; its own `.gitignore` excludes `.env`, `.massive_cache/` and `.venv/`)
- Delete: `web/README.md`, `api/README.md` (`api/` is renamed `backend/` in spec v3; `web/` must be empty for create-next-app in Task 9)

**Interfaces:**
- Produces: importable package `polybridge_research` with `__version__ = "0.1.0"`; `make test-research` runs `pytest` in `research/`.

- [ ] **Step 1: Write the failing test**

`research/tests/test_package.py`:
```python
import polybridge_research


def test_package_imports_with_version():
    assert polybridge_research.__version__ == "0.1.0"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd research && uv venv .venv && uv pip install --python .venv pytest && .venv/bin/python -m pytest -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybridge_research'`

- [ ] **Step 3: Create the package and its metadata**

`research/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "polybridge-research"
version = "0.1.0"
description = "PolyBridge research: implied-move parity on 8-K events (GatorQuant Hacks 2026)"
requires-python = ">=3.10"
dependencies = ["pandas>=2.2", "numpy>=2.0", "requests>=2.31", "matplotlib>=3.8"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
include = ["polybridge_research*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`research/requirements.txt`:
```text
# What judges install. Floors match the Massive starter. Python 3.10+.
pandas>=2.2
numpy>=2.0
requests>=2.31
matplotlib>=3.8
ipykernel>=6.29
jupyterlab>=4.0
-e .
```

`research/polybridge_research/__init__.py`:
```python
"""PolyBridge research package: implied-move parity on 8-K events."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Install and run the test**

Run: `cd research && uv pip install --python .venv -e ".[dev]" && .venv/bin/python -m pytest -q`
Expected: `1 passed`

- [ ] **Step 5: Add the Makefile, ignore rules, CONTRIBUTING and README workflow**

`Makefile`:
```makefile
.PHONY: setup-research test-research setup-backend test-backend build-engine test-engine setup-web test-web test

setup-research:
	cd research && uv venv .venv && uv pip install --python .venv -e ".[dev]"

test-research:
	cd research && .venv/bin/python -m pytest -q

setup-backend:
	cd backend && uv sync

test-backend:
	cd backend && uv run pytest -q

build-engine:
	cmake -S engine/hedgecore -B engine/hedgecore/build -G Ninja -DCMAKE_BUILD_TYPE=Release
	cmake --build engine/hedgecore/build

test-engine: build-engine
	ctest --test-dir engine/hedgecore/build --output-on-failure

setup-web:
	cd web && pnpm install

test-web:
	cd web && pnpm lint && pnpm build

test: test-research test-backend test-engine test-web
```

Append to `.gitignore`:
```gitignore

# python envs and tool caches
.venv/
backend/.venv/
research/.venv/
*.egg-info/
engine/hedgecore/build/
.ipynb_checkpoints/
```

`CONTRIBUTING.md`:
```markdown
# Working on PolyBridge in parallel

## Lanes (one owner each; never edit another lane's folder without asking)

| Lane | Folders | Scored? |
|---|---|---|
| **R · Research** | `research/`, `overlay/`, `note/` | Yes: notebook, overlay backtest, quant note |
| **P · Product** | `backend/`, `engine/`, `web/` | No: the pitch demo |

## Shared files (PR + the other lane's review required)

- `docs/contracts.md`: every type and endpoint that crosses a folder boundary
- `research/polybridge_research/schema.py`: families, tags, `Event`
- `research/HYPOTHESIS.md`, `research/HYPOTHESIS_TAGS.md`: pre-registration; changes are logged in their change log

## Branches

- Never push to `main`. Branch as `r/<thing>` (lane R) or `p/<thing>` (lane P), open a PR, merge when CI is green.
- Rebase on `main` before opening the PR. Keep PRs inside your lane's folders.

## Setup

1. `cp .env.example .env` and add `MASSIVE_API_KEY` (from the #massive Discord channel). Never commit `.env`.
2. Lane R: `make setup-research && make test-research`
3. Lane P: `make setup-backend test-backend`, `make test-engine` (needs `cmake` and `ninja`: `uv tool install cmake ninja`), `make setup-web test-web`

## Hard rules (they protect rubric points)

- Nothing in `research/` or `overlay/` imports `hedgecore` or calls an LLM.
- The out-of-sample window runs once, after the method freeze. Every peek is logged in the note.
- Every variant tried is counted.
```

In `README.md`, replace everything from `## Workflow` to the end of the file with:
```markdown
## Workflow

Read [CONTRIBUTING.md](CONTRIBUTING.md): two lanes (Research, Product), shared files change only by PR, and `make test` runs every lane's tests.

Pre-registration: [research/HYPOTHESIS.md](research/HYPOTHESIS.md) and [research/HYPOTHESIS_TAGS.md](research/HYPOTHESIS_TAGS.md).
```

- [ ] **Step 6: Remove placeholder folders and verify the starter's secrets are ignored**

Run:
```bash
git rm -q web/README.md api/README.md
git add research/starter/gqh-massive-8k-starter
git status --short research/starter | grep -E '\.env$|massive_cache' && echo "SECRET STAGED - STOP" || echo "starter clean"
```
Expected: `starter clean`

- [ ] **Step 7: Commit**

```bash
git add research/pyproject.toml research/requirements.txt research/polybridge_research research/tests Makefile CONTRIBUTING.md .gitignore README.md
git commit -m "Foundations: research package shell, Makefile, lanes, Massive starter as shipped

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Shared schema: families, tags and Event

**Files:**
- Create: `research/polybridge_research/schema.py`
- Test: `research/tests/test_schema.py`

**Interfaces:**
- Produces:
  - `class Family(str, Enum)`: `HEDGE = "hedge"`, `OPPORTUNITY = "opportunity"`
  - `H1_TAGS: frozenset[str]`, `H2_TAGS: frozenset[str]`
  - `STRATEGY_FOR_FAMILY: dict[Family, str]` = `{HEDGE: "protective_put", OPPORTUNITY: "cash_secured_put"}`
  - `assign_family(tags: Iterable[str]) -> Family | None`
  - `normalize_ticker(t: object) -> str | None`
  - `@dataclass(frozen=True) class Event(ticker: str, filing_date: datetime.date, tags: frozenset[str], source: str = "massive_8k", accession_number: str | None = None)` with property `family -> Family | None`

- [ ] **Step 1: Write the failing tests**

`research/tests/test_schema.py`:
```python
import datetime as dt
import re
from pathlib import Path

from polybridge_research.schema import (
    H1_TAGS, H2_TAGS, STRATEGY_FOR_FAMILY, Event, Family, assign_family, normalize_ticker,
)

TAGS_MD = Path(__file__).resolve().parents[1] / "HYPOTHESIS_TAGS.md"


def _tags_in_section(heading_prefix: str) -> set[str]:
    text = TAGS_MD.read_text()
    section = text.split(heading_prefix, 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([a-z0-9_]+)` \|", section, flags=re.M))


def test_code_tags_match_preregistration():
    assert H1_TAGS == _tags_in_section("## H1")
    assert H2_TAGS == _tags_in_section("## H2")
    assert len(H1_TAGS) == 7 and len(H2_TAGS) == 4
    assert not (H1_TAGS & H2_TAGS)


def test_assign_family_single_family():
    assert assign_family({"material_litigation"}) is Family.HEDGE
    assert assign_family(["workforce_reduction", "facility_closure"]) is Family.OPPORTUNITY


def test_cross_family_filing_belongs_to_neither():
    assert assign_family({"restructuring_plan", "asset_impairment"}) is None


def test_unrelated_tags_belong_to_neither():
    assert assign_family({"cfo_appointment"}) is None
    assert assign_family(set()) is None


def test_strategy_for_family():
    assert STRATEGY_FOR_FAMILY[Family.HEDGE] == "protective_put"
    assert STRATEGY_FOR_FAMILY[Family.OPPORTUNITY] == "cash_secured_put"


def test_event_family_and_immutability():
    ev = Event("AAPL", dt.date(2024, 3, 1), frozenset({"cybersecurity_incident"}))
    assert ev.family is Family.HEDGE
    assert ev.source == "massive_8k"


def test_normalize_ticker():
    assert normalize_ticker(" brk/b ") == "BRK.B"
    assert normalize_ticker("") is None
    assert normalize_ticker(None) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd research && .venv/bin/python -m pytest tests/test_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybridge_research.schema'`

- [ ] **Step 3: Implement the schema**

`research/polybridge_research/schema.py`:
```python
"""Shared vocabulary for every PolyBridge component. Changes go through a PR (see CONTRIBUTING.md).

The tag sets mirror research/HYPOTHESIS_TAGS.md exactly; tests/test_schema.py enforces it.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class Family(str, Enum):
    HEDGE = "hedge"              # H1: the chain underprices the event -> buy protection
    OPPORTUNITY = "opportunity"  # H2: the chain overprices the event -> sell protection


H1_TAGS: frozenset[str] = frozenset({
    "material_litigation", "class_action_filing", "regulatory_investigation", "cybersecurity_incident",
    "goodwill_impairment", "asset_impairment", "investment_impairment",
})
H2_TAGS: frozenset[str] = frozenset({
    "restructuring_plan", "workforce_reduction", "facility_closure", "business_line_exit",
})

STRATEGY_FOR_FAMILY: dict[Family, str] = {
    Family.HEDGE: "protective_put",
    Family.OPPORTUNITY: "cash_secured_put",
}


def assign_family(tags: Iterable[str]) -> Family | None:
    """The confirmatory family of a filing, or None. A filing with tags from both families is ambiguous
    about its side of the parity gap, so it belongs to neither (HYPOTHESIS_TAGS.md, rule 2)."""
    tag_set = set(tags)
    in_h1, in_h2 = bool(tag_set & H1_TAGS), bool(tag_set & H2_TAGS)
    if in_h1 and not in_h2:
        return Family.HEDGE
    if in_h2 and not in_h1:
        return Family.OPPORTUNITY
    return None


def normalize_ticker(t: object) -> str | None:
    """Filings write share classes as BRK/B or BRK.B; Massive's options use BRK.B."""
    if not isinstance(t, str) or not t.strip():
        return None
    return t.strip().upper().replace("/", ".")


@dataclass(frozen=True)
class Event:
    """One priced event: an 8-K filing today, a prediction-market question in the live product."""
    ticker: str
    filing_date: dt.date
    tags: frozenset[str]
    source: str = "massive_8k"
    accession_number: str | None = None

    @property
    def family(self) -> Family | None:
        return assign_family(self.tags)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_schema.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/schema.py research/tests/test_schema.py
git commit -m "Shared schema: families, pre-registered tags, cross-family exclusion, Event

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Massive API client that never hangs in a judge's kernel

**Files:**
- Create: `research/polybridge_research/massive.py`
- Test: `research/tests/test_massive.py`

**Interfaces:**
- Produces:
  - `BASE_URL = "https://api.massive.com"`
  - `class MissingApiKey(RuntimeError)`
  - `load_api_key(name: str = "MASSIVE_API_KEY", search_from: Path | None = None, interactive: bool | None = None) -> str`
  - `class MassiveClient(api_key: str, cache_dir: Path = Path(".massive_cache"), session=None, sleep=time.sleep)` with `get(path_or_url: str, params: dict | None = None) -> dict` and `get_all(path: str, params: dict | None = None, max_pages: int = 500) -> list[dict]`
  - The cache file name is `sha1(full_url).json`, the same as the starter's, so both share one cache.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_massive.py`:
```python
import json

import pytest

from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []
        self.headers = {}

    def get(self, url, timeout):
        self.urls.append(url)
        return self.responses.pop(0)


def test_key_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MASSIVE_API_KEY", "  abc123 ")
    assert load_api_key(search_from=tmp_path, interactive=False) == "abc123"


def test_key_from_dotenv_in_parent(monkeypatch, tmp_path):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    (tmp_path / ".env").write_text('MASSIVE_API_KEY="fromfile"\n')
    child = tmp_path / "research"
    child.mkdir()
    assert load_api_key(search_from=child, interactive=False) == "fromfile"


def test_placeholder_key_counts_as_missing_and_never_prompts(monkeypatch, tmp_path):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("MASSIVE_API_KEY=your-key-here\n")
    with pytest.raises(MissingApiKey, match="MASSIVE_API_KEY"):
        load_api_key(search_from=tmp_path, interactive=False)


def test_get_caches_by_full_url(tmp_path):
    session = FakeSession([FakeResponse(200, {"results": [1]})])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get("/x", {"a": 1}) == {"results": [1]}
    assert client.get("/x", {"a": 1}) == {"results": [1]}  # second call served from disk
    assert len(session.urls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_get_retries_rate_limit_then_succeeds(tmp_path):
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "0"}), FakeResponse(200, {"ok": True})])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get("/y") == {"ok": True}
    assert len(session.urls) == 2


def test_get_raises_on_client_error_and_caches_nothing(tmp_path):
    session = FakeSession([FakeResponse(403)])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="403"):
        client.get("/z")
    assert not list(tmp_path.glob("*.json"))


def test_get_all_follows_next_url(tmp_path):
    session = FakeSession([
        FakeResponse(200, {"results": [1, 2], "next_url": "https://api.massive.com/p2"}),
        FakeResponse(200, {"results": [3]}),
    ])
    client = MassiveClient("k", cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get_all("/p1") == [1, 2, 3]
    assert session.urls[1] == "https://api.massive.com/p2"


def test_bearer_header_is_set(tmp_path):
    session = FakeSession([])
    MassiveClient("secret", cache_dir=tmp_path, session=session)
    assert session.headers["Authorization"] == "Bearer secret"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd research && .venv/bin/python -m pytest tests/test_massive.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybridge_research.massive'`

- [ ] **Step 3: Implement the client**

`research/polybridge_research/massive.py`:
```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_massive.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/massive.py research/tests/test_massive.py
git commit -m "Massive client: non-interactive key loading, shared cache, retries, paging

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Strategy P&L and the parity ratio

**Files:**
- Create: `research/polybridge_research/strategies.py`, `research/polybridge_research/parity.py`
- Test: `research/tests/test_strategies.py`, `research/tests/test_parity.py`

**Interfaces:**
- Produces:
  - `STRATEGIES: list[str]` = `["stock", "long_call", "covered_call", "protective_put", "collar", "cash_secured_put"]`
  - `strategy_pnl(m_e: dict[str, float], m_x: dict[str, float], S_e: float, S_x: float, otm: float) -> dict[str, float]`. Mark keys: `"C_K"`, `f"C_U{otm}"`, `f"P_L{otm}"` (the starter's naming, e.g. `"P_L0.05"`).
  - `implied_move(call_atm: float, put_atm: float, spot: float) -> float`
  - `implied_scaled(implied: float, sessions_held: int, dte_sessions: int) -> float`
  - `realized_move(S_entry: float, S_exit: float) -> float` (signed)
  - `parity_ratio(realized: float, implied_h: float) -> float` (uses |realized|)

- [ ] **Step 1: Write the failing tests**

`research/tests/test_strategies.py`:
```python
import math

from polybridge_research.strategies import STRATEGIES, strategy_pnl

OTM = 0.05
M_E = {"C_K": 5.0, "C_U0.05": 2.0, "P_L0.05": 1.5}


def test_hand_computed_pnl_per_dollar_of_spot():
    m_x = {"C_K": 1.0, "C_U0.05": 0.2, "P_L0.05": 6.0}
    out = strategy_pnl(M_E, m_x, S_e=100.0, S_x=90.0, otm=OTM)
    assert set(out) == set(STRATEGIES)
    assert math.isclose(out["stock"], -0.10)
    assert math.isclose(out["long_call"], -0.04)            # (1 - 5) / 100
    assert math.isclose(out["covered_call"], -0.082)        # (-10 - (0.2 - 2)) / 100
    assert math.isclose(out["protective_put"], -0.055)      # (-10 + (6 - 1.5)) / 100
    assert math.isclose(out["collar"], -0.037)              # (-10 + 4.5 + 1.8) / 100
    assert math.isclose(out["cash_secured_put"], -0.045)    # -(6 - 1.5) / 100


def test_stale_leg_gives_nan_not_zero():
    m_x = {"C_K": 1.0, "C_U0.05": 0.2, "P_L0.05": float("nan")}
    out = strategy_pnl(M_E, m_x, S_e=100.0, S_x=90.0, otm=OTM)
    assert math.isnan(out["protective_put"])
    assert math.isnan(out["cash_secured_put"])
    assert math.isnan(out["collar"])
    assert math.isclose(out["long_call"], -0.04)            # unaffected legs still price
```

`research/tests/test_parity.py`:
```python
import math

from polybridge_research.parity import implied_move, implied_scaled, parity_ratio, realized_move


def test_implied_move_is_straddle_over_spot():
    assert math.isclose(implied_move(3.0, 2.0, 100.0), 0.05)


def test_implied_scaled_uses_square_root_of_time():
    assert math.isclose(implied_scaled(0.10, sessions_held=21, dte_sessions=84), 0.05)


def test_implied_scaled_nan_when_no_sessions_to_expiry():
    assert math.isnan(implied_scaled(0.10, sessions_held=5, dte_sessions=0))


def test_realized_is_signed_ratio_uses_absolute():
    r = realized_move(100.0, 94.0)
    assert math.isclose(r, -0.06)
    assert math.isclose(parity_ratio(r, 0.03), 2.0)


def test_parity_ratio_nan_on_bad_inputs():
    assert math.isnan(parity_ratio(0.02, 0.0))
    assert math.isnan(parity_ratio(float("nan"), 0.03))
    assert math.isnan(realized_move(float("nan"), 100.0))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd research && .venv/bin/python -m pytest tests/test_strategies.py tests/test_parity.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement both modules**

`research/polybridge_research/strategies.py`:
```python
"""The five library strategies plus the stock reference, as P&L per $1 of spot at entry.

Identical to the Massive starter, section 6: the stock leg is the synthetic long (ATM call - ATM put).
A NaN mark (a leg too stale to price) propagates to NaN P&L; it is never treated as zero.
"""
from __future__ import annotations

STRATEGIES = ["stock", "long_call", "covered_call", "protective_put", "collar", "cash_secured_put"]


def strategy_pnl(m_e: dict[str, float], m_x: dict[str, float], S_e: float, S_x: float, otm: float) -> dict[str, float]:
    dS = S_x - S_e
    dC_U = m_x[f"C_U{otm}"] - m_e[f"C_U{otm}"]   # the OTM call we sell
    dP_L = m_x[f"P_L{otm}"] - m_e[f"P_L{otm}"]   # the OTM put we buy (or sell, cash-secured)
    dC_K = m_x["C_K"] - m_e["C_K"]               # the ATM call we buy
    return {
        "stock": dS / S_e,
        "long_call": dC_K / S_e,
        "covered_call": (dS - dC_U) / S_e,
        "protective_put": (dS + dP_L) / S_e,
        "collar": (dS + dP_L - dC_U) / S_e,
        "cash_secured_put": (-dP_L) / S_e,
    }
```

`research/polybridge_research/parity.py`:
```python
"""Implied-move parity (Prediction-Price Parity for options), matching the Massive starter, section 7.

implied        = (ATM call + ATM put) / spot, the move priced to expiry
implied_scaled = implied * sqrt(sessions_held / dte_sessions)
ratio          = |realized| / implied_scaled; above 1 means the market under-priced the move
"""
from __future__ import annotations

import math


def implied_move(call_atm: float, put_atm: float, spot: float) -> float:
    return (call_atm + put_atm) / spot


def implied_scaled(implied: float, sessions_held: int, dte_sessions: int) -> float:
    if not dte_sessions:
        return math.nan
    return implied * math.sqrt(sessions_held / dte_sessions)


def realized_move(S_entry: float, S_exit: float) -> float:
    return S_exit / S_entry - 1


def parity_ratio(realized: float, implied_h: float) -> float:
    if math.isnan(realized) or math.isnan(implied_h) or implied_h <= 0:
        return math.nan
    return abs(realized) / implied_h
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_strategies.py tests/test_parity.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/strategies.py research/polybridge_research/parity.py research/tests/test_strategies.py research/tests/test_parity.py
git commit -m "Strategy P&L and implied-move parity, matching the Massive starter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Statistics: bootstrap, Benjamini–Hochberg, deflated Sharpe

**Files:**
- Create: `research/polybridge_research/stats.py`
- Test: `research/tests/test_stats.py`

**Interfaces:**
- Produces:
  - `bootstrap_ci(x, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> tuple[float, float]` (NaNs dropped; fewer than 5 values → `(nan, nan)`)
  - `benjamini_hochberg(pvalues) -> numpy.ndarray` of q-values, in input order
  - `expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float`
  - `deflated_sharpe(sharpe: float, n_obs: int, n_trials: int, sharpe_variance: float, skew: float = 0.0, kurtosis: float = 3.0) -> float` (a probability in [0, 1]; Bailey and López de Prado, 2014)

- [ ] **Step 1: Write the failing tests**

`research/tests/test_stats.py`:
```python
import math

import numpy as np

from polybridge_research.stats import benjamini_hochberg, bootstrap_ci, deflated_sharpe, expected_max_sharpe


def test_bootstrap_ci_brackets_the_mean_and_is_reproducible():
    x = np.random.default_rng(1).normal(0.02, 0.05, 400)
    lo, hi = bootstrap_ci(x, seed=0)
    assert lo < x.mean() < hi
    assert bootstrap_ci(x, seed=0) == (lo, hi)


def test_bootstrap_ci_wider_at_higher_level():
    x = np.random.default_rng(2).normal(0, 1, 200)
    lo95, hi95 = bootstrap_ci(x, level=0.95)
    lo975, hi975 = bootstrap_ci(x, level=0.975)
    assert lo975 < lo95 and hi975 > hi95


def test_bootstrap_ci_too_few_values_is_nan():
    lo, hi = bootstrap_ci([0.1, float("nan"), 0.2, 0.3, 0.4])
    assert math.isnan(lo) and math.isnan(hi)


def test_benjamini_hochberg_known_values():
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.20])
    # sorted p .01 .03 .04 .20 -> p*m/rank .04 .06 .0533 .20 -> step-up min .04 .0533 .0533 .20
    np.testing.assert_allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.20], rtol=1e-12)


def test_benjamini_hochberg_monotone_and_capped():
    q = benjamini_hochberg([0.9, 0.001, 0.5, 0.95])
    assert np.all(q <= 1.0)
    order = np.argsort([0.9, 0.001, 0.5, 0.95])
    assert np.all(np.diff(q[order]) >= 0)


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 0.01) == 0.0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0


def test_deflated_sharpe_penalizes_many_trials():
    one = deflated_sharpe(0.15, n_obs=500, n_trials=1, sharpe_variance=0.0025)
    many = deflated_sharpe(0.15, n_obs=500, n_trials=800, sharpe_variance=0.0025)
    assert 0.0 <= many < one <= 1.0
    assert one > 0.99
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd research && .venv/bin/python -m pytest tests/test_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybridge_research.stats'`

- [ ] **Step 3: Implement the statistics**

`research/polybridge_research/stats.py`:
```python
"""Uncertainty and multiple-testing tools. Standard library + numpy only (judges' environment).

bootstrap_ci        percentile bootstrap of the mean (the Massive starter's method, with a level argument)
benjamini_hochberg  false-discovery-rate q-values across the exploratory atlas
deflated_sharpe     Bailey & Lopez de Prado (2014): P(true Sharpe > 0) after N trials
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def bootstrap_ci(x, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    arr = np.asarray(x, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(means, [tail, 100 - tail])
    return (float(lo), float(hi))


def benjamini_hochberg(pvalues) -> np.ndarray:
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.minimum(q_sorted, 1.0)
    return q


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum Sharpe among n_trials strategies with zero true Sharpe (the SR0 benchmark)."""
    if n_trials <= 1:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sharpe_variance) * ((1 - _EULER_GAMMA) * a + _EULER_GAMMA * b)


def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int, sharpe_variance: float,
                    skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Probability that the true (per-period) Sharpe exceeds the best expected by luck across n_trials."""
    sr0 = expected_max_sharpe(n_trials, sharpe_variance)
    denom = math.sqrt(max(1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe ** 2, 1e-12))
    z = (sharpe - sr0) * math.sqrt(n_obs - 1) / denom
    return _N.cdf(z)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_stats.py -q`
Expected: `7 passed`

- [ ] **Step 5: Run the whole research suite and commit**

Run: `make test-research`
Expected: `30 passed`

```bash
git add research/polybridge_research/stats.py research/tests/test_stats.py
git commit -m "Stats: bootstrap CI with level, Benjamini-Hochberg, deflated Sharpe

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Backend skeleton with the approval gate

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/models.py`, `backend/app/store.py`, `backend/app/routes.py`, `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `polybridge_research.schema.assign_family`, `Family`, `STRATEGY_FOR_FAMILY` (Task 2)
- Produces (HTTP, documented in `docs/contracts.md` in Task 10):
  - `GET /health` → `{"status": "ok"}`
  - `POST /classify` body `{"tags": [str]}` → `{"family": "hedge" | "opportunity" | null, "strategy": str | null}`
  - `POST /proposals` body `ProposalIn{ticker: str, tags: [str], shares_held: float > 0, target_coverage: float in [0, 1] = 0.5}` → 201 `Proposal`; 422 when the tags map to no family
  - `GET /proposals` → `[Proposal]`
  - `POST /proposals/{id}/approve` → 200 `Proposal` (status `approved`); 404 unknown id; 409 already decided
  - `POST /proposals/{id}/reject` → 200 (status `rejected`); 404; 409
  - `Proposal{id: str, ticker, family, strategy, shares_held, target_coverage, status: "proposed" | "approved" | "rejected", created_at: datetime, decided_at: datetime | null}`
  - Python: `app.main.create_app() -> FastAPI`; `app.store.ProposalStore` with `propose`, `list`, `approve`, `reject`, raising `NotFound` / `AlreadyDecided`

- [ ] **Step 1: Create the project and write the failing tests**

`backend/pyproject.toml`:
```toml
[project]
name = "polybridge-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "pydantic>=2.7", "polybridge-research"]

[dependency-groups]
dev = ["pytest>=8", "httpx>=0.27"]

[tool.uv.sources]
polybridge-research = { path = "../research", editable = true }

[tool.uv]
package = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`backend/app/__init__.py`: empty file.

`backend/tests/test_api.py`:
```python
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _propose(client, tags=("material_litigation",)):
    return client.post("/proposals", json={"ticker": "ABNB", "tags": list(tags), "shares_held": 1200})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_classify(client):
    assert client.post("/classify", json={"tags": ["workforce_reduction"]}).json() == {
        "family": "opportunity", "strategy": "cash_secured_put"}
    assert client.post("/classify", json={"tags": ["restructuring_plan", "asset_impairment"]}).json() == {
        "family": None, "strategy": None}


def test_propose_then_approve(client):
    r = _propose(client)
    assert r.status_code == 201
    p = r.json()
    assert (p["family"], p["strategy"], p["status"], p["target_coverage"]) == ("hedge", "protective_put", "proposed", 0.5)
    a = client.post(f"/proposals/{p['id']}/approve")
    assert a.status_code == 200 and a.json()["status"] == "approved" and a.json()["decided_at"]
    assert [x["status"] for x in client.get("/proposals").json()] == ["approved"]


def test_approve_twice_is_conflict(client):
    pid = _propose(client).json()["id"]
    assert client.post(f"/proposals/{pid}/approve").status_code == 200
    assert client.post(f"/proposals/{pid}/approve").status_code == 409
    assert client.post(f"/proposals/{pid}/reject").status_code == 409


def test_unknown_id_is_not_found(client):
    assert client.post("/proposals/nope/approve").status_code == 404


def test_no_family_cannot_be_proposed(client):
    assert _propose(client, tags=("cfo_appointment",)).status_code == 422


def test_input_validation(client):
    bad = client.post("/proposals", json={"ticker": "X", "tags": ["material_litigation"], "shares_held": 0})
    assert bad.status_code == 422
    bad = client.post("/proposals", json={"ticker": "X", "tags": ["material_litigation"], "shares_held": 10,
                                          "target_coverage": 1.5})
    assert bad.status_code == 422
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv sync && uv run pytest -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement models, store, routes, app**

`backend/app/models.py`:
```python
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

FamilyName = Literal["hedge", "opportunity"]
Status = Literal["proposed", "approved", "rejected"]


class ClassifyIn(BaseModel):
    tags: list[str]


class ClassifyOut(BaseModel):
    family: FamilyName | None
    strategy: str | None


class ProposalIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    tags: list[str] = Field(min_length=1)
    shares_held: float = Field(gt=0)
    target_coverage: float = Field(default=0.5, ge=0, le=1)


class Proposal(BaseModel):
    id: str
    ticker: str
    family: FamilyName
    strategy: str
    shares_held: float
    target_coverage: float
    status: Status
    created_at: dt.datetime
    decided_at: dt.datetime | None = None
```

`backend/app/store.py`:
```python
"""In-memory proposal store. A proposal becomes executable only through approve(), exactly once."""
from __future__ import annotations

import datetime as dt
import threading
import uuid

from .models import Proposal


class NotFound(KeyError):
    pass


class AlreadyDecided(RuntimeError):
    pass


class ProposalStore:
    def __init__(self) -> None:
        self._items: dict[str, Proposal] = {}
        self._lock = threading.Lock()

    def propose(self, **fields) -> Proposal:
        p = Proposal(id=uuid.uuid4().hex[:12], status="proposed", created_at=dt.datetime.now(dt.UTC), **fields)
        with self._lock:
            self._items[p.id] = p
        return p

    def list(self) -> list[Proposal]:
        with self._lock:
            return list(self._items.values())

    def _decide(self, pid: str, status: str) -> Proposal:
        with self._lock:
            if pid not in self._items:
                raise NotFound(pid)
            current = self._items[pid]
            if current.status != "proposed":
                raise AlreadyDecided(pid)
            updated = current.model_copy(update={"status": status, "decided_at": dt.datetime.now(dt.UTC)})
            self._items[pid] = updated
            return updated

    def approve(self, pid: str) -> Proposal:
        return self._decide(pid, "approved")

    def reject(self, pid: str) -> Proposal:
        return self._decide(pid, "rejected")
```

`backend/app/routes.py`:
```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from polybridge_research.schema import STRATEGY_FOR_FAMILY, assign_family

from .models import ClassifyIn, ClassifyOut, Proposal, ProposalIn
from .store import AlreadyDecided, NotFound, ProposalStore

router = APIRouter()


def _store(request: Request) -> ProposalStore:
    return request.app.state.store


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/classify", response_model=ClassifyOut)
def classify(body: ClassifyIn) -> ClassifyOut:
    fam = assign_family(body.tags)
    return ClassifyOut(family=fam.value if fam else None, strategy=STRATEGY_FOR_FAMILY[fam] if fam else None)


@router.post("/proposals", response_model=Proposal, status_code=201)
def create_proposal(body: ProposalIn, request: Request) -> Proposal:
    fam = assign_family(body.tags)
    if fam is None:
        raise HTTPException(422, "These tags map to no pre-registered family, so there is no hedge to propose.")
    return _store(request).propose(ticker=body.ticker.upper(), family=fam.value, strategy=STRATEGY_FOR_FAMILY[fam],
                                   shares_held=body.shares_held, target_coverage=body.target_coverage)


@router.get("/proposals", response_model=list[Proposal])
def list_proposals(request: Request) -> list[Proposal]:
    return _store(request).list()


def _decide(request: Request, pid: str, action: str) -> Proposal:
    try:
        return getattr(_store(request), action)(pid)
    except NotFound:
        raise HTTPException(404, f"No proposal {pid}.")
    except AlreadyDecided:
        raise HTTPException(409, f"Proposal {pid} was already approved or rejected.")


@router.post("/proposals/{pid}/approve", response_model=Proposal)
def approve(pid: str, request: Request) -> Proposal:
    return _decide(request, pid, "approve")


@router.post("/proposals/{pid}/reject", response_model=Proposal)
def reject(pid: str, request: Request) -> Proposal:
    return _decide(request, pid, "reject")
```

`backend/app/main.py`:
```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .store import ProposalStore


def create_app() -> FastAPI:
    app = FastAPI(title="PolyBridge backend", version="0.1.0")
    app.state.store = ProposalStore()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: `7 passed`

- [ ] **Step 5: Smoke-run the server, then commit**

Run: `cd backend && (uv run uvicorn app.main:app --port 8000 & sleep 3; curl -s localhost:8000/health; kill %1)`
Expected: `{"status":"ok"}`

```bash
git add backend/pyproject.toml backend/uv.lock backend/app backend/tests
git commit -m "Backend skeleton: classify, proposals, one-time approval gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: hedgecore C++20 engine with GoogleTest

**Files:**
- Create: `engine/hedgecore/CMakeLists.txt`, `engine/hedgecore/include/hedgecore/types.hpp`, `engine/hedgecore/include/hedgecore/engine.hpp`, `engine/hedgecore/src/engine.cpp`
- Test: `engine/hedgecore/tests/test_engine.cpp`
- Delete: `engine/README.md` (replaced by the header comment in `engine.hpp`)

**Interfaces:**
- Produces (C++, namespace `hedgecore`):
  - `struct HedgeSpec { std::string ticker; double shares_held; double target_coverage = 0.5; double band_shares = 10; double max_hedge_shares = 0; std::int64_t max_staleness_ns = 2'000'000'000; double sigma_k = 2.0; double sigma_alpha = 0.05; };`
  - `struct Tick { std::int64_t ts_ns; double p; };` (p = market probability of the event, in [0, 1])
  - `enum class Action { Hold, Order }`, `enum class Reason { Invalid, Stale, BelowSigma, InsideBand, Rebalance, RiskCapped }`, `const char* to_string(Reason) noexcept`
  - `struct Decision { Action action; Reason reason; double order_qty; double target_hedge; double current_hedge; std::int64_t latency_ns; };` (`order_qty > 0` adds to the short hedge)
  - `class Engine { explicit Engine(HedgeSpec); Decision on_tick(const Tick&, std::int64_t now_ns); void on_fill(double qty) noexcept; double current_hedge() const noexcept; }`
  - Sizing (DeltaBridge default): `target = round(target_coverage * shares_held * p)`, clamped to `max_hedge_shares` (or `shares_held` when 0).
  - The first valid tick sizes the initial hedge h₀ without the sigma gate; later ticks pass the sigma gate only if `|Δp| ≥ sigma_k · σ(Δp)` (EWMA of past Δp², weight `sigma_alpha`).

- [ ] **Step 1: Install the build tools**

Run: `uv tool install cmake && uv tool install ninja && cmake --version && ninja --version`
Expected: cmake ≥ 3.24 and a ninja version are printed.

- [ ] **Step 2: Write the failing tests and the CMake project**

`engine/hedgecore/CMakeLists.txt`:
```cmake
cmake_minimum_required(VERSION 3.24)
project(hedgecore LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(HEDGECORE_BUILD_TESTS "Build GoogleTest suite" ON)
option(HEDGECORE_BUILD_PYTHON "Build the pybind11 module" OFF)

add_library(hedgecore_lib STATIC src/engine.cpp)
target_include_directories(hedgecore_lib PUBLIC include)
target_compile_options(hedgecore_lib PRIVATE -Wall -Wextra -Wpedantic)

if(HEDGECORE_BUILD_TESTS)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
  enable_testing()
  add_executable(hedgecore_tests tests/test_engine.cpp)
  target_link_libraries(hedgecore_tests PRIVATE hedgecore_lib GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(hedgecore_tests)
endif()

if(HEDGECORE_BUILD_PYTHON)
  find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(hedgecore src/bindings.cpp)
  target_link_libraries(hedgecore PRIVATE hedgecore_lib)
  install(TARGETS hedgecore DESTINATION .)
endif()
```

`engine/hedgecore/tests/test_engine.cpp`:
```cpp
#include <gtest/gtest.h>
#include <limits>
#include "hedgecore/engine.hpp"

using namespace hedgecore;

namespace {
constexpr std::int64_t kSec = 1'000'000'000;

HedgeSpec spec() {
  HedgeSpec s;
  s.ticker = "ABNB";
  s.shares_held = 1000;
  s.target_coverage = 0.5;
  s.band_shares = 10;
  return s;
}
}  // namespace

TEST(Engine, FirstTickSizesInitialHedge) {
  Engine e(spec());
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_EQ(d.reason, Reason::Rebalance);
  EXPECT_DOUBLE_EQ(d.target_hedge, 100.0);   // 0.5 * 1000 * 0.20
  EXPECT_DOUBLE_EQ(d.order_qty, 100.0);
  EXPECT_GE(d.latency_ns, 0);
}

TEST(Engine, StaleTickHolds) {
  Engine e(spec());
  auto d = e.on_tick({kSec, 0.20}, 5 * kSec);  // 4 s old > 2 s limit
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Stale);
}

TEST(Engine, OutOfRangeProbabilityHolds) {
  Engine e(spec());
  EXPECT_EQ(e.on_tick({kSec, 1.5}, kSec).reason, Reason::Invalid);
  EXPECT_EQ(e.on_tick({kSec, -0.1}, kSec).reason, Reason::Invalid);
  EXPECT_EQ(e.on_tick({kSec, std::numeric_limits<double>::quiet_NaN()}, kSec).reason, Reason::Invalid);
}

TEST(Engine, BandSuppressesSmallRebalances) {
  Engine e(spec());
  e.on_tick({kSec, 0.20}, kSec);
  e.on_fill(100);
  auto d = e.on_tick({2 * kSec, 0.21}, 2 * kSec);  // target 105, |105-100| < 10
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::InsideBand);
  d = e.on_tick({3 * kSec, 0.30}, 3 * kSec);       // target 150
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_DOUBLE_EQ(d.order_qty, 50.0);
}

TEST(Engine, SigmaGateIgnoresNoise) {
  Engine e(spec());
  e.on_tick({kSec, 0.50}, kSec);
  e.on_fill(250);
  double p = 0.50;
  for (int i = 0; i < 200; ++i) {                  // build a noise level of about 0.001
    p += (i % 2 ? -0.001 : 0.001);
    e.on_tick({(2 + i) * kSec, p}, (2 + i) * kSec);
  }
  auto d = e.on_tick({300 * kSec, p + 0.0005}, 300 * kSec);
  EXPECT_EQ(d.reason, Reason::BelowSigma);
}

TEST(Engine, RiskCapLimitsHedge) {
  auto s = spec();
  s.max_hedge_shares = 120;
  Engine e(s);
  auto d = e.on_tick({kSec, 0.50}, kSec);          // uncapped target 250
  EXPECT_EQ(d.reason, Reason::RiskCapped);
  EXPECT_DOUBLE_EQ(d.target_hedge, 120.0);
  EXPECT_DOUBLE_EQ(d.order_qty, 120.0);
}

TEST(Engine, ReasonNames) {
  EXPECT_STREQ(to_string(Reason::InsideBand), "inside_band");
  EXPECT_STREQ(to_string(Reason::RiskCapped), "risk_capped");
}
```

- [ ] **Step 3: Run the build to verify it fails**

Run: `make test-engine`
Expected: FAIL: CMake errors because `src/engine.cpp` and `hedgecore/engine.hpp` do not exist.

- [ ] **Step 4: Implement types, engine header and engine**

`engine/hedgecore/include/hedgecore/types.hpp`:
```cpp
#pragma once
#include <cstdint>
#include <string>

namespace hedgecore {

// A hedge the user approved in the PolyBridge UI. hedgecore never sizes anything without one.
struct HedgeSpec {
  std::string ticker;
  double shares_held = 0;                         // N, the long position being protected
  double target_coverage = 0.5;                   // c in [0, 1]
  double band_shares = 10;                        // trade only if |h* - h| >= band
  double max_hedge_shares = 0;                    // risk cap; 0 means shares_held
  std::int64_t max_staleness_ns = 2'000'000'000;  // ticks older than this are ignored
  double sigma_k = 2.0;                           // SigmaGate threshold in std devs of dp
  double sigma_alpha = 0.05;                      // EWMA weight for dp^2
};

struct Tick {
  std::int64_t ts_ns;  // venue timestamp
  double p;            // market probability of the event, in [0, 1]
};

enum class Action : std::uint8_t { Hold, Order };
enum class Reason : std::uint8_t { Invalid, Stale, BelowSigma, InsideBand, Rebalance, RiskCapped };

struct Decision {
  Action action;
  Reason reason;
  double order_qty;       // > 0 adds to the short hedge, < 0 reduces it
  double target_hedge;
  double current_hedge;
  std::int64_t latency_ns;
};

const char* to_string(Reason r) noexcept;

}  // namespace hedgecore
```

`engine/hedgecore/include/hedgecore/engine.hpp`:
```cpp
#pragma once
// hedgecore: the systematic hedge algorithm behind a user-approved PolyBridge hedge.
// Pipeline per tick: validate -> staleness gate -> sigma gate -> DeltaBridge size -> risk cap -> band.
// Gates are std::variant stages (static dispatch). on_tick allocates nothing and makes no virtual calls.
#include <array>
#include <variant>
#include "hedgecore/types.hpp"

namespace hedgecore {

struct StalenessGate {
  std::int64_t max_ns;
  bool pass(const Tick& t, std::int64_t now_ns) const noexcept { return now_ns - t.ts_ns <= max_ns; }
  static constexpr Reason fail_reason = Reason::Stale;
};

struct SigmaGate {
  double k;
  double alpha;
  double var = 0.0;
  double last_p = -1.0;
  bool pass(const Tick& t, std::int64_t) noexcept;
  static constexpr Reason fail_reason = Reason::BelowSigma;
};

using Gate = std::variant<StalenessGate, SigmaGate>;

class Engine {
 public:
  explicit Engine(HedgeSpec spec);
  Decision on_tick(const Tick& t, std::int64_t now_ns);
  void on_fill(double qty) noexcept { hedge_ += qty; }
  double current_hedge() const noexcept { return hedge_; }

 private:
  HedgeSpec spec_;
  std::array<Gate, 2> gates_;
  double hedge_ = 0.0;
  bool sized_once_ = false;
};

}  // namespace hedgecore
```

`engine/hedgecore/src/engine.cpp`:
```cpp
#include "hedgecore/engine.hpp"

#include <chrono>
#include <cmath>
#include <type_traits>
#include <utility>

namespace hedgecore {

const char* to_string(Reason r) noexcept {
  switch (r) {
    case Reason::Invalid: return "invalid";
    case Reason::Stale: return "stale";
    case Reason::BelowSigma: return "below_sigma";
    case Reason::InsideBand: return "inside_band";
    case Reason::Rebalance: return "rebalance";
    case Reason::RiskCapped: return "risk_capped";
  }
  return "unknown";
}

bool SigmaGate::pass(const Tick& t, std::int64_t) noexcept {
  if (last_p < 0) {          // first observation: nothing to compare against
    last_p = t.p;
    return true;
  }
  const double dp = t.p - last_p;
  const double sigma = std::sqrt(var);
  const bool ok = std::abs(dp) >= k * sigma;
  var = (1 - alpha) * var + alpha * dp * dp;  // update after the decision: the gate judges against the past
  last_p = t.p;
  return ok;
}

Engine::Engine(HedgeSpec spec)
    : spec_(std::move(spec)),
      gates_{StalenessGate{spec_.max_staleness_ns}, SigmaGate{spec_.sigma_k, spec_.sigma_alpha}} {}

Decision Engine::on_tick(const Tick& t, std::int64_t now_ns) {
  const auto t0 = std::chrono::steady_clock::now();
  auto finish = [&](Action a, Reason r, double qty, double target) {
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - t0).count();
    return Decision{a, r, qty, target, hedge_, static_cast<std::int64_t>(ns)};
  };

  if (!(t.p >= 0.0 && t.p <= 1.0)) return finish(Action::Hold, Reason::Invalid, 0, hedge_);

  for (auto& gate : gates_) {
    Reason failed = Reason::Rebalance;
    bool ok = std::visit([&](auto& g) {
      using G = std::decay_t<decltype(g)>;
      const bool pass = g.pass(t, now_ns);
      if (!pass) failed = G::fail_reason;
      return pass;
    }, gate);
    // The initial position h0 is sized on the first valid tick regardless of the sigma gate.
    if (!ok && !(failed == Reason::BelowSigma && !sized_once_)) return finish(Action::Hold, failed, 0, hedge_);
  }

  const double cap = spec_.max_hedge_shares > 0 ? spec_.max_hedge_shares : spec_.shares_held;
  const double uncapped = std::round(spec_.target_coverage * spec_.shares_held * t.p);
  const bool capped = uncapped > cap;
  const double target = capped ? cap : uncapped;
  const double qty = target - hedge_;

  if (std::abs(qty) < spec_.band_shares) return finish(Action::Hold, Reason::InsideBand, 0, target);
  sized_once_ = true;
  return finish(Action::Order, capped ? Reason::RiskCapped : Reason::Rebalance, qty, target);
}

}  // namespace hedgecore
```

- [ ] **Step 5: Build and run the tests**

Run: `make test-engine`
Expected: `100% tests passed, 0 tests failed out of 7`

- [ ] **Step 6: Commit**

```bash
git rm -q engine/README.md
git add engine/hedgecore/CMakeLists.txt engine/hedgecore/include engine/hedgecore/src/engine.cpp engine/hedgecore/tests/test_engine.cpp
git commit -m "hedgecore: C++20 hedge engine (gates as std::variant, DeltaBridge sizing, band, risk cap)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: hedgecore Python binding

**Files:**
- Create: `engine/hedgecore/pyproject.toml`, `engine/hedgecore/src/bindings.cpp`
- Test: `engine/hedgecore/tests/test_bindings.py`
- Modify: `backend/pyproject.toml` (add an optional `engine` dependency group)

**Interfaces:**
- Consumes: everything Task 7 produces.
- Produces: Python module `hedgecore` with `HedgeSpec` (all fields read/write, keyword constructor), `Engine(spec)`, `Engine.on_tick(ts_ns: int, p: float, now_ns: int) -> Decision`, `Engine.on_fill(qty: float)`, `Engine.current_hedge` (property); `Decision` read-only fields `action` (`"hold"`/`"order"`), `reason` (string from `to_string`), `order_qty`, `target_hedge`, `current_hedge`, `latency_ns`.

- [ ] **Step 1: Write the failing test**

`engine/hedgecore/tests/test_bindings.py`:
```python
import hedgecore


def test_round_trip_matches_cpp_semantics():
    spec = hedgecore.HedgeSpec(ticker="ABNB", shares_held=1000, target_coverage=0.5, band_shares=10)
    eng = hedgecore.Engine(spec)
    d = eng.on_tick(ts_ns=1_000_000_000, p=0.2, now_ns=1_000_000_000)
    assert (d.action, d.reason, d.order_qty, d.target_hedge) == ("order", "rebalance", 100.0, 100.0)
    eng.on_fill(100)
    assert eng.current_hedge == 100.0
    d = eng.on_tick(ts_ns=2_000_000_000, p=0.21, now_ns=2_000_000_000)
    assert (d.action, d.reason) == ("hold", "inside_band")


def test_stale_tick_holds():
    eng = hedgecore.Engine(hedgecore.HedgeSpec(ticker="X", shares_held=10))
    assert eng.on_tick(ts_ns=0, p=0.5, now_ns=10_000_000_000).reason == "stale"
```

- [ ] **Step 2: Write the binding and its build config**

`engine/hedgecore/src/bindings.cpp`:
```cpp
#include <pybind11/pybind11.h>
#include "hedgecore/engine.hpp"

namespace py = pybind11;
using namespace hedgecore;

PYBIND11_MODULE(hedgecore, m) {
  m.doc() = "PolyBridge hedgecore: the C++20 hedge algorithm for user-approved hedges";

  py::class_<HedgeSpec>(m, "HedgeSpec")
      .def(py::init([](std::string ticker, double shares_held, double target_coverage, double band_shares,
                       double max_hedge_shares, std::int64_t max_staleness_ns, double sigma_k, double sigma_alpha) {
             return HedgeSpec{std::move(ticker), shares_held, target_coverage, band_shares, max_hedge_shares,
                              max_staleness_ns, sigma_k, sigma_alpha};
           }),
           py::kw_only(), py::arg("ticker"), py::arg("shares_held"), py::arg("target_coverage") = 0.5,
           py::arg("band_shares") = 10.0, py::arg("max_hedge_shares") = 0.0,
           py::arg("max_staleness_ns") = 2'000'000'000LL, py::arg("sigma_k") = 2.0, py::arg("sigma_alpha") = 0.05)
      .def_readwrite("ticker", &HedgeSpec::ticker)
      .def_readwrite("shares_held", &HedgeSpec::shares_held)
      .def_readwrite("target_coverage", &HedgeSpec::target_coverage)
      .def_readwrite("band_shares", &HedgeSpec::band_shares)
      .def_readwrite("max_hedge_shares", &HedgeSpec::max_hedge_shares)
      .def_readwrite("max_staleness_ns", &HedgeSpec::max_staleness_ns)
      .def_readwrite("sigma_k", &HedgeSpec::sigma_k)
      .def_readwrite("sigma_alpha", &HedgeSpec::sigma_alpha);

  py::class_<Decision>(m, "Decision")
      .def_property_readonly("action", [](const Decision& d) { return d.action == Action::Order ? "order" : "hold"; })
      .def_property_readonly("reason", [](const Decision& d) { return to_string(d.reason); })
      .def_readonly("order_qty", &Decision::order_qty)
      .def_readonly("target_hedge", &Decision::target_hedge)
      .def_readonly("current_hedge", &Decision::current_hedge)
      .def_readonly("latency_ns", &Decision::latency_ns);

  py::class_<Engine>(m, "Engine")
      .def(py::init<HedgeSpec>())
      .def("on_tick", [](Engine& e, std::int64_t ts_ns, double p, std::int64_t now_ns) {
             return e.on_tick(Tick{ts_ns, p}, now_ns);
           }, py::kw_only(), py::arg("ts_ns"), py::arg("p"), py::arg("now_ns"))
      .def("on_fill", &Engine::on_fill)
      .def_property_readonly("current_hedge", &Engine::current_hedge);
}
```

`engine/hedgecore/pyproject.toml`:
```toml
[build-system]
requires = ["scikit-build-core>=0.10", "pybind11>=2.13"]
build-backend = "scikit_build_core.build"

[project]
name = "hedgecore"
version = "0.1.0"
requires-python = ">=3.12"

[tool.scikit-build]
cmake.version = ">=3.24"
cmake.define.HEDGECORE_BUILD_TESTS = "OFF"
cmake.define.HEDGECORE_BUILD_PYTHON = "ON"
wheel.packages = []
```

In `backend/pyproject.toml`, add under `[dependency-groups]`:
```toml
engine = ["hedgecore"]
```
and under `[tool.uv.sources]`:
```toml
hedgecore = { path = "../engine/hedgecore" }
```

- [ ] **Step 3: Build into the backend env and run the binding tests**

Run: `cd backend && uv sync --group engine && uv run pytest ../engine/hedgecore/tests/test_bindings.py -q`
Expected: `2 passed`

- [ ] **Step 4: Confirm the backend still passes without the engine group**

Run: `cd backend && uv sync && uv run pytest -q`
Expected: `7 passed` (plain `uv sync` installs only the default `dev` group, so this proves the backend never needs hedgecore)

- [ ] **Step 5: Commit**

```bash
git add engine/hedgecore/pyproject.toml engine/hedgecore/src/bindings.cpp engine/hedgecore/tests/test_bindings.py backend/pyproject.toml backend/uv.lock
git commit -m "hedgecore: pybind11 binding, optional engine group for the backend

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Web skeleton with a typed API client

**Files:**
- Create: `web/` via create-next-app; then `web/src/lib/api.ts`, replace `web/src/app/page.tsx`
- Create: `web/.env.example`

**Interfaces:**
- Consumes: the HTTP API from Task 6.
- Produces: `web/src/lib/api.ts` exporting `type Proposal`, `type ClassifyOut`, `API_URL`, `getHealth()`, `listProposals()`, `approveProposal(id)`; the home page shows backend status and the proposal queue with an Approve button.

- [ ] **Step 1: Scaffold Next.js non-interactively**

Run:
```bash
pnpm create next-app@latest web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm --yes --skip-install
cd web && npm pkg set packageManager=pnpm@11.0.5 && pnpm install
```
Expected: `web/package.json` exists with `"packageManager": "pnpm@11.0.5"` (CI's pnpm setup reads it) and `pnpm install` completes.

- [ ] **Step 2: Add the typed client**

`web/src/lib/api.ts`:
```ts
// Mirrors docs/contracts.md (HTTP API). Change both together, by PR.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Family = "hedge" | "opportunity";
export type ProposalStatus = "proposed" | "approved" | "rejected";

export interface ClassifyOut {
  family: Family | null;
  strategy: string | null;
}

export interface Proposal {
  id: string;
  ticker: string;
  family: Family;
  strategy: string;
  shares_held: number;
  target_coverage: number;
  status: ProposalStatus;
  created_at: string;
  decided_at: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} failed with ${res.status}`);
  return res.json() as Promise<T>;
}

export const getHealth = () => request<{ status: string }>("/health");
export const listProposals = () => request<Proposal[]>("/proposals");
export const approveProposal = (id: string) => request<Proposal>(`/proposals/${id}/approve`, { method: "POST" });
```

`web/.env.example`:
```text
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 3: Replace the home page**

`web/src/app/page.tsx`:
```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { approveProposal, getHealth, listProposals, type Proposal } from "@/lib/api";

export default function Home() {
  const [status, setStatus] = useState("checking");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus((await getHealth()).status);
      setProposals(await listProposals());
      setError(null);
    } catch (e) {
      setStatus("offline");
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-6">
      <h1 className="text-3xl font-semibold">PolyBridge</h1>
      <p>Backend: <strong>{status}</strong></p>
      {error && <p className="text-red-600">Can't reach the backend: {error}. Start it with <code>make setup-backend</code> and <code>uv run uvicorn app.main:app</code>.</p>}
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Hedge proposals</h2>
        {proposals.length === 0 && <p>No proposals yet. POST one to /proposals.</p>}
        {proposals.map((p) => (
          <div key={p.id} className="flex items-center justify-between rounded border p-3">
            <span>{p.ticker} · {p.strategy} · {p.status}</span>
            {p.status === "proposed" && (
              <button className="rounded border px-3 py-1" onClick={async () => { await approveProposal(p.id); await refresh(); }}>
                Approve
              </button>
            )}
          </div>
        ))}
      </section>
    </main>
  );
}
```

- [ ] **Step 4: Lint and build**

Run: `make test-web`
Expected: lint passes and `next build` completes with no type errors.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "Web skeleton: Next.js with typed API client and approval queue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Contracts doc, CI, and push

**Files:**
- Create: `docs/contracts.md`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: every interface from Tasks 2, 3, 6, 7, 8 and 9.
- Produces: the single source each lane reads before touching another lane's boundary; CI that runs all four suites on every PR.

- [ ] **Step 1: Write the contracts doc**

`docs/contracts.md`:
````markdown
# PolyBridge contracts

Everything that crosses a folder boundary. Change this file and the code together, in one PR reviewed by the other lane.

## Families and tags (`research/polybridge_research/schema.py`)

| Family | Value | Tags | Strategy |
|---|---|---|---|
| H1 hedge | `"hedge"` | material_litigation, class_action_filing, regulatory_investigation, cybersecurity_incident, goodwill_impairment, asset_impairment, investment_impairment | `protective_put` |
| H2 opportunity | `"opportunity"` | restructuring_plan, workforce_reduction, facility_closure, business_line_exit | `cash_secured_put` |

`assign_family(tags)` returns `None` for tags from both families or from neither.

## Event (Python)

`Event(ticker: str, filing_date: date, tags: frozenset[str], source: str = "massive_8k", accession_number: str | None = None)` and `.family`.

## Parity (`research/polybridge_research/parity.py`)

`implied = (C_K + P_K) / S_entry` · `implied_scaled = implied·√(sessions_held / dte_sessions)` · `ratio = |S_exit/S_entry − 1| / implied_scaled`

## HTTP API (`backend/`, mirrored in `web/src/lib/api.ts`)

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| GET | `/health` | none | `{"status":"ok"}` | none |
| POST | `/classify` | `{"tags": [str]}` | `{"family", "strategy"}` (nulls if no family) | 422 bad body |
| POST | `/proposals` | `{"ticker", "tags", "shares_held" > 0, "target_coverage" ∈ [0,1] = 0.5}` | 201 `Proposal` | 422 no family or bad body |
| GET | `/proposals` | none | `[Proposal]` | none |
| POST | `/proposals/{id}/approve` | none | `Proposal` status `approved` | 404 unknown, 409 already decided |
| POST | `/proposals/{id}/reject` | none | `Proposal` status `rejected` | 404, 409 |

`Proposal = {id, ticker, family, strategy, shares_held, target_coverage, status, created_at, decided_at}`

## hedgecore (`engine/hedgecore`, C++20 + Python module `hedgecore`)

- `HedgeSpec{ticker, shares_held, target_coverage=0.5, band_shares=10, max_hedge_shares=0 (= shares_held), max_staleness_ns=2e9, sigma_k=2.0, sigma_alpha=0.05}`
- `Engine(spec).on_tick(ts_ns, p, now_ns) -> Decision{action: hold|order, reason: invalid|stale|below_sigma|inside_band|rebalance|risk_capped, order_qty, target_hedge, current_hedge, latency_ns}`
- `on_fill(qty)` after the broker confirms. Default sizing: `target = round(c · N · p)`, capped.
- A `HedgeSpec` is built only from an **approved** `Proposal`.
````

- [ ] **Step 2: Write the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]

jobs:
  research:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: cd research && uv venv .venv --python 3.10 && uv pip install --python .venv -e ".[dev]"
      - run: cd research && .venv/bin/python -m pytest -q

  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: cd backend && uv sync && uv run pytest -q

  engine:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y ninja-build
      - run: cmake -S engine/hedgecore -B engine/hedgecore/build -G Ninja -DCMAKE_BUILD_TYPE=Release
      - run: cmake --build engine/hedgecore/build
      - run: ctest --test-dir engine/hedgecore/build --output-on-failure

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          package_json_file: web/package.json
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: web/pnpm-lock.yaml
      - run: cd web && pnpm install --frozen-lockfile && pnpm lint && pnpm build
```

The `research` job pins Python 3.10 on purpose: it proves the judges' minimum works.

- [ ] **Step 3: Run every suite locally**

Run: `make test`
Expected: research `30 passed`, backend `7 passed`, engine `7 tests passed`, web lint + build succeed.

- [ ] **Step 4: Commit and push**

```bash
git add docs/contracts.md .github/workflows/ci.yml
git commit -m "Contracts doc and CI for research, backend, engine, web

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 5: Confirm CI is green**

Run: `gh run watch --repo theomachado05/polybridge --exit-status`
Expected: all four jobs succeed.
