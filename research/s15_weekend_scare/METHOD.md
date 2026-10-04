# S15: do price markets that rise over the weekend fall back on Monday? A test on markets S9 did not use (pre-registered)

**Question.** S9 found, after its run and outside its method, that the give-back of weekend moves sits on one side:
Polymarket price markets that **rose** over the weekend were lower by Monday morning, most of all the oil "hit high"
markets after a weekend scare. A pattern found by looking is a lead, not a finding. This study tests it on price
markets that S9 never touched.

This file, `config.py`, `universe.py` and `universe.json` are committed **before any price of these markets is
pulled**. Every rule is fixed. Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- S9, pre-registered: after a weekend move of 5 points or more the price markets give back 2.94 points by the next
  session's 09:40 (interval -4.66 to -1.14); the fade nets -0.01 points per trade after costs and fails out-of-sample.
- S9, looked at after the run (`research/results/s9_weekend_price_markets/SUMMARY.md`): markets that rose 5 points
  or more fall 4.90 points (192 market-weekends on 37 weekends, -7.11 to -2.62); markets that fell recover 1.15
  (-0.27 to +2.80); oil "hit high" markets that rose fall 7.85 (-11.52 to -4.38). All live markets drift down 1.05
  points over the same window (-1.75 to -0.34), because a "hit" market loses value as time passes without a hit.
- **From the catalogue only** (`universe.py`): 871 price markets that are not in S9's universe, in 133 events: 463
  on stocks, 102 S&P 500, 112 crude oil, 83 silver, 66 gold, 45 natural gas. 848 have a result.
- **Not seen:** any price of any of these 871 markets.

## 1. Markets

`universe.json`: the same catalogue searches and title rule as S9, plus natural gas and five more stock tickers,
**leaving out every market S9 used**. Kept: markets with at least $10,000 traded, in events with at least $100,000
traded or in one of S9's 25 events (their smaller strikes). Each market is tagged: "leftover of an S9 event",
"weekly", or "other event".

These are different markets from S9's on mostly the same weekends. The test asks whether the pattern is general
across markets; it cannot show that it persists in time. Results are split by tag so that the markets furthest from
S9 (other events and weekly ones) can be read on their own.

## 2. The weekend clock

S9's, unchanged (`s9_weekend_price_markets.run.calendar()`): start 20:00 on the last session day before the weekend;
entry Sunday 17:55; exit 09:40 on the next stock-market session, New York time. A price reading is valid for 30
minutes. A market is live if its price at the start is between 10% and 90%. `w` = entry price − start price;
`y` = exit price − entry price, in points. A market that resolves before the exit is valued at its result (S9
amendment 1).

## 3. The test (primary)

- **Risers:** live markets with `w` ≥ +5 points. **Quiet markets:** live markets with |`w`| < 2 points (they carry
  the ordinary drift). **Fallers:** `w` ≤ −5.
- **H1:** the mean of `y` for risers is below zero, weekend-bootstrap 95% interval excluding zero.
- **H2:** the mean of `y` for risers is below the mean for quiet markets, the interval of the difference (resampling
  weekends) excluding zero. This removes the drift.
- **The pattern replicates only if both hold.**
- Also reported, same statistics: fallers; moves of 10 points or more; by asset class; by tag; the oil "hit high"
  risers on their own.

## 4. The trade (secondary)

Sell YES at the entry instant on every riser whose entry price is between 5% and 95%, 100 contracts, at most 10 a
weekend (largest rises first); buy back at the exit instant. Fills are moved against the trade by a half-spread:
S9's by asset class (crude oil 0.5 point, S&P 500 1.0, gold 1.25, silver 2.0, stocks 2.5), natural gas 2.0, and 3.0
for every market of a weekly event (half of the 6-point median spread on tonight's small open markets). Each fill
pays the market's own fee. 2× costs: half-spreads and fees doubled.

| id | rise | markets |
|---|---|---|
| **V0, primary trade** | 5 points or more | all |
| V1 | 10 points or more | all |
| V2 | 5 points or more | crude oil only |

In-sample and out-of-sample by weekend (the most recent 20% of live weekends). Mean net P&L per trade with a
weekend-bootstrap interval; Sharpe on weekend returns (52 a year), maximum drawdown, worst month, turnover; costs in
bp of capital. Print check on V0's entries (S6's rule, 10 minutes around the entry). A pass needs: at least 30 OOS
trades on at least 5 OOS weekends; OOS mean net above zero with the interval excluding zero at 1× costs; above zero
at 2×; in-sample above zero. A pass with fewer than half of the entries print-verified is "passes on modelled
prices, not verified". A Sharpe above 3 starts a bug hunt.

## 5. Caveats known in advance

- These markets are thinner than S9's (most traded $10,000 to $50,000 in their life). A mid price in a thin book can
  move without a trade. The print check says how much of it was real.
- A riser is selected on a high Sunday reading. If that reading is noise in a thin book, the next reading is lower
  by construction (regression to the mean), and a "give-back" appears that nobody could trade. H2 does not remove
  this; the print-verified subset is the guard, and it is reported separately.
- The same weekends as S9.

## Outputs

`research/results/s15_weekend_scare/`: `SUMMARY.md`, `tests.csv`, `metrics.csv`, `trades.csv`, `weekends.csv`,
`equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
