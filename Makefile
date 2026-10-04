.PHONY: setup-research test-research reproduce setup-backend test-backend build-engine test-engine test-engine-py setup-web test-web test dev dev-live dev-tlt dev-ita dev-iwm dev-nvda e2e e2e-api e2e-opportunity e2e-weekend e2e-demo share webull-check gemini-check openai-check voice-agent keys-check

research/.venv:
	$(MAKE) setup-research

setup-research:
	cd research && uv venv .venv && uv pip install --python .venv -e ".[dev]"

test-research: research/.venv
	cd research && .venv/bin/python -m pytest -q

# Reproduce the quant note's headline numbers (note/NOTE.md) from the committed result files: offline, no API key.
# One MATCH or MISMATCH line per claim; rewrites note/TABLES.md and note/figures/; exits 1 on any mismatch.
# Uses research/.venv (made by `make setup-research` when missing). Any Python with the research dependencies also
# works: `make reproduce PYTHON=/path/to/python`.
PYTHON ?=
reproduce: $(if $(PYTHON),,research/.venv)
	cd research && $(if $(PYTHON),$(PYTHON),.venv/bin/python) reproduce.py

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
# Default demo (D3): the validated closed-market weekend. "US recession in 2025?" (the one market whose expected-gap model
# passes out of sample) over Fri 2025-04-04 15:30 ET -> Mon 2025-04-07 10:00 ET, hedging SPY: 799 five-minute points at
# 3600x, about 67 s (approve the staged plan before Monday 04:00, about 61 s in).
# Recorded-price fills: REPLAY_PRICES=recorded (POLYBRIDGE_REPLAY_PRICES) makes every replay sandbox fill at the replayed
# price, so the bridge's own fills and the weekend P&L share one price time while .env stays loaded (Gemini, ElevenLabs
# and Webull keys are needed for the pitch). This replaces the older `make dev ENVFILE= ... SPEED=3600` recipe, which
# could not work: the backend finds ../.env on its own. `make dev REPLAY_PRICES=` restores today's-quote fills.
# With BROKER=webull while the market is closed, GET /account shows webull-paper (market_open false), replays trade their
# in-memory sandbox, and only approved staged orders reach Webull, executing at the 09:30 ET open.
# Other recordings play at their own sidecar replay_speed when a bridge picks them through the replay index (no
# restart). Documented alternatives, as the configured file (fills as before: today's quote when Massive answers,
# else the recorded price, labelled):
#   make dev-tlt    "Another Fed rate hike in 2026?" -> TLT (401 hourly points at 21600x, about 67 s)
#   make dev-ita    Russia/EU military clash -> ITA (18000x, about 69 s)
#   make dev-iwm    Fed October 25 bps hike -> IWM (36000x, about 72 s)
#   make dev-nvda   Opportunity division: NVDA > $230 end of September, options call spread (21600x, about 59 s)
ENVFILE := $(if $(wildcard .env),--env-file ../.env,)
REPLAY ?= backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl  # relative to the repo root
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

# Same, without a replay file: bridges start on the live Polymarket book (needs network; falls back per bridge).
dev-live:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run --group engine $(ENVFILE) uvicorn app.main:app --port 8000) & \
	(cd web && pnpm dev) & \
	wait

# `make share`: the whole app behind ONE public URL (docs/share.md). Backend :8000 + web :3000 in tunnel mode
# (NEXT_PUBLIC_API_URL=/api: the browser calls /api/*, the Next.js server proxies it to 127.0.0.1:8000 and adds
# X-Agent-Secret from AGENT_TOOL_SECRET server side), then `ngrok http 3000 --basic-auth "$NGROK_BASIC_AUTH"`. Refuses to
# start without NGROK_BASIC_AUTH=user:password and AGENT_TOOL_SECRET in .env. Prints the public URL and the one-time
# `PUBLIC_WEB_HOST=<host> make voice-agent` command. SHARE_NO_NGROK=1: the same servers, no tunnel (local check).
share:
	REPLAY=$(REPLAY) SPEED=$(SPEED) REPLAY_PRICES=$(REPLAY_PRICES) bash scripts/share.sh

# End-to-end: starts both servers, drives search -> map -> fit -> propose -> approve -> bridge -> SSE -> account over
# HTTP, clicks the real UI in headless Chrome and screenshots the 8 screens into web/e2e/screens/, then stops everything.
e2e:
	python3 scripts/e2e_demo.py $(E2E_ARGS)

e2e-api:
	python3 scripts/e2e_demo.py --no-screens $(E2E_ARGS)

# The Opportunity division over HTTP: the NVDA > $230 recording's options fit -> approved binary_vs_spread_arb proposal ->
# replay bridge with simulated multi-leg option orders (API only, about 60 s).
e2e-opportunity:
	python3 scripts/e2e_demo.py --opportunity $(E2E_ARGS)

# Closed-market mode over HTTP: the recorded 2025-04-04 weekend on the US recession 2025 market (the one market whose
# expected-gap model is validated out of sample) -> expected gap -> staged order approved -> executes at the first
# tradable moment -> P&L vs no hedge (API only, recorded prices, about 70 s).
e2e-weekend:
	python3 scripts/e2e_demo.py --weekend $(E2E_ARGS)

# The default demo's flow (the validated weekend, `make dev`'s replay), end to end over HTTP. `make e2e` stays on the TLT
# replay as the regression run.
e2e-demo:
	python3 scripts/e2e_demo.py --weekend $(E2E_ARGS)

# Webull paper smoke check, read-only: account (type / class), balance, positions, open orders, market_open, the
# extended-hours capability. Never places an order outside 09:30-16:00 ET; during the regular session
# WEBULL_SMOKE_ORDER=1 also places and cancels a 1-share SPY limit at $1.00 (cannot fill). Ids are masked.
webull-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/webull_check.py

# --- AI keys (OPENAI_API_KEY, GEMINI_API_KEY, ELEVENLABS_API_KEY in the repo-root .env; values are never printed) ------------------
# Gemini: lists the models the key can use, picks the newest flash model, runs one classify + one explain + one live
# ticker mapping through the app's own GeminiProvider; prints model, latency and results. Exit 2 = no key, 1 = failed.
gemini-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/gemini_check.py

# OpenAI (same role as Gemini; never decides a trade): lists the models the key can use (ids matching OPENAI_MODEL plus
# the newest few), runs one classify + one explain + one live ticker mapping through the app's own OpenAIProvider;
# prints model, latency and results. Exit 2 = no key, 1 = key rejected, OPENAI_MODEL not listed, or a call failed.
# Provider order in the app: OpenAI -> Gemini -> rules; LLM_PROVIDER=openai|gemini|rules|auto (default auto).
openai-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/openai_check.py

# ElevenLabs: create (or update) the PolyBridge agent with CLIENT tools matching GET /agent/tools (no tunnel), then
# write only NEXT_PUBLIC_ELEVENLABS_AGENT_ID into web/.env.local (gitignored). Idempotent. ARGS=--dry-run: no network.
voice-agent:
	cd backend && uv run --locked $(ENVFILE) python scripts/elevenlabs_agent.py $(ARGS)

# Which keys are present (names only); runs openai-check, gemini-check and read-only ElevenLabs calls when their keys are present.
keys-check:
	cd backend && uv run --locked $(ENVFILE) python scripts/keys_check.py

# --- forward tests (rules frozen; no trading) -----------------------------------------------------------------------
# make forward-ladders: research/ladder_replay/live.py once (every open date ladder's real books), a timestamped snapshot
# under backend/data_forward/ladders/. make forward-touch: list the "will it hit" markets eligible under
# research/touch_fresh/FORWARD.md (listed from Mon 5 Oct) and record their state under backend/data_forward/touch/.
# The frozen runner's timed stages: forward-touch-snapshot (Friday 15:55 New York), forward-touch-prints (after Sunday
# 20:00), forward-touch-evaluate. GET /forward/status shows the latest of each.
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
