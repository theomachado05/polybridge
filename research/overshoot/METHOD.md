# T4: overshoot or slow options at the Monday open? (method, committed before any statistic of this study is computed)

Question: R3 (`research/results/open_options/`) found that options at 09:45 on the reopening day reflected 0.44 of the prediction-market (PM) closure move. How much of the gap between the PM move and the option move is the PM overshooting (it gives the move back after the open), how much is options lagging (they close the gap later in the day), and how much is left at the end of the reopening day? Separately, which of the two prices is the better forecast of how the contract actually resolved?

This file and `config.py` are committed in one commit before any number of this study is computed. Every rule below is fixed here. A later change goes under **Amendments**, dated and marked pre- or post-data. The study is run once (`.done` marker) and reported whatever it shows. A null is an acceptable answer.

## 0. Status and what was already seen (honesty)

**This is a pre-registered re-analysis of already-seen data. It is not confirmatory.** It uses only the rows R3 committed. The following R3 results were read before this file was written (`research/results/open_options/SUMMARY.md`, `stats.json`):

- 1535 events from 44 closures; catch-up slope 0.44 [0.33, 0.57]; residual gap before costs +7.34 pt [+5.27, +9.31]; net of costs +0.79 pt [-1.21, +2.78].
- After 09:45, on the same strike pair: option move toward the PM -0.59 pt [-2.43, +0.88] (n = 1123); PM after the open -3.48 pt [-5.40, -1.62] (the PM gave back part of its move).
- Brier score on the 1535 resolved events: PM at 09:30 0.146, options at 09:45 0.120 (descriptive, no interval, no paired test).

The R3 column definitions were read in `research/open_options/measure.py` and `run.py`. No other statistic of these rows (no per-row look, no subset count beyond those R3 printed, no new combination of columns) was computed before this commit. Because the direction of the two main R3 secondaries is known, the decomposition below mostly puts intervals and shares on numbers whose sign is already known; the forecasting test adds a paired interval to a known point gap. The value of this study is the honest split and the intervals, not discovery.

## 1. Data

- Input: `research/results/open_options/events.csv`, exactly as committed by R3. Its sha256 is recorded in `RUN_LOG.md` at run time.
- **No new fetch is needed.** Every column this study uses is already in the file: `pm_close`, `pm_open` (09:30), `pm_0945`, `pm_eod` (16:00), `oc_mid` (options 15:55 before the closure), `oo_mid` (09:45), `oe_mid` (15:55 on the reopening day, same strike pair as `oo`), `outcome` (1 if YES resolved, 0 if NO, from Polymarket gamma `outcomePrices` on closed markets), `prints_in_closure`, `kind`, `closure`, `status`. So no Polymarket call and no Massive call is made. If at run time a listed column is missing, the run stops and an Amendment decides; it does not improvise a fetch.
- Nothing from `research/results/oos`, the 8-K out-of-sample window or any 8-K filing data is read.

## 2. Samples

- **E (events):** rows with `status == "event"` (R3's 1535).
- **D (decomposition sample):** E rows with `pm_eod` and `oe_mid` both present.
- **B (forecast sample):** E rows with `outcome` in {0, 1}. The close comparison additionally needs `pm_close` and `oc_mid` (always present in E by R3's filters).
- Minimum size for any verdict: at least 30 events from at least 8 distinct closures in the sample the verdict uses. Below that, the answer is "sample too small" and no claim is made.

## 3. Part (a): decomposition of the closure gap

Per event in D, with `s = +1` if `pm_open > pm_close` else `-1` (R3's sign; `|pm_open - pm_close| >= 0.03` in E so it is never zero):

- **Closure gap** `G = s * ((pm_open - pm_close) - (oo_mid - oc_mid))`. This is R3's `G`: positive when the options moved less than the PM in the PM's direction.
- **PM give-back** `R = -s * (pm_eod - pm_open)`. Positive when the PM reverses toward its Friday price after the open.
- **Options catch-up** `F = s * (oe_mid - oo_mid)`. Positive when the options keep moving toward the PM after 09:45.
- **Gap left at the end of the day** `L = s * ((pm_eod - pm_close) - (oe_mid - oc_mid))`.
- Identity: `G = R + F + L` for every event (checked in code).

Reported, each with a 95% interval: mean `G`, mean `R`, mean `F`, mean `L` over D; and the shares `share_R = sum(R) / sum(G)`, `share_F = sum(F) / sum(G)`, `share_L = sum(L) / sum(G)` (ratios of means; they add to 1). `share_R` is the part of the gap the PM gives back by the close (overshoot), `share_F` the part options close (lag), `share_L` the part neither side closes on the reopening day.

**Inference.** Closures are the clusters. Cluster bootstrap that resamples closures with replacement, 10,000 draws, seed 20261003, percentile intervals, as in R3. Every statistic in one draw uses the same resampled closures, so shares and differences are paired.

**Pass rules for (a), fixed now** (on D; minimum size from section 2):

1. **PM overshoot shown** if the lower bound of the mean-`R` interval is above 0.
2. **Overshoot is the majority of the gap** if, in addition, the lower bound of the `share_R` interval is above 0.5.
3. **Options lag shown** if the lower bound of the mean-`F` interval is above 0.
4. **Gap persists to the close** if the lower bound of the mean-`L` interval is above 0.

Verdict label: `OVERSHOOT-MAJORITY` (1 and 2), `OVERSHOOT-PARTIAL` (1, not 2) or `NO-OVERSHOOT-SHOWN` (not 1); combined with `LAG-SHOWN` or `NO-LAG-SHOWN` (rule 3); rule 4 is reported alongside as `GAP-PERSISTS` or `GAP-NOT-SHOWN-TO-PERSIST`.

Secondary for (a), reported, never used to change the verdict:

- **Same-instant version:** `pm_0945` in place of `pm_open` in `G` and `R` (removes the 15 minutes by which the option snapshot trails the PM snapshot); rows of D with `pm_0945` present; `s` unchanged.
- **Equal weight per closure:** the mean of per-closure means of `G`, `R`, `F`, `L`.
- **Subsets:** Polymarket trade print inside the closure (`prints_in_closure` true); by `kind` (daily, weekly, monthly).
- **Slopes** (OLS with intercept, cluster-bootstrap interval): `beta_open` = slope of `oo_mid - oc_mid` on `pm_open - pm_close` (R3's slope, on D); `beta_perm` = slope of `oo_mid - oc_mid` on `pm_eod - pm_close` (how much of the PM move that survives the reopening day the options had at 09:45); `beta_eod` = slope of `oe_mid - oc_mid` on `pm_eod - pm_close`.

## 4. Part (b): which price forecasts the outcome better?

Scores per event, `y` the outcome: Brier `(p - y)^2`; log score `-(y ln p + (1 - y) ln(1 - p))` with `p` clipped to [0.01, 0.99]. Lower is better for both.

Paired difference per event `d = score(PM) - score(options)`; positive means the options were the better forecast.

- **Open pair (primary):** PM at 09:30 (`pm_open`) vs options at 09:45 (`oo_mid`), on B.
- **Close pair (co-reported):** PM at the close (`pm_close`) vs options at 15:55 (`oc_mid`), on B.

Inference: mean `d` with the same closure-cluster bootstrap (paired by construction: both scores of an event stay together).

**Pass rule for (b), fixed now**, applied separately to the open pair (the headline) and to the close pair:

- `OPTIONS-BETTER` if the mean-`d` interval lies above 0 for both the Brier and the log score.
- `PM-BETTER` if it lies below 0 for both.
- `NO-DIFFERENCE-SHOWN` if neither interval excludes 0.
- `MIXED` otherwise (one score excludes 0 and the other does not, or they exclude 0 in opposite directions).

Secondary for (b), reported, never used to change the verdict:

- **Change over the closure:** per event `d_open - d_close` (Brier and log), mean with interval: did the options' forecasting edge grow or shrink over the closure?
- **Same instant:** `pm_0945` vs `oo_mid`. **End of day:** `pm_eod` vs `oe_mid` (rows with both).
- **Equal weight per closure**, the trade-print subset, and by `kind`.
- **Does the PM add anything beyond the options?** Linear-probability OLS `y = a + b1 * pm_open + b2 * oo_mid` on B, cluster-bootstrap intervals for `b1` and `b2`. "PM adds information beyond options" is stated only if the lower bound for `b1` is above 0.

## 5. Caveats the report must carry

- Re-analysis of seen data (section 0); not confirmatory.
- Overshoot and noise cannot be told apart here. Polymarket `prices-history` can be the midpoint of a thin book, and E keeps only events with a PM move of at least 3 points, so part of any give-back is mechanical regression to the mean of a noisy price. "Overshoot" in this study means "the PM gave back part of its closure move", whatever the cause. The trade-print subset is the partial check.
- The reopening day's close is the only later horizon in the data. "Never closed" means not closed by 15:55 to 16:00 on the reopening day; weekly and month-end contracts resolve later.
- The options snapshot is at 09:45 and the PM at 09:30; the same-instant secondary handles that.
- Outcomes are shared within a closure and underlying (a strike ladder on one stock resolves off one print), so the effective sample is closer to the number of closures than the number of events; the bootstrap resamples closures for that reason.
- The call spread approximates the digital and settles on a slightly different print than the PM; options are American for single names and SPY.

## 6. Outputs

- `research/results/overshoot/stats.json`: every number above.
- `research/results/overshoot/SUMMARY.md`: answer first (sample sizes, decomposition with intervals and verdict, forecasting comparison with intervals and verdict), then secondaries and caveats.
- `research/results/overshoot/decomposition.png`: the mean gap split into give-back, catch-up and left-over, with intervals.
- `research/results/overshoot/RUN_LOG.md`, `run_meta.json`, and `.done`; `run.py` refuses to run if `.done` exists.
- Tests on synthetic rows in `research/overshoot/tests` (no network), added to `research/pyproject.toml` testpaths.

Run command: `cd research && .venv/bin/python -m overshoot.run`.

## Amendments

(none)
