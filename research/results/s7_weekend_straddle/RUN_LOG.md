# S7 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 01:47 | Count of flagged ticker-weekends from odds and the calendar only | 187 at 4 points, 339 at 2 points, 254 with the narrower odds band; no equity or option price read |
| 01:49:16 | `METHOD.md` and `config.py` committed (`8b4e914`) | Before any option price was pulled |
| 01:50:43 | Runner and tests committed (`ba4564d`) | Before any option price was pulled |
| 01:51 | `python -m s7_weekend_straddle.run` | 137 s. 625 trades planned, 505 with all four quotes. The numbers in `SUMMARY.md` |
| 01:53 | `python -m s7_weekend_straddle.report` | `SUMMARY.md`, charts, `capacity.md` |

The run was made once. No rule was changed after it.

## Data

- **Links and odds:** S5's 220 links and its cached Polymarket histories (`research/s5_big_moves/`).
- **Weekends:** 55 weekend and holiday closures, Fridays 2025-10-03 to 2026-09-25; the last 11 are out-of-sample (from
  2026-07-17).
- **Options:** Massive reference contracts (first listed expiry on or after the Friday one week later) and NBBO quotes
  (`/v3/quotes`) at Friday 15:55 and Monday 09:45 New York time, through `research/arb/arbscan/datasrc.py`. No request
  failed.
- **Underlying:** the five-minute bars of S5's cache: the 15:30 price for the strike, the Friday close and the Monday
  open for the size of the move.

## Trades dropped (120 of 625)

| Reason | Trades |
|---|---|
| No valid call quote on Friday (no bid, or older than 10 minutes) | 50 |
| No underlying price in the cache (a linked ticker whose bars were not pulled for that date) | 32 |
| No valid put quote on Friday | 24 |
| No valid call quote on Monday (must be stamped after 09:30) | 7 |
| No valid put quote on Monday | 7 |

## Checks

- `python -m pytest s7_weekend_straddle/tests -q`: 7 passed (the flag uses only the five nights ending on the Friday;
  controls are matched once; the straddle buys at the ask and sells at the bid; 2× doubles every half-spread and
  commission).
- No Sharpe ratio above 3: every variant's Sharpe is strongly negative, which is what paying two option spreads every
  weekend looks like. The mid-to-mid return, which has no costs in it, is about −1% for flagged and −2% for control
  straddles: Friday's option prices were not too low.
