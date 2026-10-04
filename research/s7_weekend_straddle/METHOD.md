# S7: are options too cheap on Friday when the prediction market shows a live event? (pre-registered)

**Question.** Options cannot trade from Friday's close to Monday's open. Prediction markets can, and S5 showed that a
linked ETF or stock opens on Monday where the odds moved over the weekend (+125 bp after a 10-point move). The gap
itself cannot be traded, but it can be owned in advance: a straddle bought at Friday's close gains from a large move
in either direction. If Friday's option prices do not allow for the event the prediction market is pricing, then
straddles bought on Fridays when the odds are live should beat straddles bought on ordinary Fridays, and should pay
for their own spread.

This file and `config.py` are committed **before any option price is pulled for S7**. Every rule is fixed. Changes go
under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- S5 (`research/results/s5_big_moves/SUMMARY.md`): the opening-gap relation and its size by theme; nothing follows
  after the open.
- A count made from odds and the calendar only, with no equity or option price: 55 weekend and holiday closures in the
  window; the flag below selects 187 ticker-weekends at 4 points, 339 at 2 points and 254 with the narrower odds band.
- **Not seen:** any option price for these tickers on these dates, and whether the Friday flag says anything about the
  size of the weekend move.

## 1. The flag (known at Friday's close)

- **Links:** the 220 links of S5 (two blind labellers agreed on ticker and direction), 27 tickers.
- A ticker is **flagged** on a Friday when at least one of its linked questions has
  1. odds at the close between 10% and 90%, and
  2. a mean absolute overnight move of at least **4 points** over the five sessions ending that Friday (at least
     three of the five nights observed).
- Only odds up to Friday 16:00 New York time enter the flag. Nothing from the weekend does.

## 2. The trade

- **Buy** one at-the-money straddle on the flagged ticker at **Friday 15:55**, at the ask of each leg. **Sell** it at
  **Monday 09:45** (the first session after the closure), at the bid of each leg.
- **Expiry:** the first listed expiry on or after the Friday one week later (so the option has days to run on Monday
  and is not a same-day expiry).
- **Strike:** the listed strike nearest the underlying's price at Friday 15:30 (five-minute bars).
- **Quotes:** the last NBBO at or before the instant (Massive `/v3/quotes`), valid only if bid > 0 and ask ≥ bid, at
  most 10 minutes old on Friday, and stamped at or after 09:30 and at most 15 minutes old on Monday. A trade needs all
  four quotes; otherwise it is dropped and counted.
- **Costs:** the bid/ask of every leg (bought at the ask, sold at the bid) and $0.65 per contract per leg each way.
  **2× costs:** every half-spread and every commission doubled.
- **P&L** of one straddle = Monday proceeds − Friday cost, per contract of 100 shares. **Return** = P&L ÷ Friday
  cost.

## 3. The control

For each flagged ticker-weekend, the same trade on the same ticker on the nearest earlier weekend on which that
ticker was not flagged under the loosest rule of section 4 (the nearest later one if there is none earlier). A weekend
serves as control once per ticker.

## 4. Variants (the complete list)

| id | flag |
|---|---|
| **V0, primary** | 4 points, odds between 10% and 90% |
| V1 | 2 points, odds between 10% and 90% (the loosest) |
| V2 | 4 points, odds between 25% and 75% |

Each at 1× and 2× costs, flagged and control. The deflated Sharpe ratio uses 3 trials.

## 5. Accounting, segments, inference

- **Weekend return of the book:** the mean return of that weekend's straddles (equal premium in each). A weekend with
  no trade returns zero. Sharpe on weekend returns, annualised by the number of weekends a year; maximum drawdown;
  worst month; turnover.
- **Costs in bp** of the premium paid, and of the underlying's price.
- **Capacity:** the size quoted at the ask on Friday, in contracts and dollars of premium.
- **In-sample / out-of-sample:** by weekend, OOS is the most recent 20% of the 55 closures. Nothing is fitted.
- **Inference:** mean net return per trade, and the difference flagged minus control, each with a 95% bootstrap
  interval resampling **weekends**.
- Also reported, before costs: the mid-to-mid return of flagged and control straddles, and the underlying's absolute
  move from Friday's close to Monday's open in each group. If the flag does not pick out larger moves, the idea fails
  at the first step and that is said.
- A Sharpe above 3 starts a bug hunt before anything is reported: the flag uses nothing after Friday 16:00; the strike
  uses the 15:30 price; Monday quotes are stamped after 09:30; costs on four legs.

## 6. Success criterion (primary V0, fixed now)

A pass needs all of: at least 30 OOS flagged trades on at least 5 OOS weekends; OOS mean net return per flagged trade
above zero with a weekend-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs; in-sample above
zero; and, over the whole sample, flagged minus control above zero with an interval excluding zero. Anything else is
a null or "too few observations" and is reported as that.

## 7. Caveats known in advance

- A straddle held over a weekend pays three days of time decay and two spreads; ordinary weekends are expected to lose.
- Bond and currency ETFs in the list have thin options; many of their trades will be dropped for want of quotes.
- One theme (Iran and oil) holds most of the active weekends, so the result will lean on USO, XLE and XOP.
- The links are model judgements, and most of these markets had resolved when they were linked (S5 amendment 1).

## Outputs

`research/results/s7_weekend_straddle/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`,
`trades.csv`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
