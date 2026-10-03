# PolyBridge Demo Implementation Plan (plan #3, lane P, Tier 1 + Tier 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A demo that works for any event and any stock. A judge types a prediction-market question, a ticker, or an 8-K filing type; PolyBridge shows what the market prices, which stocks it hits, whether the price is wrong (hedge / opportunity / no edge, with evidence), and a ranked, fee-aware hedge that the C++ engine runs only after the user approves it.

**Architecture:** The FastAPI backend grows six routers (verdicts, markets, equities, mapping, hedges, bridges) on top of the existing approval gate. The backend reads research outputs as files and imports `polybridge_research` read-only helpers; it never writes to `research/`. `hedgecore` gains a fee-breakeven gate. The Next.js app gets three screens (Build, Bridge, Portfolio) in the mockup style. Live data comes from Polymarket, Kalshi and Massive with caches and a recorded replay fallback.

**Tech Stack:** FastAPI + pydantic v2, httpx (async, with `MockTransport` in tests), `anthropic` Python SDK (`claude-opus-5-5`, structured output via `messages.parse`), Server-Sent Events, C++20 `hedgecore` + pybind11, Next.js 16 + TypeScript + Tailwind.

**Spec:** `docs/superpowers/specs/2026-10-02-polybridge-design.md` (v3, §3 backend/engine/web), `docs/contracts.md`, the mockups in the original brief (Build steps 1–3, Bridge screen). Research results: `research/results/in_sample/`.

**Branch:** `p/demo`, created from `r/research-pipeline` (PR #2) so the verdict files exist; rebase onto `main` after PR #2 merges.

## Global Constraints

- Lane P only: change `backend/`, `engine/`, `web/`, `docs/demo.md`, plus `research/results/atlas/` and its export script for Task 1. Never edit any other file under `research/`, never touch the OOS window, never change pre-registered values.
- Exploratory or product-only outputs are labelled as such in the API and UI: atlas badges show "exploratory", AI mappings show "AI estimate". Confirmatory verdicts for H1/H2 are shown exactly as in `research/results/in_sample/*_verdict.txt` (currently NULL / NULL).
- `hedgecore` executes only hedges from an approved proposal; one bridge per approval (idempotent by proposal id); every order passes the fee-breakeven gate; invalid input never becomes an order.
- Keys only from `.env` (`MASSIVE_API_KEY`, optional `ANTHROPIC_API_KEY`, later `WEBULL_*`); never logged, never sent to the browser.
- Every live call has a timeout, a cache, and a fallback (cached result, curated map, or recorded replay). The demo must run with Wi-Fi off from the replay.
- AI mapping uses `claude-opus-5-5` via `client.messages.parse(..., output_format=PydanticModel)`; a refusal or any API error falls back to the curated map (no crash, no empty screen).
- Backend tests pass with plain `uv sync` (no hedgecore); bridge tests that need hedgecore run under `--group engine` and in the CI engine job.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **Polymarket/Kalshi down or slow during the pitch:** search returns cached results with a `stale: true` flag; the Bridge falls back to replay. Pinned in Tasks 3 and 9.
- **A ticker with no options or no 8-Ks:** the equity card shows "no listed options" / "no recent filings", never a 500. Pinned in Task 4.
- **No ANTHROPIC_API_KEY, or a refusal:** mapping returns the curated entries labelled "curated", or an empty list with a message. Pinned in Task 5.
- **Two clicks on "Start bridge" or two browser tabs:** exactly one engine per approved proposal. Pinned in Task 8.
- **Fees larger than the hedge benefit:** the engine holds with reason `below_fees`. Pinned in Task 7.

---

### Task 1: Exploratory atlas over all filing types (verdict badges)

**Files:** Create `research/export_atlas.py`, `research/results/atlas/atlas.csv`, `research/results/atlas/README.md`; append one row to `research/results/RUN_LOG.md`; logs under `research/results/logs/`.

**Interfaces:** Produces `research/results/atlas/atlas.csv` with columns `tag, n_events, strategy, horizon, difference, ci_lo, ci_hi, p_value, q_value, exploratory` (from `atlas.run_atlas`), in-sample window only (2024-01-01 → 2025-12-31), baseline spec, `max_events_per_tag=15`, shared 300-day placebo over `TOP_100` at the baseline bucket (seed 11), exactly as the notebook's atlas cell.

- [ ] **Step 1:** Write `research/export_atlas.py` that reproduces the notebook atlas cell (taxonomy via `client.get_all("/stocks/taxonomies/vX/disclosures", {"limit": 1000})`, placebo, `run_atlas`, `count_variants(cfg, n_tags=len(tags))`) and writes the CSV plus `variants.txt`. Never references `cfg.oos_*`.
- [ ] **Step 2:** Run it in the background with logging, same pattern as the in-sample runs (`results/logs/<ts>-atlas.log` + `.meta`: start, end, duration, commit, requests, exit).
- [ ] **Step 3:** `research/results/atlas/README.md`: "EXPLORATORY — HYPOTHESIS.md §5. Not confirmatory, not a headline. N tags × 5 strategies × 3 headline horizons; total variants = …; BH q-values across all rows."
- [ ] **Step 4:** Add the run to `RUN_LOG.md`; commit `Exploratory atlas over all 8-K filing types (in-sample, labelled exploratory)`.

### Task 2: Verdicts API

**Files:** Create `backend/app/verdicts.py`, `backend/tests/test_verdicts.py`, `backend/tests/fixtures/results/` (small fixture CSVs); modify `backend/app/main.py`, `backend/app/routes.py` (include router).

**Interfaces:**
- `load_verdicts(results_dir: Path) -> VerdictBook` reading `in_sample/{hedge,opportunity}_verdict.txt`, `*_pass_check.csv`, and `atlas/atlas.csv` if present.
- `VerdictBook.for_tag(tag) -> TagVerdict{tag, family: "hedge"|"opportunity"|None, kind: "confirmatory"|"exploratory"|"none", label: "hedge"|"opportunity"|"no_edge", evidence: {strategy, horizon, difference, ci_lo, ci_hi, q_value?}, note}`.
- Rule: tags in H1/H2 use the confirmatory family verdict (`passed` → family label, else `no_edge`). Other tags use the atlas: `hedge` if protective_put has `q_value < 0.10` and `difference > 0` at ≥ 2 headline horizons; `opportunity` likewise for cash_secured_put; else `no_edge`; always `kind="exploratory"`. Missing atlas → `kind="none"`, `label="no_edge"`, note "not tested".
- HTTP: `GET /verdicts` → list of `TagVerdict`; `GET /verdicts/{tag}` → one (404 for unknown tag). `RESULTS_DIR` defaults to `../research/results`, overridable by env var for tests.

- [ ] Steps: failing tests with fixtures (H1 tag → confirmatory no_edge; exploratory hedge-leaning tag; missing atlas; unknown tag 404) → implement → tests pass → commit.

### Task 3: Live market search (Polymarket + Kalshi)

**Files:** Create `backend/app/markets.py`, `backend/app/cache.py`, `backend/tests/test_markets.py`.

**Interfaces:**
- `cache.TTLCache(ttl_s)` with `get_or_set(key, coro_fn)`; on fetch error returns the last value with `stale=True`, or raises if none.
- Polymarket: search `GET https://gamma-api.polymarket.com/public-search?q=<q>&limit_per_type=10` → events[].markets[]; price `GET https://clob.polymarket.com/midpoint?token_id=<yes token>`; history `GET https://clob.polymarket.com/prices-history?market=<token>&interval=1d&fidelity=60`. `outcomePrices` and `clobTokenIds` arrive as JSON strings: parse with `json.loads`.
- Kalshi: `GET https://api.elections.kalshi.com/trade-api/v2/events?status=open&limit=100&with_nested_markets=true&category=<Economics|Politics|Companies|Financials>`; keyword filter on title; price from `last_price_dollars` (fallback mid of `yes_bid_dollars`/`yes_ask_dollars`).
- `Market{source, id, question, yes_price, volume_24h, end_date, url, token_id?}`.
- HTTP: `GET /markets/search?q=` → `{markets: [Market], stale: bool}` (both sources merged, sorted by volume); `GET /markets/{source}/{id}/history` → `[{t, p}]`.

- [ ] Steps: tests with `httpx.MockTransport` (parses string-encoded arrays; Kalshi filter; one source failing still returns the other; total failure returns stale cache) → implement with 5 s timeouts → commit.

### Task 4: Any-stock lookup (filings, live implied move, related markets)

**Files:** Create `backend/app/equities.py`, `backend/tests/test_equities.py`.

**Interfaces:**
- `GET /equities/{ticker}` → `{ticker, implied_move: {value, expiry, spot, as_of} | null, filings: [{date, tags, verdict: TagVerdict}], markets: [Market], notes: [str]}`.
- Implied move: `polybridge_research.pricing.fetch_chain` + `locate_spot` + `pick_expiry(90,180,120)` + ATM pair marks from `option_bars` on the last completed session; `implied = (C_K + P_K) / spot`. Uses `MassiveClient(load_api_key())` with cache dir `backend/.massive_cache`.
- Filings: last 180 days of 8-K disclosures for that ticker (`/stocks/filings/8-K/vX/disclosures?ticker=<t>&filing_date.gte=...`), grouped by filing, each tag mapped through Task 2's `VerdictBook`.
- Markets: Task 3 search with the company name (from a small `TOP_100` name map in `backend/app/data/names.json`) and the ticker.
- No chain → `implied_move: null`, note "no listed options"; no filings → `filings: []`, note "no 8-K filings in the last 180 days".

- [ ] Steps: tests with the research `FakeClient`/`FakeMarket` (importable from `research/tests/fakes.py` via sys.path in a conftest) and Task 3 mocks → implement → commit.

### Task 5: AI event → stock mapping (Tier 2)

**Files:** Create `backend/app/mapping.py`, `backend/app/data/curated_map.json` (about 30 popular questions → tickers), `backend/tests/test_mapping.py`; add `anthropic` to backend dependencies.

**Interfaces:**
- `POST /map {question: str}` → `{source: "ai"|"curated"|"none", items: [{ticker, direction: "down_on_yes"|"up_on_yes", impact_pct: float, rationale: str}], note}`.
- Pydantic models `ImpactItem`, `MarketMap(items: list[ImpactItem])`. Call:
  ```python
  response = client.messages.parse(
      model="claude-opus-5-5",
      max_tokens=16000,
      output_config={"effort": "low"},
      system=SYSTEM_PROMPT,
      messages=[{"role": "user", "content": question}],
      output_format=MarketMap,
  )
  if response.stop_reason == "refusal":  # check before reading parsed_output
      return curated_or_none(question)
  ```
  The system prompt restricts tickers to US-listed equities, asks for at most 5 items, `impact_pct` as the full move between YES and NO resolution (J), and a one-sentence rationale; it states the output is an estimate shown to a user.
- Only when `ANTHROPIC_API_KEY` (or another SDK credential) is configured; otherwise, and on refusal, `anthropic.APIError`, timeout, or empty result → curated fuzzy match (token overlap ≥ 0.5) → else `source: "none"`.
- Results cached per normalized question for 1 hour.

- [ ] Steps: tests with a fake client object exposing `messages.parse` (success; refusal → curated; APIError → curated; no key → curated; unmatched → none) → implement → commit.

### Task 6: Hedge menu priced from today's chain

**Files:** Create `backend/app/hedges.py`, `backend/tests/test_hedges.py`.

**Interfaces:**
- `GET /hedges/{ticker}?shares=<n>&label=<hedge|opportunity|no_edge>` → `{ticker, spot, expiry, options: [{strategy, legs, premium_per_share, premium_total, max_loss, breakeven, fees, half_spread_cost, covers, rank, why}]}` for the five strategies at 3-6m expiry and 5% OTM (ATM for the long call), using `polybridge_research.strategies` leg naming and today's marks; fees = `0.0035 × shares` per leg + half-spread from `costs.half_spread` (same-session quote) when available.
- Ranking: label `hedge` → protective_put, collar first; `opportunity` → cash_secured_put, covered_call first; `no_edge` → all shown with "no edge found for this event; hedge only if you want insurance" and the cheapest protection first.

- [ ] Steps: tests with `FakeMarket` (prices, ranking per label, missing quotes → spread null) → implement → commit.

### Task 7: Fee-breakeven gate in hedgecore

**Files:** Modify `engine/hedgecore/include/hedgecore/types.hpp`, `engine.hpp`, `src/engine.cpp`, `src/bindings.cpp`, `tests/test_engine.cpp`, `tests/test_bindings.py`, `docs/contracts.md`.

**Interfaces:**
- `HedgeSpec` gains `gap_per_share` (J, $/share, ≥ 0), `fee_per_share` (default 0.0035), `half_spread` ($/share, default 0.0), `min_benefit_ratio` (default 1.0); all validated in `spec_ok`.
- New `Reason::BelowFees` (`"below_fees"`). After the band check: `cost = |qty| × (fee_per_share + half_spread)`; `benefit = |qty| × gap_per_share × |p − p_at_last_order|` (for the first order, `p_at_last_order = 0`); hold with `BelowFees` when `benefit < cost × min_benefit_ratio`. Track `p_at_last_order_` updated only when an Order is emitted.
- Binding exposes the new fields and reason.

- [ ] Steps: GoogleTests (fee gate blocks a small move; allows a large move; first order sized normally when benefit is enough; invalid new fields → Invalid) + binding test → implement → `make test-engine` and binding tests pass → commit.

### Task 8: Bridge loop with SSE

**Files:** Create `backend/app/bridges.py`, `backend/app/ticks.py`, `backend/tests/test_bridges.py`; modify `backend/app/store.py` (record `bridge_started_at`).

**Interfaces:**
- `POST /bridges {proposal_id, source: "live"|"replay", market: {source, id, token_id?}, gap_per_share}` → 201 `{bridge_id}`; 404 unknown proposal; 409 not approved; 409 already started (idempotent: same proposal id returns the existing bridge with 200 if `source` matches).
- Only `family == "hedge"` proposals start hedgecore (contract §Approval to execution); `opportunity` proposals return 409 with "executed as a single simulated options order" and are shown by the UI as such.
- `ticks.LiveSource(token_id, interval_s=1.0)` polls the Polymarket midpoint; `ticks.ReplaySource(path, speed=1.0)` reads JSONL `{ts_ns, p}`.
- The loop builds `hedgecore.HedgeSpec` from the proposal (`shares_held`, `target_coverage`) plus `gap_per_share`, feeds each tick, applies simulated fills immediately (`on_fill(order_qty)`), and publishes events.
- `GET /bridges/{id}/stream` (SSE, `text/event-stream`): events `tick {ts_ns, p}`, `decision {action, reason, order_qty, target_hedge, current_hedge, latency_ns}`, `position {hedge, coverage}`; heartbeat every 15 s. `GET /bridges/{id}` → summary (counts by reason, p50/p99 latency).

- [ ] Steps: tests with `ReplaySource` on a 20-tick fixture (skipped without hedgecore via `pytest.importorskip("hedgecore")`), idempotency and 409s without hedgecore → implement → CI engine job also runs `uv run pytest tests/test_bridges.py` under `--group engine` → commit.

### Task 9: Recorded session for Wi-Fi-free demos

**Files:** Create `backend/scripts/record_ticks.py`, `backend/replays/README.md`, `backend/replays/<slug>.jsonl` (one recording, ≤ 1 MB).

- [ ] Steps: script polls one Polymarket market's midpoint every second for N minutes, writes `{ts_ns, p}` JSONL; record 20 minutes of the featured market; README names the market, time, and how to replay; commit.

### Task 10: Build screen (search → verdict → map → hedge → approve)

**Files:** Create `web/src/app/build/page.tsx`, `web/src/components/` (SearchBox, MarketCard, VerdictCard, MappingList, HedgeMenu, StepCards); extend `web/src/lib/api.ts` with typed calls for Tasks 2–6; `web/src/app/page.tsx` links to Build / Bridge / Portfolio.

**Behavior:** Mockup style (light glass panels, periwinkle→peach, three linked step cards). One search box accepts a question, a ticker, or a filing type. Results: markets (yes price, volume, source chips), equity card (implied move, recent filings with verdict badges), AI/curated mapping list. Choosing a stock opens the verdict card (confirmatory or exploratory badge, evidence numbers, "no edge, try another" when so) and the hedge menu; "Propose" calls `POST /proposals`, "Approve" calls approve, then "Start bridge" navigates to `/bridge/<id>`. Every live panel shows a loading state, a stale badge, and a clear error message.

- [ ] Steps: implement components + page; `pnpm lint && pnpm build` pass; manual walkthrough against the running backend recorded in the report; commit.

### Task 11: Bridge screen (live engine)

**Files:** Create `web/src/app/bridge/[id]/page.tsx`, components (PriceCard with sparkline, EngineNode, EquityCard, StagePills, PositionPanel, TradeLog).

**Behavior:** Subscribes to `GET /bridges/{id}/stream` via `EventSource`; shows the market price and sparkline, the engine node with p50/p99 latency, stage pills lighting up per decision reason (stale, below_sigma, inside_band, below_fees, rebalance, risk_capped), the position and coverage bar, and a trade log with the reason for every order or hold. A "Replay" badge shows when the source is the recording. Reconnects on drop.

- [ ] Steps: implement; lint/build pass; manual run on the replay source; commit.

### Task 12: Portfolio exposure map

**Files:** Create `backend/app/portfolio.py` (seeded `backend/app/data/portfolio.json`: ABNB 1,200, MAR 300, JPM, META, NVDA, …), `GET /portfolio`; `web/src/app/portfolio/page.tsx`.

**Behavior:** For each holding: open markets touching it (Task 3), recent filings with verdict badges (Task 4), remaining event exposure when a mapping exists (`N × J × (1 − p)`), and hedge status (proposed / approved / bridging). Clicking a holding opens Build prefilled.

- [ ] Steps: backend test for exposure math and empty cases → implement → page → commit.

### Task 13: Demo script and end-to-end check

**Files:** Create `docs/demo.md`, `backend/tests/test_e2e.py`.

- [ ] Steps: `docs/demo.md` is the 90-second click path (search a live question → map → pick stock → verdict → hedge → approve → bridge on live, fallback to replay) plus the 8-K path (a litigation filing → confirmatory "no edge" with evidence). `test_e2e.py` drives classify → propose → approve → bridge (replay) → stream N events with TestClient (skips without hedgecore). Commit; push `p/demo`; open PR #3.
