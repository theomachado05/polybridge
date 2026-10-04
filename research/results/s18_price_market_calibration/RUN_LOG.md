# S18 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 03:40:19 | `METHOD.md` and `config.py` committed (`93d38c1`) | Before any entry price was matched to a result |
| 03:41:32 | Runner, tests and a wording correction in the method committed (`d409b2f`) | Before the run |
| 03:41 | `python -m s18_price_market_calibration.run` | 1.5 s. Calibration and every variant at history mids. "Sell every market" (V4) has a Sharpe near 3: bug hunt before anything is reported |
| 03:42 | The bug hunt | 232 of 1,092 entry prices are within half a point of 50% (152 exactly 0.500); the markets are a median of 2.8 days old at entry |
| 03:43:26 | The first run's outputs and amendment 1 committed (`37c9a0c`) | The bug hunt, and the test at traded prices with its reading, before any print was pulled |
| 03:43 to 03:54 | `python -m s18_price_market_calibration.prints --pull` | 663 s, 3 requests a second, with a guard on the live recorder (no failed fetch). First-weekend prints of 1,092 markets; 39,374 prints kept |
| 03:54 | `python -m s18_price_market_calibration.prints` | The sellers' and buyers' tests. The numbers in `SUMMARY.md` |
| 03:57 | `python -m s18_price_market_calibration.report` | `SUMMARY.md`, charts, `capacity.md` |
| 03:58 | The count of markets left out was split by reason, and the report rebuilt | No test number changed. See "Markets left out" |

No rule was changed after a run. The texts of the wording correction and of amendment 1 first carried the times 03:42
and 03:44; their commits are stamped 03:41:32 and 03:43:26, and the texts were corrected to match.

## Data

- **Markets:** S9's 391 and S15's 871 price markets; 1,232 have a result. 1,092 have an entry (a price reading at the
  start of a weekend, between 2% and 98%, before the market closed): 772 from S15, 320 from S9; 130 events; first
  weekends from 2025-11-01 to 2026-09-26. 26.1% resolved YES; the mean entry mid is 39.1%. A market is a median of
  2.8 days old at its entry and resolves a median of 28 days later.
- **Segments:** by event, in the order of each event's first entry; out-of-sample is the last 26 events, from
  2026-06-27.
- **Prints:** Polymarket data API, up to 20,000 per market, kept only if stamped within 48 hours after the market's
  entry instant.

## Markets left out of the test at traded prices (292 of 1,092)

| Reason | Markets |
|---|---|
| Never traded during its first weekend (every print of the market was served) | 285 |
| First-weekend prints beyond the 20,000 the API keeps | 6 |
| No print served at all, or the request failed | 1 |

Of the 800 checked, 60 have no print inside the window that can be read, 657 have a taker sale of YES and 606 a taker
purchase. The 285 markets that never traded on their first weekend are also the reason the history mid is not a price
there.

## Notes

- **The first summary said the markets left out were "the most heavily traded ones".** That was wrong: only 6 are
  beyond the API's limit. The sentence was corrected when the count was split.
- **Side of a print.** The data API reports the taker's side. A print on the NO token is read as the opposite side
  on YES at one minus its price (tested).
- **The book** in `SUMMARY.md` takes up to 100 contracts per market and never more than the printed size, books P&L
  in the month of the result, and uses as capital base the largest capital locked at one time.
