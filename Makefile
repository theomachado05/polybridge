.PHONY: setup-research test-research setup-backend test-backend build-engine test-engine test-engine-py setup-web test-web test dev dev-live e2e e2e-api

setup-research:
	cd research && uv venv .venv && uv pip install --python .venv -e ".[dev]"

test-research:
	cd research && .venv/bin/python -m pytest -q

setup-backend:
	cd backend && uv sync --locked

test-backend:
	cd backend && uv run --locked pytest -q

build-engine:
	cmake -S engine/hedgecore -B engine/hedgecore/build -G Ninja -DCMAKE_BUILD_TYPE=Release
	cmake --build engine/hedgecore/build

test-engine: build-engine
	ctest --test-dir engine/hedgecore/build --output-on-failure

setup-web:
	cd web && pnpm install

test-web:
	cd web && pnpm lint && pnpm test && pnpm build

# Engine group: the hedgecore binding tests AND the whole backend suite, so the tests that skip without the engine
# (bridge/engine replay parity, test_bridges_engine, test_e2e_engine, ...) really run under `make test`.
test-engine-py:
	cd backend && uv sync --locked --group engine && uv run --locked --group engine pytest ../engine/hedgecore/tests tests -q

test: test-research test-backend test-engine test-engine-py test-web

# --- run the demo -----------------------------------------------------------------------------------------------
# `make dev`: backend (engine group, offline replay of real Polymarket history) on :8000 and the web dev server on :3000.
# Keys come from ./.env when it exists (MASSIVE_API_KEY, GEMINI_API_KEY, BROKER, WEBULL_*); any missing key degrades
# gracefully. Open http://localhost:3000 (not 127.0.0.1). Ctrl-C stops both.
# Default demo: "Another Fed rate hike in 2026?" hedging TLT (401 hourly points, 6 ticks/s at 21600x: about 67 s).
# Alternatives (pick the matching market in Build; the replay file is global to the backend):
#   REPLAY=backend/replays/russia-eu-military-2026-history.jsonl SPEED=18000 make dev   # Russia/EU -> ITA, about 69 s
#   REPLAY=backend/replays/fed-hike-25bps-oct-2026-history.jsonl SPEED=36000 make dev   # Fed October -> IWM, about 72 s
ENVFILE := $(if $(wildcard .env),--env-file ../.env,)
REPLAY ?= backend/replays/another-fed-hike-2026-history.jsonl  # relative to the repo root
SPEED ?= 21600

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && POLYBRIDGE_REPLAY_PATH=$(abspath $(REPLAY)) POLYBRIDGE_REPLAY_SPEED=$(SPEED) uv run --group engine $(ENVFILE) uvicorn app.main:app --port 8000) & \
	(cd web && pnpm dev) & \
	wait

# Same, without a replay file: bridges start on the live Polymarket book (needs network; falls back per bridge).
dev-live:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run --group engine $(ENVFILE) uvicorn app.main:app --port 8000) & \
	(cd web && pnpm dev) & \
	wait

# End-to-end: starts both servers, drives search -> map -> fit -> propose -> approve -> bridge -> SSE -> account over
# HTTP, clicks the real UI in headless Chrome and screenshots the 8 screens into web/e2e/screens/, then stops everything.
e2e:
	python3 scripts/e2e_demo.py

e2e-api:
	python3 scripts/e2e_demo.py --no-screens
