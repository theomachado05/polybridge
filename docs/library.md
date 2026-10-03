# The hedgecore algo library

PolyBridge's hedging brain is a compiled C++20 library, `hedgecore`: **17 families, 1,386 presets, built from reusable blocks**. The AI never writes trading code. It only chooses a family and a preset from this fixed, tested catalog, so every family is compiled, unit-tested, and benchmarked (default preset) ahead of time. Counts below come from `engine/hedgecore/manifest.json` (schema `hedgecore.catalog/v1`); latencies come from `engine/hedgecore/BENCH.md`.

## Blocks, families, presets

**Block** (a small header-only unit with one job) -> **family** (a fixed pipeline of blocks for one trading idea) -> **preset** (one point on the family's parameter grid).

| block kind | UI group | distinct blocks | what they do | blocks |
|---|---|---:|---|---|
| signals | Reader | 12 | read the tick and compute a number (implied probability, EWMA volatility, book imbalance, cross-venue gap, 8-K score) | `BookImbalance`, `CrossVenueGap`, `DeltaDp`, `EightKScore`, `EwmaVol`, `ImpliedProb`, `MeanRevertZ`, `Microprice`, `Momentum`, `OptionImpliedProb`, `PMid`, `PMvsOptionGap` |
| gates | Gate | 7 | pass or block a tick (staleness, session, sigma, spread, depth, cooldown, event window) | `Cooldown`, `Depth`, `EventWindow`, `Session`, `Sigma`, `Spread`, `Staleness` |
| sizers | Impact | 5 | turn a signal into a target position (delta bridge, linear or convex exposure, Kelly capped, vol target) | `ConvexExposure`, `DeltaBridge`, `KellyCapped`, `LinearExposure`, `VolTarget` |
| risk | Gate | 5 | hard limits (position cap, notional cap, daily loss cap, drawdown kill, gap-flip kill) | `DailyLossCap`, `DrawdownKill`, `GapFlipKill`, `NotionalCap`, `PositionCap` |
| execution | Execution | 5 | decide how an order goes out (no-trade band, fee gate, passive or aggressive, slicer, iceberg cap) | `FeeGate`, `IcebergCap`, `NoTradeBand`, `PassiveAggressive`, `Slicer` |
| tax | Tax | 2 | lot selection (HIFO or long-term first) and a wash-sale guard | `TaxLotSelector`, `WashSaleGuard` |
| routing | Routing | 1 | send a prediction-market leg to Polymarket or Kalshi by best price | `VenueRouter` |

Each family wires a subset of these into a pipeline, roughly: read signals, check gates, size, apply risk limits, shape execution, then (for equity legs) tax rules. A **preset** is one combination of the family's tuned parameters; the grid is the cross product of each tuned parameter's grid values. Across the 17 families that gives **1,386 presets** (never padded with duplicates). The families cover 10 event classes: `macro_fed`, `elections`, `tariffs_trade`, `geopolitics_energy`, `housing`, `fig`, `tech_regulation`, `crypto`, `corporate_8k`, `company_specific`.

## The 17 families

Division: **hedge** protects a stock the user holds against an adverse prediction-market event; **opportunity** takes a position from a prediction-market mispricing. mean is the `on_tick` batch mean; p50 and p99 are the 64-call-block view (ns per `on_tick` call). All three include `on_tick`'s own latency stamp (two clock reads, about 15 ns), so they are the full `on_tick` cost, not the decision logic alone; BENCH.md also reports the `step()`-only mean.

| family | division | event classes | instruments | blocks | tuned params (grid) | presets | mean ns | p50 ns | p99 ns |
|---|---|---:|---|---:|---|---:|---:|---:|---:|
| `equity_delta_bridge` | hedge | all 10 | equity | 11 | 4 (4 x 3 x 3 x 3 = 108) | 108 | 30.7 | 29 | 37 |
| `stress_lead_hedge` | hedge | 3 | equity, etf | 11 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.8 | 29 | 37 |
| `book_imbalance_hedge` | hedge | all 10 | equity | 11 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 32.7 | 32 | 46 |
| `poly_kalshi_spread` | hedge/opportunity | all 10 | pred_yes, pred_no | 6 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 27.1 | 27 | 73 |
| `no_bid_seller` | opportunity | all 10 | pred_no | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.7 | 30 | 39 |
| `fig_stress` | hedge | 2 | etf:KRE, etf:XLF, etf:KBE | 8 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 30.3 | 30 | 37 |
| `housing_rates` | hedge | 1 | etf:ITB, etf:XHB, etf:VNQ | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 31.6 | 31 | 42 |
| `macro_fed_hedge` | hedge | 1 | etf:SPY, etf:IWM, etf:TLT | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 30.0 | 29 | 36 |
| `election_hedge` | hedge | 1 | etf:sector | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 30.6 | 29 | 39 |
| `tariff_trade_hedge` | hedge | 1 | etf:importers, etf:exporters | 8 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 34.6 | 34 | 44 |
| `energy_geo_hedge` | hedge | 1 | etf:XLE, etf:USO | 10 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 30.2 | 30 | 36 |
| `crypto_reg_hedge` | hedge | 1 | equity:COIN, equity:MSTR | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 31.4 | 31 | 39 |
| `tech_reg_hedge` | hedge | 2 | equity:megacap_tech | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.2 | 29 | 37 |
| `binary_vs_spread_arb` | opportunity | all 10 | option:call_spread, option:put_spread | 5 | 3 (4 x 3 x 3 = 36) | 36 | 27.7 | 27 | 35 |
| `vol_vs_pm_move` | opportunity | all 10 | option:straddle, option:strangle | 4 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 28.9 | 29 | 35 |
| `eightk_opportunity` | opportunity | 2 | option:cash_secured_put, option:put_spread | 6 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 28.3 | 28 | 34 |
| `closed_session_hedge` (added 2026-10-03 for closed-market mode: holds the adverse PM YES leg while the equity session is closed, hands off at the open; opt-in, labelled an estimate, see research/results/closed_hedge) | hedge | all | PredYes | Session (closed), NoTradeBand, FeeGate, NotionalCap | small grid | **108** | not in the 16-family bench run | | |
| **total** | | | | | | **1,386** | | | |

What each family does, in one line (from the manifest):

- `equity_delta_bridge`: Short c * N * p_adverse shares of the held stock, re-sized when the prediction market moves enough to beat fees.
- `stress_lead_hedge`: Hedge fast (cross, unsliced) when the prediction market moves sharply against its own volatility; work orders passively otherwise.
- `book_imbalance_hedge`: Pre-hedge on the order-book microprice when Polymarket/Kalshi depth is lopsided, before the mid moves.
- `poly_kalshi_spread`: When this venue's YES mid is rich (cheap) against the other venue by more than half-spread + fee + entry, buy NO (YES) here and exit when the gap closes; stop if the gap flips through the entry threshold.
- `no_bid_seller`: Sell NO into bids that are rich against a fair value (other venue, EWMA, or option-implied), Kelly-sized, routed to the venue with the best all-in price, never showing more than a fraction of displayed size.
- `fig_stress`: Bank-stress, Fed and regulation odds hedge banks/insurers convexly (p^gamma), with a drawdown kill on the hedge leg.
- `housing_rates`: Mortgage-rate and home-price odds hedge rate-sensitive homebuilder/REIT ETFs with a linear rate beta.
- `macro_fed_hedge`: Fed/CPI/recession odds hedge index proxies; the hedge only grows when probability momentum confirms and only shrinks when it reverses, with a cooldown between orders.
- `election_hedge`: Election odds above a neutral level tilt a hedge on the sector ETF the outcome hurts, linear in the excess probability.
- `tariff_trade_hedge`: Tariff odds hedge trade-exposed equities convexly; the hedge grows only on z-score breakouts above the EWMA mean and shrinks only on breakdowns.
- `energy_geo_hedge`: Conflict/OPEC odds hedge energy proxies; ignores wide, unreliable PM quotes and crosses the spread on jumps.
- `crypto_reg_hedge`: Crypto regulation/ETF odds hedge crypto equities; coverage is scaled by inverse PM volatility so noisy markets earn a smaller hedge.
- `tech_reg_hedge`: Antitrust/AI-regulation odds hedge mega-cap names on the PM microprice, worked in child slices to limit impact in large positions.
- `binary_vs_spread_arb`: Buy (sell) the call spread when the PM probability of the same threshold exceeds (trails) the option-implied probability by the entry gap; exit when the gap closes.
- `vol_vs_pm_move`: PM reprices but implied vol has not moved: buy the straddle. IV spikes while the PM is quiet: sell it. Exit when IV catches up or after max_hold ticks.
- `eightk_opportunity`: A strong 8-K tag opens an event window; if the PM adverse probability confirms (falls after a bullish tag, rises after a bearish one) sell a cash-secured put or buy a put spread; close when the window ends.

## How the AI picks and tunes

The fit pipeline (`backend/app/pipeline`) is: question -> event class -> shortlist of families -> tick history -> **replay_grid** -> best preset -> plain-language rationale.

1. **Classify**: the question (or market) maps to one of the event classes (Gemini when a key is present, a keyword rules provider otherwise).
2. **Shortlist**: only families whose event classes and data requirements match are considered.
3. **Replay**: for each shortlisted family, `replay_grid` runs every preset over recent price history of that market and the underlying (or a recorded replay file when offline, labelled as such), filling at the touch plus fees. Each preset gets P&L net of fees, max drawdown, turnover and three hedge numbers (next section). **Fills respect the equity session:** when an equity order has no live quote (recorded ticks price off the close of the last finished bar), the engine's replay rejects it outside the US regular session and until that price has changed inside the session, so a stale close (a night, a weekend, a holiday, or a new session before its first bar) is never booked as a fill that harvests the opening gap (`engine/hedgecore/include/hedgecore/replay.hpp` header comment, `engine/hedgecore/src/replay.cpp`). A hedge that wants to trade on a prediction-market move at night therefore waits for the next fresh in-session price, as it would have to in reality.
4. **Pick**: hedge families are ranked by `hedge_var_reduction_vs_static` (below); opportunity families by net P&L per unit of drawdown. Highest score wins; ties go to fewer orders, then rule order. The runner-up presets are returned as alternatives. A hedge preset that never holds a short (no orders, or an average hedge ratio of 0) is **unscored**: its score against a static hedge is exactly 0 by construction, and it would otherwise win every market where each real hedge did worse than a static one (`backend/app/pipeline/tune.py`, `never_hedged`). If no preset has a defined score against a static hedge, the pick falls back to rules with the reason `NO_STATIC_BENCHMARK`.
5. **Explain**: the rationale cites the measured replay numbers. If the engine cannot score (no compiled module, too few ticks), the pick is by rules, flagged `scored: false`, and labelled as unscored rather than presented as measured.

### What the fit score means (and what it does not)

Plain hedge variance reduction, `hedge_var_reduction = 1 - var(hedged P&L changes) / var(unhedged P&L changes)`, **rewards any static short of the stock, signal or not**: a fixed short of a fraction h of the shares scores `1 - (1 - h)^2` even when the prediction-market series is constant (`replay.hpp`). Ranking on it picks the biggest hedge, not the best signal. So the fit now ranks on a different number and reports the other two beside it:

| field in `/pipeline/fit` and `fits.json` | what it is |
|---|---|
| `score` (= `score_vs_static`, `score_basis: "hedge_var_reduction_vs_static"`) | the ranking score: `1 - var(hedged) / var(unhedged x (1 - h))`, the variance cut **beyond a static hedge of the same average size**, i.e. what the prediction-market signal adds. 0 means no better than a static hedge; negative means the timing made it worse. |
| `avg_hedge_ratio` | h: the mean short as a fraction of the shares held, over the scored intervals. |
| `score_raw` | the plain `hedge_var_reduction`. Reported, never ranked, and not the hedge's edge: most of it is hedge size (`score_raw = 1 - (1 - h)^2` for a static hedge; the engine's numbers satisfy `vs_static = 1 - (1 - raw) / (1 - h)^2`). |

`score`, `score_vs_static`, `score_raw` and `avg_hedge_ratio` can be negative or near zero, and that is a valid, honest result. The three hedge numbers are `null` for opportunity fits and for unscored fits (`score_basis` is `null` then). Opportunity fits keep their own score, net P&L per unit of max drawdown.

**Distribution over the 133 precomputed markets** (`backend/app/data/fits.json`, `summary.score_vs_static` and our tally of the per-market entries **(tally)**; `backend/data_logs/precompute_fits.log`; engine library, provider `rules`, live price history for all 133, 1,000 shares held, generated 2026-10-03T11:22:50+00:00): 122 markets have a score and 11 have no fit because the question was classified unsupported. Of the 122 scores:

- 86 are above 0 and 36 are at or below 0; all 36 are negative, meaning even the best preset did worse than a static hedge of the same size.
- Only 53 are above 0.01, 31 above 0.05, 14 above 0.1 and 7 above 0.2 **(tally)**.
- Median 0.0053, quartiles -0.0009 / 0.0053 / 0.0534, mean 0.037, min -0.0596, max 0.508 (`polymarket:4713962`, `energy_geo_hedge` on ITA: raw 0.956 at an average hedge ratio of 0.70) **(tally except median, max, min)**.
- For comparison, the median raw `hedge_var_reduction` is 0.339 and the median average hedge ratio is 0.18; 24 of the 122 picks hedge less than 5 percent on average **(tally)**. Most of what the old score showed was hedge size, not signal.

How to read it: each score is the best of many presets on the same history it is reported on, so a few thousandths (the median is 0.005) is inside selection noise. The honest reading is that the signal adds a material amount on roughly 14 to 31 of 122 markets at most, not on the 86 that are positive. These are in-sample numbers, not a forecast, and no out-of-sample test of the fits exists.

Replay is what makes tuning cheap: scoring the whole library once (1,278 presets, measured before the 17th family was added, over 20,000 synthetic ticks) took 1.68 s on one thread (BENCH.md). Replay results are in-sample estimates on recent history, not out-of-sample proof, and the Build and pipeline screens label fit scores as an in-sample replay (`web/src/lib/pipeline.ts`). The score is measured on the same history it is tuned on, and the picker maximises it over many presets.

## Latency

`on_tick` batch mean is 27.1 to 34.6 ns across all 16 families on 1,000,000 synthetic ticks. That includes `on_tick`'s own latency stamp (two `steady_clock` reads, about 15 ns); the decision logic alone (`step()`) averages 4.2 to 22.9 ns. The worst 64-block p99.9 is 83 ns per call and the worst per-call p99.9 (four clock reads per call) is 458 ns. Only each family's default preset is timed. Machine: Apple M5, Apple clang version 17.0.0 (clang-1700.3.19.1), `-O3`. Full tables, method and caveats are in `engine/hedgecore/BENCH.md`. This is the cost of the decision itself, not network or Python overhead around it.

## Design rules

Spec section 8 rules. Test-enforced: no heap allocation (`NoAlloc`), NaN handling, and per-block and per-family behavior. The rest are design rules followed in the code structure, not checked by a test:

- **No heap allocation on the hot path.** `on_tick` and `on_fill` never allocate. `NoAlloc.OnTickAndOnFillNeverAllocate` overrides `operator new` in the test binary with a counter and drives every family through thousands of ticks, including its order path, asserting zero allocations.
- **No virtual calls.** Blocks are plain structs with `noexcept` methods and are header-only, so the compiler inlines them. Families are held in one `std::variant` (`AnyAlgo`) and dispatched with `std::visit`: static dispatch, no vtables.
- **Fixed-size state.** Order books are a fixed-depth (`kDepth = 5`) array inside the tick; per-algo state is a handful of doubles and small arrays.
- **NaN safety.** Missing data arrives as NaN. Blocks check inputs with finite and probability-range tests and hold with a reason code instead of trading on garbage. A non-finite fill is ignored and latches the engine into an `Invalid` state. The no-alloc test injects NaN quotes mid-stream.
- **Time comes from the tick.** Algos read the tick's own timestamp, so replay and live produce the same decisions on the same ticks.
- **Tested per block and per family.** GoogleTest suites cover each block kind, each of the 17 families, the replay harness, and the catalog (counts match the manifest).

## Reproduce

```bash
cmake -S engine/hedgecore -B build/hedgecore -DCMAKE_BUILD_TYPE=Release && cmake --build build/hedgecore -j --target hedgecore_bench && ./build/hedgecore/hedgecore_bench 1000000 20000
(cd build/hedgecore && ctest)
```
