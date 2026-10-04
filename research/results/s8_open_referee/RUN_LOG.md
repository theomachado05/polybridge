# S8 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 02:02:33 | `METHOD.md` and `config.py` committed (`1cb7cb3`) | Before the give-back was split by the asset's vote and before any P&L of the trade |
| 02:04:39 | Runner and tests committed (`f1c15fd`) | Before the run |
| 02:04 | `python -m s8_open_referee.run --no-prints` | A few seconds. The give-back table and every variant on modelled prices. No Sharpe above 3 (all negative) |
| 02:05 | `python -m s8_open_referee.run` | 225 s. The same run with the trade-print check on the primary's 62 markets. The numbers in `SUMMARY.md` |
| 02:09 | `python -m s8_open_referee.report` | `SUMMARY.md`, charts, `capacity.md` |

The two runs use identical rules; the second only adds the print check. No rule was changed after either. After the
first report the sentence about the differences whose interval excludes zero was corrected from "one of twelve" to a
count taken from `giveback.csv` (two of twelve); no number changed.

## Data

- **Prices:** nothing new was pulled. Odds (one-minute Polymarket history) and five-minute bars come from the S5 cache
  (`research/s5_big_moves/.cache`, window 2025-10-01 to 2026-10-02) and the S4 cache (`research/s4_linked_assets/.cache`,
  window 2026-01-02 to 2026-10-02).
- **Links:** 254 links on 128 markets and 48 tickers: S5's 220 agreed links without its 18 SPY links (202), and 52 S4
  links that the proposer and the blind critic agreed on, on event questions, without the motivating markets and
  without SPY.
- **Sessions:** 253, from 2025-10-01 to 2026-10-02; 55 follow a weekend or holiday. Out-of-sample is the last 51, from
  2026-07-23.
- **Mornings:** 667 market-mornings follow an overnight move of 5 points or more (554 on S5 markets, 113 on S4 markets),
  233 a move of 10 points or more. Every one had at least one linked ticker trading in the first five minutes.
- **Trade prints:** Polymarket data API, up to 20,000 prints per market, for the 62 markets the primary trades. 46 of
  the 62 hit that limit, so their older entries cannot be checked. Only prints within 10 minutes of an entry are kept
  on disk.

## Checks made on the run

- **The frame reproduces S5 amendment 3.** On S5 markets only, from 09:29 to the close: -1.555 points on 553 mornings
  after 5 points or more, and -2.860 on 198 after 10 points or more, the figures in
  `research/results/s5_big_moves/reversal.csv`.
- **No look-ahead.** The overnight move is read at 09:29, the asset's vote uses the bar from 09:30 to 09:35, the entry
  price is the 09:40 reading. Tests pin each step.
- **Costs.** 2.62 points per round trip on average: 1.0 point of spread and the fee of 0.04 × P × (1 − P) at entry and
  at exit. The median P × (1 − P) of these mornings is 0.21, higher than on the snapshot's markets, which is why the
  cost is above the snapshot's 2.0 points.

## Limits

- The spread is one snapshot of today's open markets, not the spread on the mornings traded.
- 65 of the 198 primary entries are recent enough to be checked against prints; 33 are confirmed.
