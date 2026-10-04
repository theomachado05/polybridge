# S20 run log

All times UTC, 2026-10-04 (Sunday 00:13 to about 01:00 in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 04:13 to 04:19 | Read the brief, S18's method, code and summary. From result times and the session calendar only (no print), counted which markets are open in each window | The briefed exclusion rule removes 113 open-week markets, 94% of them YES. A second rule with no look-ahead (rule B) was written into `METHOD.md` before the pull |
| 04:19:28 | `METHOD.md`, `config.py`, `windows.py` committed (`04fc9c7`) and pushed | Before any print outside S18's first weekend was pulled |
| 04:20:15 | `pull.py` committed (`e692305`) | Before the pull |
| 04:20:21 to 04:39:40 | `python -m s20_closed_vs_open.pull` | 1,159 s. One worker, 1,090 requests for 1,078 markets (0.94 a second on average, never more than one a second). 99,177 prints kept, only those inside D1 and W2. Cache 12 MB. No failed request, no retry pass needed |
| the same | Guard on the live recorder (read only) | `fetch failed` lines in `forward/recorder.log`: 51 before, 51 at every check (every 10 requests), 51 after. The guard never tripped. The recorder was still writing at 04:45 |
| 04:24:05 | `run.py` and the tests committed (`f358817`); 10 tests pass | While the pull ran. No pulled print had been read |
| 04:26 | A mechanical trial of `run` and `report` on the partial cache, output discarded | Only the exit codes were read, and the flag that W1 under rule B returns S18's numbers. No estimate was looked at. The files were overwritten by the real run |
| 04:27 | An integrity test of the cache was added (`test_cached_prints_lie_inside_their_windows`) | Committed with the results |
| 04:44 | `python -m pytest s20_closed_vs_open/tests -q` | 11 passed, exit code 0. Separately counted: 0 of the 99,177 kept prints is stamped after its market's result |
| 04:44:24 | `python -m s20_closed_vs_open.run` | 2.5 s. W1 under rule B returns S18's committed numbers to the last digit (buyers -8.87 on 606 markets, sellers +3.63 on 657, sellers' book +$2,171, Sharpe 1.53) |
| 04:45 to 04:52 | Some books have a Sharpe above 3: bug hunt. `python -m s20_closed_vs_open.after`, then `python -m s20_closed_vs_open.report` | No bug found; see "Looked at after the run" in `SUMMARY.md`. Headline numbers cross-checked from `trades.csv` by a separate calculation (means, the three book P&Ls, T3, and T1's interval with another seed: -5.8 to -0.9 against -5.51 to -1.01) |
| 04:52 | Amendment 1 written into `METHOD.md` (after the run; no rule changed) | A bias the method missed, the looks made after the run, the extra output files |

The commit that holds these results is named in the session's report and in `git log -- research/results/s20_closed_vs_open`.

## Data

- **Markets:** S18's 1,092 (`results/s18_price_market_calibration/entries.csv`), 130 events, read only. In-sample and
  out-of-sample as S18 split its events (out-of-sample: the last 26 events, from 2026-06-27).
- **W1 prints:** S18's cache (`s18_price_market_calibration/.cache/`), read only: 39,374 prints in 740 markets.
- **D1 and W2 prints:** Polymarket data API (`https://data-api.polymarket.com/trades`, `market`, `limit` 10,000,
  `offset` 0 then 10,000), for the 1,078 markets still open at their D1 start. 1,065 markets have fewer than 10,000
  prints in all (one request served everything); 7 have 10,000 to 19,999; 6 hit the 20,000 the API keeps.
- **Calendar:** SPY's sessions on disk (2025-10-01 to 2026-10-02), as S9 and S18. D1 has five sessions for 779
  markets and four (a holiday week) for 313. Two early closes (2025-11-28, 2025-12-24) end at 13:00.
- **No Kalshi call. No other source. No key was read or printed.**

## Markets per window (from `counts.csv`)

| Rule | Window | Counted | Events | With a taker purchase (events) | With a taker sale (events) | Left out: resolved | Left out: beyond the API's 20,000 prints | Left out: window not over at the pull | Left out: no print served |
|---|---|---|---|---|---|---|---|---|---|
| B | W1 | 1,085 | 130 | 606 (97) | 657 (101) | 0 | 6 | 0 | 1 |
| B | D1 | 1,073 | 130 | 859 (121) | 888 (122) | 14 | 5 | 0 | 0 |
| B | W2 | 936 | 121 | 663 (110) | 732 (110) | 150 | 3 | 3 | 0 |
| A | W1 | 1,083 | 130 | 604 (97) | 655 (101) | 2 | 6 | 0 | 1 |
| A | D1 | 960 | 128 | 751 (120) | 793 (120) | 127 | 5 | 0 | 0 |
| A | W2 | 913 | 114 | 655 (105) | 726 (107) | 173 | 3 | 3 | 0 |

## What went wrong, and what could not be verified

- **The verdict is not read from the briefed exclusion rule.** The brief's rule (A) uses the future and strips the
  open week of its winning tickets. Rule B was fixed in `METHOD.md` before the pull; both are reported everywhere.
  Under rule A, T1 does not hold (-0.82, interval -3.35 to +1.65); under rule B it does (-3.22, -5.51 to -1.01).
- **A bias the method missed.** T3's second comparison (W2 against D1 on the same markets) keeps only tickets that
  were not hit during the week, under either rule. Its negative sign is not evidence. Recorded in amendment 1.
- **Two of my own wait loops matched their own command line and never ended.** About four and a half minutes were
  lost between the end of the pull (04:39:40) and the run (04:44:24). I stopped them. They touched no data and
  nothing of the recorder's.
- **Written after the results were seen:** the answer text in `report.py`, `after.py`, and the charts' layout. They
  change no rule and no test number. Everything from `after.py` is under "Looked at after the run".
- **Not verified:** that the API's `side` is the taker's side (taken from S18, which tested the conversion to YES
  terms, not the API's claim). The time a market was actually hit: the study uses the time the market closed, which
  can lag the hit, so D1 holds some prints near 99% made after a hit. Whether a price a taker sold at could have
  been had for more size than printed.
- **Small segments.** Out-of-sample is 19 to 26 events per window; a Sharpe on its four months is not a measurement.
