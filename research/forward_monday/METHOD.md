# Forward test of the reopening taker (Study A), committed before the 2026-10-05 open

Question: on each NYSE reopening from Monday 2026-10-05 to 2026-10-30, does taking the Polymarket liquidity that is actually printed on "close above $K" markets, whenever its Yes-equivalent price is at least 5 points from the option-implied probability of the same digital, and holding to settlement, earn a positive mean P&L per $1 contract after the Polymarket taker fee and one tick of slippage?

Status: pre-registered forward test. This file and `config.py` are committed before the first reopening in the window and before any price, trade print, quote or outcome for the study exists or is fetched. Options are the signal only and are never traded. Later changes go in **Amendments** at the bottom, dated, and can only apply to reopenings that have not yet started.

## 0. Prior (seen data, sets expectations only)

- R3 (`research/results/open_options/`, 1,535 reopening events 2025-10-01 to 2026-09-28): trading the PM 09:45 mid toward the 09:45 options and holding to resolution gave +16.0 pt gross at |gap| >= 5 pt at the mid; after option costs R3's own test was NULL. Options were better calibrated (Brier 0.120 vs 0.146).
- P2 (`research/pm_taker/`): the same taker rule on non-reopening days, Jan to Aug 2026, stopped at its day-one kill test (projected 77.5 trades < 100), INSUFFICIENT, no outcome fetched.
- Discounted expectation: a few points net per trade, with high variance; with at most 4 reopenings in the window the test may well end INSUFFICIENT, and that is reported as such.

## 1. Reopenings (frozen)

A reopening is an NYSE session D whose previous calendar day is not a session (`polybridge_research.calendar.TradingCalendar`). Window of reopenings: 2026-10-05 to 2026-10-30 inclusive, which gives 2026-10-05, 10-12, 10-19 and 10-26 under the NYSE calendar. The week of D runs from D to the last NYSE session on or before the Friday of D's calendar week.

## 2. Market selection (frozen)

For each reopening D, the markets are every Polymarket market listed under gamma tag 102676 (equities) such that:

- its question parses as a "close above $K" threshold (`arbscan.parse.parse_pm_question`) of kind `daily` or `weekly`;
- its resolution date R (gamma `endDate` in America/New_York) is an NYSE session in the week of D (D <= R <= week end);
- the ticker has a clean option expiry on R: Massive `/v3/reference/options/contracts` lists standard 100-share calls on the ticker with `expiration_date = R`. Markets without one are dropped and counted.

No volume, price or liquidity filter. The listing is read at run time with metadata fields only (id, conditionId, tokens, question, startDate, endDate, feesEnabled); price and outcome fields are discarded on read and never written. The per-reopening universe is written to `universe_<D>.csv` with its sha256 in `RUN_LOG.md` before any trade print is fetched. A snapshot of the markets listed on the evening of 2026-10-03 (same metadata, no prices) is committed with this study as `snapshot_2026-10-03.csv` with `snapshot_2026-10-03.sha256`; it documents what was eligible before the open and is not used to trim the run-time universe.

## 3. Data and signal (as P2, `research/pm_taker/METHOD.md` section 2)

- **Trading window:** D from max(09:45 ET, `startDate` + 5 minutes) to 15:55 ET.
- **PM prints:** data-api `/trades?market=<conditionId>&start&end` (taker prints), paged by 500 up to the 10,000 offset cap (counted).
- **Yes-equivalent conversion, per-minute thinning** (first Yes-buy and first Yes-sell per clock minute), **evaluable ranges** (Yes-buy at x in [0.02, 0.94], Yes-sell at b in [0.06, 0.98]): unchanged from P2 (`pm_taker.core`).
- **Option probability at a print at time t:** the last NBBO of each leg at or before t - 1 s (Massive `/v3/quotes`), legs valid if bid > 0, ask >= bid and at most 300 s old; narrow call spread around K by `arbscan.implied.pick_spread`; p = e^{rT} (C1 - C2) / w with r = 0.04 and T from t to 16:00 ET on R. Usable if the band p_hi - p_lo <= 0.20, p_mid in [0.03, 0.97] and no no-arbitrage violation.
- **Evaluation order:** a market's evaluable prints in time order, stopping at the first print that qualifies at tau = 0.10.

## 4. Trade rule (frozen)

- tau = 0.05.
- **Buy YES** at the first evaluable Yes-buy print with a usable spread and x <= p_mid - tau; entry x + 0.01.
- **Buy NO** at the first evaluable Yes-sell print with a usable spread and b >= p_mid + tau; entry (1 - b) + 0.01.
- One trade per market per reopening (the first qualifying print of either side), one $1-payoff contract, held to settlement.
- **Fee:** the market's own gamma `feeSchedule`, `rate * (p (1 - p)) ^ exponent` per share at the entry price before the tick where `feesEnabled` is true (rate 0.04, exponent 1 if missing), zero otherwise.
- **Freeze:** for each reopening, the trade list (all three thresholds) is written to `trades_frozen_<D>.csv` and its sha256 logged in `RUN_LOG.md` before any outcome for that reopening is fetched. A frozen list is never rebuilt (`.frozen_<D>` marker).

## 5. Settlement

Gamma `/markets/<id>` `outcomePrices`: Y = 1 if the YES price >= 0.99, Y = 0 if <= 0.01, otherwise not yet resolved. A reopening is closed (`.done_<D>`) once all its frozen trades are resolved; until then its trades are pending and the run is repeated later for outcomes only. A market still unresolved 7 days after R is dropped and counted.

## 6. Primary analysis and pass rule

- **Estimator:** cumulative mean net P&L per trade per $1 payoff over all closed reopenings, equal weight per trade. YES: `Y - (x + 0.01) - fee(x)`; NO: `(1 - Y) - (1 - b + 0.01) - fee(1 - b)`.
- **Inference:** 95% percentile CI from a cluster bootstrap that resamples reopenings (closure clusters), 10,000 draws, seed 20261003.
- **Pass rule:** PASS if the CI lower bound is above 0 with at least 30 trades over at least 4 reopenings. NEGATIVE if the upper bound is below 0 with the same minimums. NULL if the minimums are met and neither holds. Below the minimums the status is RUNNING while reopenings in the window remain, and INSUFFICIENT once the window is over. No claim is made from a RUNNING or INSUFFICIENT status.

## 7. Secondary (reported, never change the verdict)

Two ticks of slippage; no tick; tau = 0.03 and 0.10; ticker-day clusters; splits by reopening, side and fee-enabled; capacity (half of each qualifying print's size times entry price, and times net P&L, in dollars).

## 8. Running it

`cd research && .venv/bin/python -m forward_monday.run` on or after each reopening (after 16:00 ET on D for the freeze, after the week's resolutions for outcomes). Each run processes every reopening in the window that has started and is not closed, appends to `research/results/forward_monday/` (`RUN_LOG.md`, `universe_<D>.csv`, `prints_evaluated_<D>.csv`, `trades_frozen_<D>.csv`, `trades.csv`, `stats.json`, `SUMMARY.md`), and rewrites the cumulative stats. After the last reopening is closed it writes `.done`, and later runs refuse.

## 9. Caveats

Copy-the-taker (being first to the stale quote is assumed; capacity bounded by print sizes); option-mid noise and winner's curse; outcomes within a reopening share the market move, so the effective n is near the number of reopenings; four reopenings at most.

## Amendments
