# Walk-forward out-of-sample test of the AI fit: results

Method pre-registered in [research/fit_oos/METHOD.md](../../fit_oos/METHOD.md) (commit `e2f1600df1cd`), committed before this code was written or run. One run, 2026-10-03T16:39:03+00:00.

**FAIL: the pre-registered criterion (median test vs_static > 0 and one-sided Wilcoxon p < 0.05) is not met.**

## Primary: test vs_static of the preset picked on train

Universe: 122 markets scored in-sample in `fits.json`; 122 entered the test (0 excluded, reasons below and in `per_market.csv`).

| | n | mean | median | > 0 / < 0 / = 0 | sign p | t p | Wilcoxon p |
|---|---|---|---|---|---|---|---|
| **test, chosen preset (primary)** | 122 | -0.4706 | -0.0040 | 19 / 72 / 31 | 1.000 | 0.999 | 1.000 |
| train, same preset (in-sample) | 122 | +0.0664 | +0.0138 | 98 / 24 / 0 | 4.2e-12 | 7.6e-09 | 2.1e-11 |
| test, family default preset | 122 | -0.1429 | -0.0152 | 16 / 75 / 31 | 1.000 | 1.000 | 1.000 |
| test, chosen minus default (paired) | 122 | -0.3277 | +0.0000 | 46 / 46 / 30 | 0.541 | 0.988 | 0.913 |
| test, chosen, markets with >= 100 test ticks | 52 | -0.8383 | -0.0115 | 10 / 40 / 2 | 1.000 | 0.993 | 1.000 |

All p values are one-sided (H1: > 0). vs_static = 1 - var(hedged) / var(unhedged x (1 - h)), h = the preset's average hedge ratio on the same window: > 0 means the preset beat a static short of the same average size, i.e. reading the prediction market added something.

## Secondary

* **Shrinkage.** The chosen presets' median vs_static falls from +0.0138 on train (where they were picked) to -0.0040 on test.
* **Tuning vs the family default.** Chosen minus default on test: median +0.0000, chosen better on 46 markets, worse on 46, Wilcoxon p = 0.913.
* **Clustering.** 25 distinct tickers; per-ticker mean test vs_static > 0 for 3, < 0 for 21 (sign p = 1.000). Per ticker: AEE -0.2475, AEP -0.0301, AMZN -0.0008, CCJ -0.2202, COIN -0.5109, DLR -0.0679, EQIX +0.0000, ETHA -0.0541, ETR -0.1264, EWZ -0.3130, GOOGL -2.0759, IBIT -0.0051, ICLN +0.0024, ITA -0.4665, IWM -0.3194, META -7.6533, MSFT -1.3735, MSTR +0.0021, SMR -0.0026, SPY -1.8450, TLT -0.0403, TSM -0.0031, VLO +0.0322, VRT -0.2009, XLE -0.3784.
* **Hindsight ceiling (descriptive only, not pre-registered).** Even the best preset of the chosen family picked *on test* with hindsight (a preset that never hedges counts as 0) beats a same-size static hedge in only 39 of 122 markets (median +0.0000). Better selection on train could not rescue the rest: on most test windows no preset of the family adds anything over a static hedge.
* **Idle picks.** 31 chosen presets never held a hedge on test (signal-triggered hedges that did not trigger); they count as 0, per the method. Of the rest, 19 are above 0 and 72 below.
* **Pick stability.** The train pick equals the full-history pick in fits.json for 38 of 122 markets: with ~100-400 presets and a few hundred hourly ticks, the winner changes when 40 % of the history is removed.
* **Mean vs median.** The mean (-0.4706) is driven by 11 markets below -1, where the pick's test average hedge ratio is high, so the same-size static benchmark has a tiny residual variance and vs_static = 1 - var(hedged) / ((1 - h)^2 var(unhedged)) explodes: SPY -13.72 (h 0.96), META -7.65 (h 0.8), GOOGL -6.07 (h 0.86), MSFT -4.07 (h 0.68), COIN -3.85 (h 0.86), XLE -3.07 (h 0.52). The median and the sign test do not depend on them, and they agree.

## Caveats

* The live history was refetched for this run (2026-10-03T16:39:03+00:00), a few hours after the committed precompute (fits.json, 2026-10-03 11:22 UTC), so the windows overlap but differ slightly; the train pick can differ from the fits.json pick (both are in `per_market.csv`).
* Each history is about 30 days of hourly ticks at most (many markets are younger), so a test slice is days, not months. Markets sharing a ticker share equity moves and are not independent; see clustering.
* vs_static benchmarks against a static hedge sized with hindsight (the preset's own average ratio on the same window), as the pipeline does.

## Excluded

* none

Files: `per_market.csv` (one row per market), `chart.png`, `RUN_LOG.md`.
