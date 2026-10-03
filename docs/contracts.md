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
| POST | `/proposals` | filing path `{"ticker", "tags", "shares_held" > 0, "target_coverage" ∈ [0,1] = 0.5}` **or** market-event path `{"ticker", "market": {"source", "id", "token_id"?}, "direction": "down_on_yes"\|"up_on_yes", "shares_held", "target_coverage"}` (no tags); either path may add `"algo"` (below) | 201 `Proposal` | 422 no family, both/neither basis, missing direction, bad algo, bad body |
| GET | `/proposals` | none | `[Proposal]` | none |
| POST | `/proposals/{id}/approve` | none | `Proposal` status `approved` | 404 unknown, 409 already decided |
| POST | `/proposals/{id}/reject` | none | `Proposal` status `rejected` | 404, 409 |

`Proposal = {id, ticker, family, strategy, shares_held, target_coverage, status, basis, label, market, direction, algo, created_at, decided_at, bridge_started_at}`

- `basis = "filing_tags"` (family from the pre-registered tag map; `label`, `market`, `direction` null) or `"market_event"` (always `family="hedge"`, `strategy="protective_put"`, `label="Product hedge — no confirmatory claim"`; no filing tags are invented and no research claim is made).
- `algo` (optional on `POST /proposals`, hedge proposals only): `{"family", "preset_index"? | "params"?, "source": "ai_fit"|"user"}`, the hedgecore algo the bridge will run once approved. Validated against the library (compiled catalog, else `engine/hedgecore/manifest.json`): unknown family, a family outside the hedge division (`poly_kalshi_spread`, `no_bid_seller`, option families), `preset_index` ≥ `preset_count`, unknown or out-of-bounds `params`, or both `preset_index` and `params` → 422; an `algo` on an opportunity (filing) proposal → 422. Stored pinned: a preset keeps its index; explicit params are completed with the catalog defaults. The server adds `resolved_params` (the exact params that will run), `coverage_cap` (= the proposal's `target_coverage`) and `capped` (`{param: original}` for each hedge-size param the cap lowered, else null), so the record that gets approved shows the coverage that will run; these three are ignored in requests. `null` = no fit (the legacy Engine runs).
- **The approved `target_coverage` is a hard cap on the algo path.** Every hedge-size param (`coverage`, `max_cov`) above it is lowered to it, at proposal time and again when the bridge resolves the algo (a coverage-1.0 preset on a 0.5 proposal runs with coverage 0.5). The bridge also clips every sell intent so the broker-filled short never exceeds `floor(target_coverage × shares_held)`; this holds families with no such param (`election_hedge`). A sell clipped to 0 is a `fill` with `status: "held"` and an `Algo.on_reject`; a partly clipped one carries `capped_from`.
- `POST /bridges {"proposal_id", "source": "live"|"replay", "market"?, "gap_per_share", "direction"?, "family"?, "preset_index"? | "params"?, "twin"?: {"source", "id", "token_id"?}, "replay_to_account"?}`: 404 unknown proposal, 409 not approved, 409 opportunity family; same proposal + same source is idempotent (200), a different source is 409 (one bridge per proposal). On that idempotent re-POST, a body `family`/`preset_index`/`params` that is not the algo the existing bridge runs (including any algo when it runs the legacy Engine) is 409: the caller is never told it succeeded with an algo that is not running. A market-event proposal always uses its own `market` and `direction` (the body's are ignored; `market` may be omitted); a filing proposal needs `market` in the body.
  - **Which engine.** The proposal's approved `algo` runs; a body `family`/`preset_index`/`params` that differs from it is 409 (the approval covers what runs). With no proposal algo, the body's choice runs (same validation, 422). With neither, the legacy `Engine` default spec runs (`gap_per_share` applies only to it). The algo is `hedgecore.Algo(family, params, {"shares_held"})`, always with the engine's default direction.
  - **MarketTick per tick** (NaN = not available, never invented; `eightk_score` 0 = none). Live: the primary venue's book, top 5 per side (Polymarket CLOB `/book` for the YES token, or the Kalshi `/markets/{ticker}/orderbook`, whose NO bids are YES asks at 1 − px); `no_bid = 1 − yes_ask`, `no_ask = 1 − yes_bid`; `p_other_venue` = the `twin`'s YES mid on the other venue (422 if `twin` is on the same venue; a Polymarket twin needs `token_id`), else NaN; `under_px` from the broker's quote source (Massive), `under_bid`/`under_ask` only when that quote has a spread; option fields NaN. Only algo bridges poll the equity quote (the legacy Engine never reads it); one quote per ticker per 15 s is shared by all bridges. A previous-close fallback (`massive_prev_close`) is not a current price: `under_px` stays NaN and the tick's `under_source` says `"massive_prev_close (stale: not used)"`. Replay: the recorded mid (`yes_bid = yes_ask = p`), any other MarketTick field the JSONL row carries, and `under_px` from `app/data/equity_bars/<TICKER>.json` as of the row's original time; else NaN. Bars are recorded for the demo replay's tickers (SPY, IWM, XHB, TLT). The summary's `equity_price` says what the algo can see: `"live_quote"`, `"recorded"`, or `"none"` (a replay with no equity price: the hedge families hold with `fee_unknown` on every tick).
  - **Execution.** Each Order intent (equity only for hedge families) cancels the bridge's resting order first (cancel/replace; if it filled meanwhile, that fill is applied), then goes to the active broker as a market order (limit when the intent has `limit_px`; live orders carry the tick's `under_px` as the reference price, replay orders are priced at today's market and labelled). Filled → `Algo.on_fill("equity", signed qty, fill_px)`; rejected, cancelled/expired, or a broker error/timeout → `Algo.on_reject("equity")`; open → kept as the resting order. `filled_qty` is cumulative per order: a partial fill on an open order is applied once (the resting order remembers `applied`), and a later lookup or cancel applies only the difference. If the broker cannot be read, or a cancel does not take, the resting order is kept (it may still be working), the new intent is held (`status: "held"`, `Algo.on_reject`) and the cancel is retried before the next order and at bridge end; an order the broker no longer lists is treated as expired. A bridge that ends cancels its resting order. The algo bridge's `hedge` is what the broker filled (`hedge_basis = "broker_fill"`); the legacy bridge keeps `"engine_intent"`.
  - **SSE** (`GET /bridges/{id}/stream`): `tick {ts_ns, p, venue, yes_bid, yes_ask, p_other_venue, under_px, depth, under_source?}` (raw YES orientation; `under_source` on algo bridges); `decision {engine: "algo"|"legacy", family, preset, action, reason (string), reason_code, reason_block, signal, instrument, side, qty, limit_px, order_qty (> 0 adds to the short hedge), target_hedge, current_hedge, latency_ns}` (legacy: `family`/`preset`/`signal` null); `fill {status, side, qty, family, preset, reason, broker, order_id, fill_px, fee, filled_qty, ...}`; `cancel {order_id, reason: "replace"|"bridge_end", status, kept_resting?}`; `position {hedge, coverage, hedge_basis, broker_hedge, broker_coverage, resting_order?, broker}`; `error`; `status`.
- `GET /bridges/{id}` summary includes `shares_held`, `target_coverage`, `coverage` (= hedge / shares_held), `basis`, `label`, `market`, `engine`, `algo` (`{family, preset_index, params (as run, after the cap), source, coverage_cap, capped}` or null), `resting_order`, `cancels`, `hedge_basis`, and on algo bridges `coverage_cap`, `cap_holds`, `equity_price`, `equity_source`.

### Direction: one orientation, in one place

- `direction` says which outcome hurts a long holder. `app.pipeline.ticks.orient_to_adverse(ticks, direction)` is the **only** place it is applied: afterwards YES means the adverse outcome (for `up_on_yes`: YES ↔ NO quotes, the YES book mirrored as the NO book, `p_other_venue` and `opt_implied_prob` → 1 − p; NaN stays NaN). It takes a dict of arrays (fit replays) or of floats (one live tick).
- The fit pipeline orients hedge-division ticks before `replay_grid`; bridges orient every tick before `Algo.on_tick` and before the legacy `Engine` (which then sees the adverse mid: `p` for `down_on_yes`, `1 − p` for `up_on_yes` on mid-only ticks, as before). SSE `tick` events keep the raw market.
- The backend never passes `direction` to hedgecore (`Algo`, `replay`, `replay_grid` keep their default `"down_on_yes"`). hedgecore's own flip refuses non-hedge families because their intents name the real YES/NO contract; those families are never oriented by the backend and never run on a bridge. For hedge families the engine flip and `orient_to_adverse` give identical intents (tested with the compiled engine).

## hedgecore (`engine/hedgecore`, C++20 + Python module `hedgecore`)

- `HedgeSpec{ticker, shares_held, target_coverage=0.5, band_shares=10, max_hedge_shares=0 (= shares_held), max_staleness_ns=2_000_000_000, sigma_k=2.0, sigma_alpha=0.05, gap_per_share=0 ($/share per unit of dp), fee_per_share=0.0035, half_spread=0.0, min_benefit_ratio=1.0}`
- `Engine(spec).on_tick(ts_ns, p, now_ns) -> Decision{action: hold|order, reason: invalid|stale|below_sigma|inside_band|rebalance|risk_capped|below_fees, order_qty, target_hedge, current_hedge, latency_ns}`
- An invalid `HedgeSpec` (non-finite fields, negative shares/band/cap/sigma_k/staleness/gap_per_share/fee_per_share/half_spread/min_benefit_ratio, `target_coverage` or `sigma_alpha` outside [0,1]) makes every `on_tick` return Hold with reason `invalid`.
- Fee gate (active when `gap_per_share > 0`; inactive at 0 so old callers are unchanged): after the band check, `cost = |qty|·(fee_per_share+half_spread)`, `benefit = |qty|·gap_per_share·|p − p_at_last_order|` (`p_at_last_order` is 0 until the first Order); holds with `below_fees` when `benefit < cost·min_benefit_ratio`.
- `on_fill(qty)` after the broker confirms. Default sizing: `target = round(c · N · p)`, capped.
- A `HedgeSpec` is built only from an **approved** `Proposal`.
- `on_fill` ignores a non-finite qty and latches the engine invalid (every later tick holds with reason `invalid`). A tick dated after `now_ns`, or older than `max_staleness_ns`, holds with reason `stale`.

### Approval to execution

- The bridge starts at most once per approved proposal id (idempotent, keyed by id): never a second `HedgeSpec` from one proposal.
- For now only `family == "hedge"` proposals reach hedgecore, which sizes a short stock hedge `c·N·p`. `opportunity` (cash-secured put) proposals are executed as a single simulated options order outside hedgecore until `HedgeSpec` gains `side`/`strategy`.
- The backend runs as a single uvicorn worker until the proposal store is persisted (approve-once is per process).
- The backend installs hedgecore only through the uv dependency group `engine` (`uv sync --group engine`); plain `uv sync` excludes it.
