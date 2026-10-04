# S14 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 02:41:43 | `METHOD.md` and `config.py` committed (`2e1d1c0`) | Before anything was computed |
| 02:42:45 | Runner and tests committed (`a1d895e`) | Before the run |
| 02:42 | `python -m s14_link_ceiling.run` | 3 s. C1, C2 (500 shuffles), C3. The numbers in `SUMMARY.md` |
| 02:43 to 02:45 | Follow-up checks, after the run, labelled as such in `SUMMARY.md` | See below |
| 02:46 | Run repeated with one more column in `links.csv` (the share of a link's odds variation that its largest day carries) | Same seed, same numbers; no rule changed |
| 02:46 | `python -m s14_link_ceiling.report` | `SUMMARY.md` |

## Data

Nothing was pulled. The 254 links of S8 (S5's 202 agreed links without SPY, 52 of S4's), the one-minute odds and
five-minute bars of the S5 and S4 caches, 253 sessions from 2025-10-01 to 2026-10-02; out-of-sample is the last 51,
from 2026-07-23. 179 links have at least 30 sessions with an odds move over the whole sample, 167 in-sample.

## Checks made after the run (not in the method)

- **The row "every link, out-of-sample, after the open" (+9.93, t = 2.07).** It covers only links with enough
  in-sample sessions to be ranked (894 link-days). On all 1,761 out-of-sample link-days the slope is +0.81
  (t = 0.46); S5's own figure for the period is -0.63 (t = -0.37, `results/s5_big_moves/regressions.csv`); without
  its two largest dates the row is -0.95 (t = -0.74).
- **The largest link-level t's.** GOOGL on "Will Google have the best AI model" (t = -30.05): one day, 2026-10-01,
  carries 98% of the link's variation in odds. GLD and UUP on the Warsh nomination (t = 12.94 and 8.27): 2026-01-30
  carries 89%.
- **Oil links pooled:** gap +11.83 bp per point (t = 5.44), after the open -1.11 (t = -0.84), 81 links.
- **Volatility after a big odds move:** the absolute move after the open is 1.27 times the ticker's median after
  odds moves under 2 points and 1.35 times [1.21, 1.51] after 10 points or more.

## What the pre-registered reading returned

One of the two conditions for "the links are the bottleneck" was met (C2: 15.1% of links with an after-open |t| of 2
or more, against 14.0% at the 95th percentile of the shuffles). The other (C1, persistence out-of-sample) was not.
The summary reports both and explains, as interpretation, why C2's excess is not a usable link effect.
