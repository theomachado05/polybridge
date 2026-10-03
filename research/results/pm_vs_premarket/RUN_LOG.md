# T2 run log

One entry per invocation of `python -m pm_vs_premarket.run`: code commit, arms run, wall time, network requests (cached responses not counted), exit status.

## 2026-10-03 21:51:17Z
- code commit: `9a98f82`
- wall time: 4 s
- network requests: Polymarket CLOB 0, Massive 0
- arm K: c = -0.60 bp/pp, t -0.57, p 0.573, n 379; no evidence that the PM adds information beyond the benchmark
- arm M not run: MASSIVE_API_KEY missing (ready, needs MASSIVE_API_KEY)
- exit: 2

## 2026-10-03 21:54:24Z
- code commit: `f1d87e3`
- wall time: 912 s
- network requests: Polymarket CLOB 1592, Massive 50
- arm K already run (.done present), skipped
- arm M (SPY): c = +0.17 bp/pp, t +0.82, p 0.439, n 380; no evidence that the PM adds information beyond the benchmark
- exit: 0
