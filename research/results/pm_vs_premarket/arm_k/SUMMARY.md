# T2 arm K: PM move to 08:00 ET versus the SPY pre-market move (keyless arm)

Secondary sensitivity S1 of [METHOD.md](../../../pm_vs_premarket/METHOD.md) with the SPY extended-hours benchmark, computed only from committed columns of `research/results/leadlag_closed/closures_all.csv` (no network). Code commit `9a98f82`. This is not the primary test (09:25 ET, arm M).

## Headline

- **Reading under the pass rule applied to this arm:** no evidence that the PM adds information beyond the benchmark.
- PM coefficient given the SPY move to 08:00: c = -0.60 bp per pp (95% cluster CI [-2.64, +1.44]; month-block bootstrap [-2.72, +0.97]), cluster t -0.57, Freedman-Lane p 0.573, n = 379 closures.
- Incremental R-squared of the PM move: +0.0002 (bootstrap CI [+0.0000, +0.0031]); the SPY move to 08:00 alone has R-squared 0.824.
- Without the benchmark, the PM move to 08:00 has slope d = +5.53 bp per pp (cluster t +1.91); share absorbed by the benchmark 1 - c/d = 1.11.

## Tests

| test | n | c, bp per pp [95% cluster CI] | cluster t | Freedman-Lane p | dR2 [block bootstrap CI] | benchmark beta (reduced R2) | PM-only slope d |
|---|---|---|---|---|---|---|---|
| K: x to 08:00, SPY bench 08:00 | 379 (379 dates) | -0.60 [-2.64, +1.44] | -0.57 | 0.573 | +0.0002 [+0.0000, +0.0031] | +1.062 (R2 0.824) | +5.53 |
| S3: x full closure, SPY bench 08:00 (upper bound) | 380 (380 dates) | -0.02 [-1.60, +1.55] | -0.03 | 0.977 | +0.0000 [+0.0000, +0.0015] | +1.059 (R2 0.824) | +7.52 |
| S4: election, x to 08:00 | 149 (149 dates) | +0.81 [-1.98, +3.60] | +0.57 | 0.583 | +0.0003 [+0.0000, +0.0077] | +1.116 (R2 0.807) | -0.70 |
| S4: recession, x to 08:00 | 230 (230 dates) | -0.96 [-3.58, +1.66] | -0.72 | 0.473 | +0.0006 [+0.0000, +0.0064] | +1.039 (R2 0.835) | +7.93 |

## Descriptives

n 379; SD of gap 59.8 bp, of SPY move to 08:00 51.2 bp, of the remainder 08:00 to open 25.3 bp, of the PM move to 08:00 1.48 pp; share of closures with a non-zero PM move by 08:00 0.69; correlation of PM move and SPY move +0.167.
Rows: 380 placebo closures, 1 without an SPY bar in [07:45, 08:00] ET or a PM price at 08:00.

## Caveats

- Already-seen panel (METHOD.md section 0). SPY pre-market at 08:00 is thin, which weakens the benchmark and favours finding a PM effect. S3 uses PM prices after 08:00 (including 08:30 releases) and is not a test of added information.
- Two markets in disjoint years; serial dependence handled only by month blocks.
