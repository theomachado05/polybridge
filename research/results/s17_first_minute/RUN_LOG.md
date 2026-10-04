# S17 run log

New York time, Sat 2026-10-03 to Sun 2026-10-04.

| Time | Step | Commit |
|---|---|---|
| 23:30 | Theo asks for the first-minute add-on next to S16 ("explore any possible edge"). S16's METHOD read; event rule copied from its section 1 | |
| 23:37 | METHOD.md and config.py committed, before any bar or quote | `6076c4d` |
| 23:39 | One format probe (USO, 2026-09-30: one minute-bar call, one quote; no return computed). Amendment 1: previous close from the same minute-bar call | |
| 23:40 | Runner committed; pull started (Massive, 1.5 requests a second, own cache) | `9d19f18` |
| 23:40 to 00:19 | Pull: 3,432 calls, no failure. 10+ bars 274 s, 10+ quotes 875 s, 5+ bars 1,275 s, 5+ quotes 2,302 s | |
| 23:55 | While the 5+ pull ran, F1 and F2 at 10+ computed once from the cache (no new calls) | |
| 00:19 | Full run crashed on an empty trade table: pandas renamed the `q_09:31_*` columns inside `itertuples`. Fixed (amendment 2); rerun, 3.9 s, 0 new calls | |
| 00:20 | Sharpe 3.88 on T2 at 5+ points out-of-sample: bug hunt (quotes against bars, splits, previous close). No bug; concentration documented | |
| 00:30 | SUMMARY, RUN_LOG, results committed | this commit |

## Data

- Events: `results/s8_open_referee/mornings.csv` (S8), expanded as S16 section 1: 300 ticker-days at 10+ points
  (109 dates; 54 out-of-sample), 808 at 5+.
- One-minute bars: Massive `/v2/aggs/ticker/<T>/range/1/minute/<previous session>/<day>` (adjusted), ticker and SPY.
- Quotes: Massive `/v3/quotes/<T>`, last NBBO at or before 09:31, 10:00, 15:55. Valid entry quotes: 299 of 300 (10+),
  801 of 808 (5+).
- Betas: S4's `engine.betas` on the cached daily bars.
- Cache: `research/s17_first_minute/.cache/` (not committed). No Polymarket or Kalshi call. S16's pull ran at the same
  time at 2 requests a second; this one stayed at 1.5.

## What went wrong

- The `itertuples` column renaming (amendment 2).
- No ticker-day was dropped for bars; 1 (10+) and 7 (5+) for an invalid entry quote.
