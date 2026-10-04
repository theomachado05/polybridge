# S24 run log (New York time)

| When | What |
|---|---|
| Sun 01:40 | Brief, PARALLEL_BRIEF.md and S11's method, code and results read. No `s24_*` folder existed, so the number is 24. |
| Sun 01:45 | Four catalogue probes (page size, date filters, results by market id), counted in the request budget. `fetch failed` lines in the recorder's log: 51. |
| Sun 01:48 | First catalogue run: plain offsets stopped at 2,100 events a query (the catalogue serves no deeper offset). 44 requests; list replaced. |
| Sun 01:49–01:57 | Catalogue read again, restarting below the last volume: 5,998 events for set (a), 37,988 for set (b), 440 requests. Every price field dropped before storing (asserted). |
| Sun 01:58 | Every template shape of the list read (text only). One strike ladder removed by a new text rule ("or lower" against the word "reach"). 22 tests pass. |
| Sun 01:59 | METHOD.md, config.py, the list, engine, pull and run code and tests committed and pushed before any print was pulled: `c5e0b22`. |
| Sun 01:59 | Print pull started: one worker, one request a second at most, the two sets in turns, largest event first. |
| Sun 02:02–02:03 | Format check of the prints of the first 110 markets: counts of sides and outcomes, how many markets hit the 20,000 cap. No detection. |
| Sun 02:04 | Report, audit and notes code and an end-to-end test on made-up prints committed while the pull ran: `eee3a9b`. |
| Sun 02:04 | **A detection smoke test on part of the pull** (127 pairs), written to a scratch folder only: 43 matches at 10 minutes, 34 at 2 minutes, provisional cut dates, seconds between prints, events with the most matches. No result read, no P&L. |
| Sun 02:30 | The coordinator's message arrived: the partner's study `research/ladder_replay` (origin/main `a876979` 02:11, `b57d2a8` 02:21, `4d9ac93` 02:21) found that S11's year rule misdates some rungs, and had seen results on a fresh universe that overlaps this one. Read with `git show` at 02:31. |
| Sun 02:31–02:35 | **Which case applied: prints had already been analysed (the 02:04 smoke test), so the registered test was not changed.** Amendment 1 written: the registered test stands; a secondary analysis (the partner's year check and nesting rule, and an unseen sample without the 58 shared markets) fixed before any result or P&L. Committed and pushed at 02:34:58: `61c05e0`. At that moment the pull was still running, no result had been read and `run detect` had not been run on the full pull. |
| Sun 02:42 | Print pull done in 2,537 s: 662 ladders (all 214 of set a; 448 of set b, 861 left out), 2,392 print requests. Results read for 2,342 rungs (2,275 resolved), 40 requests. `fetch failed` lines in the recorder's log: still 51; no pause was needed. |
| Sun 02:42 | `run detect` on the full pull (prints only): 375 primary trades. Cut dates from the trade dates alone: set (a) from 2025-09-11, set (b) from 2026-07-18. `secondary` classified the 161 pairs that traded from catalogue texts (7 requests, 273 markets) and compared the `outcome` text with the token on one market (9,450 prints, no disagreement). |
| Sun 02:42:36 | Cut dates, matches, coverage and pair verdicts committed and pushed **before any P&L was computed**: `e10f593`. |
| Sun 02:42:40 | `run settle`: first P&L. 86 of 375 primary trades resolved with the ladder's order violated. |
| Sun 02:43–02:50 | The 11 pairs behind those 86 trades read one by one, with their descriptions. Two faults in S11's ladder rules: the year of a rung (8 date pairs, 61 trades; the partner's finding) and the word "reach" used for levels below the price (3 strike pairs, 25 trades; new). Every pair that traded was then read (161 pairs). |
| Sun 02:45 | Amendment 2, post hoc: a direction check from the descriptions (`secondary direction`, no request), written to its own file so the files committed in `e10f593` stay as they were. |
| Sun 02:51 | Audit, report, tests (26 pass, exit code 0). SUMMARY.md written by `report.py` from the result files. Results committed and pushed: `3a482a3`. |
| Sun 02:53 | After the commit: the pooled means and intervals recomputed from `trades.csv` by separate code (they match `metrics.csv`), three trades checked by hand, the split rule and the pull order verified. Run log regenerated; this commit. |

## Commits (from `git log`, oldest first; the commit that carries this file is not in its own list)

- `c5e0b22` Sun 01:59 S24 (the ladder trade on fresh ladders): pre-registered METHOD, config, ladder list built from catalogue text by S11's rules (set a: 214 ladders listed 2024-01-01 to 2025-09-30 at $50,000+; set b: 1,309 ladders in S11's year at $10,000 to $50,000; every S11 market removed), engine, pull and run code, 22 tests. Committed before any print of these markets is pulled
- `eee3a9b` Sun 02:04 S24: report, audit and notes code and an end-to-end test on made-up prints, written while the print pull runs and before any print is analysed; no rule changed
- `61c05e0` Sun 02:34 S24 amendment 1 (02:35): the partner's ladder replay became known at 02:30, after a detection smoke test on part of the pull (02:04, match counts only) and before any result or P&L. The registered test is not changed. A secondary analysis is fixed here: the partner's rung-year check and nesting rule as written, and an unseen sample without the 58 markets its fresh universe shares with set (a). Code, the partner's market list and 2 tests
- `e10f593` Sun 02:42 S24: prints pulled (662 ladders: all 214 of set a, 448 of 1,309 of set b; 2,392 print requests, 2,927 in all). Detection from prints: 375 primary trades. Out-of-sample cut dates fixed from the trade dates alone, before any P&L: set a from 2025-09-11 (160 trade dates), set b from 2026-07-18 (67 trade dates). Pair verdicts of the secondary corrected rule (texts only). No result has been used and no P&L computed
- `3a482a3` Sun 02:51 S24 result: not a pass. Under S11's own rules the ladder trade on fresh ladders made -2.56 points per trade [-6.51, +1.27] on 375 trades on 226 dates (-4.78 at 2x; in-sample -4.46 [-9.05, -0.18]; out-of-sample +5.70 [-1.50, +13.31] on 70 trades). 86 trades resolved with the ladder's order violated, all on 11 wrongly built pairs: the rung year (8 date pairs, 61 trades, the partner's finding) and 'reach' used for levels below the price (3 strike pairs, 25 trades, new). Secondary, fixed before any result (amendment 1): corrected rule on the unseen sample +7.12 [+3.07, +11.11] on 193 trades, out-of-sample +14.47 [+0.56, +30.72] on 28 trades, +4.80 at 2x. Post hoc direction check (amendment 2): +8.14 [+3.74, +12.17] on 160 trades, no order violation, 27 out-of-sample trades; the profit is 12 payouts of $1 and $425 at the cap. SUMMARY, metrics, trades, curves, capacity, audit and run log written by report.py

## Requests (one worker, at most one a second; `.cache/requests.json`)

- In all: **2927** of 3000. By kind: probe 4, catalogue 484, prints_a 967, prints_b 1425, results 40, texts 7.
- Prints: set (a) 967 requests, set (b) 1425. The pull stopped by: budget or end of list.
- Recorder check: `fetch failed` lines in `research/forward/recorder.log` before the pull: 51; at the end: 51. Pauses taken: 0.

## Data sources

- Catalogue: `gamma-api.polymarket.com/events` (by event volume, two start-date windows) for the lists; `gamma-api.polymarket.com/markets?id=...&closed=true` for the results.
- Prints: `data-api.polymarket.com/trades`, `market=<conditionId>`, `limit=10000`, `offset=0` and `10000` (S11's call).
- No one-minute price history. No Kalshi call. No key used or printed.

## Things that went wrong or limit the result

- The freshness claim of METHOD.md section 1 failed for 58 markets: the partner's study analysed them (set (a), 20 date ladders, 38 pairs) between 02:00 and 02:21, while this study's pull ran. Results are shown with and without them.
- A detection smoke test was run on part of the pull at 02:04, before the partner's finding was known. It showed match counts only, but it means the corrected rule could not be registered as this study's test. It is a secondary analysis, fixed before any result or P&L (`61c05e0`).
- S11's rules built wrong ladders on fresh markets (the count is in SUMMARY.md). The registered test is reported as registered; the corrected rows are secondary (the partner's rule) or post hoc (the direction check).
- The descriptions and sources were read only for the pairs that traded, so the nesting rule's count over the whole list is unknown.
- The first catalogue run stopped at 2,100 events a query (offset cap) and cost 44 requests.
- Both catalogue queries stopped at their page cap: events under $289,305 (set a) and $169,507 (set b) of volume were never read.
- 861 of set (b)'s 1,309 ladders (2,946 of 3,922 pairs) were not pulled: the print budget ran out. Set (a): 0 left out.
- 21 pulled pairs have a rung with 20,000 or more prints; their earlier life could not be checked.
- 86 of 375 registered trades resolved with the ladder's order violated.
- 7 registered trades have a rung still open tonight; they are booked at their entry edge alone.
