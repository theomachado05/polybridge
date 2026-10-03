# Walk-forward out-of-sample test of the AI fit (pre-registered)

Written and committed 2026-10-03 16:33 UTC (12:33 ET), **before** any walk-forward code was written or run and before
any train/test number was seen. The only numbers known when this was written are the in-sample ones already in
`backend/app/data/fits.json` (122 scored hedge fits, median in-sample vs_static +0.0053, 86 of 122 above 0).

## Question

The fit pipeline (`backend/app/pipeline`) picks, for each market, one hedge preset out of every preset of the
shortlisted families, ranked by `hedge_var_reduction_vs_static` (the variance cut beyond a static short of the same
average size; `tune.py`). In `fits.json` the score of the winner is measured on the same history it was picked on, so it
is an in-sample maximum over ~100-400 presets and is biased upward. **Does the single preset the fit picks still beat a
same-size static hedge on data it has not seen?**

## Universe

Every market `precompute_fits.py` scored in the committed `fits.json` (`scored == true`; 122 markets), with the ticker,
direction and question recorded there, and the YES token from `app/data/market_universe.json` (via
`precompute_fits.load_jobs`). Shares held: 1000 (as the precompute). No market is added or removed by hand.

## Data

The same source the precompute used: live history through `app.pipeline.ticks.build_ticks` (Polymarket CLOB hourly
`prices-history` or Kalshi hourly candles, equity bars from Massive as-of joined at bar end, verified-twin overlay),
each market's chain bounded by the pipeline's 15 s budget (`service.TICKS_BUDGET_S`), falling back to recorded data
offline exactly as the pipeline does. The history is fetched once, at run time; it is the then-current ~30 day window,
so it overlaps but is not identical to the window the 11:22 UTC precompute saw (a few hours later). That is stated in
the results, not corrected for.

## Split (fixed now)

Per market, on the full aligned tick array of length `n` (time order):

* train = ticks `[0, n_train)`, `n_train = floor(0.60 * n)`
* purge = the next `n_purge = max(2, ceil(0.05 * n))` ticks, dropped (no tuning, no evaluation): the last train tick's
  hedge P&L interval and any stale daily-bar close cannot leak into test
* test = ticks `[n_train + n_purge, n)` (about the last 35 %)

A market enters the test only if both train and test have at least `MIN_TICKS` (10) ticks and at least one finite
equity price each; otherwise it is excluded and listed with the reason.

## Tune on train (exactly the pipeline)

On the train slice only: event class from the same classifier the committed run used (`classify` with
`RulesProvider`), shortlist from the engine catalog (`shortlist` + `unmet_requirements` with the requirements the
**train** slice meets), division from `choose_division(lists, 1000)`, ticks oriented with `orient_to_adverse(direction)`,
then `tune.tune(...)` with the real compiled engine (`hedgecore.replay_grid` via `EngineAdapter`). Same families,
same presets, same ranking score, same tie-breaks. If tune returns no scored preset on train (rules fallback), the
market is excluded and listed (it has no tuned pick to test).

## Evaluate on test

The train pick (family + preset index) is replayed by the same engine on the test slice with fresh state (the engine
replay starts flat; nothing is carried over). Recorded per market:

* **test vs_static of the chosen preset** = the primary per-market number. Comparison (a): vs_static is by
  definition the variance cut beyond a static short of the same average hedge ratio *on test*, so > 0 means the pick
  beat that static hedge out of sample.
* test vs_static of the **default preset of the chosen family** (`engine_adapter.default_preset`) = comparison (b).
* train vs_static of the chosen preset (the in-sample score) for the shrinkage.

Edge rules, fixed now: if the chosen preset never holds a hedge on test (no order or average hedge ratio 0), its test
vs_static is 0.0 (hedged == unhedged; that is the value by construction) and it stays in. If the engine's test
vs_static is undefined (NaN: a full static short, or an equity that never moved on test), the market is excluded from
the statistics and listed. The same two rules apply to the default preset in the paired comparison.

## Primary statistic and success criterion (fixed now)

Over the markets that enter the test, on test vs_static of the chosen preset:

* mean and median;
* sign test: count > 0 vs < 0 (exact zeros dropped), one-sided exact binomial p for P(> 0) > 0.5;
* one-sample t test of mean > 0 (one-sided);
* Wilcoxon signed-rank test of location > 0 (one-sided; zeros dropped, average ranks for ties, normal approximation
  with tie and continuity correction for n >= 25, exact otherwise).

**Success = median test vs_static > 0 AND one-sided Wilcoxon p < 0.05.** Anything else is reported as a failure to
show out-of-sample value, whatever the in-sample numbers say. No second split, no other train fraction, no re-run
with a different universe is used to change this verdict.

## Secondary (descriptive, no pass/fail)

* Comparison (b): chosen minus default preset on test, paired (median difference, sign test, Wilcoxon one-sided
  chosen > default). Does tuning beat simply taking the family default?
* Shrinkage: median train vs_static of the pick vs its median test vs_static.
* Clustering: many markets share a ticker (e.g. IBIT, VRT, ICLN), so they are not independent. Per-ticker mean of
  test vs_static, and the sign test across tickers.
* The same primary statistics restricted to markets whose test slice has at least 100 ticks.

## Outputs

`backend/scripts/walk_forward_fits.py` writes `research/results/fit_oos/`: `SUMMARY.md`, `per_market.csv`,
`chart.png` (train vs test vs_static per market, and the test distribution), `RUN_LOG.md` (command, time, engine,
data sources, every exclusion). The split/purge logic is unit-tested offline with a fake engine in
`backend/tests/test_walk_forward.py`. The run is done once.
