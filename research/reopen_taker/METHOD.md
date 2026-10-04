# Study A: options-anchored Polymarket taker on weekend and holiday reopenings (method, committed before any price, trade print or outcome for this study was fetched)

Question: on the Polymarket "close above" markets of R3 (reopening sessions after a weekend or a market holiday), if we take the first printed taker trade from 09:45 ET whose Yes-equivalent price is at least 5 points away from the option-implied probability at 09:45, trade toward the options and hold to settlement, is the mean P&L per $1 contract positive after the Polymarket taker fee and one tick of slippage?

## 0. Status: a re-analysis of seen closures, not a confirmation

Every closure, market, Polymarket price and option-implied probability used here was already seen. R3 (`research/results/open_options/`) measured these same 1,535 events over 44 closures (reopening days 2025-11-10 to 2026-09-28) and found that after 09:45 the PM gives back -3.48 pt [-5.40, -1.62] of its closure move; the overshoot re-analysis of the same rows found a +3.84 pt give-back by the close, and R3 found trading the 09:45 mid toward the options at |gap| >= 5 pt earned +16.0 pt gross [+10.9, +20.2] (526 events, 43 closures). This study is a pre-registered re-analysis of those seen closures using the prices of trades that actually printed, with fees and slippage. It asks whether the seen mid-based edge survives execution at printed prices; it cannot confirm the edge out of sample, and a PASS is not evidence on fresh data. A null or INSUFFICIENT is reported as one.

## 1. Sample (frozen)

- **Markets:** every row of R3's committed `research/results/open_options/events.csv` with `status == "event"` (Polymarket; daily, weekly and monthly "close above" markets), keyed by `market_id`. No new selection; R3's own filters stand.
- **Option-implied probability:** R3's 09:45 ET value for the same digital, `oo_mid` (bounds `oo_lo`, `oo_hi`). pm_taker's band and range rules are applied to it: usable only if `oo_hi - oo_lo <= 0.20` and `oo_mid` in [0.03, 0.97]; other rows are dropped and counted. This replaces pm_taker's "last option NBBO strictly before the print" because the task allows the 09:45 value and time is short; the option signal is therefore fixed for the day and grows staler through the session. The NBBO-before-print variant is not run.
- **Trading window:** the reopening session `open_day`, from 09:45:00 ET to 15:55:00 ET inclusive.
- **Clusters:** the closure (`closure` column, 44 values).

## 2. Data

- **Gamma metadata** (`/markets/<id>`): `conditionId`, `feesEnabled`, `feeSchedule`. The record also carries `outcomePrices`; it is not used for outcomes.
- **PM prints:** data-api `/trades?market=<conditionId>&start=<window start>&end=<window end>` (taker prints), paged by 500 up to the 10,000 offset cap (capped markets counted), one market at a time, cached on disk.
- **Yes-equivalent conversion, per-minute thinning (first Yes-buy and first Yes-sell per clock minute), evaluable ranges (Yes-buy x in [0.02, 0.94], Yes-sell b in [0.06, 0.98])** exactly as pm_taker (`pm_taker.core.yes_equiv`, `thin`, `evaluable`).
- **Outcome:** R3's committed `outcome` column (Polymarket resolution, 1 = YES), allowed by the task. Rows without an outcome are dropped and counted.

## 3. Trade rule (frozen, pm_taker values)

- Threshold tau = 0.05. Buy YES at the first evaluable Yes-buy print with x <= p - tau, entry x + 0.01. Buy NO at the first evaluable Yes-sell print with b >= p + tau, entry (1 - b) + 0.01. One trade per market (the first qualifying print of either side), one $1-payoff contract, held to settlement.
- Fee: the market's `feeSchedule`, `rate * (q (1 - q)) ^ exponent` per share at the entry price q before the tick, when `feesEnabled` (rate 0.04, exponent 1 if the schedule is missing), else zero (`pm_taker.core.fee_params`, `fee_per_share`).
- The trade list for tau 0.03, 0.05 and 0.10 is written to `trades_frozen.csv` and hashed in `RUN_LOG.md` before outcomes are joined (outcomes are already in a seen file, so this freeze is procedural).

## 4. Primary analysis

- Net P&L per trade per $1 payoff: YES `Y - (x + 0.01) - fee(x)`; NO `(1 - Y) - (1 - b + 0.01) - fee(1 - b)`. Mean over trades, equal weight.
- 95% percentile CI from a closure-cluster bootstrap, 10,000 draws, seed 20261003.
- **PASS** if the CI lower bound is above 0 with at least 30 trades over at least 8 closures. **INSUFFICIENT** (no claim) if fewer than 30 trades or 8 closures. **NEGATIVE** if the upper bound is below 0. Otherwise **NULL**.

## 5. Secondary (never change the verdict)

1. Slippage +0.02 (two ticks) at tau 0.05.
2. tau = 0.03 and tau = 0.10, each with its own first-qualifying trades, one tick.
3. Splits by side and by market kind (daily, weekly, monthly).
4. Capacity: for each tau = 0.05 trade, the print's notional (size times entry price) in dollars, summed; and CAPACITY_SHARE (half) of the print size times net P&L per share, summed, as dollar profit at capacity.

## 6. Caveats the report must carry

- Seen closures (section 0): this is not out-of-sample evidence.
- Copy-the-taker: being first to the stale print is assumed; capacity is bounded by print sizes.
- The 09:45 option probability is stale for later prints; the stock moves during the session, so a gap measured against it can be a signal error rather than a PM error.
- Trades within a closure share the market move; the effective n is near the number of closures.
- Monthly markets settle weeks after the trade; capital is tied up longer and no financing charge is applied.

## 7. Outputs

`research/results/reopen_taker/`: `SUMMARY.md` (verdict first), `stats.json`, `trades_frozen.csv`, `trades.csv`, `RUN_LOG.md`, `.done` (a second run refuses). Code in `research/reopen_taker/`, synthetic tests in `research/reopen_taker/tests/`.

## Amendments
