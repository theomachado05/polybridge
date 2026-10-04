# Prediction market versus pre-market trading over a closure (pre-registered, thesis pass 2, study T2)

**Question.** When the stock market is closed, futures and pre-market SPY keep trading. Does the Polymarket move during a closure tell us anything about the SPY opening gap **beyond what the overnight benchmark (index futures or SPY extended-hours trading) has already done by a fixed time before the open**? This is the main open objection to the closed-market relation (`research/results/leadlag_closed/SUMMARY.md`): the PM move and the gap may both just track the futures move.

This file and `config.py` are committed in one commit **before any data for this study is fetched and before any statistic of this study is computed**. Every rule below is fixed here. A later change goes under "Amendments" with the date, the reason and whether it came before or after data. Each arm is run once (a `.done` marker refuses a second run) and reported whatever it shows.

Status: a descriptive regression study. Nothing is traded. A null is an acceptable answer and goes in "what didn't work".

## 0. What was looked at before this commit (honesty)

- **The primary panel is not fresh.** It is the 380-closure placebo panel of the closed-market study, whose full-closure relation is known: +7.52 bp of SPY gap per pp of oriented PM move (HC3 t 2.58, permutation p 0.001). Its timing test T4 (PM move up to 08:00 ET against the SPY move from 08:00 ET to the open, on the 17 news closures) was null: 7 of 16 agree, slope +0.62, permutation p 0.278. Summary statistics published in `research/gap_model/METHOD.md` section 0 (over all 397 rows: oriented move SD 2.7 pp, gap SD 69 bp) are known. The columns `dpm_early_o_pp` and `resid_bp` of `closures_all.csv` exist and were produced by that study; no regression, correlation or tabulation of them on the panel has been computed by the author of this study, and none of the benchmark-controlled statistics below has ever been computed.
- **The secondary panel** (`research/results/leadlag_replication/results.csv`, 10 rule-selected markets, 1,211 usable rows over 492 dates) is also already seen: pooled slope +0.63 bp per pp, date-permutation p 0.126.
- **Futures data availability, from code and docs only (no network).** The repo's Massive client (`research/polybridge_research/massive.py`) is a generic REST wrapper; every call site in the repo uses equity aggregates (`/v2/aggs/ticker/...`), option endpoints or the 8-K disclosure endpoint. No file in the repo calls a futures endpoint, and the closed-market and replication studies say futures were not observed ("Massive equity bars only"). **Whether this key can read ES/NQ futures aggregates is unknown.** The rule for that is fixed in section 2.
- **Massive key.** At this commit no `MASSIVE_API_KEY` is present in this worktree's environment or `research/.env`. Arm M (section 4) therefore may not run in this session; arm K (section 4) needs no key.

## 1. Measures

For each closure c (from the RTH close of one trading day to the 09:30 ET open of the next, as defined in `research/leadlag_closed/closures.py`):

- **Outcome `g`**: SPY opening gap in bp, `1e4 * (open / prev_close - 1)`, exactly as `leadlag_closed.closures.equity_measures` computes it (prev_close = close of the last RTH bar of the close day; open = open of the first RTH bar starting within 5 minutes of 09:30 ET).
- **Benchmark time `T`**: primary **09:25 ET** on the open day; sensitivity **08:00 ET**.
- **Benchmark move `b_T`** (bp), the overnight move of the benchmark from the close to `T`:
  - SPY extended hours: `1e4 * (px_T / prev_close - 1)`, with `px_T` = close of the last 1-minute SPY bar that **ends** at or before `T` and no earlier than `T - 15 min`. Missing if no such bar (never imputed).
  - ES futures (if the probe of section 2 succeeds): `1e4 * (es_T / es_close - 1)` with `es_close` = close of the last 1-minute bar of the front contract ending at or before the SPY close instant (end of the last RTH SPY bar, 16:00 or 13:00 ET) and no earlier than 15 min before it, `es_T` by the same rule at `T`. Same contract at both ends.
- **Remainder `r_T` = `g - b_T`** (approximately the move from `T` to the open). Not used in the test statistic, which uses `g` directly (section 3); reported descriptively.
- **PM move to `T`, `x_T`** (pp, oriented): `sign * (pm(T) - pm(close))`, with `pm(t)` = last CLOB price at or before `t`, at most 30 minutes old (`leadlag_closed.closures.pm_at`), `close` = the SPY close instant, `sign` = the market's fixed pre-set sign from the source study (+1 if Yes is good for US equities). Missing if either price is missing.
- **PM move over the full closure, `x_full`** (pp, oriented): `sign * (pm(09:30) - pm(close))`, as in the source studies. Used only in secondary S3.

## 2. Benchmark choice (fixed now, applied once at run time)

1. Before any panel bar is fetched, arm M sends **one probe** for ES 1-minute aggregates on a fixed window, 2024-06-03 08:00 to 09:30 ET, to `GET /futures/vX/aggs/{ticker}` with `resolution=1min`, `window_start.gte`, `window_start.lt` (nanosecond UTC), trying the tickers `ESM4` then `ESM24` in that order.
2. If a probe returns HTTP 200 with at least 30 bars, the benchmark for the **whole study** is **ES** (front quarterly contract, H/M/U/Z; the front contract for a closure is the first one whose expiry, the third Friday of the contract month, is **more than 8 calendar days** after the open day; ticker spelled in the format that passed the probe), with NQ as the QQQ-secondary benchmark.
3. Otherwise (any HTTP error, empty result, unparseable rows, fewer than 30 bars) the benchmark for the whole study is **SPY extended-hours 1-minute bars** (Massive `/v2/aggs/ticker/SPY/range/1/minute`, which include pre-market, as `leadlag_closed/data.py` already fetches), with QQQ extended hours as the secondary benchmark.
4. The probe result and the chosen benchmark are written to the run log and the summary. The rule does not look at any panel outcome.

## 3. Estimator and tests

Model (OLS with intercept, rows = market x closure):

`g = a + beta * b_T + c * x_T + e`

Because `g = b_T + r_T`, the coefficient `c` is the same as in a regression of the remainder `r_T` on `b_T` and `x_T`: `c` is what the PM move up to `T` says about the gap **given** the benchmark's own move up to `T`. Both moves use the same information set (prices up to `T`).

- **Reduced model**: `g = a + beta * b_T + e`. **Incremental R-squared** `dR2 = R2(full) - R2(reduced)`.
- **Standard errors**: clustered by closure date (CR1: `G/(G-1) * (n-1)/(n-k)`). In the primary panel each date has one row (the two markets cover disjoint years), so this equals HC1; in the secondary panel several markets share a date and the same `g` and `b_T`.
- **Permutation test (Freedman-Lane, in date blocks)**: fit the reduced model, take its residuals per closure date (identical across rows of a date, because `g` and `b_T` are date-level), permute the date residuals **within blocks of calendar months** (month of the close day), add them back to the reduced fitted values, refit the full model and record the clustered t of `c`. 10,000 permutations, seed 20261003. `p = (#{|t*| >= |t_obs|} + 1) / 10,001`, two-sided.
- **Bootstrap CI** (reported, not in the verdict): 2,000 resamples of calendar-month blocks with replacement (seed 20261003), percentile 95% CIs for `c` and `dR2`.
- **PM-only comparison** (reported, not in the verdict): `g = a + d * x_T`; the share of the PM-only slope absorbed by the benchmark, `1 - c / d` (reported only if `d != 0`).

**Primary test**: primary panel (section 5), `T` = 09:25 ET, benchmark per section 2, SPY outcome.

**Pass rule (fixed now, applied literally).** The prediction market **adds information beyond the benchmark** if all three hold: (i) `c > 0`; (ii) clustered t of `c` > 1.96; (iii) Freedman-Lane p < 0.05. Otherwise: **no evidence that the PM adds information beyond the benchmark**. If `c < 0` with clustered t < -1.96 and p < 0.05, that is reported as a significant negative coefficient (not a pass).

**Secondary (reported, not in the verdict)**, each with the same estimator:
- S1. `T` = 08:00 ET, same benchmark, primary panel.
- S2. Secondary panel (replication, 10 markets), `T` = 09:25 and 08:00.
- S3. Contemporaneous upper bound: `g = a + beta * b_T + c * x_full`, `T` = 09:25 and 08:00, primary panel. `x_full` uses PM prices after `T` that the benchmark at `T` cannot see (for `T` = 08:00 this includes the 08:30 ET data releases), so a positive `c` here is not a test of added information; it bounds how much co-movement is left once the benchmark is in.
- S4. By market in the primary panel (election, recession), `T` = 09:25.
- S5. QQQ outcome with the QQQ (or NQ) benchmark, `T` = 09:25, primary panel.
- Descriptives: n, SD of `g`, `b_T`, `r_T`, `x_T`; R-squared of the reduced model; correlation of `x_T` and `b_T`.

## 4. Arms and run order

- **Arm K (keyless, runs first).** `T` = 08:00 ET, benchmark = SPY extended hours, primary panel, computed **only from the committed columns** of `research/results/leadlag_closed/closures_all.csv` (rows with `news == False` and empty `reason`): `x_T = dpm_early_o_pp` (oriented PM change from the close to 08:00 ET, same staleness rule) and `b_T = 1e4 * ((1 + gap_bp/1e4) / (1 + resid_bp/1e4) - 1)`, where `resid_bp = 1e4 * (open / px_0800 - 1)` with the same 15-minute bar rule as section 1. No network. It is the S1 sensitivity with the SPY benchmark, computed early because it needs no key. It is reported with its own line and is **not** the primary test. Its outputs go to `research/results/pm_vs_premarket/arm_k/` with marker `arm_k/.done`.
- **Arm M (needs `MASSIVE_API_KEY`).** Probe (section 2), then SPY/QQQ (or ES/NQ) 1-minute bars and fresh CLOB histories (public, reusing `leadlag_closed.data.fetch_closure_pm` and `leadlag_replication.data.fetch_market_pm`, windows close - 300 min to open + 30 min) for both panels; primary test, S1 to S5. Outputs in `research/results/pm_vs_premarket/` with marker `.done`. If the key is missing, the runner exits with code 2 before any Massive request and writes nothing but the run log line; arm M stays runnable.
- One command runs whatever has not run: `cd research && .venv/bin/python -m pm_vs_premarket.run`. Each arm refuses to run a second time once its marker exists.
- The `gap_bp` and `pm(close)` recomputed in arm M from fresh data are compared with the committed `closures_all.csv` / `results.csv` values (rows with both, max absolute difference reported). The fresh values are used.

## 5. Panels

- **Primary**: the 380 placebo closures of `closures_all.csv` (`news == False`, empty `reason`): election market (sign +1, closures starting 2024-04-01 to 2024-11-04) and recession market (sign -1, 2025-01-10 to 2025-12-30); tokens from `research/leadlag_closed/events.yaml`. **Already seen; not confirmatory evidence for the original relation, but the benchmark-controlled question has not been computed on it.**
- **Secondary**: rows of `results.csv` with empty `reason` (10 markets; token ids and signs from `research/leadlag_replication/markets.json`).
- Usable row for a test: finite `g`, `b_T`, `x_T` (or `x_full` for S3). Nothing else is removed. Rows with `x_T = 0` stay in.
- Nothing dated 2026 is requested (the equity fetcher clamps at 2025-12-31). No 8-K data, no option data, nothing under `research/results/oos`.

## 6. Expected n and power (before data)

- **n.** Primary: up to 380 closures (380 dates). Expected losses: closures without a SPY bar ending in [09:10, 09:25] ET (rare: pre-market SPY trades every minute near the open on almost every day) and PM prices staler than 30 minutes at `T` (the source study needed the same at 09:30). Expected about 360 to 380. Secondary: up to 1,211 rows over 492 dates.
- **Power, primary (T = 09:25).** `SE(c) ~ sd(e) / (sd(x_T | b_T) * sqrt(n))`. Assumed (not measured): the remainder from 09:25 to the open has SD about 10 bp; `sd(x_T | b_T)` between 1 and 2 pp (move SD 2.7 pp over all 397 rows, heavy-tailed, smaller on the placebo panel). With n = 370: SE(c) between 0.26 and 0.52 bp per pp; the minimum detectable `c` at 80% power and two-sided 5% is about 2.8 x SE, **0.7 to 1.5 bp per pp**, that is 10% to 20% of the original +7.52.
- **Power, S1 (T = 08:00, also arm K).** Remainder SD about 30 bp (includes 08:30 releases): SE(c) between 0.8 and 1.6, MDE about **2.2 to 4.4 bp per pp** (30% to 60% of +7.52).
- **Prior.** The original +7.52 did not replicate (+0.63 on new markets), T4 was null, and the market-hours lead-lag study found no PM lead (equities, if anything, first). The discounted expectation for `c` at 09:25 is close to 0. A 5-minute remainder leaves little for any predictor; that is the point of the test: if the PM's co-movement with the gap is just the futures move, `c` collapses once `b_T` is in. A null here is informative: with the MDE above, it rules out the PM carrying more than about a fifth of the original slope as information the benchmark has not priced by 09:25.

## 7. Outputs

`research/results/pm_vs_premarket/`: `SUMMARY.md` (generated), `tests.json`, `rows_primary.csv`, `rows_secondary.csv` (arm M); `arm_k/SUMMARY.md`, `arm_k/tests.json`, `arm_k/rows.csv`; `RUN_LOG.md` (one entry per invocation: code commit, arm, wall time, network requests, exit status). Caches go under `research/results/pm_vs_premarket/.massive_cache/` (gitignored). Code: `research/pm_vs_premarket/` (`config.py`, `stats.py`, `data.py`, `run.py`, `report.py`); synthetic tests in `research/pm_vs_premarket/tests/`.

## 8. Caveats stated in advance

- **Known panel.** See section 0. A pass on the primary panel would be a statement about that panel only.
- **SPY pre-market is thin early in the morning.** At 08:00 the last print can be minutes old and wide; that weakens the benchmark and favors finding a PM effect at 08:00 (bias against the null). At 09:25 pre-market SPY is active.
- **ES vs SPY timing.** ES trades 18:00 to 17:00 ET with a daily halt; SPY extended hours run 04:00 to 20:00 ET. Between 20:00 and 04:00 only ES moves; by 08:00 SPY has caught up through pre-market trading.
- **PM staleness.** CLOB history is at most one point per minute; the 30-minute staleness rule lets an older price stand for `pm(T)`.
- **Two markets, disjoint years** in the primary panel; serial dependence within months is handled only by the month-block permutation and bootstrap.

## Amendments

(none)
