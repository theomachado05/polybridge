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
