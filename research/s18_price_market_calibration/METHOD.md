# S18: are Polymarket's price markets fairly priced against how they resolve? (pre-registered)

**Question.** Every trade tested so far tried to time a move and paid the spread twice. This one does not time
anything. Polymarket's price markets ("Will WTI hit $100 in April?") are bought mostly as lottery tickets. If the
cheap ones are priced above the chance that they pay, the trade is to sell them once and hold to the result: one
spread, one fee, no exit. The test is calibration: over all the price markets with a result, do the markets priced
at 10% pay 10% of the time?

This file and `config.py` are committed **before any entry price is matched to any result**. Every rule is fixed.
Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- 384 of S9's 391 markets have a result and 94 resolved YES; 848 of S15's 871 have a result (their split is not
  known to me). Both universes and their weekend prices are on disk.
- S9: live markets lose 1.05 points from Sunday 17:55 to Monday 09:40 (-1.75 to -0.34); in S15 quiet markets lose
  0.89. That can be fair time decay of a "hit" market or overpricing. This study separates the two.
- **Not seen:** any entry price set against any result; any calibration table.

## 1. Markets and the entry

- **Markets:** the 1,262 price markets of S9 (`s9_weekend_price_markets/universe.json`) and S15
  (`s15_weekend_scare/universe.json`) that have a result. An **event** is one Polymarket event (one asset, one
  horizon); its strikes are one bet.
- **Entry instant:** for each market, the start of the first weekend (20:00 New York time on the last session day)
  at which it has a price reading at most 30 minutes old. One entry per market. Prices come from the two caches;
  nothing is pulled.
- **Entry price** `p`: that reading. Markets priced below 2% or above 98% are left out.

## 2. The test: calibration

- **Buckets** by entry price: 2 to 10%, 10 to 25%, 25 to 50%, 50 to 75%, 75 to 90%, 90 to 98%.
- For each bucket: the number of markets and events, the mean entry price, the share that resolved YES, and the
  difference (share − price), with a 95% interval resampling **events**.
- The same for the "hit high" markets, the "hit low" markets, each asset class, and S9's markets against S15's.
- **C1:** markets priced 2 to 25% resolve YES less often than priced (difference below zero, interval excluding
  zero). **C2:** markets priced 75 to 98% resolve YES more often than priced. These are the two halves of the
  usual lottery-ticket bias.

## 3. The trade

- **V0, primary:** sell YES (buy NO) at the entry instant on every market priced 5 to 25%, 100 contracts, and hold
  to the result. The fill is moved against the trade by the half-spread of its asset class (S9's and S15's values;
  3.0 points for weekly events) and pays the market's own fee. Nothing is paid at the result. **2× costs:** the
  half-spread and the fee doubled.
- **P&L per contract** = entry price received − fee − result (1 or 0). **Capital** = (1 − entry price) × 100,
  locked from the entry to the result.

| id | trade | markets |
|---|---|---|
| **V0, primary** | sell YES at 5 to 25% | all |
| V1 | buy YES at 75 to 95% | all |
| V2 | sell YES at 5 to 25% | S9's markets only (the heavily traded ones) |
| V3 | sell YES at 5 to 25% | crude oil only |
| V4 | sell YES at 5 to 95% (short every market) | all |

Each at 1× and 2× costs. The deflated Sharpe ratio uses 5 trials.

## 4. Accounting, segments, inference

- **Per trade:** net P&L in points per contract, and the return on the capital locked. 95% interval resampling
  events.
- **Book:** P&L booked in the month of the result. Capital base: the largest capital locked at one time. Sharpe on
  monthly returns (12 a year), maximum drawdown, worst month, turnover. Costs in points and in bp of capital.
  Capacity: tonight's size at the best price (S9 and S15).
- **In-sample / out-of-sample:** by event, in the order of the events' first entry; OOS is the most recent 20% of
  events. Nothing is fitted.
- A Sharpe above 3 starts a bug hunt: the entry price uses nothing after the entry instant; the result is never an
  input; costs are on; one event is not carrying it.

## 5. Success criterion (primary V0, fixed now)

A pass needs all of: at least 30 OOS trades in at least 10 OOS events; OOS mean net P&L per trade above zero with an
event-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs; in-sample above zero at 1× costs;
and C1 holding over the whole sample. Anything else is a null or "too few observations".

## 6. Caveats known in advance

- **One year, and one oil shock in it.** Selling "hit" markets is selling insurance against large moves. A year with
  a large move in oil and a calm year give different answers, and resampling events does not cure that: events in
  the same months share the same weather.
- The loss on one trade (up to 95 points) is many times the gain (5 to 25 points).
- Entry prices are mids from Polymarket's history, with the same doubts as in S9 and S15: a thin market's mid may
  not be a price anyone could sell at.
- Markets that were hit before their first weekend never enter. That matches what a trader entering on Friday
  evenings would have faced.

## Outputs

`research/results/s18_price_market_calibration/`: `SUMMARY.md`, `calibration.csv`, `metrics.csv`, `trades.csv`,
`equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

**Correction of wording, 2026-10-04 03:42 UTC, before the run.** Section 1 says "the 1,262 price markets ... that
have a result". The two universes hold 1,262 markets in 137 events, and 1,232 of them have a result (384 in S9, 848
in S15). Only those 1,232 can enter. No rule changes.
