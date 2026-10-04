# T2: does the PM move add information about the SPY open beyond the overnight benchmark?

Pre-registered in [METHOD.md](../../pm_vs_premarket/METHOD.md). Single run of arm M, code commit `f1d87e3`. Benchmark chosen by the section 2 probe: **SPY** (probe: ESM4: HTTPError: 404 Client Error: Not Found for url: https://api.massive.com/futures/vX/aggs/ESM4?resolution=1min&window_start.gte=17174; ESM24: HTTPError: 404 Client Error: Not Found for url: https://api.massive.com/futures/vX/aggs/ESM24?resolution=1min&window_start.gte=1717).

## Headline

- **Verdict under the pre-set rule:** no evidence that the PM adds information beyond the benchmark.
- PM coefficient given the benchmark move to 09:25 ET: c = +0.17 bp per pp (95% cluster CI [-0.23, +0.57]; bootstrap [-0.24, +0.42]), cluster t +0.82, Freedman-Lane p 0.439, n = 380.
- Incremental R-squared +0.0000 [+0.0000, +0.0001]; benchmark alone R-squared 0.988; PM-only slope d = +7.27, absorbed 0.98.

## Tests

| test | n | c, bp per pp [95% cluster CI] | cluster t | Freedman-Lane p | dR2 [block bootstrap CI] | benchmark beta (reduced R2) | PM-only slope d |
|---|---|---|---|---|---|---|---|
| Primary: x to 09:25, bench 09:25 | 380 (380 dates) | +0.17 [-0.23, +0.57] | +0.82 | 0.439 | +0.0000 [+0.0000, +0.0001] | +1.017 (R2 0.988) | +7.27 |
| S1: x to 08:00, bench 08:00 | 379 (379 dates) | -0.60 [-2.64, +1.44] | -0.57 | 0.573 | +0.0002 [+0.0000, +0.0031] | +1.062 (R2 0.824) | +5.53 |
| S2: replication panel, 09:25 | 1211 (492 dates) | -0.07 [-0.14, -0.01] | -2.11 | 0.036 | +0.0000 [+0.0000, +0.0001] | +1.008 (R2 0.989) | +0.61 |
| S2: replication panel, 08:00 | 1209 (492 dates) | -0.07 [-0.31, +0.17] | -0.56 | 0.595 | +0.0000 [+0.0000, +0.0004] | +1.046 (R2 0.868) | +0.84 |
| S3: x full closure, bench 09:25 | 380 (380 dates) | +0.20 [-0.20, +0.60] | +0.96 | 0.366 | +0.0000 [+0.0000, +0.0002] | +1.017 (R2 0.988) | +7.52 |
| S3: x full closure, bench 08:00 | 380 (380 dates) | -0.02 [-1.60, +1.55] | -0.03 | 0.977 | +0.0000 [+0.0000, +0.0015] | +1.059 (R2 0.824) | +7.52 |
| S4: election, 09:25 | 149 (149 dates) | +0.07 [-0.57, +0.71] | +0.22 | 0.830 | +0.0000 [+0.0000, +0.0004] | +1.031 (R2 0.991) | -2.15 |
| S4: recession, 09:25 | 231 (231 dates) | +0.30 [-0.19, +0.79] | +1.19 | 0.279 | +0.0001 [+0.0000, +0.0001] | +1.008 (R2 0.987) | +10.55 |
| S5: QQQ outcome and benchmark, 09:25 | 380 (380 dates) | +0.07 [-0.43, +0.58] | +0.29 | 0.784 | +0.0000 [+0.0000, +0.0001] | +1.019 (R2 0.989) | +8.36 |

## Consistency with committed tables

SPY gap (bp): 380 rows with both, max abs difference 2.842e-14; PM at close (pp): 380 rows with both, max abs difference 7.105e-15. Replication panel: SPY gap (bp): 1211 rows with both, max abs difference 2.842e-14; PM at close (pp): 1211 rows with both, max abs difference 7.105e-15.

## Caveats

- Already-seen panels (METHOD.md section 0); see section 8 of METHOD.md.
