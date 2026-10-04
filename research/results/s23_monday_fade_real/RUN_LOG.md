# S23 run log

All times New York, Sun 2026-10-04, read from the machine's clock. Commit hashes read from `git log`.

| Time | What |
|---|---|
| 00:38 | Start. Read `PARALLEL_BRIEF.md`, S6 (`METHOD.md`, `run.py`, `SUMMARY.md`, `trades.csv` header), the partner's `reopen_taker` method, code and summary with `git show origin/r/thesis-pass-2:...`. No `s23_*` folder existed, so the number 23 was free. |
| 00:39 | Structure of the inputs looked at with the result and P&L columns left unread (the partner's `y`, `pnl_t1`, `pnl_t2` were excluded from the load): row counts by tau, trade counts by time window, closure mapping, fee flags; S6's print cache sizes and field names. Everything seen is listed in METHOD.md section 0. |
| 00:42 | **Pre-registration committed and pushed: `7b9e3e4`** (`METHOD.md`, `config.py`). No P&L of this study had been computed. |
| 00:45 | Runner and 18 unit tests written; tests pass (exit code 0). **Committed before the run: `9482b64`.** |
| 00:45 | First run of `s23_monday_fade_real.run` (1 second). Exit code 0. |
| 00:47 | Checks on the passing T2 book: three trades read print by print; T2 replayed from the raw records by code that shares nothing with the runner (32 trades, +$312.62, the same). `after.py` written for the checks made after the run. |
| 00:48 | Second run after the chart code changed (labels collided in the first charts). `metrics.csv`, `trades.csv` and `staircase.csv` are byte-identical to the first run (sha256 `99cc9eef…`, `c4b82842…`, `981f6d4b…` before and after). |
| 00:51 | `report.py` wrote `SUMMARY.md` and `capacity.md` from the result files. Tests rerun: 18 pass, exit code 0. |

## Data sources (no network call was made)

| Input | Source | Version |
|---|---|---|
| S6 entries | `research/results/s6_monday_fade/trades.csv`, rows V0 at 1x costs (187) | last commit touching it `7fba6a6`; sha256 `afb781e554d037cb…` |
| S6 prints | `research/s6_monday_fade/.cache/prints_<market>.json` | on disk only (git-ignored); 180 files, 10,965 prints, largest file 919 prints |
| Partner's trades | `git show fb66dc7a07ff:research/results/reopen_taker/trades.csv` | blob `78a25dad9eed`; 1,154 rows; the run stops if the blob differs |
| Closure calendar | `open_day` of `research/results/open_options/events.csv` | 45 reopening days, 2025-11-10 to 2026-09-28 |

## What went wrong, and what could not be verified

- **The brief's window counts differ from exact seconds.** The brief gives 82 / 118 / 140 / 62 trades by time since 09:45. Those are whole clock
  minutes (prints up to 10:00:59 counted as "within 15 minutes"). On exact seconds the counts are 74 / 121 / 145 / 62. This was found before any P&L
  was read. Exact seconds were fixed as the primary and the clock-minute reading as a reported variant. Both fail H1 and H2.
- **T1 could not pass, and that was known before the run:** the first 15 minutes hold 6 trades in the most recent 20% of closures against the 30 the
  pass line needs. Written into METHOD.md section 0 before the commit.
- **One unit test had a wrong expected value** (my arithmetic: a print I expected to miss the 2-point line cleared it by 0.1 point). The test was
  corrected before the first run; no rule and no code changed.
- **`after.py` crashed once** on a column that pandas read as text (`s6_verified` is empty on the T1 rows). Fixed by casting; no result changed.
- **The charts were redrawn once.** Result files identical, as above. `run_meta.json` records code commit `9482b64`; the chart changes were
  committed afterwards with the results.
- **Not verifiable offline:** that the `side` field of a print is the taker's side (S6 and the partner's study assume it, and so does this one); the
  fee flag of each S6 market (T2 charges the fee on every trade, which errs against the trade); the partner's raw prints (its cache is not on this
  machine, so T1 rests on its committed `trades.csv`, whose 1x P&L column this run reproduces exactly from price, side, fee flag and result).
- **Bootstrap seeds and draws differ from S6's** (10,000 draws, seed 20261004, against S6's 2,000 draws, seed 0), so the interval of the modelled
  row reads +$14.89 to +$26.22 here against S6's published +$15.08 to +$26.28. The same for the verified set: -$3.85 to +$38.71 against -$3.99 to +$36.94.
- **Sharpe convention:** 52 closures a year as the brief asked. S6 used 51.0, so its 4.27 reads 4.31 here.

## Looked at after the run

Listed in SUMMARY.md under the heading of that name and written to `after_run.json` by `after.py`: an interval for the T2 Sharpe, the plain
t-statistic, print timing, size concentration, duplicated records, the overlap with S6's verified set, and the independent replay. None of it
changes a verdict or a rule.
