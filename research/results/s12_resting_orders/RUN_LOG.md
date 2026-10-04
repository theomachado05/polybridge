# S12 run log

All times New York, Sat 2026-10-03.

| Time | Step | Commit |
|---|---|---|
| 22:42 | Read PARALLEL_BRIEF.md, S8 and S9 summaries, their trades/mornings/weekends files (no prints) | |
| 22:45 | METHOD.md and config.py committed and pushed, before any print was pulled | `d0c680e` |
| 22:48 | Runner and tests committed (12 tests pass), before any print was pulled | `e2cc281` |
| 22:48 to 22:51 | First pull: prints for 174 S9 markets, deadline mids for S9's 120-minute window | |
| 22:52 | Bug found: all 60 S8 markets served 0 prints (missing condition id read as NaN, so the gamma lookup was skipped). Fixed, S8 print files deleted, S8 pulled again (about 3 minutes). Amendment 1 | |
| 22:54 | First run (2 seconds). Checks: one fill traced by hand against its raw prints (sale at 0.52 filled by three taker buys at 0.525 after 6.1 minutes); gross ≥ mid-to-mid on every filled order; 9 rows with a missing 120-minute deadline mid (5 orders, weekend of 2026-04-20, R1/R3 only). Amendment 2 | |
| 22:55 | capacity.md wording corrected (it stated something the data does not show); rerun; results committed | `2306efb` |
| 23:05 to 23:20 | METHOD.md amendments, SUMMARY.md (tables generated from metrics.csv and criterion.csv), this log | this commit |

## Data sources

- Orders: `results/s9_weekend_price_markets/trades.csv` (V0, 1×: 307), `weekends.csv` (fees);
  `results/s8_open_referee/mornings.csv` (|move| ≥ 10 points, 09:40 price in [0.05, 0.95]: 221).
- Prints: `https://data-api.polymarket.com/trades?market=<condition>&takerOnly=true`, two pages of 10,000, at
  3 requests a second. S9 condition ids from `s9_weekend_price_markets/universe.json`; S8 from gamma
  `/markets/<id>`. Only prints within 120 minutes after an entry or an exit kept, in
  `research/s12_resting_orders/.cache/` (5.3 MB, not committed).
- Reach: 301 of 307 S9 orders and 80 of 221 S8 orders had prints back to their entry instant.
- Deadline mids: S8 from the S4/S5 one-minute caches; S9 from S9's weekend cache, and for the 120-minute deadline
  from `clob.polymarket.com/prices-history` (one window per S9 market-weekend).
- No Kalshi calls. No Massive calls. The forward recorder was not touched.

## What went wrong

- The S8 condition-id bug above (fixed before any result was computed).
- The one-minute history has a gap on Monday 2026-04-20 after 09:40: 5 S9 orders use the exit mid instead of the
  120-minute deadline mid (variants R1 and R3 only).
- Commits carry the co-author line the brief asks for.
