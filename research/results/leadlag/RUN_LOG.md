# Lead-lag run log

One entry per run of `python -m leadlag.run`: code commit, wall time, network requests, exit status.

The first entry below is the only cold run (empty cache, real network). Later entries re-ran the same fetched data after report-text changes, so they show 0 requests; the cache (`cache/`) is gitignored, so a fresh clone repeats the cold run. Earlier smoke runs on two events and one earlier full run were deleted from this log before the entries below were written; the full run is reconstructed in the first entry, from memory of the session and git history, and is marked as such. Data results are identical across entries from 07:56Z on; only SUMMARY.md wording and added descriptive columns changed. This log is append-only from here on.

## approx. 2026-10-03 07:53-07:55Z (reconstructed, original entry deleted)
- code commit: `cf751b0` (pipeline commit made at 07:52Z; run came right after it, with the later `b409094`/`d827cba` wording edits possibly applied)
- wall time, request counts: not recorded
- result: 28 usable, 4 dropped of 32, the same events as later runs
- pooled test, as far as recorded: classical Granger F (p=10) equity to PM about 7.7 (p about 2e-12) against a HAC Wald p of about 0.07; PM to equity F about 0.7. The gap between the two led to METHOD.md Amendment 2.
- exit: 0
- note: this entry is reconstructed, not machine-written. The 07:56Z entry below is the first one the run script wrote, and it happened after Amendment 2 was committed (`77eaa7c`), so the 'cold run' wording below refers to the first logged run, not the first full run.

## 2026-10-03 07:56:09Z
- code commit: `77eaa7c`
- wall time: 29 s
- network requests: Polymarket CLOB 32, Massive 160 (cached responses are not counted)
- result: 28 usable, 4 dropped of 32
- exit: 0

## 2026-10-03 07:57:01Z
- code commit: `fd91f4d`
- wall time: 6 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 28 usable, 4 dropped of 32
- exit: 0

## 2026-10-03 07:57:20Z
- code commit: `fd91f4d` + uncommitted changes in leadlag/
- wall time: 7 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 28 usable, 4 dropped of 32
- exit: 0

## 2026-10-03 07:58:03Z
- code commit: `ab86d8c`
- wall time: 6 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 28 usable, 4 dropped of 32
- exit: 0

## 2026-10-03 08:04:59Z
- code commit: `4dad739` + uncommitted changes in leadlag/
- wall time: 6 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 28 usable, 4 dropped of 32
- exit: 0

## 2026-10-03 08:05:23Z
- code commit: `4dad739` + uncommitted changes in leadlag/
- wall time: 6 s
- network requests: Polymarket CLOB 0, Massive 0 (cached responses are not counted)
- result: 28 usable, 4 dropped of 32
- exit: 0
