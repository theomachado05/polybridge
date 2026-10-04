# S16 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 03:33 | Counts of large overnight moves in Kalshi's quoted mids, and the quoted spread at 09:40 | No outcome computed. 104 market-sessions at 5 points with a 6-hour quote, 50 with 30 minutes; median spread 1 cent |
| 03:34:13 | `METHOD.md` and `config.py` committed (`f7ce87e`) | Before any give-back or P&L was computed on Kalshi's quotes |
| 03:35:40 | Runner and tests committed (`83ef560`) | Before the run |
| 03:35 | `python -m s16_kalshi_quotes.run` | 1.5 s. K1, K2 and every variant of the trade |
| 03:36:19 | Amendment 1 committed (`31c20aa`): K3, the mirror of K2 | After the first run, before K3 was computed |
| 03:36 | `python -m s16_kalshi_quotes.run` | The same run with K3 added. K1, K2 and the trade are unchanged |
| 03:37 | `python -m s16_kalshi_quotes.report` | `SUMMARY.md`, charts, `capacity.md` |

No rule was changed after a run. The amendment's text first carried the time 03:37; the commit is stamped 03:36:19
and the text was corrected to match.

## Data

- Nothing was pulled. S1's cache: one-minute Kalshi candles (closing best bid and ask) of 33 markets and the
  one-minute Polymarket history of their twins. 31 markets have at least one session with an overnight reading.
- 249 sessions from 2025-10-07 to 2026-10-02; out-of-sample is the last 50, from 2026-07-24. Most twins began to
  trade on both venues in 2026, so most market-sessions fall out-of-sample.
- 2,886 market-sessions with a 6-hour quote rule, 1,038 with the 15-minute rule.

## Notes

- **The quote in force.** The count made before the commit dropped one-sided candles first and then took the last
  remaining quote. The run takes the last candle at or before the instant and uses it only if it is two-sided, so a
  later one-sided candle cancels an earlier quote. That is why the primary has 98 trades and 5 dropped for want of an
  exit quote, against the 104 counted.
- **Fee multiplier:** 1.0 for every market in the sample.
- **Spread:** 1.0 point at the median over 2,211 market-sessions priced between 5% and 95% at 09:40; on the 98
  sessions the primary trades, median 5.0 points and mean 10.5.
