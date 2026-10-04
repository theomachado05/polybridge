.PHONY: setup-research test-research setup-backend test-backend build-engine test-engine test-engine-py setup-web test-web test dev dev-live dev-tlt dev-ita dev-iwm dev-nvda e2e e2e-api e2e-opportunity e2e-weekend e2e-demo share webull-check gemini-check openai-check voice-agent keys-check

research/.venv:
	$(MAKE) setup-research

setup-research:
	cd research && uv venv .venv && uv pip install --python .venv -e ".[dev]"

test-research: research/.venv
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

test-engine-py:
	cd backend && uv sync --locked --group engine && uv run --locked --group engine pytest ../engine/hedgecore/tests tests -q

test: test-research test-backend test-engine test-engine-py test-web

ENVFILE := $(if $(wildcard .env),--env-file ../.env,)
REPLAY ?= backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl
SPEED ?= 3600
REPLAY_PRICES ?= recorded

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && POLYBRIDGE_REPLAY_PATH=$(abspath $(REPLAY)) POLYBRIDGE_REPLAY_SPEED=$(SPEED) POLYBRIDGE_REPLAY_PRICES=$(REPLAY_PRICES) uv run --group engine $(ENVFILE) uvicorn app.main:app --port 8000) & \
	(cd web && pnpm dev) & \
	wait

dev-tlt:
	$(MAKE) dev REPLAY=backend/replays/another-fed-hike-2026-history.jsonl SPEED=21600 REPLAY_PRICES=

dev-ita:
	$(MAKE) dev REPLAY=backend/replays/russia-eu-military-2026-history.jsonl SPEED=18000 REPLAY_PRICES=

dev-iwm:
	$(MAKE) dev REPLAY=backend/replays/fed-hike-25bps-oct-2026-history.jsonl SPEED=36000 REPLAY_PRICES=

dev-nvda:
	$(MAKE) dev REPLAY=backend/replays/nvda-230-sep-2026-history.jsonl SPEED=21600 REPLAY_PRICES=

dev-live:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run --group engine $(ENVFILE) uvicorn app.main:app --port 8000) & \
	(cd web && pnpm dev) & \
	wait

share:
	REPLAY=$(REPLAY) SPEED=$(SPEED) REPLAY_PRICES=$(REPLAY_PRICES) bash scripts/share.sh

e2e:
	python3 scripts/e2e_demo.py $(E2E_ARGS)

e2e-api:
	python3 scripts/e2e_demo.py --no-screens $(E2E_ARGS)

e2e-opportunity:
	python3 scripts/e2e_demo.py --opportunity $(E2E_ARGS)

e2e-weekend:
	python3 scripts/e2e_demo.py --weekend $(E2E_ARGS)

e2e-demo:
	python3 scripts/e2e_demo.py --weekend $(E2E_ARGS)

webull-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/webull_check.py

gemini-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/gemini_check.py

openai-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/openai_check.py

voice-agent:
	cd backend && uv run --locked $(ENVFILE) python scripts/elevenlabs_agent.py $(ARGS)

keys-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/keys_check.py

.PHONY: forward-ladders forward-touch forward-touch-snapshot forward-touch-prints forward-touch-evaluate
forward-ladders:
	cd backend && uv run $(ENVFILE) python ../scripts/forward_ladders.py

forward-touch:
	cd backend && uv run $(ENVFILE) python ../scripts/forward_touch.py list

forward-touch-snapshot:
	cd backend && uv run $(ENVFILE) python ../scripts/forward_touch.py snapshot

forward-touch-prints:
	cd backend && uv run $(ENVFILE) python ../scripts/forward_touch.py prints

forward-touch-evaluate:
	cd backend && uv run $(ENVFILE) python ../scripts/forward_touch.py evaluate
