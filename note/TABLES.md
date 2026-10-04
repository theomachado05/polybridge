# Tables for the quant note

Written by `research/reproduce.py` (`make reproduce`) from the committed trade lists `research/results/ladder_replay/trades_fresh.csv` (rule as registered) and `research/results/ladder_replay/order_check/trades_fresh.csv` (year-checked), with `ladder_replay.replay.metrics`. Do not edit by hand.

## Date-ladder book: in-sample and out-of-sample, net of costs

| | Rule as registered, in-sample | Rule as registered, out-of-sample | Rule as registered, whole sample | Year-checked, in-sample | Year-checked, out-of-sample | Year-checked, whole sample |
|---|---|---|---|---|---|---|
| Trades | 533 | 117 | 650 | 460 | 102 | 562 |
| Entry dates (New York) | 178 | 43 | 221 | 170 | 41 | 211 |
| Net points per trade | +0.86 | +9.85 | +2.47 | +8.74 | +9.20 | +8.82 |
| 95% interval (dates resampled) | [-3.72, +5.44] | [+5.69, +14.03] | [-1.14, +6.26] | [+6.51, +11.45] | [+4.86, +14.01] | [+6.73, +11.13] |
| Losing trades | 74 | 0 | 74 | 0 | 0 | 0 |
| Total dollars, net | $330 | $297 | $627 | $1,234 | $245 | $1,480 |
| Return on locked capital | 2.1% | 10.9% | 3.4% | 8.2% | 10.4% | 8.5% |
| Annualised return | 24% | 238% | 41% | 99% | 272% | 111% |
| Volatility, annualised | 55.7% | 45.1% | 55.5% | 22.5% | 45.0% | 20.3% |
| Sharpe | 0.31 | 2.87 | 0.42 | 3.68 | 2.86 | 4.20 |
| Months in the Sharpe | 16 (2025-10 to 2027-01) | 6 (2026-07 to 2026-12) | 16 (2025-10 to 2027-01) | 16 (2025-10 to 2027-01) | 6 (2026-07 to 2026-12) | 16 (2025-10 to 2027-01) |
| Worst month | -40.3% (2026-02) | +0.0% (2026-11) | -40.3% (2026-02) | +0.0% (2026-11) | +0.0% (2026-11) | +0.0% (2026-11) |
| Sharpe, resolved trades only | 0.28 (13 months to 2026-10) | 4.01 (4 months to 2026-10) | 0.41 (13 months to 2026-10) | 4.30 (13 months to 2026-10) | 4.12 (4 months to 2026-10) | 5.15 (13 months to 2026-10) |
| Volatility, resolved trades only | 62.2% | 47.3% | 62.0% | 22.7% | 47.2% | 19.7% |
| Worst month, resolved trades only | -40.3% (2026-02) | +5.7% (2026-09) | -40.3% (2026-02) | +1.5% (2026-10) | +5.7% (2026-09) | +2.3% (2026-01) |
| Maximum drawdown | $649 (20.7%) | $0 (0.0%) | $649 (20.7%) | $0 (0.0%) | $0 (0.0%) | $0 (0.0%) |
| Turnover a year | 6.3x | 14.4x | 5.9x | 6.3x | 20.4x | 5.8x |
| Capital put into trades | $15,975 | $2,735 | $18,710 | $15,093 | $2,368 | $17,460 |
| Most capital locked at once | $3,139 | $940 | $3,139 | $2,970 | $572 | $2,970 |
| Median days locked | 9.7 | 4.2 | 7.9 | 6.8 | 3.0 | 5.6 |
| Median trade, contracts | 20 | 10 | 18 | 20 | 10 | 19 |
| Trades not yet resolved | 28 | 11 | 39 | 28 | 11 | 39 |

Definitions: fresh date ladders of `research/ladder_replay/`, 2025-10-01 to 2026-10-04 (end excluded); in-sample is entries before 2026-07-22 (294 days) and out-of-sample is entries from that date (74 days), the cut S11 fixed before this replay; every figure is net of one tick against us on each leg and both taker fees, at min(print sizes, 100) contracts, held to resolution, with the 39 unresolved year-checked trades valued at their guaranteed floor; a point is one cent per contract; the interval is a 2000-draw bootstrap over entry dates (seed 41); return on locked capital = net dollars / capital put into trades; annualised return = net dollars / (capital x days locked / 365); monthly return = net dollars of the trades resolving in a New York month / their capital (0 for a month with no resolution), volatility = its standard deviation x sqrt(12), Sharpe = its mean / standard deviation x sqrt(12) with no risk-free rate, worst month = its minimum, and because an unresolved trade is booked at its floor in the month its market ends, the study's series runs past the run date (4 October 2026) to the month shown, so the "resolved trades only" rows repeat the three figures on resolved trades and stop at the last month with a resolution (they are computed here, not by the study); maximum drawdown = largest peak-to-trough fall of cumulative net dollars by resolution time, in dollars and as a share of the most capital locked at once; turnover = capital put into trades / most capital locked at once, per 365 days of the column's window; **the year-checked run re-derives each rung's year (amendment 5) and was fixed after the registered run and after its losing trades had been seen, so only the registered columns are confirmatory.**
