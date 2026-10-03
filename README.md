# PolyBridge

Hedge equity positions using live prediction-market prices (Polymarket + Kalshi) as the signal. A human approves every hedge; a compiled C++ algo library runs it on a paper or simulated account.

**Start here:** [v4 design spec](docs/superpowers/specs/2026-10-03-polybridge-v4-design.md) · [HTTP contracts](docs/contracts.md) · [90-second demo script](docs/demo.md) · [voice agent](docs/voice-agent.md)

| Folder | Stack | Role |
|---|---|---|
| `engine/` | C++20 · pybind11 | hedgecore: header-only blocks composed into algo families (1,278 presets), run on approved hedges |
| `backend/` | Python 3.12 · FastAPI | Control plane: markets, AI mapping and fit, proposals, bridges (SSE), broker (sim / Webull paper), portfolio |
| `web/` | Next.js · TypeScript | UI: Build chat, AI pipeline, Bridge live, Library, Portfolio, Connect, Profile |
| `research/` | Python | Evidence: pre-registered 8-K study, lead-lag case studies, closed-market study, options-arbitrage scan |
| `scripts/`, `replays/`, `web/e2e/` | Python, Node | End-to-end demo driver, recorded Polymarket replays, headless-Chrome UI walk and screenshots |

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 24+ with pnpm, `cmake` and `ninja` (`uv tool install cmake ninja`) to build the C++ library, Chrome for the screenshot pass.

```bash
cp .env.example .env            # then fill in the keys you have (table below); every key is optional except for live data
cd backend && uv sync --locked --group engine && cd ..   # builds hedgecore (the C++ algo library)
make setup-web                  # pnpm install

make dev                        # backend :8000 (offline replay) + web :3000, Ctrl-C stops both
# open http://localhost:3000  (not 127.0.0.1: the backend's CORS allows localhost only)
```

`make dev` replays a month of real Polymarket history for the Fed October 2026 market at 36000x (about 72 seconds), so the click path does not depend on Polymarket being reachable (replay fills use a Massive quote when one is available, else the recorded price from the replay; see the fallbacks in [docs/demo.md](docs/demo.md#4-fallbacks-what-each-failure-looks-like-and-what-to-say)). `make dev-live` starts bridges on the live Polymarket book instead. `REPLAY=replays/<file>.jsonl make dev` plays another recording ([replays/README.md](replays/README.md)).

| Command | What it does |
|---|---|
| `make dev` | Backend (engine group, replay) + web dev server |
| `make test` | Every lane: research, backend, C++ (ctest), engine bindings, web lint + build |
| `make e2e` | Starts both servers, drives the full flow over HTTP with assertions, clicks the real UI in headless Chrome, saves 8 screenshots to `web/e2e/screens/`, stops everything |
| `make e2e-api` | The HTTP half of `make e2e` only (no web server, no Chrome) |
| `make test-backend` / `test-engine` / `test-engine-py` / `test-web` / `test-research` | One lane |

### Environment variables

Keys live only in `.env` (gitignored) or your shell. A missing key means a graceful fallback, never a crash or a 500.

| Variable | Used by | Without it |
|---|---|---|
| `MASSIVE_API_KEY` | backend: equity quotes and bars, options chains, research notebooks | no live equity quote or options data; recorded bars and the bundled data still work |
| `GEMINI_API_KEY` (optional `GEMINI_MODEL`, default `gemini-2.5-flash`) | backend: event classification and the fit rationale | a keyword-rules classifier and a template rationale; the UI labels it "rules-based fit" |
| `ELEVENLABS_API_KEY` | only to create or edit the voice agent through the ElevenLabs API/CLI | nothing: the app does not read it |
| `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` | web (`web/.env.local`): embeds the voice widget | no voice button renders |
| `BROKER` (`sim` default, or `webull`) | backend: which account takes orders | the simulated account ($1,000,000, deterministic) |
| `WEBULL_APP_KEY`, `WEBULL_APP_SECRET` (optional `WEBULL_ACCOUNT_ID`, `WEBULL_BASE_URL`) | backend: Webull OpenAPI paper trading when `BROKER=webull` | the simulated account, labelled "Simulated account" |
| `POLYBRIDGE_REPLAY_PATH`, `POLYBRIDGE_REPLAY_SPEED` | backend: replay file and speed for `source: "replay"` bridges and the offline fallback | `replays/<market id>.jsonl` at real time |
| `NEXT_PUBLIC_API_URL` | web: backend URL | `http://localhost:8000` |
| `SIM_ACCOUNT_PATH`, `SIM_START_CASH` | backend: where the simulated account is saved and its starting cash | `backend/.sim_account.json` (gitignored), $1,000,000 |

Real-money execution is out of scope: accounts are simulated or Webull paper only.

## Honest labels

Replay vs live, AI estimate vs measured, simulated vs Webull paper, case study vs proof: the UI says which one you are looking at. A replay bridge trades in a replay sandbox (not your account) unless started with `replay_to_account`. Evidence so far: lead-lag during market hours is mixed to negative, the closed-market study is mixed, and the options-arbitrage scan found 5 resolved gaps and 0 executable ones. See [docs/demo.md](docs/demo.md#claims-we-make-and-do-not-make).

## Workflow

Read [CONTRIBUTING.md](CONTRIBUTING.md): two lanes (Research, Product), shared files change only by PR, and `make test` runs every lane's tests.

Pre-registration: [research/HYPOTHESIS.md](research/HYPOTHESIS.md) and [research/HYPOTHESIS_TAGS.md](research/HYPOTHESIS_TAGS.md).
