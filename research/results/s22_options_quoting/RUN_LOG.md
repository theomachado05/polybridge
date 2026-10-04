# S22 run log

- 2026-10-04 00:41:16 NY: run starts at commit 866d512; no network; input `research/results/pm_taker_v2/prints_evaluated.csv` at commit fb66dc7
- 2026-10-04 00:41:16 NY: input read: 1155 rows, 970 with status ok, sha256 ebf27079a5556860d9032a9e92bc3218d59eebc19295001c5e65caa9bc2734f0; 324 markets, 48 resolution dates 2026-04-01 to 2026-08-14; taker sides {'SELL': 488, 'BUY': 482}
- 2026-10-04 00:41:16 NY: out-of-sample fixed before any fill is computed: the last 10 of 48 dates, 2026-07-07 to 2026-08-14
- 2026-10-04 00:41:16 NY: primary_m5: 74 fills; {'prints_through_quote': 74, 'dropped_no_size': 0, 'dropped_no_result': 0}
- 2026-10-04 00:41:16 NY: m2: 300 fills; {'prints_through_quote': 300, 'dropped_no_size': 0, 'dropped_no_result': 0}
- 2026-10-04 00:41:16 NY: m10: 21 fills; {'prints_through_quote': 21, 'dropped_no_size': 0, 'dropped_no_result': 0}
- 2026-10-04 00:41:16 NY: stress_m7_through_1c: 29 fills; {'prints_through_quote': 29, 'dropped_no_size': 0, 'dropped_no_result': 0}
- 2026-10-04 00:41:16 NY: tick_grid_m5: 68 fills; {'prints_through_quote': 68, 'dropped_no_size': 0, 'dropped_no_result': 0}
- 2026-10-04 00:41:16 NY: benchmark_every_print_at_px: 970 fills; {'prints_through_quote': 970, 'dropped_no_size': 0, 'dropped_no_result': 0}
- 2026-10-04 00:41:16 NY: verdict on the pre-registered pass rule: FAIL; 1. at least 100 fills: FAILED (74 fills); 2. fills on at least 30 resolution dates: FAILED (27 dates); 3. mean above zero, whole sample: held (+24.51 pt, 74 fills); 4. 95% interval excludes zero, whole sample: held ([+8.57, +37.52]); 5. mean above zero in-sample: held (+27.39 pt, 65 fills); 6. mean above zero out-of-sample: held (+3.77 pt, 9 fills); 7. mean above zero under the stress: held (+6.01 pt, 29 fills)
- 2026-10-04 00:41:16 NY: book (primary): {'resolution_dates_in_sample': 48, 'dates_with_fills': 27, 'days_per_year': 128.9118, 'total_pnl_usd': 623.9705, 'total_capital_usd': 1036.5404, 'return_on_capital': 0.602, 'bankroll_usd': 181.1934, 'sharpe': 2.8232, 'max_drawdown_usd': -145.8818, 'max_drawdown_share_of_bankroll': -0.8051, 'worst_month': '2026-06', 'worst_month_pnl_usd': -50.6859, 'worst_month_share_of_bankroll': -0.2797, 'winning_dates': 21, 'losing_dates': 6, 'best_date': '2026-05-06', 'best_date_pnl_usd': 288.5336, 'worst_date': '2026-05-13', 'worst_date_pnl_usd': -76.4978, 'sharpe_without_best_date': 2.4355, 'best_market_share_of_pnl': 0.4072}
- 2026-10-04 00:41:16 NY: book (stress): {'resolution_dates_in_sample': 48, 'dates_with_fills': 18, 'days_per_year': 128.9118, 'total_pnl_usd': -37.154, 'total_capital_usd': 540.2697, 'return_on_capital': -0.0688, 'bankroll_usd': 86.4993, 'sharpe': -0.4039, 'max_drawdown_usd': -151.4607, 'max_drawdown_share_of_bankroll': -1.751, 'worst_month': '2026-05', 'worst_month_pnl_usd': -78.7536, 'worst_month_share_of_bankroll': -0.9105, 'winning_dates': 11, 'losing_dates': 7, 'best_date': '2026-04-17', 'best_date_pnl_usd': 74.3963, 'worst_date': '2026-05-13', 'worst_date_pnl_usd': -74.4978, 'sharpe_without_best_date': -1.4236, 'best_market_share_of_pnl': -2.0024}
- 2026-10-04 00:41:16 NY: files written: metrics.csv, trades.csv, trades_variants.csv, daily.csv, equity_curve.png, drawdown.png, capacity.md

## Timeline, commits and sources (written by hand after the run; hashes read from `git log`)

- Data source: one file, `research/results/pm_taker_v2/prints_evaluated.csv`, read with `git show` from commit `fb66dc7` of `origin/r/thesis-pass-2` (git blob `7597b31`, sha256 above). No network call of any kind. No key read.
- 00:33 to 00:36 NY: read PARALLEL_BRIEF.md and, with `git show` only, the partner's SUMMARY.md, METHOD.md, config.py, core.py, run.py, report.py, the progress lines of their RUN_LOG.md, and `arbscan/implied.py` and `arbscan/datasrc.py`. No row of the input file, their trades.csv or stats.json was opened.
- `afb1cec`, 2026-10-04 00:36:40 NY: METHOD.md and config.py committed and pushed, before any row of the input file was read. (The header of METHOD.md says "about 00:45", the time given in the brief; the machine clock at the commit was 00:36:40.)
- `866d512`, 2026-10-04 00:41:12 NY: run.py, 23 unit tests on synthetic rows (all pass, exit code 0) and amendment A1 (the benchmark row), committed and pushed, still before any row of the input file was read. The runner was smoke-tested on random synthetic rows in the scratchpad first; that is where a chart-label fault (dollar signs read as maths) was found and fixed before this commit.
- 00:41:16 NY: the run, one invocation at commit `866d512`, lines above. Not rerun.
- 00:42 to 00:46 NY: looks after the run. First an inline script, then the same looks saved as `post_run.py` and rerun to write `post_run.csv`. The independent recomputation in plain pandas matched the runner: 74 fills, 27 dates, 46 markets, +24.51 points, offer 15 at -6.24, bid 59 at +32.33, $623.97 on $1,036.54. Three fills were checked by hand against the raw rows. Tests rerun: 23 pass, exit code 0.

## What went wrong

- The pass rule failed on sample size: 74 fills (100 needed) on 27 resolution dates (30 needed).
- The Sharpe of the primary book is 2.82. That is under the "above 3" line of the house rules, but close, so the checks were run anyway (above). It rests on 27 active dates, a mostly long-YES book in a window where YES kept winning, and one market that made 40.7% of the dollars.
- SUMMARY.md was not written by this session. The session's tooling refused to let a sub-session write a summary file. The full summary text was handed to the main session to write and commit; every number in it is in `metrics.csv` and `post_run.csv`.
- Another session pushed to the branch between this session's pushes. No conflict; only S22 paths were committed here.
