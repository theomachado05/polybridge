# The hedgecore algo library

PolyBridge's hedging brain is a compiled C++20 library, `hedgecore`: **16 families, 1,278 presets, built from 37 reusable blocks**. The AI never writes trading code. It only chooses a family and a preset from this fixed, tested catalog, so everything it can recommend has been compiled, unit-tested, and benchmarked ahead of time. Counts below come from `engine/hedgecore/manifest.json` (schema `hedgecore.catalog/v1`); latencies come from `engine/hedgecore/BENCH.md`.

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

Each family wires a subset of these into a pipeline, roughly: read signals, check gates, size, apply risk limits, shape execution, then (for equity legs) tax rules. A **preset** is one combination of the family's tuned parameters; the grid is the cross product of each tuned parameter's grid values. Across the 16 families that gives **1,278 presets** (never padded with duplicates). The families cover 10 event classes: `macro_fed`, `elections`, `tariffs_trade`, `geopolitics_energy`, `housing`, `fig`, `tech_regulation`, `crypto`, `corporate_8k`, `company_specific`.

## The 16 families

Division: **hedge** protects a stock the user holds against an adverse prediction-market event; **opportunity** takes a position from a prediction-market mispricing. p50 and p99 are `on_tick` ns per call from the 64-call-block view in BENCH.md (clock cost amortized); mean is the batch mean.

| family | division | event classes | instruments | blocks | tuned params (grid) | presets | mean ns | p50 ns | p99 ns |
|---|---|---:|---|---:|---|---:|---:|---:|---:|
| `equity_delta_bridge` | hedge | all 10 | equity | 11 | 4 (4 x 3 x 3 x 3 = 108) | 108 | 28.6 | 28 | 36 |
| `stress_lead_hedge` | hedge | 3 | equity, etf | 11 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 30.1 | 29 | 39 |
| `book_imbalance_hedge` | hedge | all 10 | equity | 11 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 32.5 | 32 | 35 |
| `poly_kalshi_spread` | hedge/opportunity | all 10 | pred_yes, pred_no | 6 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 34.7 | 27 | 28 |
| `no_bid_seller` | opportunity | all 10 | pred_no | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.2 | 29 | 41 |
| `fig_stress` | hedge | 2 | etf:KRE, etf:XLF, etf:KBE | 8 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 34.0 | 34 | 45 |
| `housing_rates` | hedge | 1 | etf:ITB, etf:XHB, etf:VNQ | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.2 | 29 | 35 |
| `macro_fed_hedge` | hedge | 1 | etf:SPY, etf:IWM, etf:TLT | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 28.7 | 29 | 35 |
| `election_hedge` | hedge | 1 | etf:sector | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.4 | 28 | 36 |
| `tariff_trade_hedge` | hedge | 1 | etf:importers, etf:exporters | 8 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.7 | 29 | 39 |
| `energy_geo_hedge` | hedge | 1 | etf:XLE, etf:USO | 10 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 29.9 | 29 | 31 |
| `crypto_reg_hedge` | hedge | 1 | equity:COIN, equity:MSTR | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 31.3 | 31 | 39 |
| `tech_reg_hedge` | hedge | 2 | equity:megacap_tech | 9 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 28.8 | 29 | 31 |
| `binary_vs_spread_arb` | opportunity | all 10 | option:call_spread, option:put_spread | 5 | 3 (4 x 3 x 3 = 36) | 36 | 28.4 | 26 | 32 |
| `vol_vs_pm_move` | opportunity | all 10 | option:straddle, option:strangle | 4 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 28.5 | 28 | 35 |
| `eightk_opportunity` | opportunity | 2 | option:cash_secured_put, option:put_spread | 6 | 4 (3 x 3 x 3 x 3 = 81) | 81 | 28.8 | 28 | 35 |
| **total** | | | | | | **1,278** | | | |

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
3. **Replay**: for each shortlisted family, `replay_grid` runs every preset over recent real ticks of that market and the underlying, filling at the touch plus fees. Each preset gets P&L net of fees, max drawdown, turnover, and `hedge_var_reduction` (how much the hedge cut the variance of the user's P&L).
4. **Pick**: hedge families score on `hedge_var_reduction`; opportunity families score on net P&L per unit of drawdown. Highest score wins; ties go to fewer orders, then rule order. The runner-up presets are returned as alternatives.
5. **Explain**: the rationale cites the measured replay numbers. If the engine cannot score (no compiled module, too few ticks), the pick is by rules, flagged `scored: false`, and labelled as unscored rather than presented as measured.

Replay is what makes tuning cheap: scoring the whole library once (1,278 presets over 20,000 synthetic ticks) took 1.73 s on one thread (BENCH.md). Replay results are in-sample estimates on recent history, not out-of-sample proof, and the UI labels them that way.

## Latency

Batch mean per `on_tick` is 28.4 to 34.7 ns across all 16 families on 1,000,000 synthetic ticks; the worst 64-block p99.9 is 69 ns per call and the worst per-call p99.9 (which includes two clock reads) is 167 ns. Machine: Apple M5, Apple clang version 17.0.0 (clang-1700.3.19.1), `-O3`. Full tables, method and caveats are in `engine/hedgecore/BENCH.md`. This is the cost of the decision itself, not network or Python overhead around it.

## Design rules

These are enforced by tests, not just convention (spec section 8):

- **No heap allocation on the hot path.** `on_tick` and `on_fill` never allocate. `NoAlloc.OnTickAndOnFillNeverAllocate` overrides `operator new` in the test binary with a counter and drives every family through thousands of ticks, including its order path, asserting zero allocations.
- **No virtual calls.** Blocks are plain structs with `noexcept` methods and are header-only, so the compiler inlines them. Families are held in one `std::variant` (`AnyAlgo`) and dispatched with `std::visit`: static dispatch, no vtables.
- **Fixed-size state.** Order books are a fixed-depth (`kDepth = 5`) array inside the tick; per-algo state is a handful of doubles and small arrays.
- **NaN safety.** Missing data arrives as NaN. Blocks check inputs with finite and probability-range tests and hold with a reason code instead of trading on garbage. A non-finite fill is ignored and latches the engine into an `Invalid` state. The no-alloc test injects NaN quotes mid-stream.
- **Time comes from the tick.** Algos read the tick's own timestamp, so replay and live produce the same decisions on the same ticks.
- **Tested per block and per family.** GoogleTest suites cover each block kind, each of the 16 families, the replay harness, and the catalog (counts match the manifest).

## Reproduce

```bash
cmake -S engine/hedgecore -B build/hedgecore -DCMAKE_BUILD_TYPE=Release && cmake --build build/hedgecore -j --target hedgecore_bench && ./build/hedgecore/hedgecore_bench 1000000 20000
(cd build/hedgecore && ctest)
```
