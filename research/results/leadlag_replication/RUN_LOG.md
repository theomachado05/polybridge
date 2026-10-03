# Overnight-gap replication run log

One entry per run of `python -m leadlag_replication.run`: code commit, wall time, network requests (cache hits not counted; the cache is gitignored), exit status.

## 2026-10-03 16:43:21Z
- code commit: `5423df1` + uncommitted changes in leadlag_replication/ (METHOD.md pre-registered at `7a780b5`)
- mode: fetch + analysis
- wall time: 537 s
- network requests: Polymarket CLOB 1212, Massive 72 (cached responses are not counted)
- result: 10 markets, 1211 of 1212 rows usable (492 dates); b = +0.63 bp/pp, HC3 t = +1.20, date-perm p = 0.1262; sign 310/620 p = 1.000; verdict: does not replicate
- exit: 0

## 2026-10-03 16:53:10Z
- code commit: `2068ed5` + uncommitted changes in leadlag_replication/ (METHOD.md pre-registered at `7a780b5`)
- mode: re-analysis of saved CSV
- wall time: 3 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 10 markets, 1211 of 1212 rows usable (492 dates); b = +0.63 bp/pp, HC3 t = +1.20, date-perm p = 0.1262; sign 310/620 p = 1.000; verdict: does not replicate
- exit: 0
