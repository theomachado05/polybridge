# Strategy backtest run log

One entry per invocation of `python -m strategy_backtest.run`: code commit, wall time, network requests, last session, split date, exit status. Cached responses are not counted (the cache is gitignored).

## 2026-10-03 22:14:22Z
- code commit: `d32365f`
- wall time: 9 s
- network requests: Polymarket CLOB 0, gamma 0, Massive 35 (cached responses are not counted)
- last session: n/a; first OOS day: n/a
- result: crashed: TypeError: index is not a valid DatetimeIndex or PeriodIndex
- exit: 1

## 2026-10-03 22:16Z approx. (entry written by hand: the process was killed, so its own log entry never ran)
- code commit: `f7d1f4d`
- result: stopped by hand during the Polymarket fetch after both panel-A markets showed 0 closures (empty gamma metadata for closed markets); no walk-forward, trade, metric or output file was produced. Fix `2ff3d7e`, METHOD.md Amendment 2.
- note: before the runs, 1,378 Polymarket CLOB cache files whose request URLs are identical to this study's were copied from sibling worktrees' caches (same URL, same response); they are not counted as network requests.
- exit: killed (144)

## 2026-10-03 22:18:04Z
- code commit: `8466aab`
- wall time: 188 s
- network requests: Polymarket CLOB 5463, gamma 4, Massive 0 (cached responses are not counted)
- last session: 2026-10-02; first OOS day: 2026-03-18
- result: verdict Fail (the overlay never trades in OOS (books identical, no effect))
- exit: 0

## Post-run edits (by hand, no rerun)
- SUMMARY.md verdict bullet: the generated text printed 0.00% relative drawdown and volatility changes for the no-trade case; replaced with the actual relative values from `metrics.csv` (-0.51% and -0.48%, both worse, caused by the in-sample hedge cash carried into OOS). Verdict unchanged (Fail).
- SUMMARY.md sanity section: added the explanations of the 3 gap differences vs R1 (early-close days), the 13 oriented-move differences (09:29 vs 09:30) and the closing-auction days behind the daily-close vs minute-close differences. No number changed.
- METHOD.md Amendment 2: start time of the second invocation corrected to about 22:16Z.
