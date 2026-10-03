# Closed-market hedging: does it reduce the loss at the open? (pre-registered, R1)

**Question.** A holder is long US equities (SPY) when the regular session closes. While the session is closed (overnight, weekend, holiday) the prediction market (PM) keeps trading. Does a hedge built from the PM signal make the profit and loss (P&L) at the next open less variable than (a) no hedge and (b) a static hedge of the same average size?

This is test R1 of closed-market mode (`docs/design.md`, sections 2 and 6). It tests the two hedges of the product spec (section "Product behaviour", items 4 and 5): hedge A (hold the adverse PM contract during the closure, unwind at the open) and hedge B (an equity hedge staged for the next session).

This file and `config.py` are committed **before any data is fetched for this study** (the only new fetch is the live Polymarket order books used for the cost assumption, section 6). Every rule and threshold below is fixed. A later change goes under "Amendments" with the reason, and the original stays in git history. One run produces the result, and the result is reported whatever it shows.

## 0. What was known before this commit (honesty)

- **The price data are not new.** The panel is the closure table of the closed-market study (`research/results/leadlag_closed/closures_all.csv`, built by `research/leadlag_closed/`, committed). Its headline statistics are known to the author: across the 380 placebo closures the SPY open gap rose +7.52 bp per pp of oriented PM move (HC3 t 2.58, R-squared 0.042, permutation p 0.001); the recession market alone showed a steeper relation than the election market; the PM move to 08:00 ET did not predict the SPY move from 08:00 ET to the open (T4, events); in the events, the first 30 minutes after the open tended to reverse the gap. Before this commit the author also printed the column means and standard deviations of the table (oriented PM move sd 2.7 pp, gap sd 69 bp, first-30-minute return sd 28 bp, 08:00-to-open return sd 26 bp, across all 397 rows) and its row counts. No hedge P&L, rate path or variance of any hedged series has been computed.
- So this is **pre-registered analysis of already-seen data**, not a fresh sample. The R-squared of 0.042 already bounds what any PM-sized hedge of the gap can achieve in sample (about a 4% variance reduction), and the author knew that when writing the criterion. The value of fixing the rules now is that the sizing, the controls, the costs and the success criterion cannot be tuned to the outcome.
- **Replication panel.** A separate agent is producing `research/results/leadlag_replication/results.csv` (10 new markets, same closure definitions). At the time of this commit only its METHOD.md is committed. Section 7 says how it is used if its results are committed when this study runs.

## 1. Data and sample

- **Primary panel:** the **380 placebo closures** of `closures_all.csv` (rows with `news == False`): every closure of the Trump-wins market (start day 2024-04-01 to 2024-11-04, sign +1) and of the US-recession-2025 market (2025-01-10 to 2025-12-30, sign -1), minus the closures of the 17 hand-picked news events. These closures were not selected on outcomes.
- **Sensitivity panel:** all 397 rows (placebo plus the 17 hindsight-selected news closures). Reported, never the headline.
- Columns used (definitions in `research/leadlag_closed/METHOD.md` section 3): `dpm_o_pp` (oriented PM change from the close to the open, pp; positive = equity-bullish), `dpm_early_o_pp` (same, from the close to 08:00 ET), `gap_bp` (SPY open over previous regular close), `ret30_bp` (SPY 10:00 price over the open), `resid_bp` (SPY open over the 08:00 ET price), `market`, `closure`, `open_day`.
- **No new price series is fetched.** No 8-K disclosure data and no option data are touched; nothing dated 2026 is read except the live order books of section 6 (current books, not history).
- Order: closures are sorted by `(open_day, closure, market)`. Each market's closures are consecutive and do not overlap, and the two panels do not overlap in time.

## 2. The rate, fitted without look-ahead

The expected gap is `E = rate x dpm_o` (bp), as in the product spec (item 3).

- For closure t of market m, `rate_t` is the OLS slope of `gap_bp` on `dpm_o_pp` (with an intercept; only the slope is used) over the **earlier closures of the same market**: those whose `open_day` is on or before closure t's `closure` day. The gap of every one of them was known at closure t's close. Closure t itself and every later closure are never used.
- **Per-market minimum:** at least 20 earlier closures of market m, of which at least 10 have `dpm_o != 0`. If that is not met, use the **pooled** slope over all earlier closures of all markets in the panel, under the same minimum. If that is not met either, there is no rate and the closure is outside the evaluation sample (below).
- **Clip at zero:** if the fitted slope is negative, `rate_t = 0` (no hedge). The product only hedges in the direction the rate implies, and a negative fitted rate means "no usable signal".
- No upper cap.

**Evaluation sample:** every closure of the panel with a rate (section 2). All strategies are evaluated on exactly the same closures. The burn-in closures are listed as excluded with the reason `no rate yet`. A closure with a missing input for a given hedge (for example no 08:00 ET price) is excluded from that hedge's comparison only, with the reason recorded; its controls are computed on the same reduced set.

## 3. Strategies (all per $1 of SPY held long at the close; all P&L in bp of that position)

### Hedge A: PM contract held through the closure (primary)

- At the close, buy `N_t = rate_t / 100` **adverse contracts** per $1 of SPY. The adverse contract is the one that gains when equities are expected to fall: YES of the recession market (sign -1), NO of the Trump-wins market (sign +1). Its price change over the closure is `-dpm_o` pp, so the PM leg earns `-rate_t x dpm_o` bp of the position.
- Unwind at the open (the product's handoff: the PM leg is closed at 09:30 ET).
- Cost: buy and sell each cross one PM half-spread `hs` (pp, section 6): `cost_A = 2 x hs x rate_t` bp.
- **Window:** previous regular close to the open. `Y_A = gap_bp - rate_t x dpm_o - 2 x hs x rate_t`.
- Unhedged in the same window: `Y_0 = gap_bp`.
- **Static control (A):** the same trade with a constant size, the mean of `rate_t` over the evaluation sample (`rbar`): `Y_SA = gap_bp - rbar x dpm_o - 2 x hs x rbar`. It has the same average size as hedge A; it differs only in that the size does not follow the market's own fitted rate.

### Hedge B: equity hedge staged for the open (primary)

- At the open, the expected gap from the last PM print before the open is `E_t = rate_t x dpm_o` (bp). Hedge fraction `f_t = clip(-E_t / K, 0, 1)` with **K = 100 bp**: an expected loss of 100 bp or more hedges the whole position, an expected gain hedges nothing. The hedge is a short SPY sale of `f_t` of the position at the 09:30 open, covered at 10:00 ET (the 09:59 bar close, as in `ret30_bp`).
- Cost: 2 bp of the hedged notional per side: `cost_B = 4 x f_t` bp.
- **Window:** open to 10:00 ET (P&L is measured from the open onward, because an order that executes at the open cannot change the gap). `Y_B = (1 - f_t) x ret30_bp - 4 x f_t`. Unhedged in the same window: `Y_0B = ret30_bp`.
- **Static control (B):** constant fraction `fbar` = mean of `f_t` over the evaluation sample: `Y_SB = (1 - fbar) x ret30_bp - 4 x fbar`.

### Hedge B, pre-market variant: executes at 08:00 ET (secondary, same criterion reported)

- Same rule with the PM at 08:00 ET: `E08_t = rate_t x dpm_early_o`, `f08_t = clip(-E08_t / K, 0, 1)`, sold at the 08:00 ET SPY price and covered at 10:00 ET.
- Window 08:00 to 10:00 ET. Position return `R08 = 1e4 x ((1 + resid_bp/1e4) x (1 + ret30_bp/1e4) - 1)`. `Y_B08 = (1 - f08_t) x R08 - 4 x f08_t`; unhedged `R08`; static `(1 - fbar08) x R08 - 4 x fbar08`.
- It uses the same rate as hedge A (fitted on close-to-open gaps).

## 4. Primary measure, inference and success criterion

- **Measure:** variance (ddof 1) of the combined P&L per $ of position in the hedge's window.
- **Variance reduction vs no hedge:** `VR0 = 1 - Var(Y_H) / Var(Y_0)`.
- **Gain vs the static control:** `VRS = (Var(Y_S) - Var(Y_H)) / Var(Y_0)` (share of the unhedged variance removed beyond the static hedge).
- **Bootstrap:** 10,000 resamples of the evaluation closures with replacement (iid over closures), seed 20261003; the same resample indices are used for every strategy so the differences are paired; 95% percentile intervals. The rates and sizes are taken as given in each resample (they were fixed by the expanding window), and the static sizes `rbar`, `fbar` are kept at their full-sample values.
- **Success criterion, per hedge (A and B are judged separately; fixed now):**
  - **"Reduces the loss variance"** if the 95% CI of `VR0` lies entirely above 0 **and** the 95% CI of `VRS` lies entirely above 0.
  - **"Partial"** if exactly one of the two CIs lies above 0.
  - **"No evidence"** otherwise. A CI that lies entirely below 0 is reported as "increases variance".
- The headline is hedge A and hedge B (09:30). The 08:00 variant and everything in section 5 are secondary.

## 5. Secondary (reported, not part of the verdict)

- Mean P&L, mean cost, 5th percentile and worst P&L of each strategy, and the mean P&L on the closures where the unhedged loss was worse than -50 bp ("bad opens").
- **Block bootstrap:** the same CIs with a moving-block bootstrap over the sorted evaluation closures, block length 10.
- **Costs:** results at `hs` = 1 tick (0.1 pp), and at 5.0 pp (the median half-spread of thin live equity-threshold books in `research/results/arb/run_meta.json`). Equity cost 10 bp per side for the 08:00 variant (pre-market spreads are wider).
- **K:** hedge B at K = 50 and K = 200 bp.
- **Per market** (election, recession) VR0 and VRS for hedge A.
- **Whole path, close to 10:00 ET:** unhedged `1e4 x ((1 + gap/1e4)(1 + ret30/1e4) - 1)`; hedge A alone (PM leg over the closure); hedge B alone (equity leg after the open); A then B (the product's handoff). VR0 of each against the unhedged whole path.
- **In-sample bound (not a strategy):** hedge A with the full-panel per-market slope (look-ahead). It shows the most a PM-sized gap hedge could have removed on these data.
- **Sensitivity panel:** the primary results on all 397 closures (news events included).

## 6. Cost inputs

- **PM half-spread `hs`:** median of the live Polymarket books at run time. Pool: gamma `/markets`, active and not closed, ordered by lifetime volume descending, the first 100 markets with an order book and CLOB token ids. For each, the CLOB `/book` of the first token (YES). Keep two-sided books with mid in [2%, 98%]. `hs = (best ask - best bid) / 2` in pp; take the median. At least 10 usable books are required; otherwise `hs = 0.5 pp` and the summary says the fetch fell short. The raw books are saved (`books_live.json`). Weekend books are what a closure hedge would actually cross, so the Saturday fetch is the relevant one.
- **Equity:** 2 bp per side of the hedged notional (fixed by the task brief; SPY's quoted spread is about one cent on a price of several hundred dollars, so 2 bp per side is a conservative allowance for spread plus fees in the regular session).
- No financing cost, no capital charge for the cash paid for PM contracts, no PM fee (Polymarket charges no fee on these markets). Stated as a caveat.

## 7. Replication panel (secondary)

If, when this study runs, `research/results/leadlag_replication/results.csv` is committed to git (checked with `git ls-files`), hedge A is applied to it with the same rules: per-market expanding rate on that market's own earlier rows, pooled fallback over all earlier rows of all its markets, the same minimums, each usable market x closure row as a separate $1 position. Its bootstrap resamples **closure dates** (all rows of a date together), because several markets share one SPY gap. Hedge B needs the first-30-minute and 08:00 prices, which that study does not compute; it is reported as not applicable there. If the file is not committed, the summary says the replication panel was not available. Uncommitted results are never used.

## 8. Outputs

`research/results/closed_hedge/`: `SUMMARY.md` (generated from the results), `closures_hedged.csv` (every closure, every strategy's P&L, rate, sizes, exclusion reason), `results.json`, `chart.png`, `books_live.json`, `RUN_LOG.md`. Code in `research/closed_hedge/`, synthetic tests in `research/closed_hedge/tests/`.

## 9. Caveats stated in advance

- **Small signal.** The known R-squared (0.042) caps the in-sample variance reduction of hedge A near 4%. A pass needs that small effect to survive an expanding-window rate and a bootstrap; a null is the expected outcome and is reported as is.
- **Hedge B cannot touch the gap** at 09:30; it can only change the variance after the open. Against a static hedge of the same average size it wins only if big expected gaps come with bigger post-open moves (a variance-timing effect), since spreading a hedge evenly is otherwise the lower-variance choice.
- **Fills are simulated.** PM fills at mid plus or minus a half-spread taken from today's books, not the historical books (Polymarket publishes no book history). Large hedges would walk the book.
- **Closures are not independent** (consecutive overnight closures share regimes). The block bootstrap is the check.
- **Two markets only, one per period**, both loosely tied to the equity market. Rates are market-specific and the recession market sits near 3-5% late in 2025, where a 1 pp move is a large relative move.
- **Variance ignores the mean.** Costs mostly shift the mean, so the mean P&L and cost are reported next to every variance.

## Amendments

1. **After the single run (commit `2068ed5`): report additions only; rules, data, sizes and verdicts unchanged.** The run gave hedge A "no evidence" and hedge B (09:30) "reduces the loss variance" (VRS lower CI bound +0.50%, just above zero; "partial" under the block bootstrap). Because a lower bound that close to zero can rest on a few closures, two **exploratory** descriptions were added to the summary, outside the verdict: (a) a concentration check, the VR0 and VRS after dropping the 1, 3 and 5 closures that contribute most to VRS, with their dates; (b) for hedge B, the sd of the first-30-minute return on closures where the hedge is active vs not, and the correlation of the hedge size with that return. Two generated sentences written before the run were wrong for the outcome and were replaced: the cost note claimed the 5.0 pp case barely moved the variance (it moved it a lot, because hedge A's cost of 2 x hs x rate varies with the fitted rate), and the product notes were rewritten to quote the results. The summary was regenerated from the saved `results.json` and `closures_hedged.csv` (`python -m closed_hedge.run --report-only`): no new fetch, no refit. Also stated: of the 100 top-volume live markets, 21 had a usable book (the rest were one-sided or priced outside [2%, 98%]), which meets the pre-set minimum of 10.
2. **Replication panel, applied after the run (primary untouched).** The single run (16:52:47 UTC) found `research/results/leadlag_replication/results.csv` not committed, so the summary said "not available". It was committed at 16:54:16 UTC (`0d24380`). Section 7 is now applied to it as a follow-up, exactly as written there (hedge A only, per-market expanding rate with pooled fallback, same minimums, the run's saved PM half-spread, bootstrap over closure dates), via `python -m closed_hedge.run --replication-only`. Its file names the oriented change `x_pp` and the SPY gap `gap_spy_bp`; the loader maps those to `dpm_o_pp` and `gap_bp` (the run's loader would have reported "columns not recognised"). Rows with a non-empty `reason` are dropped. It is reported as secondary and labelled as added after the run.
3. **2026-10-03, post-run, editorial only:** plan link repointed from the deleted docs/superpowers/plans/2026-10-03-closed-market-mode.md to docs/design.md; no rule, threshold or parameter changed.
