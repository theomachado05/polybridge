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

Arguments: ticks per family (default 1000000) and ticks for the `replay_grid` run (default 20000). The tape is synthetic and deterministic (LCG seed 42, a random-walk probability in [0.05, 0.95], 5-level books, an underlying, option and 8-K fields), the same tape for every family, with the family's default preset and `shares_held = 1000`. An untimed warm-up pass over all 1e6 ticks runs before the timed passes (warm cache and branch predictors). Fills are fed back through `on_fill` in every pass (per-call, 64-block, batch mean and step() mean) so algo state evolves as in a live bridge; in the batch, block and step() passes the `on_fill` call is inside the timed region, in the per-call pass it is outside.

## on_tick latency per family (1,000,000 ticks each)

`AlgoBase::on_tick` stamps `Intent::latency_ns` itself with two `steady_clock::now()` reads (about 15 ns together on this machine). So every `on_tick` figure below is the full cost of `on_tick` including that self-timing, not the decision logic alone. Four views:

- **mean**: total wall time of a batch of 1e6 `on_tick` calls divided by 1e6. The bench adds no clock reads per call, but `on_tick`'s own two reads are inside it.
- **step() mean**: the same batch loop calling the family's `step()` directly, so no latency stamp. This is the decision logic alone.
- **per-call** p50 / p99 / p99.9: a `steady_clock` read around every call. With `on_tick`'s own reads that is four clock reads per call, and the figure is quantized to the clock tick (about 42 ns on Apple Silicon), so it is an upper bound and its p50 is pinned at one tick.
- **64-block** p50 / p99 / p99.9: time of each 64-call block divided by 64. This amortizes only the bench's outer two clock reads; `on_tick`'s own two reads per call remain in the figure. The tail shows jitter across blocks, not a single worst call.

All values in nanoseconds.

| family | mean | step() mean | per-call p50 | per-call p99 | per-call p99.9 | 64-block p50 | 64-block p99 | 64-block p99.9 | orders emitted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `equity_delta_bridge` | 30.7 | 13.6 | 42 | 84 | 84 | 29 | 37 | 54 | 17,989 |
| `stress_lead_hedge` | 29.8 | 10.3 | 42 | 42 | 84 | 29 | 37 | 41 | 6,885 |
| `book_imbalance_hedge` | 32.7 | 16.7 | 42 | 84 | 84 | 32 | 46 | 54 | 40,890 |
| `poly_kalshi_spread` | 27.1 | 4.2 | 42 | 42 | 458 | 27 | 73 | 83 | 8 |
| `no_bid_seller` | 29.7 | 13.3 | 42 | 42 | 84 | 30 | 39 | 42 | 239,761 |
| `fig_stress` | 30.3 | 11.4 | 42 | 83 | 84 | 30 | 37 | 40 | 928 |
| `housing_rates` | 31.6 | 16.1 | 42 | 42 | 84 | 31 | 42 | 50 | 58,823 |
| `macro_fed_hedge` | 30.0 | 14.1 | 42 | 83 | 84 | 29 | 36 | 39 | 10,672 |
| `election_hedge` | 30.6 | 14.8 | 42 | 42 | 84 | 29 | 39 | 45 | 36,553 |
| `tariff_trade_hedge` | 34.6 | 22.9 | 42 | 84 | 84 | 34 | 44 | 49 | 44,589 |
| `energy_geo_hedge` | 30.2 | 11.5 | 42 | 42 | 84 | 30 | 36 | 42 | 40,890 |
| `crypto_reg_hedge` | 31.4 | 14.1 | 42 | 42 | 84 | 31 | 39 | 44 | 67,665 |
| `tech_reg_hedge` | 29.2 | 8.7 | 42 | 42 | 84 | 29 | 37 | 39 | 20,075 |
| `binary_vs_spread_arb` | 27.7 | 16.8 | 42 | 83 | 167 | 27 | 35 | 41 | 568,388 |
| `vol_vs_pm_move` | 28.9 | 18.1 | 42 | 83 | 125 | 29 | 35 | 42 | 122,372 |
| `eightk_opportunity` | 28.3 | 16.3 | 42 | 42 | 84 | 28 | 34 | 37 | 1 |
| `closed_session_hedge` ¹ | 29.7 | 9.8 | 42 | 84 | 84 | 29 | 37 | 39 | 2,922 |

¹ `closed_session_hedge` was added after the run above, so its row comes from a second run, `hedgecore_bench 1000000 20000` built in `engine/hedgecore/build` (CMake Release, same machine, compiler and flags, 2026-10-03, while other jobs shared the machine). In that run `equity_delta_bridge` measured 30.2 ns mean and 14.0 ns step() mean, close to its row above, so the two runs are comparable for `on_tick`. The family checks the NYSE calendar once per minute of tick time (session edges fall on whole minutes), so on this 1-second tape most ticks skip the calendar math. The tape starts on 1970-01-01, an NYSE holiday, and crosses six regular sessions (Fri 1970-01-02 to Fri 01-09), so both the closed-market path (YES leg sized and resized) and the open path (handoff unwind) run. Since this run the family checks the full NYSE calendar (one-off closures and 13:00 early closes, `us_equity_regular_session`) instead of `us_equity_session`; that adds a few integer operations to the once-per-minute check and was not re-measured.

Summary: `on_tick` batch mean 27.1 to 34.6 ns across the first 16 families (first run; `closed_session_hedge` 29.7 ns from the second run, see footnote ¹), including its own latency stamp; the decision logic alone (`step()` mean) is 4.2 to 22.9 ns. Worst per-call p99.9 is 458 ns (a few clock ticks, four clock reads); worst 64-block p99.9 is 83 ns per call. Every family decides in well under a microsecond, about four orders of magnitude below the 1 ms scale of a network round trip to a venue.

Caveats, stated plainly:

- Synthetic tape, not recorded market data; real books branch differently. Order counts differ a lot by family on this tape (`poly_kalshi_spread` emitted 8 orders and `eightk_opportunity` 1, because the tape rarely opens a cross-venue gap or an 8-K event), so those two mostly measure the no-trade path. The no-alloc test, `NoAlloc.OnTickAndOnFillNeverAllocate`, drives every family through the order path on a separate tape.
- Measures `on_tick` only: not the network, JSON parsing, or the Python bridge around it.
- One machine, one run, one thread. Expect other CPUs to differ.

## replay_grid throughput

`replay_grid(family, position, ticks)` replays every preset of a family over the same ticks with the replay harness (fill model, fees, P&L, drawdown, hedge variance reduction, per-tick latency capture). Run here over the first 20,000 ticks of the tape after one warm-up call. Throughput is presets x ticks per second, single thread.

| family | presets | ticks | seconds | preset-ticks / s |
|---|---:|---:|---:|---:|
| `equity_delta_bridge` | 108 | 20,000 | 0.140 | 1.544e+07 |
| `stress_lead_hedge` | 81 | 20,000 | 0.108 | 1.493e+07 |
| `book_imbalance_hedge` | 81 | 20,000 | 0.110 | 1.468e+07 |
| `poly_kalshi_spread` | 81 | 20,000 | 0.100 | 1.613e+07 |
| `no_bid_seller` | 81 | 20,000 | 0.105 | 1.543e+07 |
| `fig_stress` | 81 | 20,000 | 0.113 | 1.439e+07 |
| `housing_rates` | 81 | 20,000 | 0.107 | 1.518e+07 |
| `macro_fed_hedge` | 81 | 20,000 | 0.106 | 1.524e+07 |
| `election_hedge` | 81 | 20,000 | 0.105 | 1.538e+07 |
| `tariff_trade_hedge` | 81 | 20,000 | 0.110 | 1.468e+07 |
| `energy_geo_hedge` | 81 | 20,000 | 0.108 | 1.506e+07 |
| `crypto_reg_hedge` | 81 | 20,000 | 0.108 | 1.498e+07 |
| `tech_reg_hedge` | 81 | 20,000 | 0.106 | 1.524e+07 |
| `binary_vs_spread_arb` | 36 | 20,000 | 0.047 | 1.531e+07 |
| `vol_vs_pm_move` | 81 | 20,000 | 0.105 | 1.549e+07 |
| `eightk_opportunity` | 81 | 20,000 | 0.103 | 1.569e+07 |
| `closed_session_hedge` ¹ | 108 | 20,000 | 0.219 | 9.879e+06 |

The first 16 families (1,278 presets) over 20,000 ticks: 1.68 s total, 1.521e+07 preset-ticks per second (sum of the table's seconds from the first run, so this is the cost of scoring those families once on one thread).

¹ From the second run, which was slowed by other jobs on the machine: `equity_delta_bridge` took 0.199 s (1.087e+07 preset-ticks/s) in that run against 0.140 s above, so compare `closed_session_hedge` with that same-run figure rather than with the rows above. With all 17 families the library has 1,386 presets.

## Micro families: `ladder_pair` and `touch_ticket_reference`

Added on 2026-10-04 (branch `p/engine-micro`). Status words are fixed: `ladder_pair` is a **lead**,
`touch_ticket_reference` is **unvalidated** (it emits proposals only unless the tick carries `validated = True`).
These families take their own tick types (`LadderTick`, `TicketTick`), so they are not in `AnyAlgo` and the 17
families, their 1,386 presets and their replay outputs are unchanged (locked by `tests/golden/`).

**Run:** the same `hedgecore_bench 1000000 20000` command, built in `engine/hedgecore/build` (CMake Release, same
machine, compiler and flags as above), 2026-10-04 03:21 ET. Other jobs shared the machine (load average about 5.7). In
this run `equity_delta_bridge` measured 29.9 ns mean and 13.8 ns step() mean (30.7 and 13.6 above), so the rows below
are comparable with the table above.

**Tape (synthetic, deterministic, LCG seed 42, 1-second ticks, 1,000,000 ticks per family, default preset).**
`ladder_pair`: rich bid 0.50 + 0.08 z against a cheap ask of 0.47, sizes 5 to 120 on each leg, taker fee rate 0.02
on both legs, tick 0.01, rich quote age 0 to 89 s, nested flag missing on 1 tick in 10, `event_held` 0.
`touch_ticket_reference`: bid 0.30 + 0.10 z, ask bid + 0.02, central reference 0.28, sizes 1 to 200, `validated` True on
every other tick, positions 0. Fills are fed back in full at the quoted price in every pass, as for the other families.

| family | status | mean | step() mean | per-call p50 | per-call p99 | per-call p99.9 | 64-block p50 | 64-block p99 | 64-block p99.9 | presets | orders emitted |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ladder_pair` | lead | 26.5 | 5.5 | 42 | 42 | 84 | 26 | 33 | 35 | 18 | 22 |
| `touch_ticket_reference` | unvalidated | 26.3 | 3.5 | 42 | 42 | 84 | 25 | 31 | 33 | 1 | 2 |

All values in nanoseconds, same four views as above. `on_tick` keeps `AlgoBase::on_tick`'s latency stamp (two
`steady_clock` reads inside the call); `step()` mean is the decision logic alone. Neither family allocates on the tick
path (`NoAlloc.MicroFamiliesNeverAllocate`).

**Replay throughput** (`replay_ladder` / `replay_tickets`, every preset over the first 20,000 rows of the tapes above,
one warm-up call first; fills only at the quoted bid or ask, never more than the quoted size, never at a mid):

| family | presets | rows | seconds | preset-rows / s | notes |
|---|---:|---:|---:|---:|---|
| `ladder_pair` | 18 | 20,000 | 0.011 | 3.280e+07 | rows spread over 50 pairs in 10 events |
| `touch_ticket_reference` | 1 | 20,000 | 0.001 | 3.173e+07 | 200 tickets, 20 underlyings, 40 events |

**On the research files** (correctness, not timing): replaying
`research/results/ladder_replay/order_check/trades_fresh.csv` (562 rows) through `replay_ladder` with the research
rule's settings (min_edge 0, max_age 60 s, cap 100, no event cap, 3,600 s between entries on a pair, tick 0 because
the file's prices already carry its one tick per leg) gives 562 trades and a mean of +8.8235 points per trade, the same
count and mean as the file; replaying the 303 U-all markets of `research/results/s21_options_anchor/trades.csv`
through `replay_tickets` proposes exactly the 60 markets of S21's book B0 and emits no order. On those rows the
self-stamped `on_tick` latency is below the clock's 42 ns resolution at the median (p50 0 ns, p99 42 ns as read).

Caveats, stated plainly:

- Synthetic tapes. On them `ladder_pair` emitted 22 orders: after about 20 entries the pair reaches its per-event cap
  of 1,000 contracts and the 3,600 s re-entry gap applies between entries, so most ticks take the capped or cooldown
  path. `touch_ticket_reference` emitted 2 orders before its 100-contract ticket cap filled; most later ticks end at the
  cap. Both order paths run under the no-alloc test on separate tapes.
- The research-file replays check that the family reproduces the research rule's selection and arithmetic. They are
  not new evidence: the ladder file is the year-checked sample whose rule was fixed after the registered test came back
  NULL, and the S21 book failed its own confirmation rule.
- One machine, one run, one thread, shared with other jobs.
