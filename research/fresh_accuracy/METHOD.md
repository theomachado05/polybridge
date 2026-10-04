# Fresh-market accuracy: is the option-implied probability a better forecast than the Polymarket price? (pre-registered)

**Question.** On Polymarket "close above $K" stock and SPY markets that no earlier study touched, is the option-implied probability (a call spread priced from the NBBO at the same instant) a more accurate forecast of the market's result than the Polymarket price? Accuracy is the Brier score and the log score at the arb scan's fixed snapshots. A gated secondary (H3) asks whether, on Kalshi's 16:00 S&P 500 and Nasdaq-100 markets, the Kalshi price is as accurate as SPXW and NDXP options within a fixed margin.

This decides one product rule: which price PolyBridge shows as the reference probability for an equity threshold. If the primary passes, the product treats the option-implied probability as the reference and labels the Polymarket price a noisier copy.

Status: pre-registered and run once. This file, `config.py`, `freeze.py` and the frozen market list `frozen_ids.csv` (with its SHA-256 in `frozen_ids.sha256`) are committed **before any price, quote or outcome of a study market is fetched or read**. Every rule and threshold below is fixed. A later change goes under **Amendments**, dated and marked pre- or post-data; the original text stays in git history. A null is reported as a null.

Data scope: no 8-K data. Option data: Massive (`research/polybridge_research/massive.py`), NBBO quotes and contract listings. Polymarket: gamma (`/events/keyset`), CLOB `prices-history`, data-api `/trades`. Kalshi: public `/historical/...` and live market endpoints. The option-implied probability reuses `research/arb/arbscan` unchanged (`parse.parse_pm_question`, `implied.pick_spread`, `score.score_row`, `costs`).

## 0. What was known before this commit (freshness disclosure)

- **The hypothesis is not fresh. The markets and outcome dates are.** The arb scan (`research/results/arb/`, resolved Polymarket rows resolving 2026-08-15 to 2026-10-12) reported Brier PM 0.0843 vs options 0.0789, difference +0.0054 on 2,761 rows in 272 events. Recomputed before this commit from `arb_gaps.csv`: without exact-0.500 placeholders, Brier difference +0.0044 on 2,743 rows (resolution-date-cluster SE 0.0015 over 34 dates), log-score difference +0.0195 (SE 0.0036). R3 (`research/results/open_options/`) and the T4 re-analysis of R3's rows found options more accurate than the PM at the Monday open (Brier difference +0.0267 [+0.0189, +0.0349]) and at the same instant 09:45 (+0.0121 [+0.0051, +0.0195]), on rows selected for a closure move of at least 3 points, and that the PM adds nothing once options are known. The overshoot (PM give-back) lead from T4 comes from seen data and **is not tested here**: R3 already used every weekend and holiday closure in Polymarket's equity history, so it cannot be confirmed on fresh Polymarket data. This study confirms only the forecasting half of T4.
- On the arb rows, PM sat above options by about 1.3 points when PM < 0.2 and below by about 1.8 points when PM > 0.8 (a favourite-longshot pattern); the direction of the main effect is therefore known.
- Kalshi index markets in the arb window: Brier 0.2029 vs 0.2033, difference -0.0004 (date-cluster SE 0.0019, 500 rows, 34 dates).
- Metadata looked at before this commit (no price or outcome of a frame market was read): the Polymarket Equities tag listing (ids, questions, start and end dates), Kalshi listing and candle field names on non-frame markets, Massive contract listings for a handful of (underlying, expiry) pairs. Count from metadata: about 9,349 frame markets on 120 resolution dates.

## 1. Polymarket frame (frozen rule)

A market is in the frame when all of the following hold, applied by `freeze.py` to the gamma `/events/keyset` listing (tag 102676 `Equities`, `closed=true`, event end date 2025-10-14T00:00Z to 2026-08-14T23:59:59Z):

1. the market itself is `closed`;
2. its question passes `arbscan.parse.parse_pm_question` with kind daily, weekly or monthly (the arb rule; ticker from the question or the event title, strike from the question);
3. it has a CLOB token and an `endDate`; resolution date = `endDate` in America/New_York, and it lies in 2025-10-14 .. 2026-08-14 (the window ends the day before the arb scan's window);
4. its id does not appear in `research/results/open_options/events.csv` (any R3 pair, whatever its status);
5. its resolution date is not any `res_date` in that file (no outcome realisation shared with R3).

`freeze.py` reads only id, question, event title, ticker, strike, kind, start date, end date, token and condition id. It never reads `outcomePrices`, `lastTradePrice`, `bestBid`, `bestAsk` or any other price field. The list is written to `frozen_ids.csv` (sorted by resolution date, then id) and its SHA-256 to `frozen_ids.sha256`. Frozen result (`frozen_counts.json`): 9,349 markets (daily 4,431, weekly 4,394, monthly 524) on 120 resolution dates from 2025-11-21 to 2026-08-14, 15 tickers; SHA-256 `6cd5b9bd197dd279213c733e90e30600f85caf086c0d00a83d4a0cab7cf8d77e`. The runner refuses to start if the hash of the file it loads differs.

## 2. Snapshots and rows

- **S1** = 15:45 ET on the NYSE session before the resolution date (`TradingCalendar.before`); **S2** = 12:00 ET on the resolution date. These are the arb scan's definitions.
- A (market, snapshot) row exists only if the snapshot is **strictly before the market's `endDate`** and **at or after its `startDate`**. A market listed after S1 contributes only its S2 row; one listed after S2 contributes none. Each dropped snapshot is counted (`snapshot_before_listing`, `snapshot_not_before_end`). A market with no `startDate` keeps both snapshots (arb rule).

## 3. Prices

**Polymarket.** One CLOB `prices-history` request per market, fidelity 1, from S1 - 3600 s to S2 + 600 s (arb rule). The PM price at a snapshot is the last point with timestamp **at or before** the snapshot. The row is `pm_stale` if that point is more than **15 minutes (900 s)** older than the snapshot. If the series is coarser than that, those rows fail the age rule by rule; the window is never widened. Rows whose PM price is **exactly 0.500** are dropped (`pm_placeholder`, the R3 rule for an unquoted book). Rows outside [0.02, 0.98] are dropped (`pm_extreme`, the arb "informative" rule, kept unchanged although it is asymmetric in its effect on the two forecasts).

**Options.** Clean expiry only: the underlying (the Polymarket ticker; SPY markets use SPY options) must have listed calls expiring **on the resolution date** (Massive `/v3/reference/options/contracts`, `expired=true` for past dates; index roots restricted to SPXW and NDXP by `arbscan.datasrc.contract_map`). Otherwise the row is `no_clean_expiry` and dropped. The probability is `arbscan.score.score_row`: narrow call spread (neighbours of K if K is listed, else the strikes just below and above; a leg without a valid quote steps one listed strike outward, at most twice), `p = e^{rT}(C1 - C2)/w`, r = 4%, T to 16:00 ET on the expiry; bounds `p_lo` (bid1 - ask2) and `p_hi` (ask1 - bid2); a wide spread one strike further out on each side for the coarseness flag (`width_sens > 0.05`). Each leg is the last NBBO **at or before** the snapshot (`timestamp.lte`, newest first), valid only if bid > 0, ask >= bid, and its timestamp is no later than the snapshot and **no more than 10 minutes (600 s)** before it. A later quote never fills in. No valid narrow pair: `no_chain`, dropped.

**Scored row.** `status == scored` from `score_row`, clean expiry, PM price fresh, informative and not 0.500. The outcome y (1 if the market resolved YES, from gamma `outcomePrices` `["1","0"]`, 0 if `["0","1"]`, else the row is dropped as `no_outcome`) is read **only in the scoring step, after the coverage gate**.

## 4. Primary test

For each scored row: `p_PM` = the PM price; `p_opt` = clip(`p_mid`, 0, 1) (the narrow-spread mid, already clamped by arbscan).

- `d_B = (p_PM - y)^2 - (p_opt - y)^2`
- `d_L = LS(p_PM) - LS(p_opt)`, `LS(p) = -[y ln p + (1 - y) ln(1 - p)]` with p clipped to [0.01, 0.99].

Positive means options were more accurate. The estimates are the row-weighted means of `d_B` and `d_L` (ratio of sums in each bootstrap draw).

**Inference.** Cluster bootstrap over **resolution dates** (every strike, ticker and snapshot resolving on one date shares one market move), 10,000 draws, seed **20261004**, 95% percentile intervals. Run once.

**Pass rule (fixed now).**

- **INSUFFICIENT** if fewer than **2,000** scored rows or fewer than **40** resolution dates. No claim either way. This is decided before any outcome is joined (section 7b).
- **PASS** (options more accurate than the Polymarket price on fresh markets) if the 95% CI lower bound is above 0 for **both** mean `d_B` and mean `d_L`.
- **REVERSED** (Polymarket more accurate) if either point estimate is negative with its 95% CI entirely below 0.
- **PARTIAL** if exactly one of the two CIs is entirely above 0 and REVERSED does not apply.
- **NULL** otherwise.

## 5. Secondaries (reported, never used to rescue or change the verdict)

1. Event clustering (ticker x resolution date) instead of date clustering.
2. S1 and S2 separately; daily, weekly and monthly separately.
3. **Equal weight per resolution date** (mean of per-date means, same bootstrap). Weekly markets put many rows on Fridays. The report states explicitly whether the verdict computed under this weighting would differ from the primary verdict, and that the primary verdict stands either way.
4. Trade-print subset: rows whose market has at least one Polymarket data-api trade print within +/-10 minutes of the snapshot (any side, any outcome token), fetched only for markets with a scored row.
5. Encompassing logit: y on logit(p_opt) and logit(p_PM) (both clipped to [0.01, 0.99]) with an intercept, date-clustered sandwich SEs; report the PM coefficient with its 95% CI.
6. Favourite-longshot slope: OLS of (p_PM - p_opt) on (p_opt - 0.5), date-clustered SE. Predicted negative.
7. Mean Brier and log score of each forecast, and the coarse-row share (`width_sens > 0.05`).

## 6. Gated H3: Kalshi index equivalence

Run **only if the primary verdict is PASS** (fixed sequence, so the familywise 5% holds) **and** the primary results are written before **01:30 ET on 2026-10-04**. Otherwise the report says "H3 not run" and why.

- **Frame (frozen now).** Series `KXINXU` (underlying SPX, options SPXW) and `KXNASDAQ100U` (NDX, options NDXP); the 16:00 ET event of every NYSE session from 2025-10-01 to 2026-08-14 (event ticker `<SERIES>-<YYMONDD>H1600`). Markets of each event from `/historical/markets?event_ticker=...` (settled before the historical cutoff) or, if that returns none, the live `/markets?event_ticker=...`. Keep `strike_type` greater or greater_or_equal with a `floor_strike`, nonzero `volume_fp`, then the top 8 by `volume_fp` (ties by ticker), the arb's rule.
- **Snapshot.** S2 = 12:00 ET on the resolution date (ET date of `close_time`); the row needs `open_time` at or before S2 and S2 strictly before `close_time`.
- **Price.** 1-minute candles from `/historical/markets/{ticker}/candlesticks` (or the live `/series/{series}/markets/{ticker}/candlesticks`) from S2 - 1800 s to S2. The last candle ending at or before S2 whose yes_bid and yes_ask closes give a two-sided book, **0 < bid <= ask < 1**, at most 15 minutes old; Kalshi price = mid. (The two-sided condition excludes the empty 0/1 book, whose mid 0.5 is the Kalshi analogue of the Polymarket placeholder.) Informative filter, clean expiry, option rule and outcome (`result` yes/no) as above.
- **Test.** Same `d_B`, date-cluster bootstrap (10,000 draws, seed 20261004). **EQUIVALENT** if the 90% CI of mean `d_B` lies inside **[-0.003, +0.003]** (TOST at 5%). Otherwise **OPTIONS-BETTER** or **KALSHI-BETTER** if the 95% CI excludes 0 on that side, else **INCONCLUSIVE**. `d_L` is reported, not tested. Costs reported: observed Kalshi half-spread and the taker fee 0.07 p(1 - p).

## 7. Kill test (day one, outcome-blind)

a. **Scorer check, before any fresh call.** The scoring module run on the seen `research/results/arb/arb_gaps.csv` (Polymarket, scored, clean, resolved) must reproduce Brier difference +0.0054 on 2,761 rows, and +0.0044 on 2,743 rows without placeholders, to 4 decimals. If not, stop and fix before freezing. (Done before this commit: +0.0054 on 2,761; +0.0044 on 2,743; log +0.0195; 34 dates.)
b. **Coverage gate, inside the single run.** After all prices and quotes are fetched and before any outcome is joined, count scored rows and resolution dates. Below 2,000 or 40, write INSUFFICIENT and exit without scoring.
c. **Slice check.** A seeded random 50-market slice of the frozen list (seed 20261004) is fetched first and checked only for request success, PM staleness and option-leg validity, never scored. Valid rate = scored rows (as in section 3, before outcomes) over all (market, snapshot) rows that pass section 2. If the valid rate is below **30%** the run stops before the full download (the arb's valid yield was 2,743 of 5,872, 47%).

## 8. Costs

No trade is claimed, so costs do not enter any verdict. Reported from data per row: the option half-band (p_hi - p_lo)/2 and the commission per $1 of payoff (`arbscan.costs.commission_per_share`, $0.65 per contract per leg). Polymarket historical spreads are not observable. The report states that an accuracy deficit is not an executable edge: the arb scan found 0 executable gaps (5 verified), and R3's net gap was +0.79 pt [-1.21, +2.78].

## 9. Expected n and power

About 9,349 frame markets x up to 2 snapshots. At the arb's valid yield (about 47%), roughly 7,000 to 9,000 rows on about 100 to 120 date clusters, fewer if many midweek single-stock dailies lack a same-day expiry. Scaling the arb's date-cluster SEs by sqrt(34/110): SE about 0.00083 (Brier) and 0.0020 (log). MDE at 80% power, two-sided 5%: 0.0023 and 0.0056. Discounted priors (half the arb estimate): Brier +0.0022, log +0.0098, giving power about 0.75 and 1.00, joint about 0.75; at the undiscounted arb estimates joint power is above 0.99. At 60 clusters joint power under the discounted prior falls to about 0.5, which is why the 40-date floor exists. H3: at about 200 dates the SE is about 0.00075 and P(EQUIVALENT) is about 0.95 if the true gap is 0.

## 10. Caveats the report must carry

- Wording: "the Polymarket price is a worse forecast than options", never "Polymarket traders know less". The PM price is a per-minute series that can be a stale last price or the midpoint of a wide book; that handicap is the mechanism, and the trade-print subset is the check.
- The call spread averages the density over [K1, K2]; Polymarket settles on the Pyth 16:00 print, options on the official close; SPY and single-name options are American.
- The fresh frame is earlier in Polymarket's life and has more midweek dailies and weeklies than the arb's window; a different effect size is possible.
- Rows are strongly dependent within a date; inference clusters on date and the equal-weight secondary is reported.
- Freshness: fresh markets and outcome dates, hypothesis and direction already seen (section 0).

## 11. Outputs

`research/results/fresh_accuracy/`: `SUMMARY.md` (verdict first), `stats.json`, `rows.csv` (one row per (market, snapshot) with status), `accuracy_chart.png`, `RUN_LOG.md` (commit, times, request counts), `slice_check.json`, and `.done`, which makes the scoring step refuse a second run. Synthetic tests in `research/fresh_accuracy/tests` (no network).

## Amendments

(none)
