# Chronological holdout of the fresh-market accuracy test (pre-registered)

**Question.** Same as `research/fresh_accuracy/METHOD.md`: on Polymarket "close above $K" stock and SPY markets, is the option-implied probability (call spread from the NBBO at the same instant) a more accurate forecast than the Polymarket price? This file changes only the window, the frozen list and the inference; it is committed, with `freeze.py`, `frozen_ids.csv` and `frozen_ids.sha256`, before any price, quote or outcome of a holdout market is fetched or read. Run once.

## 0. Why this window

The hypothesis came from the arb scan, `research/results/arb/arb_gaps.csv`, committed 2026-10-03 05:14:24 EDT (commit 786b45e). A market is untouched by construction if its outcome did not exist when that file was committed. The holdout is therefore every market whose resolution time (`endDate`) is strictly after 2026-10-03 05:14:24 EDT and at or before 2026-10-04 23:59:59 EDT (resolved by the run date), and whose id does not appear in `arb_gaps.csv`.

Calendar facts checked before this commit: 2026-10-02 is a Friday, 2026-10-03 a Saturday and 2026-10-04 a Sunday. No NYSE session closes between the scan commit and the run. The last session before the commit, Friday 2026-10-02, closed at 16:00 ET on 2026-10-02, about 13 hours before the scan commit, and `arb_gaps.csv` holds scored Polymarket rows with outcomes on that date (400 rows over 200 markets, 134 markets with a scored row). The scan has no row on 2026-10-03. 2026-10-02 is excluded under both conditions of the rule (the scan scored it, and its outcomes were known before the commit).

Catalogue check (metadata only, gamma `/events/keyset`, tag 102676, end dates 2026-10-02 to 2026-10-05 03:59 UTC, closed and open): 200 "close above" markets (46 daily, 154 weekly), all ending 2026-10-02 16:00 ET and all present in `arb_gaps.csv`; one other market ends 2026-10-03 23:59 ET and fails the question parser (`out_of_scope_type`). `freeze.py` reproduces this from the listing.

**Consequence, stated before any data.** The frozen holdout list is empty (0 markets; `frozen_counts.json`). The verdict is INSUFFICIENT by the rule in section 4 and no price, quote or outcome is fetched. The earliest dates that would give a nonempty holdout are Monday 2026-10-05 (daily markets, outcomes after 16:00 ET that day) and Friday 2026-10-09 (weekly); the scan holds prices but no outcomes for 46 and 110 of their rows respectively.

## 1. Frame (frozen rule)

Identical to `fresh_accuracy` section 1 (closed market, `arbscan.parse.parse_pm_question` kind daily, weekly or monthly, CLOB token and `endDate`, not an R3 id or R3 resolution date), applied by `freeze.py` to the gamma listing with event end dates 2026-10-02 to 2026-10-04, then restricted to (a) `endDate` in (2026-10-03T05:14:24-04:00, 2026-10-04T23:59:59-04:00] and (b) id not in `arb_gaps.csv`. Fields read: id, question, event title, ticker, strike, kind, start and end date, token and condition id. No price field is read. SHA-256 of `frozen_ids.csv` in `frozen_ids.sha256`; the runner refuses a list whose hash differs.

## 2. Snapshots, prices, rows

Unchanged from `fresh_accuracy` sections 2 and 3, by importing its code (`fresh_accuracy.rows.pm_market_rows`, `fresh_accuracy.run.Runner`, `fresh_accuracy.stats`), not modifying it: S1 = 15:45 ET on the prior NYSE session, S2 = 12:00 ET on the resolution date; snapshot strictly before `endDate` and at or after `startDate`; PM price = last CLOB point at or before the snapshot, stale if older than 900 s; exact 0.500 dropped; [0.02, 0.98] filter; clean expiry (calls listed expiring on the resolution date); narrow call spread with `p = e^{rT}(C1 - C2)/w`, r = 4%; option legs at most 600 s old, never filled from a later quote; outcome from gamma `outcomePrices`, read only after the coverage gate.

## 3. Test

`d_B = (p_PM - y)^2 - (p_opt - y)^2` and `d_L` as in `fresh_accuracy` section 4; positive means options were more accurate; row-weighted means.

**Primary interval.** All markets share at most a few resolution dates, so the primary 95% interval is a cluster bootstrap over **underlying tickers** (10,000 draws, seed 20261004, percentile). Also reported: the event-clustered interval (ticker x resolution date; identical to the ticker interval when there is one date) and the date-clustered interval when there is more than one date.

## 4. Verdict rule (fixed now)

- **INSUFFICIENT** if fewer than 100 scored rows with outcomes. Report what exists, no claim.
- **PASS** if mean `d_B` > 0 and its ticker-clustered 95% interval lies above 0.
- **DIRECTION-CONSISTENT** if mean `d_B` > 0 and the interval includes 0.
- **FAIL** if mean `d_B` <= 0.

`d_L`, Brier and log score of each forecast, mean PM age and mean option-leg age, and the subset with PM age at most 30 s are reported and never change the verdict.

## 5. Outputs

`research/results/fresh_accuracy_latest/`: `rows.csv`, `summary.json`, `SUMMARY.md`, `RUN_LOG.md`, and `.done`, which makes `run.py` refuse a second run.

## Amendments

(none)
