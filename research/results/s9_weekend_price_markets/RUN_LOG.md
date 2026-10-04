# S9 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 02:13:52 | Live books of the open price markets read once, to set the half-spreads | 321 two-sided books, 196 priced between 10% and 90%. Crude oil: median spread 1.0 point on 7 markets, median $20 at the best price. No historical price read |
| 02:15:51 | `python -m s9_weekend_price_markets.universe` (catalogue only) | 2,128 events seen, 371 match the title rule, 25 kept (volume of $1,000,000 or more), 391 of their 594 markets kept (volume of $50,000 or more) |
| 02:16:31 | `METHOD.md`, `config.py`, `universe.py`, `universe.json` committed (`6e1876a`) | Before any price of these markets was pulled |
| 02:18:56 | Amendment 1 committed (`deb2e65`); `universe.py --outcomes` | Settlement rule for markets that resolve during the trade. 384 of 391 markets have a result, 94 resolved YES. Still no price pulled |
| 02:21:09 | Runner and tests committed (`ee0049f`) | Before any price was pulled |
| 02:21 to 02:27 | `python -m s9_weekend_price_markets.run --pull` | 364 s. 391 markets, 376 with prices inside weekend windows, 10,677,480 one-minute points kept, 0 failures |
| 02:27 | `python -m s9_weekend_price_markets.run --no-prints` | The tests and every variant on modelled prices. No Sharpe above 3 |
| 02:28 to 02:35 | `python -m s9_weekend_price_markets.run` | 482 s. The same run with the print check on the primary's 174 markets. The numbers in `SUMMARY.md` |
| 02:37 | `python -m s9_weekend_price_markets.report` | `SUMMARY.md`, charts, `capacity.md` |

The two runs use identical rules; the second only adds the print check. No rule was changed after either.

## Data

- **Universe:** 25 events, 391 markets: 212 crude oil, 87 gold, 49 silver, 35 stocks, 8 S&P 500. 263 charge takers
  0.04 × P × (1 − P); 128 charge nothing.
- **Weekends:** 52 in the calendar from 2025-10-01 to 2026-10-02 (SPY sessions of the S5 cache); 44 have at least one
  live market, from the weekend before 2025-11-03 to the one before 2026-09-28. Out-of-sample is the last 9, from
  2026-08-03.
- **Market-weekends:** 1,054 on 253 markets; 401 with a weekend move of 5 points or more, 201 with 10 or more. No
  trade was dropped for want of an exit price; 4 primary trades were settled at the market's result (amendment 1).
- **Oil-linked event odds (T2):** 44 questions from the S5 and S4 caches; 36 weekends have both those odds and a live
  signed oil price market.
- **Trade prints:** up to 20,000 per market for the 174 markets the primary trades; 5 hit that limit; 1,137 prints
  within 10 minutes of an entry kept on disk. 295 of the 307 primary entries could be checked, 62 are confirmed.

## Notes

- **A test fixture was wrong, not the code.** The first version of the calendar test listed sessions that were not
  consecutive; corrected before the runner was committed.
- **A warning at build time** ("mean of empty slice") comes from weekends on which no oil-linked question was
  priced between 10% and 90%; those weekends have no T2 observation.
- **Looked at after the run** and labelled so in `SUMMARY.md`: the split by the direction of the weekend move, and
  the average drift of all live markets (-1.05 points from Sunday 17:55 to Monday 09:40).

## Limits

- Half-spreads come from one night of markets far smaller than last spring's.
- 20% of the primary entries have a print at the assumed price within 10 minutes: Sunday at 17:55 is a thin moment.
