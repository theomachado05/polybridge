# hedgecore benchmark

Measured results for the `hedgecore` C++ library: `on_tick` latency per family and `replay_grid` throughput. Every number below is copied from one run of `hedgecore_bench`; nothing is estimated.

## Machine and build

| item | value |
|---|---|
| model | `Mac17,2` (`sysctl hw.model`) |
| CPU | Apple M5, 4P + 6E cores |
| OS | macOS 26.4.1 |
| compiler | Apple clang version 17.0.0 (clang-1700.3.19.1) |
| flags | `-O3 -DNDEBUG` (CMake Release), `-std=c++20`, no `-march=native`, no LTO, single thread |
| date | 2026-10-03 |

## Exact command

From the repo root:

```bash
cmake -S engine/hedgecore -B build/hedgecore -DCMAKE_BUILD_TYPE=Release && cmake --build build/hedgecore -j --target hedgecore_bench && ./build/hedgecore/hedgecore_bench 1000000 20000
```

Arguments: ticks per family (default 1000000) and ticks for the `replay_grid` run (default 20000). The tape is synthetic and deterministic (LCG seed 42, a random-walk probability in [0.05, 0.95], 5-level books, an underlying, option and 8-K fields), the same tape for every family, with the family's default preset and `shares_held = 1000`. An untimed warm-up pass over all 1e6 ticks runs before the timed passes (warm cache and branch predictors). Fills are fed back through `on_fill` in the per-call pass so algo state evolves as in a live bridge.

## on_tick latency per family (1,000,000 ticks each)

Three views of the same work:

- **mean**: total wall time of a batch of 1e6 calls divided by 1e6. No per-call clock cost. This is the best estimate of the work itself.
- **per-call** p50 / p99 / p99.9: a `steady_clock` read around every call. This includes two clock reads and is quantized to the clock tick (about 42 ns on Apple Silicon), so it is an upper bound and its p50 is pinned at one tick.
- **64-block** p50 / p99 / p99.9: time of each 64-call block divided by 64 (clock cost amortized 64x). The tightest per-call view; the tail shows jitter across blocks, not a single worst call.

All values in nanoseconds.

| family | mean | per-call p50 | per-call p99 | per-call p99.9 | 64-block p50 | 64-block p99 | 64-block p99.9 | orders emitted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `equity_delta_bridge` | 28.6 | 42 | 42 | 84 | 28 | 36 | 43 | 17,989 |
| `stress_lead_hedge` | 30.1 | 42 | 83 | 84 | 29 | 39 | 49 | 6,885 |
| `book_imbalance_hedge` | 32.5 | 42 | 84 | 84 | 32 | 35 | 42 | 40,890 |
| `poly_kalshi_spread` | 34.7 | 42 | 83 | 84 | 27 | 28 | 34 | 8 |
| `no_bid_seller` | 29.2 | 42 | 42 | 84 | 29 | 41 | 54 | 239,761 |
| `fig_stress` | 34.0 | 42 | 84 | 84 | 34 | 45 | 48 | 928 |
| `housing_rates` | 29.2 | 42 | 83 | 84 | 29 | 35 | 37 | 58,823 |
| `macro_fed_hedge` | 28.7 | 42 | 83 | 84 | 29 | 35 | 69 | 10,672 |
| `election_hedge` | 29.4 | 42 | 83 | 125 | 28 | 36 | 38 | 36,553 |
| `tariff_trade_hedge` | 29.7 | 42 | 84 | 84 | 29 | 39 | 41 | 44,589 |
| `energy_geo_hedge` | 29.9 | 42 | 83 | 84 | 29 | 31 | 37 | 40,890 |
| `crypto_reg_hedge` | 31.3 | 42 | 42 | 84 | 31 | 39 | 50 | 67,665 |
| `tech_reg_hedge` | 28.8 | 42 | 42 | 84 | 29 | 31 | 36 | 20,075 |
| `binary_vs_spread_arb` | 28.4 | 42 | 83 | 167 | 26 | 32 | 35 | 568,388 |
| `vol_vs_pm_move` | 28.5 | 42 | 83 | 167 | 28 | 35 | 38 | 122,372 |
| `eightk_opportunity` | 28.8 | 42 | 83 | 84 | 28 | 35 | 57 | 1 |

Summary: batch mean 28.4 to 34.7 ns per `on_tick` across all 16 families. Worst per-call p99.9 is 167 ns (a few clock ticks); worst 64-block p99.9 is 69 ns per call. Every family decides in well under a microsecond, about four orders of magnitude below the 1 ms scale of a network round trip to a venue.

Caveats, stated plainly:

- Synthetic tape, not recorded market data; real books branch differently. Order counts differ a lot by family on this tape (`poly_kalshi_spread` emitted 8 orders and `eightk_opportunity` 1, because the tape rarely opens a cross-venue gap or an 8-K event), so those two mostly measure the no-trade path. The no-alloc test, `NoAlloc.OnTickAndOnFillNeverAllocate`, drives every family through the order path on a separate tape.
- Measures `on_tick` only: not the network, JSON parsing, or the Python bridge around it.
- One machine, one run, one thread. Expect other CPUs to differ.

## replay_grid throughput

`replay_grid(family, position, ticks)` replays every preset of a family over the same ticks with the replay harness (fill model, fees, P&L, drawdown, hedge variance reduction, per-tick latency capture). Run here over the first 20,000 ticks of the tape after one warm-up call. Throughput is presets x ticks per second, single thread.

| family | presets | ticks | seconds | preset-ticks / s |
|---|---:|---:|---:|---:|
| `equity_delta_bridge` | 108 | 20,000 | 0.143 | 1.505e+07 |
| `stress_lead_hedge` | 81 | 20,000 | 0.109 | 1.486e+07 |
| `book_imbalance_hedge` | 81 | 20,000 | 0.117 | 1.387e+07 |
| `poly_kalshi_spread` | 81 | 20,000 | 0.101 | 1.611e+07 |
| `no_bid_seller` | 81 | 20,000 | 0.114 | 1.419e+07 |
| `fig_stress` | 81 | 20,000 | 0.123 | 1.313e+07 |
| `housing_rates` | 81 | 20,000 | 0.110 | 1.478e+07 |
| `macro_fed_hedge` | 81 | 20,000 | 0.108 | 1.500e+07 |
| `election_hedge` | 81 | 20,000 | 0.107 | 1.516e+07 |
| `tariff_trade_hedge` | 81 | 20,000 | 0.115 | 1.415e+07 |
| `energy_geo_hedge` | 81 | 20,000 | 0.108 | 1.504e+07 |
| `crypto_reg_hedge` | 81 | 20,000 | 0.109 | 1.488e+07 |
| `tech_reg_hedge` | 81 | 20,000 | 0.110 | 1.466e+07 |
| `binary_vs_spread_arb` | 36 | 20,000 | 0.047 | 1.530e+07 |
| `vol_vs_pm_move` | 81 | 20,000 | 0.107 | 1.515e+07 |
| `eightk_opportunity` | 81 | 20,000 | 0.104 | 1.559e+07 |

All 1,278 presets over 20,000 ticks: 1.73 s total, 1.476e+07 preset-ticks per second (sum of the table's seconds, so this is the cost of scoring the whole library once on one thread).
