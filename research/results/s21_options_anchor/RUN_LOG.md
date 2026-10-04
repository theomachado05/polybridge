# S21 run log

All times New York, Sun 2026-10-04. Branch `r/weekend-options`. Commit hashes read from `git log`.

## Timeline

| Time | What |
|---|---|
| 00:13 | Session start. No `s21_*` folder existed, so the study is S21. Read PARALLEL_BRIEF.md, S18's SUMMARY.md, `prints_markets.csv`, `run.py`, `report.py`, and the option code (`arb/arbscan/datasrc.py`, `implied.py`). |
| 00:17 | Parsing rules written and checked on catalogue metadata only (no option data): all 424 stock and S&P markets parse, 0 dropped. |
| 00:19 | **Pre-registration commit `df3cb4a`** (METHOD.md, config.py, the parsing code), pushed. No option quote had been requested. |
| 00:20:43 | Probe: one market (AAPL "hit $285 before 2026") anchored online, 7 requests, to see that Massive answers; and one contract listing for SPX (no quote) to see that index options are served under the underlying `SPX`. Both worked. |
| 00:20:55 | Full pull started: one worker, at most 2 requests a second. |
| 00:25 | Code commit `146ebb1` (pull, anchor builder, the three tests, report, 16 unit tests), pushed while the pull ran and before any result was read. |
| 00:37:53 | Pull finished: **2,015 requests in 1,018 s, 0 errors, 2.0 requests a second throughout.** |
| 00:38 | First full run of the tests. Books show a Sharpe above 3, so the bug hunt below was done before anything was written up. |
| 00:42 | METHOD.md amendment 2 (the bug hunt's checks, added after the result, not pre-registered). |
| 00:45 | SUMMARY.md, charts, capacity.md written from the result files; 18 unit tests pass (exit code 0). |

The result commit (`1fce155`, 00:46) is recorded at the end of this file.

## Data sources

- **Polymarket side: nothing pulled.** Traded prices, P&L, results, segments and sizes are S18's `prints_markets.csv`; entry and result times are S18's `entries.csv`; question, label, sign and listing time are the universe records of S9 and S15. No call to Polymarket or Kalshi was made.
- **Options: Massive only.** `/v3/reference/options/contracts` (calls of one underlying and one expiry, `expired=true`) and `/v3/quotes/<option>` (`timestamp.lte` = the anchor instant, newest first, limit 1). Cache: `research/s21_options_anchor/.cache/cache.jsonl`, 2,023 lines, 748 KB (2,015 from the pull, 8 from the probe). Not committed.
- **The session clock** (which Friday, half sessions): SPY five-minute bars in `s5_big_moves/.cache/eq_SPY.npz`.

## The recorder

`fetch failed` lines in `research/forward/recorder.log` (read only): **51 before the pull, 51 during every check, 51 after.** The pull never had to slow down. The recorder was not touched.

## What went wrong, and what could not be verified

1. **The pass rule could not be met, and this was known before the pull.** Only 30 of the 424 markets are in S18's out-of-sample events and 15 of those have a taker sale; B0 holds 2. Line (4) needs 30. METHOD.md section 7 says so in advance.
2. **37 markets have no anchor** (387 of 424 anchored): 24 with no quote at or before the instant on the bracketing strikes, 9 with no usable pair of legs, 4 with no listed strikes around the level. **18 of them are Netflix** (8 of its 26 markets anchored): the 10-for-1 split of November 2025 changed the option symbols and strikes, and the rules drop those markets rather than repair them. The others: SPY 7 (levels far from the price on 1 May and 31 July 2026 whose neighbouring strikes had no quote yet, most likely because they were listed later), SPX 4 (June levels asked for on 9 January), PLTR 3, and one each of AMZN, GOOGL, MSFT, OPEN, RKLB.
3. **214 of the 387 anchors moved a leg outward** by one or two listed strikes, because the nearest strike had no quote at the instant (strikes that were listed later). The bracket is then wider (median width 10 dollars, 2.5% of the level, against 5 dollars and 1.8% where no leg moved), and the anchor is the average probability over the bracket. On the 128 markets with a taker sale whose anchor needed no leg moved the filtered book still earns (+21.27 [+1.13, +36.57], 30 markets) but the markets it leaves earn +12.99 [+7.86, +17.80]: the gap between taken and left is smaller there. Reported in `checks.csv` and in the summary.
4. **A zero bid was accepted on a leg** (15 anchors), a stated difference from the existing code, fixed before the pull. R1 reruns the primary without them: +23.40 [+10.73, +34.42] on 56 markets.
5. **Clerical:** METHOD.md's header says "about 00:45"; the pre-registration commit was made at 00:19. Recorded as amendment 1; git's timestamp is the record.
6. **Debug runs on a partial cache.** While the pull was running, `run.py` and `report.py` were each executed twice on the partial cache to see that the code ran; their output was sent to a scratch file and only the exit code and tracebacks were read. No result was read before the pull finished, and no rule, threshold or bucket was changed at any time.
7. **Not verified:** Massive's NBBO records against a second source; the taker side of S18's prints (taken as S18 reports them); that each S&P index question resolves on the index level the SPXW options settle on; whether news on the Saturday or Sunday explains why some tickets traded far above Friday's anchor (the anchor is Friday 15:55, the tickets traded Friday 20:00 to Sunday 20:00).

## The bug hunt (a Sharpe above 3 was reported, so the rule applies)

Sharpe above 3, at 1× fee: U (S18's unfiltered book on the anchored markets) 3.24, in-sample 3.69; U-all (the same on all 303 stock and S&P markets with a taker sale) 3.03, in-sample 3.38; B1 in-sample 3.00. B2's -3.78 is two markets and three months and means nothing. The primary B0 is 2.70 (in-sample 2.86).

What was checked, in order:

- **Recomputed independently** (a separate script reading the raw cache and S18's file, not the study's code path): all 387 anchors from their two cached leg quotes: 0 mismatches; the option type (calls for up, puts for down), the strikes inside the symbols, the expiry inside the symbols, the bracket around the level: all assert clean. T1's five bucket means and counts, the mean and count of B0, B1, B2, R1, U, U-left and U-all in every segment, and B0's book dollars: all equal to the files.
- **No look-ahead.** Every leg quote is between 0.001 and 305 seconds older than the anchor instant; the instant is 14,700 seconds (4 hours 5 minutes) before the first traded price on a full session and 25,500 seconds on the half session of 2025-11-28. The rule selects on the anchor and S18's traded price only; the result enters only the P&L.
- **Where the Sharpe comes from.** The largest values belong to S18's own unfiltered book, which never uses the anchor. Monthly P&L of U: one losing month in eleven (-$52 in December 2025 on a capital base of $3,678). B0: no losing month in ten, capital base $752. With ten or eleven monthly numbers a Sharpe is known to about plus or minus 2.5 (`checks.csv`). This is the Sharpe of selling insurance over months in which the insured moves mostly did not come; it is a small-sample number, not a property of the rule.
- **Is it the anchor or only the price level?** Anchors shuffled across markets (5,000 draws): taken minus left +4.00 [-3.49, +11.45]; none of the draws reaches the observed +19.19. Inside each of S18's five traded-price buckets the taken markets earned more than the left ones. With the price level held fixed in a regression the gap's coefficient is -0.569 [-1.05, -0.08] for buyers and +0.747 [-0.10, +1.59] for sellers (the sellers' interval includes zero).
- **Small prints.** Each market counts once in the per-contract means. B0 on markets with 100 or more printed contracts: +30.23 [+11.16, +44.06] (29 markets); under 100: +14.83 [+2.73, +26.83] (31). Weighted by the contracts the book holds: +29.08.
- **One bet per Friday.** Resampling the 13 Fridays instead of the 33 events: B0 +22.27 [+11.11, +32.04]; taken minus left +19.19 [+4.74, +29.24]; T1 slope -0.605 [-1.033, -0.076].
- **A stricter rule, for robustness only.** Selling only when the traded bid is 5 or more points above the top of the anchor's band: +28.52 [+14.08, +40.52] on 25 markets.

No bug was found. The checks were added after the result was seen and are labelled so everywhere; none replaces a pre-registered test.

## Tests

`cd research && .venv/bin/python -m pytest s21_options_anchor/tests -q` : 18 passed, exit code 0.

## Commits

| Hash | What |
|---|---|
| `df3cb4a` | Pre-registration: METHOD.md, config.py, parsing rules. Before any option quote. |
| `146ebb1` | Pull, anchor builder, tests T1 to T3, report, 16 unit tests. During the pull, before any result was read. |
| `1fce155` | The result: SUMMARY.md, every result file, the bug hunt (`checks.py`, METHOD.md amendments 1 and 2), 18 unit tests. 00:46. |
