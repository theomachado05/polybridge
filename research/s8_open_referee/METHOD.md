# S8: when the stock market reopens and does not confirm the odds, do the odds give the move back? (pre-registered)

**Question.** While stocks and options are shut, the prediction market is the only place a piece of news can be
priced, and S5 found it gives part of an overnight move back once the stock market is open (-2.9 points after a move
of 10 points or more). The stock market's open is the first independent opinion on that move. If the linked ETF or
stock opens **without** moving the way the odds say it should, the odds probably overshot, and the trade is on
Polymarket: sell the overnight move at 09:40 and buy it back at the close. If the asset **does** confirm the move,
there should be nothing to fade.

This file and `config.py` are committed **before the give-back is split by the asset's move and before any P&L of the
trade is computed**. Every rule is fixed. Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- S5 amendment 3 (`research/results/s5_big_moves/reversal.csv`), on the 93 S5 markets, odds only: from 09:29 to the
  close the odds give back 1.55 points after an overnight move of 5 points or more (553 market-days, interval -2.30
  to -0.88) and 2.86 points after 10 points or more (198 market-days, -4.37 to -1.40).
- A round trip on Polymarket costs about 2.0 points on open markets priced between 10% and 90%
  (`research/results/s5_big_moves/pm_cost_snapshot.json`: median spread 1.0 point, median $786 at the best price).
- S5: the linked asset opens where the odds moved (+6.88 bp per point) and does nothing more after the open. S5b:
  inside the session neither side leads by an amount worth trading.
- **Not seen:** the give-back split by what the asset did at the open; any give-back on the S4 markets; any P&L of a
  trade on the odds.

## 1. Markets and links

- **S5 links:** the 220 links on 93 markets that two blind labellers agreed on.
- **S4 links:** the links on S4's markets that the proposer and the blind critic agreed on, on questions classed as
  events, leaving out the markets that motivated S4.
- **Links to SPY are dropped.** Every asset move is measured in excess of β × SPY, which is zero for SPY itself.
- Prices are the ones already in the S4 and S5 caches (5-minute bars, one-minute odds). No new price is pulled.

## 2. The signal, known at 09:35 New York time

For each market on each stock-market session:

- **Overnight move** `x`: the change in the YES price from the previous session's close to 09:29, in points. An odds
  reading is valid for 30 minutes.
- **The asset's vote** `g`: for each linked ticker, the move from the previous close to 09:35 (the close of the first
  five-minute bar) in excess of β × SPY's move over the same span, in bp, multiplied by the link's direction (+1 if
  the asset should rise when YES rises). `g` is the mean over the market's linked tickers that have a first bar.
  β is the 60-session beta used in S4 and S5.
- **Not confirmed:** `sign(x) × g ≤ 0` (the assets did not move the way the odds did). **Confirmed:** `> 0`.
  A market with no linked ticker trading in the first five minutes has no vote and is left out.

## 3. The trade (on Polymarket)

- **When:** the overnight move is at least the variant's threshold, the vote is "not confirmed", and the YES price at
  09:40 is between 5% and 95%.
- **Entry at 09:40:** sell the move. If YES rose overnight, sell YES (buy NO); if it fell, buy YES. 100 contracts.
- **Exit:** at the stock market's close of the same session (primary), at the price then.
- **At most 10 trades a session**, the largest overnight moves first.
- **Prices and costs.** Polymarket's history is a mid price, not a quote. Every fill is moved against the trade by a
  half-spread of **0.5 point** (the median spread of 1.0 point measured on open markets, section 0), and pays the fee
  of 0.04 × P × (1 − P) per contract, at entry and at exit. **2× costs:** the half-spread and the fee doubled.
- **Capital** of a trade: the price paid for the side bought, times 100. The book's capital base is the largest
  capital deployed in one session.
- **Print check.** For every primary entry, public trade prints within 10 minutes of 09:40 at a price at least as
  good as the one assumed, on the side that proves the fill was there (S6's rule). The data API serves only the latest
  20,000 prints of a market, so old entries on busy markets cannot be checked; the share checked is reported.

## 4. Variants (the complete list)

| id | overnight move | vote needed | exit | nights |
|---|---|---|---|---|
| **V0, primary** | 5 points or more | not confirmed | the close | all |
| V1 | 10 points or more | not confirmed | the close | all |
| V2 | 5 points or more | not confirmed | 09:40 of the next session | all |
| V3 | 5 points or more | any vote (the benchmark: what the vote adds) | the close | all |
| V4 | 5 points or more | not confirmed | the close | weekends and holidays only |

Each at 1× and 2× costs. The deflated Sharpe ratio uses 5 trials. The primary is the 5-point rule because the
10-point rule cannot reach 30 out-of-sample trades on this sample.

## 5. Accounting, segments, inference

- **Per trade:** net P&L in points per contract (cents per $1 of face value) and in dollars for 100 contracts.
- **Book:** P&L by session ÷ capital base. Sharpe annualised by 252; maximum drawdown; worst month; turnover.
- **Costs in bp** of the capital of each trade.
- **Capacity:** from the size at the best price measured on open markets.
- **In-sample / out-of-sample:** by session; OOS is the most recent 20% of the 253 sessions. Nothing is fitted.
- **Inference:** mean net P&L per trade with a 95% bootstrap interval resampling **dates** (several markets on one
  date share the news).
- **The test behind the trade, before costs:** the mean change in the odds from 09:40 to the close, signed by the
  overnight move, for "not confirmed" and for "confirmed" mornings, and the difference between them with a date
  bootstrap; at 5 and at 10 points; on all nights and on weekends. Also the change from 09:29 to 09:40 (what happens
  before anyone can act on the vote) and from 09:40 to the next 09:40.
- **Hindsight check:** the links were labelled by models whose knowledge ends in June 2026. The primary is also
  reported on sessions from 2026-07-01 only. The out-of-sample segment lies wholly after that date.
- A Sharpe above 3 starts a bug hunt before anything is reported: the vote uses nothing after 09:35; the entry price
  is the 09:40 reading; costs on both fills; the date clustering.

## 6. Success criterion (primary V0, fixed now)

A pass needs all of: at least 30 OOS trades on at least 10 OOS dates; OOS mean net P&L per trade above zero with a
date-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs; in-sample above zero at 1× costs; and,
over the whole sample, a give-back on "not confirmed" mornings larger than on "confirmed" ones with an interval for
the difference excluding zero. A pass on modelled prices with fewer than half of the entries confirmed by prints is
reported as "passes on modelled prices, not verified", never as an edge. Anything else is a null or "too few
observations" and is reported as that.

## 7. Caveats known in advance

- The historical spread is unknown. The half-spread comes from one snapshot of today's open markets.
- Several markets on one date are often the same news (six Iran questions move together); the date bootstrap allows
  for it, the count of trades overstates the independent bets.
- The links are model judgements. A wrong direction turns a confirming vote into a refusing one.
- Size at the best price is small (hundreds of dollars). Whatever this shows, it is a small trade.

## Outputs

`research/results/s8_open_referee/`: `SUMMARY.md`, `metrics.csv`, `giveback.csv`, `equity_curve.png`, `drawdown.png`,
`trades.csv`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
