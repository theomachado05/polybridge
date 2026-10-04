# PolyBridge design

PolyBridge hedges stock positions with live prediction-market prices (Polymarket and Kalshi). Its one rule is **evidence gating**: the app labels every signal either **validated** (its market passed a pre-registered out-of-sample test) or **unvalidated estimate**, and enforces the label. While the stock market is closed, staged equity orders (hedge B) are planned only on a validated market unless the holder sets an explicit, acknowledged override, and hedge A (the prediction-market leg) runs only on its own opt-in and is always labelled an estimate; in regular hours a hedge on an unvalidated market runs only after an explicit acknowledgement at approval; every decision, fill and staged order carries its label (section 6). Most markets fail that check, and the app says so.

The setting that makes this useful is simple: **stocks close, prediction markets don't.** Overnight, at weekends and on holidays a prediction market keeps trading while the stock cannot. PolyBridge watches that move, estimates the open gap where the evidence allows it, and stages an equity hedge for the first moment the stock can trade. Nothing trades without the holder's approval.

This page describes the system as it stands. Every research number is in `research/EVIDENCE.md`, which names its source file; if this page and a source file disagree, the source file wins.

Contents: 1 what it is and how it fits together, 2 closed-market mode, 3 the C++ library, 4 the AI fit, 5 accounts (simulator, Webull paper), 6 evidence gating, 7 front end and voice, 8 safety rules, 9 library groups in the UI, 10 liquidity and capacity, 11 capital controls, 12 options chain and hedge-instrument comparison.

## 1. What it is and how it fits together

### Thesis, and what the tests did to it

The starting thesis was that in stress a prediction-market price reprices before the stock, so it can be used to hedge early. The tests narrowed it:

- **During market hours there is no prediction-market lead.** Of 20 stress events where both series moved, the prediction market moved first in 9, the stock first in 9, together in 2 (sign test p = 1.000).
- **While the stock is closed, the picture is scoped.** On the US-recession market the expected-gap model held out of sample in time (sign right in 97 of 151 closures, 64.2%); it failed on the 10-market replication panel (50.2% of 878). Staging the equity hedge for 09:30 cut post-open variance (+11.42% [+5.10, +18.14] against no hedge), and that result is fragile.

So the product is built around closed hours and around a per-market evidence check, not around a general claim that prediction markets lead.

### Two divisions on one signal stack

The signal stack: prediction-market price, its change (delta), implied probability, bids and asks, the Polymarket and Kalshi order books, the cross-venue gap, and the 8-K signal.

| Division | What it does | Instruments | Main signal |
|---|---|---|---|
| **Hedge** | Hedges an equity position from the prediction market, including while equities are closed | equities and ETFs; prediction-market YES/NO legs | PM price and book, delta, Polymarket–Kalshi gap |
| **Opportunity** | Compares the PM probability with the options-implied probability of the same threshold; 8-K-driven option trades | options (Massive data), PM legs | PM vs option-implied probability, 8-K tags |

The Opportunity division shows the mechanism, not an edge: the options-versus-PM scan found 5 verified gaps and 0 executable, and options at the open has no evidence behind it (R3 NULL), so its simulated trade is staged only with an explicit acknowledgement (section 6).

### Architecture

| Part | Stack | Role |
|---|---|---|
| `engine/hedgecore` | C++20, header-only, pybind11 | The algo library: blocks composed into 17 families, 1,386 presets. Decides each tick; replays and grid-searches presets. |
| `backend/` | Python 3.12, FastAPI | Control plane: market search, AI mapping and fit, proposals and approval, bridges (server-sent events), closed-market mode, broker, portfolio. |
| `web/` | Next.js, TypeScript | The UI: Landing, Build chat, Connect, AI pipeline, Bridge live, Portfolio, Library, Profile. |
| `research/` | Python | Pre-registered studies and their results; the evidence the product gates on. |

A hedge goes through these steps:

1. **Pick.** The holder picks a prediction market and a held stock (Build chat). The stock mapping is an AI estimate and is labelled as one.
2. **Fit.** The AI fit classifies the market, shortlists families, replays real price history and picks a preset (section 4).
3. **Approve.** A proposal starts pending and arrives with its `evidence` status and a `capacity` block (the hedge against the liquidity caps, its estimated cost, and the capital budget; sections 10 and 11). It is pinned to the approved algorithm and capped at the approved coverage; starting a bridge is refused (409) until it is approved, and for any other algorithm. A proposal on an unvalidated market is approved only with `ack_unvalidated: true` (else 409 `EVIDENCE_UNVALIDATED`).
4. **Bridge.** The bridge feeds ticks (live book or a recorded replay) to the compiled algo, passes each order through the liquidity gate and the capital budget, sends it to the active broker and streams decisions, fills and reasons to the UI.
5. **Closed hours.** When the equity session closes, closed-market mode takes over (section 2).

## 2. Closed-market mode

While US equities are closed (after-hours, overnight, weekend, holiday, pre-market) and the prediction market trades, a bridge behaves as follows.

### Product behaviour

1. **Session clock.** Every moment is classified as regular, pre-market, after-hours, overnight, weekend or holiday on the NYSE calendar, including early closes (`backend/app/closed/session.py`, `GET /session`). A replay uses each tick's recorded time, so a replayed Saturday behaves like a Saturday.
2. **Closure tracker.** The bridge tracks the prediction-market move since the last regular close (`backend/app/closed/tracker.py`).
3. **Expected open gap.** Expected gap = rate × PM move (in points), shown with an 80% band and the number of closures behind the rate (`backend/app/closed/gap.py`, `GET /closed/expected-gap`). The rate is the market's own when it has enough past closures, otherwise the pooled rate with a wide band. The gap reads **validated** only under the evidence gate in section 6; everything else is an **unvalidated estimate**.
4. **Hedge A: hold the prediction-market contract (opt-in, an estimate).** Buy the adverse YES over the closure, sized by the C++ family `closed_session_hedge`, and unwind it at the open. Fills are simulated (there is no Polymarket trading account) and labelled so. Each PM order is capped at 50% of the tick's book depth within 2 cents of the mid (section 10). It is off unless the proposal opts in, and it is never called protection: R1 found no evidence that it reduces the open-gap loss, and on the replication panel it increased variance.
5. **Hedge B: staged session order (the default).** An equity hedge order is planned from the expected gap once the gap is at least 10 bp against the position, and queued for the first tradable moment (`backend/app/closed/staged.py`, `POST /staged/plan`, `POST /staged/{id}/approve`, `DELETE /staged/{id}`).
   - Timing: the next pre-market (04:00 ET) when the executing broker supports extended hours, otherwise the 09:30 ET open. **The Webull paper sandbox accepts orders only from 09:30 to 16:00 ET** (it answers HTTP 417 "Orders cannot be placed at this time" outside those hours), so extended hours are off for Webull unless `WEBULL_EXTENDED_HOURS=1`, and a staged order executes at the 09:30 open. R1's evidence is for the 09:30 version; its 08:00 ET variant was only partial.
   - Evidence gate: a plan is made only when the market's expected gap is validated. On an unvalidated market `plan_for` refuses with 409 `EVIDENCE_GATE` unless the override is set and confirmed: `act_on_unvalidated` on a proposal counts only when its approval carried `ack_unvalidated: true` (a proposal on a validated market approves without the acknowledgement, so its flag alone confirms nothing), and on a bridge it is accepted only for a proposal approved with the acknowledgement. Each plan stores `evidence_gate: validated | override` and an `EVIDENCE_*` decision; each broker order's note says `evidence: ...`; a bridge reports a refusal once per closure as an SSE `staged` event `{event: "refused"}`.
   - Approval: the holder approves the plan, naming the quantity seen. Nothing is sent before that. The plan passes the liquidity caps (section 10) when it is made and again when it executes, and the capital budget (section 11) at approval (409 `CAPITAL_BUDGET`) and at execution.
   - Revert and resize: if the PM move reverts the plan is cancelled; a smaller move resizes an unsent order down; an approved order is never resized up past what was approved.
   - A replay sends it only at a fresh recorded price, never at a stale Friday close.
   - It works by timing, not direction, and executes after the gap has formed, so it cannot recover the gap itself.
6. **Opportunity at the open (an unvalidated estimate).** At the close the option-implied probability of threshold markets is snapshotted; at the open it is compared with the PM probability (`backend/app/closed/opportunity.py`). R3 is NULL after option costs, so the comparison is shown as an estimate, not an edge. A simulated debit-spread trade for the open can be staged (`POST /closed/opportunity/trades`), but only with `ack_unvalidated: true` (else 409 `evidence_unvalidated`); it needs approval, executes only in the 30 minutes after the open, and before its combo is sent it passes the option participation caps (section 10) and the capital budget at the account its legs fill in (section 11). Fills are simulated (`SimBroker.place_combo`), also behind Webull paper.
7. **Safety is unchanged.** Nothing runs without approval. The equity algo holds while the session is closed (nothing is sent; the decision is reported as `session_closed`). One coverage cap covers the PM and equity legs together. Every decision carries a reason code. At the open the bridge hands off: the equity algo resumes and manages the position, staged fills included.

### What the holder sees

- **Bridge:** "Market closed · reopens Mon 09:30 ET / pre-market 04:00" and a session pill; a closed-market panel with the PM move since the close, the expected gap with its band, its validated or unvalidated-estimate badge, the staged orders with **Approve plan** and **Cancel**, the hand-off timeline, and the P&L since the close against no hedge.
- **Build:** a Weekend mode card while equities are closed, explaining hedge B (default) and hedge A (opt-in, estimate).
- **Portfolio:** weekend exposure per holding (expected gap × position), validated or estimate.

### The recorded weekend

`backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl` is one real weekend, picked by a fixed rule: the largest adverse weekend PM move on the one market whose expected gap is validated ("US recession in 2025?", hedging SPY). It is the April 2025 tariff weekend, Friday 15:30 ET to Monday 10:00 ET. On it, with 1,000 SPY shares and a 50% cap: P&L from the Friday close to Monday 10:00 is -$10,870 with no hedge and -$8,276 hedged, +$2,594 against no hedge; the staged order alone lost $1,607, because SPY rallied after the open (`backend/replays/README.md`). It shows the mechanism on one weekend; it is not evidence.

## 3. The C++ library (`engine/hedgecore`)

Blocks compose into named algo families; every family has a parameter grid; a preset is one grid point. The library counts its presets, measures each family's latency and exports a manifest. The AI only ever chooses from what is compiled. Today: **17 families, 1,386 presets, 37 blocks** (`engine/hedgecore/manifest.json`). A decision takes 27.1 to 34.6 ns per `on_tick` on a synthetic benchmark tape (`engine/hedgecore/BENCH.md`); that is the decision only, not end-to-end latency. More detail: `docs/library.md`.

### 3.1 Blocks (`include/hedgecore/blocks/*.hpp`)

Header-only, no heap allocation and no virtual calls on the hot path, `std::variant` dispatch.

| Kind | Blocks |
|---|---|
| signals | `PMid`, `ImpliedProb`, `BookImbalance`, `Microprice`, `CrossVenueGap`, `DeltaDp`, `EwmaVol`, `Momentum`, `MeanRevertZ`, `OptionImpliedProb`, `PMvsOptionGap`, `EightKScore` |
| gates | `Staleness`, `Sigma`, `Spread`, `Depth`, `Session`, `Cooldown`, `EventWindow` |
| sizers | `DeltaBridge` (h* = round(c·N·p_adverse)), `LinearExposure`, `ConvexExposure`, `KellyCapped`, `VolTarget` |
| execution | `NoTradeBand`, `FeeGate` (benefit vs fee + half-spread), `Slicer`, `PassiveAggressive`, `IcebergCap` |
| risk | `PositionCap`, `NotionalCap`, `DrawdownKill`, `GapFlipKill`, `DailyLossCap` |
| tax | `TaxLotSelector` (HIFO / long-term first), `WashSaleGuard` (blocks re-buys within 30 days of a loss sale) |
| routing | `VenueRouter` (PM leg to Polymarket or Kalshi by best price) |

### 3.2 Algo families (`include/hedgecore/algos/*.hpp`)

Each family is a fixed composition of blocks plus a grid of 2 to 5 parameters.

| Family | Division | Event classes | Instruments | Presets | Idea |
|---|---|---|---|---|---|
| `equity_delta_bridge` | hedge | all | equity | 108 | DeltaBridge on the adverse probability, fee-gated |
| `stress_lead_hedge` | hedge | macro_fed, geopolitics_energy, fig | equity, ETF | 81 | Hedge faster when the PM move is large against its volatility |
| `book_imbalance_hedge` | hedge | all | equity | 81 | Pre-hedge when the PM book imbalance leads the mid |
| `poly_kalshi_spread` | hedge / opportunity | all with both venues | PM legs | 81 | Trade the cross-venue gap net of fees |
| `no_bid_seller` | opportunity | all | PM NO leg | 81 | Sell into rich NO bids when the implied probability is overstated |
| `fig_stress` | hedge | fig, macro_fed | KRE, XLF, KBE | 81 | Bank-stress, Fed and regulation questions to bank ETFs |
| `housing_rates` | hedge | housing | ITB, XHB, VNQ | 81 | Mortgage-rate and home-price questions to rate-sensitive ETFs |
| `macro_fed_hedge` | hedge | macro_fed | SPY, IWM, TLT | 81 | Fed, CPI and recession odds to index hedges |
| `election_hedge` | hedge | elections | sector ETFs | 81 | Election odds to sector tilts |
| `tariff_trade_hedge` | hedge | tariffs_trade | importer / exporter ETFs | 81 | Tariff odds to trade-exposed equities |
| `energy_geo_hedge` | hedge | geopolitics_energy | XLE, USO | 81 | Conflict and OPEC odds to energy |
| `crypto_reg_hedge` | hedge | crypto | COIN, MSTR | 81 | Crypto regulation and ETF odds to crypto equities |
| `tech_reg_hedge` | hedge | tech_regulation, company_specific | mega-cap tech | 81 | Antitrust and AI-regulation odds to the names |
| `binary_vs_spread_arb` | opportunity | any with listed options | call / put spread | 36 | PM probability vs the option-implied probability of the same threshold |
| `vol_vs_pm_move` | opportunity | any with options | straddle / strangle | 81 | PM repricing without an implied-volatility move |
| `eightk_opportunity` | opportunity | corporate_8k, company_specific | cash-secured put, put spread | 81 | 8-K tag plus PM signal to an option trade |
| `closed_session_hedge` | hedge | all | PM YES leg, equity | 108 | Hedge A: size the PM leg over a closure, hand off to the equity at the open |

### 3.3 Hot-path types (`include/hedgecore/market.hpp`)

- `MarketTick`: timestamp, venue, YES/NO bid and ask, five book levels per side, the other venue's YES mid, the underlying's price, bid and ask, option mid, delta, implied volatility and implied probability, and the 8-K score. A missing field is NaN, never invented.
- `Intent`: hold or order, instrument, side, quantity, limit price (NaN = marketable), a block-level reason code, the triggering signal value and the decision latency.
- `Position` and `Params` (up to 8 values per preset).
- Each family is a class with an id, a parameter spec (names, ranges, grid), `on_tick(tick, now) -> Intent` and `on_fill(instrument, qty, px)`. `make_algo(id, params, position)` returns a `std::variant` of all families.
- `catalog()` lists families with division, event classes, instruments, blocks, parameters, grid and preset count.
- `replay(...)` returns order count, P&L, fees, drawdown, hedge variance reduction, turnover and latency percentiles. Fills are at the touch plus fees. An equity order with no live quote is refused outside the regular session and until the price has changed inside it, so a stale close is never booked as hedge P&L. `replay_grid(...)` runs every preset.
- The older `Engine` / `HedgeSpec` / `Tick` API stays and is covered by its tests.

### 3.4 Python binding (`hedgecore` module)

| Function | Returns |
|---|---|
| `hedgecore.catalog()` | the manifest as a dict |
| `hedgecore.Algo(family, params, position)` | `.on_tick(tick) -> dict`, `.on_fill(instrument, qty, px)` |
| `hedgecore.replay(family, params, position, ticks)` | stats dict; `ticks` is a dict of equal-length arrays named like the `MarketTick` fields |
| `hedgecore.replay_grid(family, position, ticks)` | list of stats dicts with `preset_index` and `params` |
| `hedgecore.Engine` | the older engine |

`engine/hedgecore/manifest.json` is generated from `catalog()` (`engine/hedgecore/scripts/gen_manifest.py`) and committed; the backend falls back to it when the module is not built.

## 4. The AI fit (`backend/app/pipeline/`)

`POST /pipeline/fit` takes a market (or a question), a ticker, a direction and the shares held, and runs five steps:

1. **Classify** the market into an event class (`macro_fed`, `elections`, `tariffs_trade`, `geopolitics_energy`, `housing`, `fig`, `tech_regulation`, `crypto`, `corporate_8k`, `company_specific` or `unsupported`). Gemini (`GEMINI_API_KEY`, default model `gemini-2.5-flash`) with the manifest's classes as the allowed set; keyword rules when there is no key or Gemini does not answer within 8 s.
2. **Shortlist** the families whose event classes include it, split by division.
3. **Build ticks** from the market's real price history (Polymarket `prices-history`, Kalshi history) aligned to Massive equity bars; a recorded replay file offline. Missing book depth stays empty.
4. **Tune:** `replay_grid` per shortlisted family. Hedge presets are ranked by the variance cut **beyond a static hedge of the same average size** (what the PM signal adds). Raw variance reduction is reported but never ranked, because any static short earns it.
5. **Explain:** Gemini writes a short rationale from the structured result only; a template without a key.

The response names the event class, division, family, preset, parameters, score, alternatives, rationale, the classifier used (`gemini` or `rules`) and the tick source. `scripts/precompute_fits.py` fits the market universe ahead of time into `app/data/fits.json`, so the demo is instant.

**What the score is.** An in-sample replay number, the best of many presets on the same history it was tuned on. Over 122 scored markets the median is 0.0053, and in the pre-registered walk-forward test the picked preset did not beat a static hedge out of sample (median -0.0040). The AI fit is configuration, not edge.

## 5. Accounts (`backend/app/broker/`)

- **One interface (`Broker`):** `account()`, `positions()`, `place_order(OrderRequest)`, `orders(status?)`, `cancel(id)`. Routes: `GET /account`, `GET /positions`, `GET /orders`, `POST /orders`, `DELETE /orders/{id}`. `POST /orders` is the manual route; it passes the same liquidity caps and capital budget as the bridges, but refuses (409 `LIQUIDITY_CAPPED` or `CAPITAL_BUDGET`) instead of cutting, because the caller named the size (sections 10 and 11).
- **`SimBroker`** (default): $1,000,000 starting cash, deterministic. Equity fills at the Massive quote (or the bridge's price) ± half-spread plus a per-share fee; options at the quote mid ± half-spread plus a per-contract fee; prediction legs at the PM book. State in `backend/.sim_account.json` (gitignored).
- **`WebullBroker`:** the same interface on the Webull OpenAPI paper-trading sandbox, on when `BROKER=webull` and the Webull keys are set (`WEBULL_APP_KEY` or its alias `WEBULL_API_KEY`, `WEBULL_APP_SECRET`, optional `WEBULL_ACCOUNT_ID`). It talks only to `api.sandbox.webull.com`; any other host is refused and the simulator is used. Full notes, with what was verified live and what was not: `backend/app/broker/WEBULL_NOTES.md`.
- **Regular hours only.** The Webull paper sandbox accepts orders only from 09:30 to 16:00 ET (tested 2026-10-03: a 1-share SPY limit order on a Saturday was refused with HTTP 417, nothing to cancel). Outside those hours the account still reads (balance, positions) and staged orders wait for the 09:30 open.
- **Margin account.** `WEBULL_ACCOUNT_ID` is the paper **Individual Margin** account (type `MARGIN`). Read live and read-only on 2026-10-03: cash $1,000,000, net liquidation $1,000,000, no `buying_power` key but `day_buying_power` $4,000,000 (4x), `overnight_buying_power` $2,000,000 (2x), `option_buying_power` $1,000,000, no positions, no open orders. The app's `buying_power` is Webull's explicit figure when present, else the **overnight** figure (a staged hedge is held through a closure, so the 4x intraday number would overstate deployable capital). Webull shorts only in margin accounts; SPY and AAPL list short margin 0.50 and maintenance 0.30.
- **Short-sale readiness.** `broker.can_short(symbol)` reads Webull's instrument profile (`shortable`, `easy_to_borrow`, `status`; cached 15 min). A short of a symbol Webull lists as not shortable or liquidate-only is refused before it is sent (`not_shortable: ...`); an unknown answer never blocks. Surfaced at `GET /broker/capabilities`, `GET /broker/shortable/{symbol}`, `GET /portfolio` and `make webull-check`. No borrow rate or locate size is exposed by Webull.
- **Reconciliation.** Webull fills asynchronously, so `backend/app/broker/reconcile.py` runs one pass every 15 s in the regular session: one read of open orders, then the final state (order detail) of each order this app placed that has left the open list, at most 4 detail reads per pass (Webull allows 2 per 2 s). One more pass runs right after the close for late fills, then it idles until the next open. Failures back off 15 / 30 / 60 / 120 s and never stop the loop. Webull statuses map to ours (`PARTIAL_FILLED` stays open with `filled_qty`; unknown words stay open, never booked as done; the raw word is kept). History reads use `x-version: v3`, 7-day windows, at most 5 pages. Controls: `GET /broker/reconcile`, `POST /broker/reconcile/start|stop|run`; `WEBULL_RECONCILE=0` turns auto-start off.
- **Options at Webull: the finding.** Webull's Trading API documents US option orders (single legs and strategies such as `VERTICAL`, `STRADDLE`, `IRON_CONDOR`), but nothing says the paper sandbox accepts them, the account's option level is not exposed, and with the market closed nothing could be tested. So option legs route to the simulator by default, labelled so, and the capital check prices them against that simulator account. Webull option placement exists behind `WEBULL_OPTIONS=1` (default off; a combo is one net limit at quoted mids plus half-spreads, never a market order), tested with mocked HTTP only; turn it on only after a manual single-leg test during market hours. **With `WEBULL_OPTIONS=1`** a bridge's option combo goes to the Webull paper account: its fill record says `routed: "Webull paper (WEBULL_OPTIONS=1 ...)"` and is not marked simulated, it is sent only in the regular session, and the capital check uses the Webull account; a leg combination Webull has no strategy for still fills in the simulator, with a note. Manual option orders (`POST /orders`) follow the same rule. The options-at-the-open trade always fills in the simulator.
- **Replays never touch the account.** A replay bridge trades in its own sandbox simulator unless started with `replay_to_account`. So on a closed day the demo fills in the simulator while the Connect screen shows the Webull paper account connected.
- The UI always names the account in use: "Simulated account" or "Webull paper".

## 6. Evidence gating

### The rule

A signal may act on a position only as far as a pre-registered out-of-sample test supports it, for that market. The app labels each number **validated** (it passed) or **unvalidated estimate** (it did not, or was never tested), and shows the band and the closure count either way. The gate lives in `backend/app/closed/evidence.py` and reads `backend/app/data/gap_evidence.json`, built from `research/results/gap_model/tests.json`. `GET /closed/evidence` returns it for a market.

### How the gate is enforced

`signal_status(market, ticker)` applies one rule everywhere: **validated** only when the market's own out-of-sample record passes R2, its own rate is the one in use, and that rate was estimated on this ticker. Anything else is unvalidated.

| Where | What happens on an unvalidated market |
|---|---|
| `POST /proposals` | The proposal stores `evidence` (status, reason, rate source, basis ticker) |
| `POST /proposals/{id}/approve` | 409 `EVIDENCE_UNVALIDATED` with the reason and how to proceed, unless the body says `{"ack_unvalidated": true}`. The status is re-checked at approval |
| `POST /bridges` | Checks again and refuses a proposal approved without the acknowledgement |
| `POST /closed/opportunity/trades` | R3 is NULL, so every trade is unvalidated: staged only with `ack_unvalidated: true` (else 409 `evidence_unvalidated`); the trade stores `evidence: "unvalidated (acknowledged)"` |
| Regular hours (bridge running) | The approved algo runs; every `decision`, `fill`, `staged` and `hedge_a` event carries the bridge's label `evidence: "validated"` or `"unvalidated (acknowledged)"`, with one exception: the staged `{event: "refused"}` event's `evidence` is the expected-gap view (an object: `validated`, `status`, `evidence`, `rate_source`, `basis_ticker`, `reasons`, ...). A staged event's `order.evidence_gate` says whether the plan itself is `validated` or `override` |
| Closed hours (staged hedge B) | `plan_for` refuses with 409 `EVIDENCE_GATE` unless `act_on_unvalidated` is set on a proposal approved with `ack_unvalidated: true`, or on the bridge (accepted only for such a proposal); each plan stores `evidence_gate: validated \| override`, each broker order's note says `evidence: ...`, and a refusal is reported once per closure as an SSE `staged` event `{event: "refused"}` |

The demo weekend (US recession 2025 on SPY) is validated and approves without the acknowledgement. The voice agent's approve tool sets `ack_unvalidated` only after the user has acknowledged it.

### What passes today

| Item | Test | Verdict | What the product does |
|---|---|---|---|
| Expected gap | R2, walk-forward in time | Passes on the US-recession market only (97 of 151, 64.2%; slope +1.28); fails on the 10-market replication panel (50.2% of 878) | **Validated** only for that market, with its own rate and on SPY (the ticker R2 tested); every other market or ticker is an unvalidated estimate |
| Hedge B (staged order at 09:30) | R1 | Passes, fragile: +11.42% [+5.10, +18.14] vs no hedge, +6.82% [+0.50, +13.54] vs a same-size static hedge; partial under block bootstrap | The default closed-market action, labelled with its scope |
| Hedge A (PM contract over the closure) | R1 | No evidence; increased variance on the replication panel | Opt-in, off by default, labelled an estimate, never protection |
| Options at the open | R3 | NULL after costs: options repriced by 0.44 of the PM move (CI 0.33 to 0.57), net residual +0.79 pt [-1.21, +2.78] | An estimate, never called an edge; its simulated trade is staged only with `ack_unvalidated: true` (409 `evidence_unvalidated` otherwise) and labelled `unvalidated (acknowledged)` |
| AI fit | Walk-forward | Fails (median -0.0040, Wilcoxon p = 1.000) | Configuration, not edge; scores labelled in-sample |

R1 and R2 are pre-registered analyses of an already-seen 380-closure panel; the four tests on new data (replication, fit walk-forward, 8-K out of sample, R3) failed or were NULL. The 8-K study, pre-registered and frozen before its single out-of-sample run, is null in-sample; out of sample H1 INSUFFICIENT, H2 NULL: it is the most rigorous of the studies that did not work. Full table, method commits and caveats: `research/EVIDENCE.md`.

## 7. Front end and voice

- **The UI** (`web/`) follows a high-fidelity design prototype: the liquid-glass style and 8 screens (Landing, Build chat, Connect brokerage, AI pipeline, Bridge live, Portfolio, Library, Profile). Our API replaces the prototype's simulated data wherever an endpoint exists; where none exists the prototype's behaviour stays, labelled.
- Highlights: the **AI fit card** on Build (event class, family, preset, score, rationale, alternatives); the **Library** screen (families, presets, latency, read live from the catalog); the **Account** panel (broker name, cash, positions, fills); the closed-market views in section 2.
- **Voice:** an ElevenLabs agent whose tools call our API (search markets, fit, propose, approve, start a bridge, account). The backend lists the tools at `GET /agent/tools`; the web app embeds the widget when `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` is set. Approving and starting a bridge need an explicit "yes". Setup: `docs/voice-agent.md`.

## 8. Safety rules

- **Paper or simulated accounts only.** Real-money execution is out of scope; the Webull client refuses any host but the sandbox.
- **Human approval.** Proposals start pending; a bridge runs only the approved algorithm, capped at the approved coverage; staged orders execute only after **Approve plan**.
- **Evidence gate.** An unvalidated market needs `ack_unvalidated` at approval and, in closed hours, a confirmed `act_on_unvalidated` before a staged equity plan is made; hedge A needs its own opt-in and is always an estimate; the options-at-the-open trade needs `ack_unvalidated`; everything is labelled (section 6).
- **Caps and gates.** One coverage cap across PM and equity legs; a fee gate holds any order whose benefit does not beat its cost; a no-trade band holds small rebalances; drawdown and gap-flip kills; every decision has a reason code.
- **Liquidity caps** on every order path (section 10): bridges, staged plans, hedge A's PM leg, the options-at-the-open trade and the manual `POST /orders`. On the automated paths an order larger than its cap is cut to the cap and says which cap bound (`liquidity_capped`); the manual route refuses it (409). With no liquidity numbers an order is not capped and is labelled `unknown`.
- **Capital budget** (section 11), on the bridges, staged plans, the options-at-the-open trade and `POST /orders` (hedge A's simulated PM leg is depth-capped but not budget-checked): an exposure-increasing order that breaches the gross or per-event budget, or the broker's buying power, is refused (`capital_budget`); if the account cannot be read, such orders are refused (fail closed). Orders that only reduce exposure are never refused. An exposure-increasing order with no price at all (no live quote, no cached price, no broker mark or quote) has an unknown notional, so it is refused at the account too (fail closed); in a replay sandbox it goes ahead unchecked and labelled.
- **No stale prices.** Replays fill an equity order only at a fresh in-session price; a closed-market staged order in a replay waits for a fresh recorded price.
- **Honest labels.** Replay vs live, AI estimate vs measured, simulated vs Webull paper, validated vs unvalidated estimate, in-sample vs out of sample, case study vs proof.
- **Keys only in `.env`** (gitignored): `MASSIVE_API_KEY`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, the Webull keys. A missing key means a graceful fallback, never a crash or a 500.
- **Research discipline.** Methods are committed before data is fetched; out-of-sample windows are frozen and run once; `research/HYPOTHESIS.md` is append-only.
- **Engineering.** C++20, header-only blocks, no heap allocation and no virtual calls in `on_tick`; a GoogleTest per block and per family; a latency benchmark per family. Tests run offline with HTTP mocked.

## 9. Library groups in the UI

The Library screen groups blocks the way the design does:

| Block kind | UI group |
|---|---|
| signals | Reader |
| sizers | Impact |
| gates, risk | Gate |
| execution | Execution |
| tax | Tax |
| routing | Routing |

The preset count shown is whatever `catalog()` reports (1,386 today). The design mock quotes about 1,284 algorithms; that figure is not used, and grids are never padded with duplicate presets.

## 10. Liquidity and capacity (`backend/app/liquidity/`)

Every order is checked against what the market can absorb, and every proposal says before approval whether its hedge fits.

### Inputs (`service.py`)

| Instrument | What is read | Source |
|---|---|---|
| Equity | 20-day ADV (shares and dollars); daily sigma from the last 20 close-to-close returns; median volume of the 09:30 ET five-minute bar over the last 20 sessions; spread from the last quote | Massive daily and 5-minute bars, last quote. With no quote, the Corwin-Schultz (2012) high-low estimate from daily bars, labelled as such. A quote taken outside the regular session is flagged ("its spread may be wider than at the open") |
| Option | open interest, volume, bid/ask (when the plan has a quote, else the fmv mark), delta | Massive chain snapshot |
| Prediction market | depth within 1, 2 and 5 cents of the mid, each side, plus the verified twin's book | full Polymarket CLOB book or Kalshi order book |

Each Massive call is bounded at 8 s, each book call at 4 s, each route at 12 s. Equity numbers are cached 300 s and books 15 s. A failed refresh serves the last good value marked stale, unknown numbers stay empty (never invented), and a route never returns a 500. The order gates read only cached numbers, so an order never waits on the network. A bridge starts fetching its ticker's numbers in the background when it starts.

### Participation caps (fixed in `model.py`)

| Instrument | Cap | Why |
|---|---|---|
| Equity, per order | at most 10% of the opening five-minute volume | hedge B executes at the open, so the order is sized against that window, not the whole day |
| Equity, per day | at most 1% of ADV, summed over every order in the ticker in the same ET session date | a common institutional participation ceiling; it keeps the square-root impact near k x sigma x 0.1 |
| Option, per order | at most 10% of the contract's volume and at most 5% of its open interest, on every leg | open interest turns over slowly |
| PM leg, per order | at most 50% of the depth within 2 cents of the mid, on the side taken | the book is never swept past 2 cents |

The per-day count is kept separately for the account and for each replay sandbox. The gate sits on every order path: equity orders in the algo and legacy bridges, staged plans (when planned and again when executed), every leg of an opportunity bridge's option combo, every leg of the options-at-the-open trade (at execution), hedge A's PM leg (using the tick's book depth), and the manual `POST /orders` (equity and option orders; it refuses rather than cuts, and counts its equity orders toward the per-day cap). Prediction legs sent through `POST /orders` are simulated and not depth-capped, because the request carries no book. A capped order is cut to the cap and carries `gates: [{reason: "liquidity_capped", limit, limit_qty, capped_from, rule}]` and a `liquidity` block; the bridge summary counts `liquidity_capped`. With no cached numbers the order is not capped and is labelled "unknown".

### Cost model

`cost_bp = half_spread_bp + k x sigma_daily x sqrt(q / ADV) x 1e4`, with k = 1.0, the conservative end of the square-root-law estimates (Toth et al. 2011; Almgren et al. 2005). Options are costed at the half spread only (their impact is not modelled; the caps keep orders small). PM legs are costed by walking the book.

### Outputs

Max order, max position (one session's daily cap, so a hedge can always be taken off the next day inside the same cap), estimated cost at a size, and **capacity**: the largest holding in dollars whose hedge (coverage x holding) fits one order at the open and fits one session. `POST /proposals` returns a `capacity` block before approval: the hedge against the caps, whether it fits, estimated cost, orders and sessions needed, capacity in dollars, the PM book depth, and the capital fit (section 11).

Routes: `GET /liquidity/{ticker}?coverage&qty`, `GET /liquidity/option?underlying&strike&expiry&right`, `GET /liquidity/pm?source&id&token_id`. Each response shows its sources and how stale they are.

### One snapshot (Saturday 2026-10-03, Friday's data)

From `docs/liquidity-snapshot-2026-10-03.json` (the service run once at 19:40 UTC with the Massive key; bars end with the Friday 2026-10-02 session; the spread is the last quote, which on a Saturday is from after hours or overnight). Coverage 0.5.

| | SPY | TLT | ITA |
|---|---|---|---|
| Price | $769.64 | $77.48 | $207.79 |
| ADV | 46.0M shares ($35.2B) | 47.8M shares ($3.82B) | 857k shares ($184M) |
| Opening 5-min volume (median) | 1,242,403 | 805,109 | 30,996 |
| Max order (binding cap) | 124,240 shares (opening volume) | 80,510 (opening volume) | 3,099 (opening volume) |
| Max per session (1% ADV) | 460,473 | 478,458 | 8,572 |
| Cost at the max order | 4.2 bp (0.8 half spread + 3.4 impact) | 3.3 bp (0.6 + 2.7) | 89.4 bp (84.4 + 5.0) |
| Holding whose hedge fits one order at the open | $191M | $12.5M | $1.29M |
| ... and fits one session | $709M | $74M | $3.56M |

ITA's cost is almost all spread from an after-hours quote (168.9 bp wide); the service's Corwin-Schultz estimate from the same 20 daily bars is 55.1 bp, so read ITA's cost as an upper bound until a regular-session quote is taken. Same run: the SPY 650 put expiring 2026-12-18 caps at 82 contracts per order (bound by Friday's volume of 826; open interest 20,048 would allow 1,002); the "Another Fed rate hike in 2026?" Polymarket book (live on Saturday, mid 0.725, 1-cent spread) caps a buy at 4,026 contracts and a sell at 2,191, costing about 0.9 and 1.5 cents against the mid at those sizes.

## 11. Capital controls (`backend/app/capital/`)

### Budget

| Limit | Default | Override |
|---|---|---|
| Gross hedge notional (every short equity hedge at its price, plus the risk of open option structures, plus approved or working staged sells not yet filled) | at most 50% of account equity | `CAPITAL_MAX_GROSS_PCT` or `app.state.capital_limits` |
| Per-event exposure (the same, summed per prediction market) | at most 20% of account equity | `CAPITAL_MAX_EVENT_PCT` |

The gross figure is never below the broker's own short positions, so a short left by an earlier server run is not forgotten when the in-memory bridges are.

### Margin

| Position | Requirement |
|---|---|
| Short equity | Reg T 50% initial, 30% maintenance |
| Long option | the premium, paid in full |
| Short spread | its max loss (width minus credit) |
| Short put | cash-secured by default (strike minus credit); with `CAPITAL_SHORT_PUT_MODE=margin`, the Reg T naked-put rule |
| Short call (manual route only; no algo sells a bare call) | its strike notional minus the credit, the same cash-secured analogue as a sold straddle |

### Pre-trade check

Buying power is checked against the active broker's own number. The simulator reports buying power as excess cash, so the order's initial margin must fit it. Webull reports buying power as notional, so the order's notional must fit it. Option orders are checked against the account their legs fill in: the simulator behind Webull paper by default, the Webull paper account itself when `WEBULL_OPTIONS=1` (section 5); the options-at-the-open trade always fills in, and is checked against, the simulator. An exposure-increasing order that breaches any limit is refused with `capital_budget`: bridge equity orders, bridge option openings, staged approval (409 `CAPITAL_BUDGET`) and staged execution, the options-at-the-open trade at execution (its max loss: debit plus fees), and the manual `POST /orders` (409 `CAPITAL_BUDGET`; a sell that opens or adds to a short, or an option order that opens or adds to a position; a long equity buy is left to the broker's own cash check). An order that only reduces exposure is never refused.

Contingencies: the account is read with an 8 s bound and cached 10 s; if it cannot be read, exposure-increasing orders are refused (fail closed) and `GET /capital` says why. A failed check fails closed at the account too. A replay sandbox is evaluated against its own simulator but not enforced, and says so (`enforced: false`). **An order with no price fails closed too.** An exposure-increasing equity order is priced from the tick or the order's reference, else the cached Massive price, else the broker's own mark of a position in the ticker, else its quote provider (`capital.order_price`). When none gives a price its notional is unknown, so at the account it is refused (`capital_budget`, on the bridges, staged plans and `POST /orders`); in a replay sandbox it goes ahead unchecked and labelled. (The liquidity gate's equivalent case is not refused: with no liquidity numbers an order is not capped and is labelled `unknown`.)

What the running total does not carry: option positions opened through `POST /orders` or by the options-at-the-open trade are checked when they open, but they are not added to the gross and per-event totals afterwards (those count bridges, staged orders and the broker's own short equity positions). Manual orders have no prediction market, so they count against the `unattributed` event.

`GET /capital` returns equity, buying power, gross hedge notional, staged and option exposure, initial and maintenance margin, use per event, and any breaches.

### What binds first, in practice

On the $1,000,000 Webull paper account at the default budget, the per-event limit is $200,000 of hedge notional: about 259 SPY, 2,581 TLT or 962 ITA shares at the snapshot prices, with $100,000 of Reg T initial margin. That is far inside each ticker's liquidity caps (section 10), so for this account capital binds before liquidity. Liquidity binds first only for books in the millions (ITA, about $1.3M of holding at 50% coverage) or hundreds of millions (SPY, about $191M).

## 12. Options chain and hedge-instrument comparison (`backend/app/options/`)

- **Chain** (`GET /options/chain/{underlying}`): one expiry of the Massive chain, per contract quote, last price, volume, open interest, IV and greeks. Greeks are Massive's where present, else Black-Scholes from the mark, labelled `computed`. The plan's chain snapshot has no bid/ask, so the contracts nearest the money get their last NBBO from `/v3/quotes` (15-minute delayed) and the rest stay fmv-marked; each row says which. With the market closed it is the last session's close, labelled so, with a staleness flag.
- **Hedge-instrument comparison** (`GET /options/hedge-quote?ticker&shares`): what it costs to hedge a long position four ways, side by side: short stock, protective put, collar and put spread. Legs are bought at the ask and sold at the bid (no quote: fmv plus or minus an estimated half spread, flagged). Each strategy reports upfront cash, expected cost (spread and fees if fairly priced; borrow too for short stock, at an assumed 0.30% a year because neither Massive nor Webull reports a borrow rate), the delta-equivalent shares, margin, liquidity flags, and P&L scenarios from -30% to +20%. The ranking is by expected cost. It is a quote, not an order.
- **Marks** (`GET /options/mark/{contract}`): the mid with its spread source (`nbbo`, `estimated` or `settlement`) and realistic exit prices; bridges and the portfolio use it for option P&L.

Exact response shapes: `docs/contracts.md`.
