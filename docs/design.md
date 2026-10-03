# PolyBridge design

PolyBridge hedges stock positions with live prediction-market prices (Polymarket and Kalshi). Its one rule is **evidence gating**: a market's signal is checked out of sample before it is allowed to act on a position, and the app labels every signal either **validated** or **unvalidated estimate**. Most markets fail that check, and the app says so.

The setting that makes this useful is simple: **stocks close, prediction markets don't.** Overnight, at weekends and on holidays a prediction market keeps trading while the stock cannot. PolyBridge watches that move, estimates the open gap where the evidence allows it, and stages an equity hedge for the first moment the stock can trade. Nothing trades without the holder's approval.

This page describes the system as it stands. Every research number is in `research/EVIDENCE.md`, which names its source file; if this page and a source file disagree, the source file wins.

Contents: 1 what it is and how it fits together, 2 closed-market mode, 3 the C++ library, 4 the AI fit, 5 accounts, 6 evidence gating, 7 front end and voice, 8 safety rules, 9 library groups in the UI.

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

The Opportunity division shows the mechanism, not an edge: the options-versus-PM scan found 5 verified gaps and 0 executable, and options-at-the-open is research only (section 6).

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
3. **Approve.** A proposal starts pending. It is pinned to the approved algorithm and capped at the approved coverage; starting a bridge is refused (409) until it is approved, and for any other algorithm.
4. **Bridge.** The bridge feeds ticks (live book or a recorded replay) to the compiled algo, sends each order to the active broker and streams decisions, fills and reasons to the UI.
5. **Closed hours.** When the equity session closes, closed-market mode takes over (section 2).

## 2. Closed-market mode

While US equities are closed (after-hours, overnight, weekend, holiday, pre-market) and the prediction market trades, a bridge behaves as follows.

### Product behaviour

1. **Session clock.** Every moment is classified as regular, pre-market, after-hours, overnight, weekend or holiday on the NYSE calendar, including early closes (`backend/app/closed/session.py`, `GET /session`). A replay uses each tick's recorded time, so a replayed Saturday behaves like a Saturday.
2. **Closure tracker.** The bridge tracks the prediction-market move since the last regular close (`backend/app/closed/tracker.py`).
3. **Expected open gap.** Expected gap = rate × PM move (in points), shown with an 80% band and the number of closures behind the rate (`backend/app/closed/gap.py`, `GET /closed/expected-gap`). The rate is the market's own when it has enough past closures, otherwise the pooled rate with a wide band. The gap reads **validated** only under the evidence gate in section 6; everything else is an **unvalidated estimate**.
4. **Hedge A: hold the prediction-market contract (opt-in, an estimate).** Buy the adverse YES over the closure, sized by the C++ family `closed_session_hedge`, and unwind it at the open. Fills are simulated (there is no Polymarket trading account) and labelled so. It is off unless the proposal opts in, and it is never called protection: R1 found no evidence that it reduces the open-gap loss, and on the replication panel it increased variance.
5. **Hedge B: staged session order (the default).** An equity hedge order is planned from the expected gap once the gap is at least 10 bp against the position, and queued for the first tradable moment (`backend/app/closed/staged.py`, `POST /staged/plan`, `POST /staged/{id}/approve`, `DELETE /staged/{id}`).
   - Timing: the next pre-market (04:00 ET) when the executing broker supports extended hours, otherwise the 09:30 ET open. **The Webull paper sandbox accepts orders only from 09:30 to 16:00 ET** (it answers HTTP 417 "Orders cannot be placed at this time" outside those hours), so extended hours are off for Webull unless `WEBULL_EXTENDED_HOURS=1`, and a staged order executes at the 09:30 open. R1's evidence is for the 09:30 version; its 08:00 ET variant was only partial.
   - Approval: the holder approves the plan, naming the quantity seen. Nothing is sent before that.
   - Revert and resize: if the PM move reverts the plan is cancelled; a smaller move resizes an unsent order down; an approved order is never resized up past what was approved.
   - A replay sends it only at a fresh recorded price, never at a stale Friday close.
   - It works by timing, not direction, and executes after the gap has formed, so it cannot recover the gap itself.
6. **Opportunity at the open (research only).** At the close the option-implied probability of threshold markets is snapshotted; at the open it is compared with the PM probability (`backend/app/closed/opportunity.py`). R3 is NULL after option costs, so this is shown as research, not a trade.
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

- **One interface (`Broker`):** `account()`, `positions()`, `place_order(OrderRequest)`, `orders(status?)`, `cancel(id)`. Routes: `GET /account`, `GET /positions`, `GET /orders`, `POST /orders`, `DELETE /orders/{id}`.
- **`SimBroker`** (default): $1,000,000 starting cash, deterministic. Equity fills at the Massive quote (or the bridge's price) ± half-spread plus a per-share fee; options at the quote mid ± half-spread plus a per-contract fee; prediction legs at the PM book. State in `backend/.sim_account.json` (gitignored).
- **`WebullBroker`:** the same interface on the Webull OpenAPI paper-trading sandbox, on when `BROKER=webull` and the Webull keys are set (`WEBULL_APP_KEY` or its alias `WEBULL_API_KEY`, `WEBULL_APP_SECRET`, optional `WEBULL_ACCOUNT_ID`). It talks only to `api.sandbox.webull.com`; any other host is refused and the simulator is used. Options route to the simulator, labelled so.
- **Trading hours.** The Webull paper sandbox accepts orders only from 09:30 to 16:00 ET (tested 2026-10-03: a 1-share SPY limit order on a Saturday was refused with HTTP 417, nothing to cancel). Outside those hours the account still reads (balance, positions) and staged orders wait for the 09:30 open.
- **Replays never touch the account.** A replay bridge trades in its own sandbox simulator unless started with `replay_to_account`. So on a closed day the demo fills in the simulator while the Connect screen shows the Webull paper account connected.
- The UI always names the account in use: "Simulated account" or "Webull paper".

## 6. Evidence gating

### The rule

A signal may act on a position only as far as a pre-registered out-of-sample test supports it, for that market. The app labels each number **validated** (it passed) or **unvalidated estimate** (it did not, or was never tested), and shows the band and the closure count either way. The gate lives in `backend/app/closed/evidence.py` and reads `backend/app/data/gap_evidence.json`, built from `research/results/gap_model/tests.json`. `GET /closed/evidence` returns it for a market.

### What passes today

| Item | Test | Verdict | What the product does |
|---|---|---|---|
| Expected gap | R2, walk-forward in time | Passes on the US-recession market only (97 of 151, 64.2%; slope +1.28); fails on the 10-market replication panel (50.2% of 878) | **Validated** only for that market, with its own rate and on SPY (the ticker R2 tested); every other market or ticker is an unvalidated estimate |
| Hedge B (staged order at 09:30) | R1 | Passes, fragile: +11.42% [+5.10, +18.14] vs no hedge, +6.82% [+0.50, +13.54] vs a same-size static hedge; partial under block bootstrap | The default closed-market action, labelled with its scope |
| Hedge A (PM contract over the closure) | R1 | No evidence; increased variance on the replication panel | Opt-in, off by default, labelled an estimate, never protection |
| Options at the open | R3 | NULL after costs: options repriced by 0.44 of the PM move (CI 0.33 to 0.57), net residual +0.79 pt [-1.21, +2.78] | Research only, not a trade |
| AI fit | Walk-forward | Fails (median -0.0040, Wilcoxon p = 1.000) | Configuration, not edge; scores labelled in-sample |

R1 and R2 are pre-registered analyses of an already-seen 380-closure panel; the four tests on new data (replication, fit walk-forward, 8-K out of sample, R3) failed or were NULL. The 8-K study, pre-registered and frozen before its single out-of-sample run, is NULL in-sample and out of sample: it is the most rigorous of the studies that did not work. Full table, method commits and caveats: `research/EVIDENCE.md`.

## 7. Front end and voice

- **The UI** (`web/`) follows the high-fidelity design in `design/design_handoff_polybridge/`: the liquid-glass style and 8 screens (Landing, Build chat, Connect brokerage, AI pipeline, Bridge live, Portfolio, Library, Profile). Our API replaces the prototype's simulated data wherever an endpoint exists; where none exists the prototype's behaviour stays, labelled.
- Highlights: the **AI fit card** on Build (event class, family, preset, score, rationale, alternatives); the **Library** screen (families, presets, latency, read live from the catalog); the **Account** panel (broker name, cash, positions, fills); the closed-market views in section 2.
- **Voice:** an ElevenLabs agent whose tools call our API (search markets, fit, propose, approve, start a bridge, account). The backend lists the tools at `GET /agent/tools`; the web app embeds the widget when `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` is set. Approving and starting a bridge need an explicit "yes". Setup: `docs/voice-agent.md`.

## 8. Safety rules

- **Paper or simulated accounts only.** Real-money execution is out of scope; the Webull client refuses any host but the sandbox.
- **Human approval.** Proposals start pending; a bridge runs only the approved algorithm, capped at the approved coverage; staged orders execute only after **Approve plan**.
- **Caps and gates.** One coverage cap across PM and equity legs; a fee gate holds any order whose benefit does not beat its cost; a no-trade band holds small rebalances; drawdown and gap-flip kills; every decision has a reason code.
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
