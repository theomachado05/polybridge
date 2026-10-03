# Expected-gap model: out-of-sample accuracy (pre-registered, plan task R2)

**Question.** The product's closed-market mode shows an *expected open gap* = rate x PM move, with a per-market rate estimated from that market's own past closures and a pooled fallback (plan `docs/superpowers/plans/2026-10-03-closed-market-mode.md`, Product behaviour item 3). Is that number accurate **out of sample**: if each rate is fitted only on closures that ended before the test closure began, does the predicted gap get the sign of the realized SPY open gap right more than half the time, and does the realized gap rise with the predicted gap?

This file and `config.py` are committed **before any statistic of this study is computed**. Every parameter below is fixed here. A later change goes under "Amendments" with the reason; the original stays in git history. The study is run once and reported whatever it shows.

**No data is fetched.** The study reuses saved closure tables (section 2). No 8-K disclosure data, no option data and nothing dated 2026 is read or requested.

## 0. What was looked at before this commit (honesty)

- The published results of the closed-market study on the same panel (`research/results/leadlag_closed/SUMMARY.md`): full-sample pooled slope +7.52 bp per pp (OLS with intercept, HC3 t 2.58, permutation p 0.001), 60% sign agreement at |move| >= 1 pp; recession market about 70% agreement, election market about 47%. **This test therefore runs on a panel whose full-sample relation the author already knows.** The expanding-window design limits but does not remove that bias (section 7).
- Row counts of `closures_all.csv`, to fix the minimum training size: 397 rows, of which 380 unselected placebo closures (election 149, recession 231) and 17 news closures; non-zero oriented PM moves among all 397 rows: election 108, recession 164. A one-line `describe()` of the oriented move and the SPY gap over all 397 rows was printed (move SD 2.7 pp, gap SD 69 bp). Nothing else, and no fitted rate, prediction or accuracy figure.
- The replication panel (`research/results/leadlag_replication/results.csv`) does not exist at this commit; its run belongs to another task. Its code was read only for the column names.

## 1. Model (what the product will compute)

- **Oriented PM move** `x` (pp): the change in the market's Yes price over the closure, times the market's fixed sign (+1 if Yes is good for US equities, -1 if bad), as defined in the source studies. A positive `x` means the PM moved in the equity-bullish direction.
- **Rate** (bp of SPY open gap per pp of `x`): least squares **through the origin**, `rate = sum(x*g) / sum(x^2)`, over the training closures of that market. No intercept, because the product's formula is `expected gap = rate x move`: a closure with no PM move gets an expected gap of 0.
- **Standard error of the rate:** HC3 for the through-origin fit, `h_i = x_i^2 / sum(x^2)`, `se^2 = sum(x_i^2 * (e_i / (1 - h_i))^2) / (sum(x^2))^2`. Also kept: the residual SD `s = sqrt(sum(e^2) / (n - 1))`.
- **Minimum training size `N_MIN = 20`** closures with `x != 0` (closures with `x = 0` add nothing to the through-origin rate).
- **Per-market rate** if the market has at least `N_MIN` non-zero training closures. **Pooled fallback** otherwise: the same estimator over the training closures of **all** markets in the analysis set. If the pooled training set also has fewer than `N_MIN` non-zero closures, no prediction is made (burn-in; the closure is not a test closure).
- **Predicted gap** for a test closure: `pred = rate x x` (bp).
- **Band** (secondary, section 4): the nominal 80% interval `pred +- 1.2816 * sqrt(x^2 * se_eff^2 + s^2)`, with `se_eff = se` for a per-market rate and `se_eff = sqrt(se_pooled^2 + tau^2)` for the pooled fallback, where `tau` is the SD (ddof 1) of the per-market rates of the training markets that have at least `N_MIN` non-zero closures; if fewer than two such markets exist, `tau = |pooled rate|`. This is the "wide band" for a market with too little history.

## 2. Data and panels

- **Panel A (primary):** the 380 unselected placebo closures of the closed-market study, `research/results/leadlag_closed/closures_all.csv`, rows with `news == False`: Trump-wins market (`will-donald-trump-win-the-2024-us-presidential-election`, sign +1, closures starting 2024-04-01 to 2024-11-04) and US-recession-2025 market (`us-recession-in-2025`, sign -1, closures starting 2025-01-10 to 2025-12-30). Columns used: `closure` (close day), `open_day`, `market`, `dpm_o_pp` (= `x`), `gap_bp` (SPY), `gap_qqq_bp`, `kind`.
- **Mapped ETF.** Both panel-A markets map to SPY in the source study (broad macro/political markets), so the mapped-ETF test is the SPY test. QQQ is a secondary outcome.
- **Panel B (secondary, conditional):** the replication panel `research/results/leadlag_replication/results.csv` (10 rule-selected markets, SPY primary, QQQ secondary), used **only if the file exists with at least one usable row when this study is run**. Usable = empty `reason`, finite `x_pp` and `gap_spy_bp`. If it does not exist, the summary says "not available at run time" and nothing is waited for or fetched.
- Usable rows: finite `x` and finite outcome gap. Nothing else is removed.

## 3. Out-of-sample procedure (expanding window)

1. Sort the analysis set by close day `closure` (ties: by market name).
2. For each closure t of market m, the **training set** is every row of the analysis set with `open_day <= closure(t)`: closures whose realized gap was known by 09:30 ET of the close day of t, i.e. before t began at 16:00 ET. This excludes t itself and any same-day row of another market.
3. Fit the market rate on the training rows of m and the pooled rate on all training rows, choose per section 1, predict `pred_t`. Record the source (`own` or `pooled`), the rate, its n and SE.
4. The test set is every closure with a prediction.

## 4. Tests (two-sided, alpha 0.05, no multiplicity adjustment)

**Primary (panel A, SPY):**
- **G1, sign accuracy.** Among test closures with `pred != 0` and `gap != 0`: hits = `sign(pred) == sign(gap)`. Exact two-sided binomial against 0.5.
- **G2, slope.** OLS `gap = a + c * pred` over all test closures. Reported: `c`, HC3 t, R-squared and the **permutation p-value** (10,000 shuffles of the gap vector across test closures, seed 20261003, two-sided on |c|, p = (count + 1) / (10,000 + 1)). Also reported, not in the verdict: the HC3 t of `c - 1` (a calibrated model has `c = 1`).

**Verdict (fixed now, applied literally).**
- **"Accurate out of sample"** if both hold: (i) G1 accuracy > 50% with binomial p < 0.05; (ii) G2 `c > 0` with permutation p < 0.05.
- **"Partial"** if exactly one holds.
- **"Not accurate out of sample"** otherwise.

**Calibration table (primary panel, reported):** test closures grouped by predicted gap (bp): `<= -10`, `(-10, -3]`, `(-3, 0)`, `= 0`, `(0, 3)`, `[3, 10)`, `>= 10`. Per bucket: n, mean predicted, mean realized, median realized, sign hit rate (where pred and gap are non-zero).

**Secondary (reported, not in the verdict):**
- G1 restricted to test closures with `|x| >= 1.0 pp` (tolerance 1e-9).
- G1 and G2 with the QQQ gap as outcome (rates refitted on QQQ gaps).
- G1 and G2 by market and by rate source (`own` vs `pooled`).
- Out-of-sample R-squared against a zero forecast, `1 - sum((g - pred)^2) / sum(g^2)`, and against the expanding mean of all past training gaps, `1 - sum((g - pred)^2) / sum((g - mean_past)^2)`.
- Empirical coverage of the nominal 80% band (section 1), overall and by source.
- All 397 closures (the 17 hand-picked news closures added back), G1 and G2.
- Panel B, if available (section 2): the same procedure on panel B with per-market rates from panel-B rows and the pooled fallback over all training rows of panels A and B. G1 as above; G2 with the permutation over **closure dates** (one permutation of the date-to-gap map applied to every row of that date), because rows of different markets share dates.

## 5. Product export (`backend/app/data/gap_rates.json`)

Written by the same run, from the **full** usable sample (no holdout), because the product uses all history available up to now:
- Per market (panel A, plus panel B markets if available): slug, Yes token id, sign, mapped ETF (`SPY`), rate on the oriented move (bp per pp), rate on the raw Yes-price move (`sign * rate`), HC3 SE, residual SD, n, n with `x != 0`, first and last closure, and `use` = `own` if n with `x != 0` >= `N_MIN`, else `pooled`.
- Pooled rate over every usable row in the export, with the same fields; `tau` (between-market SD of the own-rate markets, ddof 1); `N_MIN`; the band rule of section 1; the out-of-sample verdict and headline figures; provenance (generator, git commit, method path).

## 6. Outputs

`research/results/gap_model/`: `SUMMARY.md` (generated), `predictions.csv` (every test row with source, rate, prediction and band), `tests.json`, `chart.png` (realized vs predicted with the fitted line and the calibration-bucket means; rate path over time), `RUN_LOG.md` (commit, wall time, network requests = 0, exit status). Code: `research/gap_model/` (`config.py`, `model.py`, `run.py`), reusing `leadlag_closed.stats` (HC3 OLS, binomial). Synthetic tests: `research/gap_model/tests/`.

## 7. Caveats stated in advance

- **Known panel.** Panel A is the panel on which the full-sample relation was found. An expanding-window test cannot use future closures, but the choice of model form (through-origin, `N_MIN`) was made knowing the full-sample result. Panel B (if available) is the cleaner check because its prices were not seen by the author.
- **Two markets, two regimes.** Panel A has two markets in disjoint years. The pooled fallback for the recession market's first closures is in effect the election-market rate, a different market in a different year. This is the situation the product faces for a new market and is kept on purpose.
- **Co-movement, not lead.** The PM move and the gap span the same closure. E-mini futures and pre-market SPY trade during the closure and are not observed. An accurate expected gap means the PM closure move is informative about the gap the equity open shows; it does not mean the gap can be captured after the fact.
- **Heavy tails.** One closure (the 2024 election night, a news closure, not in panel A) moved 38.6 pp. The permutation p-value is the primary slope inference for this reason.
- **Many zero moves.** Closures with `x = 0` get `pred = 0`; they enter G2 and the calibration table but not G1.
- **Serial dependence.** Consecutive closures of one market are not independent; binomial and HC3 inference treat them as such and are somewhat optimistic.

## Amendments

(none)
