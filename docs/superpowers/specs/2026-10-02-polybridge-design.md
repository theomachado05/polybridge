# PolyBridge — Design Spec

**Date:** 2026-10-02 · **Event:** GatorQuant Hackathon · **Status:** Draft for team review

## 1. Thesis

Prediction markets were built so people could hedge real-world events. PolyBridge runs the
bridge in reverse: it treats the live Polymarket / Kalshi order book as a **price signal** and
uses it to hedge an **equity position** that the event moves.

Example: *"Will California ban short-term rentals statewide before 2027?"* trades at YES 23¢.
An AI impact model estimates a YES outcome moves ABNB −3.2% (≈ −1% revenue, −5% brand).
A user long 1,200 ABNB picks a hedge; a low-latency C++ algo stack then re-sizes that hedge
tick by tick as the probability moves, aware of the user's fees, tax lots and wash-sale rules.

## 2. Demo goal and success criteria

The deliverable is an **end-to-end live demo** for judges.

- Real prediction-market data (Polymarket + Kalshi), real equity quotes, real AI impact estimates.
- Simulated execution: orders go to an in-engine paper gateway, never a real broker.
- Tick-to-decision latency measured inside the engine and shown in the UI (p50 / p99).
- The demo cannot die on stage: every live input has a recorded-replay fallback (§9).

Success = a judge can (1) pick an event, (2) see ranked affected stocks with reasoning,
(3) pick a ranked hedge, (4) watch the Bridge screen hedge live with an explained trade log.

## 3. Architecture

Two planes. The **hot path is C++ only**; Python never sits between a tick and an order.

```
 HOT PATH — engine/ (C++20, one process)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ feed threads (pinned)              strategy thread (pinned)              │
 │  Polymarket CLOB WS ─┐                                                   │
 │  Kalshi WS / REST ───┼─► SPSC lock-free rings ─► algo pipeline ─► paper gateway
 │  Equity WS / sim ────┘                              │                 │  │
 │                          telemetry ring ◄───────────┴── non-blocking ─┘  │
 └──────────── ZeroMQ: control REP (tcp:5555) · telemetry PUB (tcp:5556) ───┘
                                   │
 CONTROL PLANE — api/ (Python 3.12, FastAPI)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ markets/   event search over Polymarket Gamma + Kalshi REST              │
 │ impact/    Claude → ranked tickers, expected move, rationale (cached)    │
 │ hedges/    rank put spread / collar / dynamic short / buy YES            │
 │ portfolio/ seeded demo account: lots, cost basis, account type, tax rate │
 │ bridge/    start/stop/configure engine bridges; telemetry → UI at ~15 Hz │
 └───────────────────────────── REST + WebSocket ───────────────────────────┘
                                   │
 UI — web/ (Next.js App Router, TypeScript, Tailwind)
   Build (Event → Equity → Hedge) · Bridge (live) · Library · Portfolio
```

### 3.1 Hot-path rules (engine/)

- One thread per feed, one strategy thread; each pinned to a core where the OS allows it.
- Feed → strategy handoff through single-producer/single-consumer lock-free ring buffers.
- JSON decoded with simdjson. No heap allocation and no virtual dispatch on the per-tick path:
  the algo stack is a template pipeline, all state preallocated when a bridge starts.
- Telemetry (algo states, fills, reasons, latency samples) is pushed to its own ring and sent by
  a separate publisher thread. A slow subscriber can drop telemetry; it can never stall a hedge.
- Latency is measured as `t_decision − t_tick_received` (monotonic clock), recorded per algo
  into an HDR-style histogram; p50 / p99 published once per second.
- Honest claim for the pitch: decision latency is microseconds; network delay to the venues
  (≈20–150 ms) dominates and is outside our control. We add nothing on top of it.

### 3.2 Why not Python on the hot path

The GIL, asyncio scheduling and object allocation would add milliseconds of jitter per tick, so
calling C++ from a Python loop would waste the C++. Python owns everything that is allowed to be
slow: LLM calls, ranking, portfolio state, UI fan-out.

## 4. Data sources

| Feed | Source | Mode | Notes |
|---|---|---|---|
| Event discovery | Polymarket Gamma API, Kalshi `trade-api/v2/markets` | REST, api/ | Public, no key |
| Prediction book | Polymarket CLOB market WebSocket | WS, engine/ | Public, no key |
| Prediction confirm | Kalshi WebSocket (API key) or REST poll at 1 Hz (no key) | engine/ | Used as cross-venue confirmation |
| Equity quotes | Finnhub WebSocket (free key) | WS, engine/ | Outside market hours → sim feed (§9) |
| Impact model | Anthropic API, `claude-sonnet-5-5` | api/ | Structured output, cached per (event, ticker) |

Secrets live in `.env` (never committed); `.env.example` lists `FINNHUB_API_KEY`,
`ANTHROPIC_API_KEY`, optional `KALSHI_API_KEY_ID` / `KALSHI_PRIVATE_KEY_PATH`.

## 5. Components

### 5.1 Impact model (api/impact)

Input: event (title, description, resolution date) + candidate tickers (user holdings first,
then model-suggested). Output per ticker, as a validated Pydantic schema:

```json
{ "ticker": "ABNB", "move_on_yes_pct": -3.2,
  "components": { "revenue_pct": -1.0, "brand_pct": -5.0 },
  "rationale": "CA ≈ 9% of nights; 18-month phase-in. Brand hit sized on NYC Local Law 18 comps.",
  "confidence": 0.6 }
```

Results are cached to disk (JSON) so a demo run never waits on the LLM, and the same event
always shows the same numbers. A small set of demo events is pre-warmed at startup.

### 5.2 Hedge ranking (api/hedges)

Four hedge types, ranked for the account (taxable vs. IRA, marginal rate, lots held):

| Type | Covers | Cost model | Tax note |
|---|---|---|---|
| Dynamic short (engine-driven) | Scales with Δp | $0.0035/sh + borrow rate | Lot-aware, avoids wash sales |
| Put spread | Defined range | Option debit (BS-priced from IV) | Equity option |
| Collar | Floor/cap | ≈ zero cost | May pause holding period |
| Buy YES | Pays on resolution only | Contract price | Treatment unclear; not a price hedge |

Only **Dynamic short** runs live in the engine. The other three are priced and explained but
executed as a single simulated order.

### 5.3 Engine algo library (engine/)

About 12 real algo families. Every family is parameterised, and the **Library** is the registry
of families × parameter grid (that is where the "1,284 algos" comes from; the UI says so).

| Stage | Family | Role |
|---|---|---|
| Gate | SigmaGate | Ignore Δp below k·σ of recent prob noise |
| Gate | CrossVenueConfirm | Require Kalshi to agree in direction with Polymarket |
| Signal | BookImbalanceReader | Bid/ask depth imbalance on the YES book |
| Signal | DriftEstimator | How much of the event the stock already prices in |
| Sizing | DeltaBridge | Target hedge from p, impact, position (below) |
| Sizing | InventoryBand | No-trade band (hysteresis) to avoid churn |
| Execution | VolAdaptiveSlicer | Slice the order by equity volatility |
| Execution | TWAP | Time-sliced fallback slicer |
| Execution | FeeAwareRouter | Pick venue and size net of fees |
| Tax | TaxLotOptimizer | Choose lots to cover / short against |
| Tax | WashSaleGuard | Block trades that would trigger a wash sale |
| Risk | RiskLimits | Max hedge, max notional per minute, kill switch |

**DeltaBridge default policy** (tunable per bridge):
target coverage `c = clamp(α · p · |m| / m_ref, 0, c_max)`, target short `h* = round(c · N)`,
where `p` = YES probability, `m` = move on YES, `N` = shares held, `m_ref` = 1%, `α` and `c_max`
set by the bridge config (defaults α = 1.0, c_max = 1.0). With the demo inputs, coverage rises
with p, and InventoryBand only trades when `|h* − h| ≥ band`.

Each decision emits a **reason record**, which becomes the trade-log text in the UI: which gates passed,
Δp and volume, confirming venue price, expected drift, slicer parameters, fee and lot choice.

## 6. Engine ↔ API contract (ZeroMQ, JSON v1)

Control, REQ/REP on `tcp://*:5555`:

```json
{"op":"start_bridge","bridge_id":"abnb-ca-str","event":{"polymarket_token_id":"…","kalshi_ticker":"…"},
 "equity":{"symbol":"ABNB","shares":1200,"lots":[{"qty":1200,"cost":101.20,"acquired":"2023-04-11"}]},
 "impact":{"move_on_yes_pct":-3.2},"hedge":{"type":"dynamic_short","alpha":1.0,"c_max":1.0,"band":20},
 "costs":{"per_share":0.0035,"borrow_bps_annual":30},"stack":["SigmaGate","CrossVenueConfirm","BookImbalanceReader","DeltaBridge","InventoryBand","VolAdaptiveSlicer","TaxLotOptimizer","FeeAwareRouter","RiskLimits"]}
{"op":"stop_bridge","bridge_id":"abnb-ca-str"}
{"op":"status"}
```

Telemetry, PUB on `tcp://*:5556`. The topic is the message type:

- `tick` — `{bridge_id, venue, price, volume, ts_ns}`
- `algo` — `{bridge_id, name, state: passed|fired|executing|blocked, sigma, latency_ns, detail}`
- `fill` — `{bridge_id, side, qty, price, algo, fee, lot, reason, ts_ns}`
- `position` — `{bridge_id, long, hedge_short, avg_short, coverage, pnl_today}`
- `latency` — `{bridge_id, p50_ns, p99_ns, samples}`

The contract is frozen at v1 at kickoff; any change goes through a PR touching this section.

## 7. UI (web/)

Matches the reference mockups: light glass panels, periwinkle→peach gradients, faint grid.

- **Build**: three linked cards (Event · Equity · Hedge) plus a step panel. Step 1 is market search
  with category chips and "touches your X". Step 2 is ranked stocks with expected-move bars and
  rationale. Step 3 is ranked hedge cards with an "AI pick" badge.
- **Bridge**: prediction card (price, sparkline, volume, confirming venue), engine node in the centre,
  equity card. The algo-stack pills show live state and latency. Below are portfolio P&L, coverage,
  and the "Trades & reasoning" log.
- **Library**: browse families × parameters, with measured latency per family.
- **Portfolio**: holdings, active bridges, realised and unrealised P&L.

API: REST for Build/Library/Portfolio; one WebSocket `/ws/bridge/{id}` per live bridge, throttled to about 15 Hz.

## 8. Demo account (seeded)

Taxable account, 32% marginal rate. Holdings: ABNB 1,200 sh, MAR 300 sh, JPM, META, NVDA
(sizes in `api/portfolio/seed.json`). No auth: single demo user.

## 9. Failure handling and demo safety

- **Market closed / equity feed down** → engine switches to a sim feed: a geometric Brownian
  motion (random walk in log price) seeded from the last real quote. The UI shows a `SIMULATED` badge.
- **Venue WS drops** → reconnect with backoff; the bridge holds its current hedge (no trading on stale data)
  and the UI shows the feed as stale.
- **Replay mode** → the engine records raw feed messages to `engine/recordings/*.jsonl`, and
  `--replay <file>` plays them back at real speed. We record a good session before demo day.
- **LLM down** → serve cached impact results; never block the UI on Claude.
- **Engine not running** → api/ ships `fake_engine.py`, which replays a recording over the same
  ZeroMQ sockets, so web/ and api/ can be built without a compiled engine.

## 10. Testing

- engine: GoogleTest unit tests per algo family plus a deterministic replay test (fixed input → fixed fills);
  a latency micro-benchmark gate in CI.
- api: pytest for ranking, impact schema validation, and contract round-trip against `fake_engine.py`.
- web: typecheck plus lint in CI; manual demo walkthrough checklist.
- CI (GitHub Actions): build engine, run all tests, lint web on every PR to `main`.

## 11. Repo and team workflow

```
polybridge/
  web/        Next.js app
  api/        FastAPI control plane (+ fake_engine.py)
  engine/     C++20 engine (CMake, FetchContent: simdjson, IXWebSocket, cppzmq, GoogleTest)
  docs/       specs, contract, demo script
  docker-compose.yml  Makefile  .env.example  .github/workflows/ci.yml
```

- `main` is protected; work on `feat/<area>-<thing>` branches and merge via PR.
- Ownership by folder (CODEOWNERS once owners are named): web · api · engine.
- `make dev` runs engine and api in Docker, plus `pnpm dev` for web.

## 12. Out of scope

Real broker execution, user accounts/auth, real tax filing logic, options execution in the
engine, mobile apps.
