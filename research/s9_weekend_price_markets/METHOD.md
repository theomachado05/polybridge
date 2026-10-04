# S9: Polymarket's own price markets over the weekend, while the asset is shut (pre-registered)

**Question.** Polymarket lists markets on the price of oil, gold, silver, the S&P 500 and large stocks ("Will WTI hit
$100 in April?"). They trade all weekend. The assets do not: futures stop on Friday evening and reopen on Sunday at
18:00 New York time, stocks and their options reopen on Monday. So from Friday night to Sunday evening these markets
are the only live price of the asset, and they are the closest thing to an option on it that can be traded on a
Saturday.

Two questions follow.

1. **Do they overshoot?** Elsewhere the odds gave back part of a large move once the real market was open (S5, S8).
   If a price market moves over the weekend and the asset then reopens, does the market give the move back? The
   trade: on Sunday at 17:55, five minutes before futures reopen, sell the weekend move; buy it back on Monday at
   09:40.
2. **Do they follow the news markets during the weekend?** When the odds on an oil-linked event (Iran, mostly) move
   on a Saturday, do the oil price markets move with them the same weekend, and is anything left for Monday?

This file, `config.py`, `universe.py` and `universe.json` are committed **before any price of these markets is
pulled**. Every rule is fixed. Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- S5 amendment 3 and S8: event markets give back 2.6 points after an overnight move of 10 points or more, about the
  cost of a round trip. R3 and S6: thin stock-threshold markets show the same pattern, with prices that mostly cannot
  be traded (half-spread 4.5 points, $2 at the best price on a weekend).
- **From the catalogue only** (titles, volumes, dates, fee schedules; `universe.py`): 25 events with at least
  $1,000,000 traded, 391 markets with at least $50,000 each: 212 on crude oil, 87 gold, 49 silver, 35 stocks, 8 S&P
  500. The oil events traded $84 million (March 2026), $61 million (April), $40 million (May). 263 of the 391 markets
  charge takers 0.04 × P × (1 − P); 128 charge nothing.
- **Tonight's live books** (Sat 2026-10-03 22:13 New York time), open markets of the same kind priced between 10% and
  90%, used only to set the half-spread: crude oil median spread 1.0 point (7 markets, median $20 at the best price);
  gold 2.5 points (8); silver 4.0 (10); S&P 500 2.0 (9); stocks 3.5 to 5.0 (54). This month's markets are much smaller
  than last spring's.
- **Not seen:** any historical price of any of these markets.

## 1. Markets

- **Universe:** `universe.json`, built by `universe.py` from Polymarket's catalogue search with the rules in
  `config.py`: events whose title names a price target ("hit", "settle at") for crude oil, gold, silver, the S&P 500
  or one of nine large stocks; event volume at least $1,000,000; market volume at least $50,000. Crypto is left out
  (it never shuts).
- **Sign of a market:** +1 if YES needs a higher price (HIGH, ↑), −1 for a lower one (LOW, ↓), none for a range
  ("settle at $60 to $65").
- **Fee:** the market's own schedule from the catalogue.

## 2. The weekend clock (New York time)

A weekend is a stock-market closure that contains a Saturday and a Sunday (the calendar of SPY sessions already in
the S5 cache).

- **Start:** 20:00 on the last session day before the weekend, when after-hours trading has ended.
- **Entry:** Sunday 17:55, five minutes before futures reopen.
- **Exit:** 09:40 on the next stock-market session (Monday, or Tuesday after a Monday holiday).
- A price reading is valid for 30 minutes. A market is **live** on a weekend if its price at the start is between 10%
  and 90%.
- **Weekend move** `w` = entry price − start price, in points. **Reopen move** `y` = exit price − entry price.

## 3. The trade

- **When:** a live market's weekend move is at least the variant's threshold and its entry price is between 5% and
  95%.
- **Fade (primary):** sell the move at the entry instant (sell YES if it rose, buy YES if it fell), 100 contracts;
  close at the exit instant. **Follow** is the mirror.
- **At most 10 trades a weekend**, the largest weekend moves first.
- **Prices and costs.** Polymarket's history is a mid price. Every fill is moved against the trade by a half-spread:
  crude oil **0.5 point**, S&P 500 1.0, gold 1.25, silver 2.0, stocks 2.5 (half of tonight's median spreads,
  section 0). Each fill pays the market's own fee. **2× costs:** half-spreads and fees doubled.
- **Capital** of a trade: the price paid for the side bought, times 100. The book's capital base is the largest
  capital deployed on one weekend.
- **Print check.** For every primary entry, public trade prints within 10 minutes of the entry instant at a price at
  least as good as assumed, on the side that proves the fill was there (S6's rule). The data API serves the latest
  20,000 prints of a market; the share of entries that can be checked is reported.

## 4. Variants (the complete list)

| id | weekend move | direction | exit | markets |
|---|---|---|---|---|
| **V0, primary** | 5 points or more | fade | next session 09:40 | all |
| V1 | 10 points or more | fade | next session 09:40 | all |
| V2 | 5 points or more | fade | next session 09:40 | crude oil only |
| V3 | 5 points or more | fade | Sunday 19:00, one hour after futures reopen | crude oil, gold, silver, S&P 500 |
| V4 | 5 points or more | follow | next session 09:40 | all |

Each at 1× and 2× costs. The deflated Sharpe ratio uses 5 trials. The primary is the fade because every earlier test
of this kind found a give-back, not a continuation.

## 5. Tests before costs

- **T1, the give-back.** The mean of `y` signed by `w` (negative = the weekend move was given back), after weekend
  moves of 5 and of 10 points or more; all markets, and by asset class; to the next session's 09:40 and to Sunday
  19:00. Intervals resample weekends.
- **T2, the link (crude oil only, signed markets).** `x` = the weekend move, start to entry, in the odds of the
  oil-linked event questions: the S5 and S4 questions whose agreed links name USO, XLE, XOP, XOM, CVX or OXY, each
  signed by its link direction, averaged over the questions priced between 10% and 90% at the start. Through-origin
  slopes, errors clustered by weekend, of
  - the price markets' weekend move (signed by the market's sign) on `x`: do they move together while oil is shut?
  - the price markets' reopen move on `x`: is anything left after the reopen?
- **T3, what the weekend move was worth.** Slope of `y` on `w` (−1 means the whole move was given back, 0 that it
  held).

## 6. Accounting, segments, inference

- **Per trade:** net P&L in points per contract and in dollars for 100 contracts. **Book:** P&L by weekend ÷ capital
  base; Sharpe annualised by 52; maximum drawdown; worst month; turnover. **Costs in bp** of the capital of a trade.
- **Capacity:** the size at the best price on tonight's books, and the printed sizes behind verified entries.
- **In-sample / out-of-sample:** by weekend; OOS is the most recent 20% of the weekends on which at least one market
  is live. Nothing is fitted.
- **Inference:** mean net P&L per trade with a 95% bootstrap interval resampling **weekends** (the strikes of one
  asset on one weekend are one bet).
- A Sharpe above 3 starts a bug hunt before anything is reported: the weekend move uses nothing after Sunday 17:55;
  costs on both fills; whether the mid prices were quotes at all (the print check); whether one weekend carries it.

## 7. Success criterion (primary V0, fixed now)

A pass needs all of: at least 30 OOS trades on at least 5 OOS weekends; OOS mean net P&L per trade above zero with a
weekend-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs; in-sample above zero at 1× costs.
A pass with fewer than half of the entries confirmed by prints is reported as "passes on modelled prices, not
verified", never as an edge. Anything else is a null or "too few observations" and is reported as that.

## 8. Caveats known in advance

- About 45 weekends, and the oil markets of March to June 2026 will carry most of the moves: one theme, one spring.
- The strikes of one asset move together; the count of trades overstates the independent bets.
- A "hit" market that is hit after the reopen jumps to 100%: the fade can lose far more than it can win.
- Half-spreads come from one night of much smaller markets. Historical books are not published.

## Outputs

`research/results/s9_weekend_price_markets/`: `SUMMARY.md`, `metrics.csv`, `tests.csv`, `equity_curve.png`,
`drawdown.png`, `trades.csv`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
