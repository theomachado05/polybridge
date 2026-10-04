# Run log: fresh-market accuracy

## Primary run

- Commit: `fe02fd6`
- Started 2026-10-03T22:28:55.552824+00:00, finished 2026-10-04T00:23:53.848916+00:00 (6898 s)
- Command: `cd research && SHARED_MASSIVE_CACHE=<shared dir> .venv/bin/python -m fresh_accuracy.run`
- Slice check: 45/100 valid (45.0%), threshold 30%, status {'scored': 45, 'pm_extreme': 38, 'no_chain': 5, 'no_clean_expiry': 11, 'pm_placeholder': 1}
- Coverage gate: 7111 rows, 89 dates
- Requests (cache hits not counted): {"clob.polymarket.com": 9350, "data-api.polymarket.com": 4573} Polymarket/Kalshi; {"api.massive.com": 20678} Massive
- Failures: http 0, massive 0
- Verdict: PASS
- Single run, no rerun. Massive quote cache shared at the scratchpad `shared_massive_cache/` (keyed by sha1 of the quote URL, i.e. contract and second).
- Note added after the run (no rule changed): no monthly market produced a scored row (status of the 1,048 monthly rows: pm_extreme 640, no_clean_expiry 397, pm_placeholder 11), so the kind split shows daily and weekly only.
