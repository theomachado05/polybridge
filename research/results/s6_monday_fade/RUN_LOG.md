# S6 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 01:40:56 | `METHOD.md` and `config.py` committed (`7ef1a8d`) | Before any P&L of the trade was computed |
| 01:42:21 | Runner and tests committed (`180bd62`) | Before the run |
| 01:42 | `python -m s6_monday_fade.run --no-prints` | 1 s. Every variant; the modelled numbers. Sharpe above 3: bug hunt before reporting |
| 01:43 | `python -m s6_monday_fade.run` | 101 s. The same run with the trade-print check on the primary's 180 markets. The numbers in `SUMMARY.md` |
| 01:45 | `python -m s6_monday_fade.report` | `SUMMARY.md`, charts, `capacity.md` |

The two runs use identical rules; the second only adds the print check. No rule was changed after either.

## Data

- **Events:** `research/results/open_options/events.csv` as committed by R3: 5,021 eligible pairs, 1,535 events with
  every measurement and a result. 45 closures with at least one pair, 2025-10 to 2026-09; the last 9 are out-of-sample
  (from 2026-08-03).
- **Half-spread:** measured before the trade was run on the recorder's Polymarket threshold books, 2026-10-03 23:09:48
  to 2026-10-04 00:00:00 UTC: 158 markets, median 4.5 points (quartiles 4.0 to 6.5), median $2.33 at the best price.
- **Trade prints:** Polymarket data API, one request of up to 10,000 prints per market, for the 180 markets the
  primary variant trades.

## Notes

- **V2 equals V0.** The method lets V2 use every pair with valid measurements whatever the closure move. R3's file
  carries the 09:45 measurements only for its events, so no pair was added.
- **Entry time.** Prints are checked within ±10 minutes of 09:45 New York time on the reopening day.

## Sharpe above 3: the pre-registered checks

| Check | Outcome |
|---|---|
| The signal uses only 09:45 prices | Yes (`test_sell_yes_when_polymarket_is_above_the_band_after_costs` and the three tests after it) |
| The result is never an input | Yes |
| Costs on every trade | Yes: 4.5 points of half-spread and the fee on entry |
| R3's filter for the 0.50 placeholder | Applied by R3 at the close and at the open, not at 09:45. 40 of the primary's 187 entries have a 09:45 price between 0.45 and 0.55 |
| The print check | 21 of 187 entries verified. The modelled Sharpe of 4.3 is the unverified entries |

## Tests

`python -m pytest s6_monday_fade/tests -q`: 10 passed.
