# Closed-market lead-lag run log

One entry per run of `python -m leadlag_closed.run`: code commit, wall time, network requests, exit status. Cached responses are not counted (the cache is gitignored, so a fresh clone repeats the cold run).

## 2026-10-03 08:44:38Z
- code commit: `b2106b4`
- mode: fetch + analysis
- wall time: 274 s
- network requests: Polymarket CLOB 398, Massive 42 (cached responses are not counted)
- result: 17 of 17 events usable, 380 of 380 placebo closures usable; verdict: mixed
- exit: 0

## 2026-10-03 08:51:01Z
- code commit: `b2106b4` + uncommitted changes in leadlag_closed/
- mode: fetch + analysis
- wall time: 101 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 17 of 17 events usable, 380 of 380 placebo closures usable; verdict: mixed
- exit: 0

## 2026-10-03 08:53:10Z
- code commit: `b2106b4` + uncommitted changes in leadlag_closed/
- mode: re-analysis of saved CSV
- wall time: 2 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 17 of 17 events usable, 380 of 380 placebo closures usable; verdict: mixed
- exit: 0

## 2026-10-03 08:58:34Z
- code commit: `20f3a9c` + uncommitted changes in leadlag_closed/
- mode: re-analysis of saved CSV
- wall time: 2 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 17 of 17 events usable, 380 of 380 placebo closures usable; verdict: mixed
- exit: 0
