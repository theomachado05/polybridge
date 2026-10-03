# P2: options-anchored Polymarket taker on fresh daily markets (method, committed before any price, trade, quote or outcome data for this study was fetched)

Question: on Polymarket daily "Will X close above $K on D?" markets, take the liquidity that was actually printed (data-api taker prints) whenever its Yes-equivalent price is at least 5 points away from the option-implied probability of the same digital, measured from the option NBBO just before that print, and hold to settlement. Is the mean P&L per $1 contract, after the Polymarket taker fee and one tick of slippage, above zero on a sample no study has looked at?

Status: a pre-registered, cost-inclusive strategy test, run once. Options are only the signal; they are never traded. A null is an acceptable answer and is reported as one. Everything below is fixed before the run; later changes go in **Amendments** at the bottom, dated and marked pre- or post-data.

## 0. What was known before

All of this is SEEN data. It sets the prior only and is not used as confirmation.

- **R3 (`research/results/open_options/`), reopening days.** Options beat the PM as a forecaster of the same digital (Brier 0.120 vs 0.146); in a linear probability model the PM adds nothing once options are known (coefficient +0.02 [-0.15, +0.17] on PM, +1.04 on options). Trading the PM 09:45 mid toward the 09:45 options and holding to resolution gave a gross +6.8 pt per contract over 1,535 events (day-cluster CI [+4.1, +9.6]) and +16.0 pt [+10.9, +20.2] at |gap| >= 5 pt (526 events, 43 closures). R3 rows were selected on a PM closure move of at least 3 pt, and the figures are at the mid.
- **Overshoot re-analysis (unmerged branch, re-use of R3 rows):** the PM gives back about half of its closure move after the open, +3.84 pt [+1.84, +6.22]; options beat the PM on Brier and log score at every instant compared. This is a lead from seen rows.
- **Arb scan (`research/results/arb/`), resolved weekday rows 2026-08-17 to 10-02,** the same rule at the mid on daily markets: +9.0 pt [+4.9, +13.6] at 15:45 the day before (438 trades, 34 days); +3.7 pt [-1.1, +9.2] at 12:00 on the resolution day. Only 5 of 224 two-leg gaps had a print at the needed price, so mids are partly phantom.
- **Kalshi kill test (seen rows):** trading toward the options at Kalshi's own bid/ask loses 1.9c per contract (threshold 0) and 4.6c (threshold 2 pt). Kalshi is not used.
- **Lead-lag:** in market hours equities lead the PM (equity-to-PM Granger F 7.72 against 0.71 the other way).
- **Feasibility calls (metadata only, no price, trade or outcome series):** gamma lists no equity "close above" market before October 2025. A full gamma listing 2025-10-01 to 2026-08-14 was saved as metadata only (id, conditionId, YES token, ticker, strike, endDate, startDate, feesEnabled, question; no outcomePrices) to the scratchpad file `fresh_daily_listing_meta.json`, sha256 `6d1c551f77d5a9697e37c34b13454f4487d1d61e9c36d285ff4b328fef5be747`, 5,704 daily markets. Massive contract lists: megacaps (AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA) list Wednesday and Friday expiries from 2026-02-11; SPY lists every session. Field names of data-api `/trades` were checked on one seen R3 market (AAPL > $250 on 2026-02-02), together with the `start` and `end` time filters and the 10,000-row offset cap.

Discounted expectation: halving the seen S1 mid edge and taking off about 1 pt for fee and tick gives about +3 to +5 pt net per trade.

## 1. Sample frame (frozen rule)

- **Markets:** every row of the listing above whose question parses as a daily "close above" market (`arbscan.parse.parse_pm_question`, kind `daily`). No volume, price or liquidity filter.
- **Resolution date D:** the market's `endDate` in America/New_York.
- **Non-reopening sessions only:** D is an NYSE session and the previous calendar day D-1 is also a session (`polybridge_research.calendar.TradingCalendar`). This keeps Tuesday to Friday after ordinary weeknights and drops every day after a weekend or holiday, which is R3's frame.
- **Window of resolution dates:** 2026-01-20 to 2026-08-14 inclusive. R3 used only reopening days; the arb scan's resolved rows start 2026-08-15; the overshoot and arm-K studies re-used R3 and the 380-closure panel. No row of this frame has been looked at.
- **Clean option expiry:** a listed call expiry on exactly D for the market's ticker (Massive `/v3/reference/options/contracts`, `expiration_date = D`, `expired=true`, standard 100-share contracts). Markets without one are dropped and counted. The expiry list is written into the frozen universe file (`universe.csv`, with its sha256 in `RUN_LOG.md`) before any trade or quote is fetched.
- **Trading window:** the regular session of D-1, from max(10:00 ET, `startDate` + 5 minutes) to 15:55 ET. There is no early close in the window. A market listed after 15:55 ET on D-1 has an empty window and contributes nothing (counted).

## 2. Data

- **PM prints:** data-api `/trades?market=<conditionId>&start=<window start>&end=<window end>` (default `takerOnly=true`), paged by 500 up to the 10,000 offset cap (a market that hits the cap is counted). One market at a time, cached on disk.
- **Yes-equivalent conversion** (as `arbscan/verify.py`): a YES trade at q with side S stays (q, S); a NO trade at q becomes a YES trade at 1 - q on the opposite side. "Yes-buy" = the taker bought YES (or sold NO): it lifted a YES ask at x. "Yes-sell" = the taker sold YES (or bought NO): it hit a YES bid at b.
- **Per-minute thinning:** per market and clock minute, keep only the first Yes-buy print and the first Yes-sell print (ordered by timestamp, then by the data-api's reversed order).
- **Evaluable prints:** a kept Yes-buy with x in [0.02, 0.94], or a kept Yes-sell with b in [0.06, 0.98]. Outside those ranges a print cannot qualify at any threshold used here (p_mid is capped to [0.03, 0.97] and the smallest threshold is 0.03), so no option quote is fetched for it.
- **Option-implied probability at a print at time t (seconds):** the last NBBO of each leg stamped at or before t - 1 s (Massive `/v3/quotes/<contract>`, `timestamp.lte = t - 1 s`, `order=desc`, `limit=1`), so the signal never uses a quote from the print's own second. A leg is valid if bid > 0, ask >= bid, and the quote is at most 300 s old at t - 1 s. Strikes are picked by `arbscan.implied.pick_spread` (narrow neighbours of K, at most two steps outward if a leg is invalid). p = e^{rT} (C1 - C2) / w with r = 0.04 and T from t to 16:00 ET on D; `p_mid` from leg mids, `p_lo` and `p_hi` from bid/ask bounds. The spread is **usable** if `p_hi - p_lo <= 0.20`, `p_mid` in [0.03, 0.97], and the raw mid is inside [0, 1]. A print without any valid pair is `no_spread`; a pair that fails the band or the range is `unusable`. The Massive cache is keyed by full URL and may be shared with other studies.
- **Evaluation order and stop:** a market's evaluable prints are evaluated in time order, and evaluation stops at the first print that qualifies at tau = 0.10 (see section 3) or when the prints run out. The tau = 0.03 and 0.05 trades always occur at or before that print, so all three thresholds are fully determined.
- **Settlement (read only after the trade list is frozen):** the Polymarket resolution from gamma `/markets/<id>` `outcomePrices`: Y = 1 if the YES price is >= 0.99, Y = 0 if <= 0.01, otherwise unresolved (dropped and counted). The same record gives `feesEnabled` and `feeSchedule`. Cross-check: the Massive daily close of the ticker on D against K; disagreements are counted and listed but never drop or flip a row.

## 3. Trade rule (frozen)

- Threshold **tau = 0.05**.
- **Buy YES** at the first evaluable Yes-buy print with a usable spread and x <= p_mid(t) - tau. Entry = x + 0.01.
- **Buy NO** at the first evaluable Yes-sell print with a usable spread and b >= p_mid(t) + tau. Entry = (1 - b) + 0.01.
- One trade per market: the first qualifying print of either side. Size: one $1-payoff contract per trade.
- **Fee:** the market's own `feeSchedule`, `rate * (p (1 - p)) ^ exponent` per share at the entry price p before the tick (x for YES, 1 - b for NO), where `feesEnabled` is true (rate 0.04, exponent 1 if the schedule is missing); zero otherwise (`arbscan.costs.fee_from_gamma`).
- **Freeze:** the trade list (market, time, side, print price, size, p_mid, p_lo, p_hi, strikes) for all thresholds is written to `trades_frozen.csv` and its sha256 is recorded in `RUN_LOG.md` before any outcome is fetched.

## 4. Primary analysis

- **Estimator:** mean net P&L per trade per $1 payoff, every trade weighted equally. YES: `Y - (x + 0.01) - fee(x)`. NO: `(1 - Y) - (1 - b + 0.01) - fee(1 - b)`.
- **Inference:** 95% percentile CI from a cluster bootstrap that resamples resolution days D (all tickers on one day share the market factor), 10,000 draws, seed 20261003.
- **Pass rule:** PASS if the lower bound of the day-cluster 95% CI is above 0 with at least 100 trades on at least 30 distinct resolution days. INSUFFICIENT, with no claim either way, if fewer than 100 trades or fewer than 30 days qualify. NEGATIVE if the upper bound is below 0. Otherwise NULL.

## 5. Secondary (reported, never used to change the verdict)

1. Slippage of +0.02 (two ticks) instead of +0.01; whether the sign survives. Copying a taker who already consumed the stale quote may cost more than one tick.
2. No tick (entry at the print price).
3. tau = 0.03 and tau = 0.10 (their own first-qualifying trades).
4. Equal weight per day (mean of daily means) and a ticker-day cluster bootstrap.
5. Splits by ticker, by side (YES vs NO) and by fee-enabled.
6. Mid variant: at the same evaluated instants, the CLOB `prices-history` YES mid (fidelity 1 minute, last point at or before t, at most 15 minutes old) with an assumed 2.5c half-spread; buy YES at mid + 0.025 if mid <= p_mid - 0.05, buy NO at (1 - mid) + 0.025 if mid >= p_mid + 0.05; first qualifying instant; fee as above.
7. Signal calibration: Brier score and a 10-bin reliability table of p_mid against Y over all evaluated prints with a usable spread, next to the same for the print price.
8. Capacity: for each trade, half the print size (shares) times the net P&L per share and times the entry price, summed over trades, in dollars.
9. Settlement-source disagreements (Polymarket resolution vs close against K).

## 6. Expected n, MDE, type-M

About 2,480 eligible markets on 83 resolution days (about 420 ticker-days). Trades: guessed 250 to 800 over 60 to 83 days. Scaling from the seen S1 rows (CI half-width 4.4 pt with 438 trades over 34 days): at 83 days and about 400 trades the day-cluster SE is about 1.5 pt, MDE about 4.2 pt at 80% power and two-sided 0.05; at 250 trades over 60 days, SE about 2.2 pt and MDE about 6 pt. Power against the discounted +3 to +5 pt is about 45 to 85%. If the true edge is 2 pt with SE 1.5, power is about 27% and a significant estimate would overstate it about 2x. The report says so if the estimate lands near the MDE (about 4 to 6 pt).

## 7. Kill tests and the time stop (prices only, never outcomes)

1. **Day one:** build the trade list for the resolution dates in the first 3 weeks of the window (2026-01-20 to 2026-02-09) first. Projected trades over the window = trades in those weeks times (eligible markets in the window / eligible markets in those weeks); projected days = days with a trade in those weeks times (eligible days in the window / eligible days in those weeks). If projected trades < 100 or projected days < 30, stop and report INSUFFICIENT.
2. If more than 30% of evaluated prints in those weeks are `no_spread`, the option measurement is broken: stop and report INSUFFICIENT.
3. **Time stop:** if the full trade list is not frozen by 01:30 ET on 2026-10-04, stop and report INSUFFICIENT. The universe is never trimmed after looking.

## 8. Costs

Polymarket taker fee per the market's feeSchedule (at most 1c per share). Entry at the printed price plus 0.01 against us. No option cost (options are the signal only). No exit cost: positions are held to settlement. Capital: $1 per share for at most about 30 hours, no financing charge.

## 9. Caveats the report must carry

- **Copy-the-taker assumption.** Being first to the stale quote is assumed. If faster bots already pick these quotes off, the sign may survive while our share does not; real capacity is bounded by print sizes.
- **Thin prints.** Early-2026 daily markets traded little; the trade count may fall short of the power target.
- **Option-mid noise and winner's curse.** Single-name 1DTE option bands can be wide; selecting on the gap shrinks the realised edge. The band cap and the calibration table address it. Risk-neutral vs physical differences are small at a one-day horizon.
- **Correlated outcomes.** Trades on one day share the market move, so the effective n is closer to the number of days than to the number of trades.
- **Regime.** The seen S1 lead came from August to October 2026.

## 10. Outputs

`research/results/pm_taker/`: `SUMMARY.md` (verdict first), `stats.json`, `universe.csv`, `trades_frozen.csv`, `trades.csv` (with outcomes and P&L), `prints_evaluated.csv`, `chart.png`, `RUN_LOG.md` (commit, times, request counts, hashes), and `.done`, which makes a second run refuse. Code in `research/pm_taker/`, synthetic tests in `research/pm_taker/tests/`.

## Amendments

(none)
