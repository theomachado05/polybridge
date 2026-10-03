# Closed-market hedge run log

One entry per run of `python -m closed_hedge.run`: code commit, wall time, network requests, exit status.

## 2026-10-03 16:52:47Z
- code commit: `2068ed5`
- mode: live books + analysis of the saved closure panel
- wall time: 19.2 s
- network requests: gamma 1, CLOB /book 100; Massive 0; no 8-K or option data
- PM half-spread: 0.050 pp from 21 books
- replication panel: not available (results.csv not committed when this study ran)
- result: hedge A no evidence, hedge B reduces the loss variance, B 08:00 partial; n = 346 of 380
- exit: 0

## 2026-10-03 16:54:29Z
- code commit: `0d24380` + uncommitted changes in research/closed_hedge/
- mode: report re-render from saved results.json and closures_hedged.csv (METHOD.md Amendment 1); no fetch, no refit, primary numbers unchanged
- wall time: 0.1 s
- network requests: none
- exit: 0

## 2026-10-03 16:54:37Z
- code commit: `0d24380` + uncommitted changes in research/closed_hedge/
- mode: report re-render from saved results.json and closures_hedged.csv (METHOD.md Amendment 1); no fetch, no refit, primary numbers unchanged
- wall time: 0.1 s
- network requests: none
- exit: 0

## 2026-10-03 16:54:44Z
- code commit: `0d24380` + uncommitted changes in research/closed_hedge/
- mode: report re-render from saved results.json and closures_hedged.csv (METHOD.md Amendment 1); no fetch, no refit, primary numbers unchanged
- wall time: 0.1 s
- network requests: none
- exit: 0
