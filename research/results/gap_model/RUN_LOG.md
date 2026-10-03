# Expected-gap OOS run log

One entry per run of `python -m gap_model.run`: code commit, wall time, network requests, exit status.

## 2026-10-03 16:52:25Z
- code commit: `2068ed5`
- mode: analysis of saved closure tables (panel A + panel B)
- wall time: 2 s
- network requests: 0
- result: 327 test closures; sign accuracy 141/235 (60.0%, p = 0.00262); slope +1.25 (permutation p = 0.0003); verdict: Accurate out of sample
- exit: 0

## 2026-10-03 16:53:22Z
- code commit: `210afc3`
- mode: report regeneration after the display-only Amendment 1 (same code path, seeded); predictions.csv byte-identical and tests.json identical to the 16:52:25Z run
- wall time: 2 s
- network requests: 0
- result: 327 test closures; sign accuracy 141/235 (60.0%, p = 0.00262); slope +1.25 (permutation p = 0.0003); verdict: Accurate out of sample
- exit: 0

Inputs read by both runs (sha256): `research/results/leadlag_closed/closures_all.csv` 228bbe4dec56c82070005aab4cc8fe7f0c7d4838b5a14b0c80c391a829457c9c (committed); `research/results/leadlag_replication/results.csv` 5f88a2c7bb4d017f47d09054a2ff7e4ac1ad0e3d67f2d84af7e1762bc2d55b19 (written by the replication run that finished 12:52 ET, not yet committed by that task at the time of these runs).
