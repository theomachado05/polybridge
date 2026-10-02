# PolyBridge — Design Spec

**Date:** 2026-10-02 · **Event:** GatorQuant Hackathon · **Status:** Draft for team review
**Diagrams:** [`docs/system-map.html`](../../system-map.html) (system, parity, tick loop)

## 1. Thesis

Prediction markets were built so people could hedge real-world events. PolyBridge runs the
bridge in reverse: it treats the live Polymarket / Kalshi order book as a **price signal** and
uses it to hedge an **equity position** that the event moves.

Example: *"Will California ban short-term rentals statewide before 2027?"* trades at YES 23¢.
An AI impact model estimates the event's price gap for ABNB. A user long 1,200 ABNB picks a
hedge. From a library of 1,200+ C++ algos, the AI assembles the best-fitting stack, and that
stack keeps the hedge sized tick by tick as the probability moves. It accounts for the user's
fees, tax lots and wash-sale rules.

## 2. Demo goal and success criteria

The deliverable is an **end-to-end live demo** for judges.

- Real prediction-market data (Polymarket + Kalshi), real equity quotes, real AI impact estimates.
- Simulated execution: orders go to an in-engine paper gateway, never a real broker.
- Tick-to-decision latency measured inside the engine and shown in the UI (p50 / p99).
- The demo cannot die on stage: every live input has a recorded-replay fallback (§10).

Success = a judge can (1) pick an event, (2) see ranked affected stocks with reasoning,
(3) pick a ranked hedge, (4) see which algo stack the AI chose and why it won the replay test,
(5) watch the Bridge screen hedge live with an explained trade log.

## 3. Fundamentals: Prediction–Price Parity (PPP)

PPP is the assumption that links the two markets. **The stock already prices in the event at the
prediction market's probability:**

```
S_now = p · S_yes + (1 − p) · S_no
J     = S_no − S_yes          (event gap, $/share; sign gives direction)
```

`p` is the YES probability (Polymarket, confirmed by Kalshi). `S_yes` and `S_no` are where the stock
would trade if the event resolved each way. Consequences everyone builds on:

1. **The impact model outputs J, not "move on YES".** The move still at risk depends on p:
   on YES the stock moves −(1−p)·J, on NO it moves +p·J.
   ABNB example: S = $128.40, J = $4.11 (3.2%), p = 0.23 → −$3.17 (−2.5%) left on YES, +$0.95 on NO.
2. **Exposure is defined against probability.** For N shares, `dV/dp = −N·J`
   (ABNB: −$49 per 1¢ of p). Remaining event downside = `N·(1−p)·J` (ABNB: $3,798).
3. **The initial hedge h₀ is sized from the remaining exposure** at a target coverage chosen by
   the hedge config. Exact sizing rules are owned by the engine team and are deliberately left
   to a later spec revision. This spec only fixes their inputs: p₀, J, N, S, lots and costs.
4. **The parity gap is the trading signal.** The stock-implied probability is
   `p_implied = (S_no − S) / J`. When `p_implied` and the market's p disagree beyond noise, the stock
   has not caught up and the engine acts. When they agree, it holds and saves fees.
5. **Stock short vs. YES contract:** shorting h shares hedges h/N of the event but also h/N of all
   non-event risk. Buying about N·J dollars of YES is the pure event hedge, but it pays only at resolution.
   That trade-off is why the Hedge step offers several hedge types.

## 4. Architecture

Two planes. The **hot path is C++20 only**; Python never sits between a tick and an order.

```
 HOT PATH — engine/ (C++20, one process)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ feed threads (pinned)              strategy thread (pinned)              │
 │  Polymarket CLOB WS ─┐                                                   │
 │  Kalshi WS / REST ───┼─► SPSC lock-free rings ─► algo pipeline ─► paper gateway
 │  Equity WS / sim ────┘                              │                 │  │
 │                          telemetry ring ◄───────────┴── non-blocking ─┘  │
 │  replay scorer (worker pool, same pipeline code, offline)                │
 └──────────── ZeroMQ: control REP (tcp:5555) · telemetry PUB (tcp:5556) ───┘
                                   │
 CONTROL PLANE — api/ (Python 3.12, FastAPI)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ markets/   event search over Polymarket Gamma + Kalshi REST              │
 │ impact/    Claude → J per ticker + rationale (cached)                    │
 │ composer/  Claude proposes algo stacks from the catalog manifest          │
 │ hedges/    rank put spread / collar / dynamic short / buy YES            │
 │ portfolio/ seeded demo account: lots, cost basis, account type, tax rate │
 │ bridge/    score → start/stop/configure bridges; telemetry → UI at ~15 Hz │
 └───────────────────────────── REST + WebSocket ───────────────────────────┘
                                   │
 UI — web/ (Next.js App Router, TypeScript, Tailwind)
   Build (Event → Equity → Hedge) · Bridge (live) · Library · Portfolio
```

### 4.1 Language standard

**C++20** (GCC 12+ / Clang 15+), the standard most HFT production systems run. The engine
uses `std::variant`/`std::visit`, concepts, `std::span` and `std::from_chars`. Errors are values
(a small in-house `expected<T,E>`), with no exceptions on the hot path. Nothing in the design needs C++23/26.

### 4.2 Hot-path rules (engine/)

- One thread per feed, one strategy thread; each pinned to a core where the OS allows it.
- Feed → strategy handoff through single-producer/single-consumer lock-free ring buffers.
- JSON decoded with simdjson. No heap allocation and no virtual dispatch on the per-tick path;
  all state is preallocated when a bridge starts.
- Telemetry (algo states, fills, reasons, latency samples) goes onto its own ring and is sent
  by a separate publisher thread. A slow subscriber can drop telemetry; it can never stall a hedge.
- Latency = `t_decision − t_tick_received` (monotonic clock), recorded per algo into an
  HDR-style histogram. p50 / p99 are published once per second.
- Honest claim for the pitch: decision latency is microseconds. Network delay to the venues
  (≈20–150 ms) dominates and is outside our control; we add nothing on top of it.

### 4.3 Why not Python on the hot path

The GIL, asyncio scheduling and object allocation add milliseconds of jitter per tick. Python
owns everything that is allowed to be slow: LLM calls, ranking, portfolio state, UI fan-out.

## 5. Data sources

| Feed | Source | Mode | Notes |
|---|---|---|---|
| Event discovery | Polymarket Gamma API, Kalshi `trade-api/v2/markets` | REST, api/ | Public, no key |
| Prediction book | Polymarket CLOB market WebSocket | WS, engine/ | Public, no key |
| Prediction confirm | Kalshi WebSocket (API key) or REST poll at 1 Hz (no key) | engine/ | Cross-venue confirmation |
| Equity quotes | Finnhub WebSocket (free key) | WS, engine/ | Outside market hours → sim feed (§10) |
| Impact + composer | Anthropic API, `claude-sonnet-5-5` | api/ | Structured output, cached |

Secrets live in `.env` (never committed). `.env.example` lists `FINNHUB_API_KEY`,
`ANTHROPIC_API_KEY`, optional `KALSHI_API_KEY_ID` / `KALSHI_PRIVATE_KEY_PATH`.

## 6. Components

### 6.1 Impact model (api/impact)

Input: event (title, description, resolution date) + candidate tickers (user holdings first,
then model-suggested). Output per ticker, as a validated Pydantic schema:

```json
{ "ticker": "ABNB", "gap_pct": 3.2, "direction": "down_on_yes",
  "components": { "revenue_pct": -1.0, "brand_pct": -5.0 },
  "rationale": "CA ≈ 9% of nights; 18-month phase-in. Brand hit sized on NYC Local Law 18 comps.",
  "confidence": 0.6 }
```

`gap_pct` is |J| / S. The api turns it into J, S_yes and S_no using the live S and p (§3). The UI
shows both the priced-in part and the part still at risk. Results are cached to disk (JSON) per
(event, ticker), so a demo never waits on the LLM. Demo events are pre-warmed at startup.

### 6.2 Hedge ranking (api/hedges)

Four hedge types, ranked for the account (taxable vs. IRA, marginal rate, lots held):

| Type | Covers | Cost model | Tax note |
|---|---|---|---|
| Dynamic short (engine-driven) | Scales with Δp and parity gap | $0.0035/sh + borrow rate | Lot-aware, avoids wash sales |
| Put spread | Defined range | Option debit (BS-priced from IV) | Equity option |
| Collar | Floor/cap | ≈ zero cost | May pause holding period |
| Buy YES | Pays on resolution only | Contract price | Treatment unclear; not a price hedge |

Only **Dynamic short** runs live in the engine. The other three are priced and explained, then
executed as a single simulated order.

### 6.3 Algo library (engine/lib)

**Goal:** a ready catalog of 1,200+ C++20 HFT algos, generic enough to serve any event and any
equity, that the AI uses as building blocks for each bridge.

**Structure: families → presets → catalog.**

- **About 40 hand-written families**, each a small C++ struct satisfying a stage concept
  (`GateAlgo`, `SignalAlgo`, `SizingAlgo`, `BandAlgo`, `ExecAlgo`, `TaxAlgo`, `RiskAlgo`).
- **Presets:** each family exposes a parameter grid (e.g. SigmaGate k ∈ {1.5, 2, 2.5, 3} ×
  window ∈ {30s, 2m, 10m}). Each named, tested preset is one catalog entry. Target ≥ 1,200 entries
  (≈ 40 families × ≈ 30 presets).
- **Event- and ticker-agnostic:** every algo reads only a normalized `BridgeState`, with no knowledge
  of the specific event or stock:
  `p, Δp, σ_p, book_imbalance, p_kalshi, J, S, σ_S, p_implied, h, N, lots[], costs, t`.
  A new market or ticker needs no new code.

Starter family list (the engine team extends it to about 40):

| Stage | Families |
|---|---|
| Gate | SigmaGate, CrossVenueConfirm, VolumeGate, SpreadGate, StalenessGate, TimeToResolutionGate |
| Signal | ParityGap, BookImbalanceReader, MomentumP, MeanRevertP, DriftEstimator, VenueLeadLag |
| Sizing | DeltaBridge, ParityCoverage, ConvexCoverage, KellyCapped, VolScaledCoverage |
| Band | InventoryBand, AdaptiveBand, CostBreakevenBand |
| Execution | VolAdaptiveSlicer, TWAP, VWAPProxy, IcebergSlicer, FeeAwareRouter, UrgencyScaler |
| Tax | TaxLotOptimizer, WashSaleGuard, HoldingPeriodGuard |
| Risk | RiskLimits, NotionalRateLimit, DrawdownKill, BorrowCostGuard |

Each decision emits a **reason record** (gates passed, Δp and volume, confirming venue,
parity gap, slicer params, fee, lot choice). That record becomes the trade-log text in the UI.

**Runtime-composable, still zero overhead.** A stack has one slot per stage. Each slot is a
`std::variant` over that stage's families, so choosing any combination at runtime is just
filling slots with preset parameters. On each tick, `std::visit` compiles to a jump table:
no virtual calls, no heap, state preallocated at `start_bridge`.

**Catalog manifest.** `engine/tools/export_manifest` generates `catalog/manifest.json` from the
code: id, family, stage, params, regime tags (e.g. `thin_book`, `high_vol_equity`,
`near_resolution`) and measured µs per call. The manifest is generated, never hand-edited, so what
the AI sees is always what is compiled. The UI Library screen browses it.

### 6.4 AI composer + replay scorer: "AI proposes, replay picks"

```
event + equity + account + catalog manifest
      │
      ▼
api/composer: Claude proposes K = 5 candidate stacks (JSON, validated against manifest)
      │
      ▼
engine replay scorer: runs every candidate through the SAME pipeline code on
  recorded sessions + simulated PPP paths (worker pool, in parallel)
  score = hedge error vs. remaining exposure + fees + tax drag + turnover penalty; p99 latency reported
      │
      ▼
best stack → start_bridge → live engine        (UI shows all K with scores and the winner)
```

- Claude supplies judgment: which families fit a thin book, a near-resolution event or a
  volatile stock. The scorer supplies proof. The final pick is measured, not just the model's opinion.
- The scorer uses the live pipeline code, so a score measures exactly what will run.
- If Claude is unavailable, fall back to a default stack per hedge type.

## 7. Engine ↔ API contract (ZeroMQ, JSON v1)

Control, REQ/REP on `tcp://*:5555`:

```json
{"op":"score_stacks","request_id":"…","state":{"p0":0.23,"J":4.11,"S":128.40,"N":1200},
 "candidates":[{"stack":[{"slot":"gate","preset":"SigmaGate.k2.w2m"}, "…"]}],
 "data":{"recordings":["demo-abnb-01"],"sim_paths":200}}
{"op":"start_bridge","bridge_id":"abnb-ca-str","event":{"polymarket_token_id":"…","kalshi_ticker":"…"},
 "equity":{"symbol":"ABNB","shares":1200,"lots":[{"qty":1200,"cost":101.20,"acquired":"2023-04-11"}]},
 "ppp":{"p0":0.23,"J":4.11,"S_yes":125.24,"S_no":129.35},
 "hedge":{"type":"dynamic_short","target_coverage":0.5},
 "costs":{"per_share":0.0035,"borrow_bps_annual":30},
 "stack":[{"slot":"gate","preset":"SigmaGate.k2.w2m"},{"slot":"signal","preset":"ParityGap.z1_5"},"…"]}
{"op":"stop_bridge","bridge_id":"abnb-ca-str"}
{"op":"status"}
```

Telemetry, PUB on `tcp://*:5556`. The topic is the message type:

- `tick` — `{bridge_id, venue, price, volume, ts_ns}`
- `parity` — `{bridge_id, p_market, p_implied, gap, remaining_exposure}`
- `algo` — `{bridge_id, slot, preset, state: passed|fired|executing|blocked, latency_ns, detail}`
- `fill` — `{bridge_id, side, qty, price, preset, fee, lot, reason, ts_ns}`
- `position` — `{bridge_id, long, hedge_short, avg_short, coverage, pnl_today}`
- `latency` — `{bridge_id, p50_ns, p99_ns, samples}`
- `score` — `{request_id, candidate, hedge_error, cost, turnover, p99_ns, rank}`

The contract is frozen at v1 at kickoff. Any change goes through a PR that edits this section.

## 8. UI (web/)

Matches the reference mockups: light glass panels, periwinkle→peach gradients, faint grid.

- **Build**: three linked cards (Event · Equity · Hedge) plus a step panel.
  - Step 1: market search with category chips and "touches your X".
  - Step 2: ranked stocks, showing the priced-in and remaining moves (PPP) with rationale.
  - Step 3: ranked hedge cards with an "AI pick" badge, then the composer view: K candidate stacks, their replay scores, and the winner.
- **Bridge**: prediction card (price, sparkline, volume, confirming venue), engine node in the centre,
  equity card. Below those: parity gap readout; algo-stack pills with live state and latency;
  portfolio P&L and coverage; the "Trades & reasoning" log.
- **Library**: browse the generated manifest (families → presets), with measured µs and regime tags.
- **Portfolio**: holdings, active bridges, realised and unrealised P&L.

API: REST for Build/Library/Portfolio; one WebSocket `/ws/bridge/{id}` per live bridge, throttled to about 15 Hz.

## 9. Demo account (seeded)

Taxable account, 32% marginal rate. Holdings: ABNB 1,200 sh, MAR 300 sh, JPM, META, NVDA
(sizes in `api/portfolio/seed.json`). No auth; single demo user.

## 10. Failure handling and demo safety

- **Market closed / equity feed down** → the engine switches to a sim feed that follows PPP: S is driven
  by p plus geometric Brownian motion (GBM) noise, seeded from the last real quote. The UI shows a `SIMULATED` badge.
- **Venue WS drops** → reconnect with backoff. The bridge holds its hedge (no trading on stale data)
  and the UI shows the feed as stale.
- **Replay mode** → the engine records raw feed messages to `engine/recordings/*.jsonl`, and
  `--replay <file>` plays them back at real speed. We record good sessions before demo day; the
  scorer uses the same recordings.
- **LLM down** → serve cached impact results and the default stack. Never block the UI on Claude.
- **Engine not running** → api/ ships `fake_engine.py`, which replays a recording over the same
  ZeroMQ sockets, so web/ and api/ can be built without a compiled engine.

## 11. Testing

- engine:
  - GoogleTest unit tests per family.
  - A catalog test that instantiates every preset and checks its manifest entry.
  - A deterministic replay test: fixed input → fixed fills.
  - A latency micro-benchmark gate in CI.
- api: pytest covering ranking, the impact schema, PPP math (the ABNB numbers in §3 are a test fixture),
  composer output validated against the manifest, and a contract round-trip against `fake_engine.py`.
- web: typecheck plus lint in CI; a manual demo walkthrough checklist.
- CI (GitHub Actions): build the engine, run all tests and lint web on every PR to `main`.

## 12. Repo and team workflow

```
polybridge/
  web/        Next.js app
  api/        FastAPI control plane (+ fake_engine.py)
  engine/     C++20 engine (CMake, FetchContent: simdjson, IXWebSocket, cppzmq, GoogleTest)
    lib/        algo families (one header per family)
    catalog/    presets + generated manifest.json
    tools/      export_manifest, replay scorer CLI
  docs/       specs, system-map.html, demo script
  docker-compose.yml  Makefile  .env.example  .github/workflows/ci.yml
```

- `main` is protected. Work on `feat/<area>-<thing>` branches and merge via PR.
- Ownership by folder (CODEOWNERS once owners are named): web · api · engine.
- `make dev` runs the engine and api in Docker, plus `pnpm dev` for web.

## 13. Out of scope (this revision)

Exact hedge-sizing rules (next revision, §3.3), real broker execution, user accounts/auth,
real tax filing logic, options execution in the engine, mobile apps.
