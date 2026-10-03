# Macro-panel run log

One entry per invocation of `python -m macro_panel.run`: code commit, stage reached, wall time, network requests (cache hits not counted), exit status.

## 2026-10-03 21:50:29Z
- code commit: `2f19407` (METHOD.md pre-registered at `bb3ca5f`)
- stage reached: selection
- wall time: 12 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: froze 70 eligible markets to markets.json; commit it, then run again
- exit: 0

## 2026-10-03 21:51:00Z
- code commit: `5840d54` (METHOD.md pre-registered at `bb3ca5f`)
- stage reached: equity
- wall time: 86 s
- network requests: Polymarket CLOB 2612, Massive 0 (cached responses are not counted)
- result: ready, needs MASSIVE_API_KEY: 36 markets, 2609 PM-quoted rows; stopped before any equity request
- exit: 2

## 2026-10-03 21:54:24Z
- code commit: `e2a9bcd` (METHOD.md pre-registered at `bb3ca5f`)
- stage reached: equity
- wall time: 3 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: ready, needs MASSIVE_API_KEY: 36 markets, 2609 PM-quoted rows; stopped before any equity request
- exit: 2

## 2026-10-03 22:10:07Z
- code commit: `e2a9bcd` (METHOD.md pre-registered at `bb3ca5f`)
- stage reached: analysis
- wall time: 277 s
- network requests: Polymarket CLOB 0, Massive 17 (cached responses are not counted)
- result: 36 markets, 2609 of 2612 rows usable (353 dates); b = +0.81 bp/pp [-0.14, +1.76], clustered t = +1.67, date-perm p = 0.0535; verdict: does not hold; macro - geo d = +0.08 [-1.35, +1.52] (no difference shown)
- exit: 0
