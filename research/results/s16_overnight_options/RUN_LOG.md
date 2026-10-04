# S16 (overnight options): run log

All times New York (EDT) unless marked Z (UTC). The label was S16, then S17 for a few minutes, then S16 again (METHOD.md amendments 2 and 3); the folder never changed.

## Commits (read from `git log`, newest first; the commit that adds this file is the one after these)

| Hash | Time | Message |
|---|---|---|
| `25abd7e` | 2026-10-04 00:44 | S16 (overnight options): INTERIM result, main sample complete (285 of 300 event ticker-days, 52 out-of-sample): all three pre-registered trades fail a |
| `5e6a5ca` | 2026-10-03 23:46 | S16 (overnight options): amendment 3, the label is S16 again (label only, no rule changed); a spread split marked as not pre-registered |
| `b8c53ac` | 2026-10-03 23:45 | S17 (overnight odds against options): analysis runner, report generator and tests (21 pass), written while the pull runs; no rule changed |
| `d80ff94` | 2026-10-03 23:39 | S17 (overnight odds against options): amendment 2, the label changes from S16 to S17 because of a clash; folders unchanged, no rule changed |
| `c18e2bc` | 2026-10-03 23:38 | S16: plan, puller and engine; amendment 1 (early closes, KRE and XLF bars, control counts), before any option quote is pulled |
| `1185abb` | 2026-10-03 23:34 | S16 overnight options: method and config, committed before any option quote is pulled |

## Data sources

- Odds: the one-minute Polymarket caches of S5 and S4 on disk and `results/s8_open_referee/mornings.csv`. **No call to Polymarket or Kalshi.**
- Underlying prices: cached five-minute bars (`eq_<TICKER>.npz` of S5 and S4); KRE and XLF bars pulled from Massive (amendment 1).
- Options: Massive `/v3/reference/options/contracts` (one listing request per ticker-day), `/v3/quotes/<contract>` (the last NBBO at or before each instant, one request per leg and instant), `/v2/aggs/ticker/<contract>/range/1/day` (day volume). No modelled price anywhere.
- Cache: `research/s16_overnight_options/.cache/cache.jsonl`, 13,652 lines (not committed).

## The pull

- Run 1: 13683 requests in 6935.3 s; tiers finished [1, 2, 3, 4, 5]; stopped: no (ran to the end); failed requests 0; final rate 2.0 a second; recorder `fetch failed` lines before 51, after 51; ended 2026-10-04T05:34:01Z.

Lines of the pull's own log (UTC):

```
2026-10-04T03:38:25Z pull start: 1738 plan items {"1": 541, "2": 26, "4": 291, "5": 880}
2026-10-04T03:38:25Z recorder `fetch failed` lines before the pull: 51
2026-10-04T04:39:52Z tier 1 finished: 541 items, 7271 requests so far
2026-10-04T04:42:54Z tier 2 finished: 26 items, 7629 requests so far
2026-10-04T04:47:43Z tier 3 finished: 285 events, 8199 requests so far
2026-10-04T04:59:37Z tier 4 finished: 291 items, 9609 requests so far
2026-10-04T05:34:01Z tier 5 finished: 880 items, 13683 requests so far
2026-10-04T05:34:01Z pull end {"finished_tiers": [1, 2, 3, 4, 5], "stopped": null, "requests": 13683, "errors": 0, "recorder_before": 51, "recorder_after": 51}
```

## Notes, and anything that went wrong

- The partial draft of SUMMARY.md that the coordinating session saw (in-sample trades only, 0 out-of-sample) was produced during the pull as a mechanical check of the code. It was **not a bug in the split or in the control matching**: tier 1 is pulled in event-date order and had reached 2025-12-19, while out-of-sample starts on 2026-06-22. At that moment all 54 planned out-of-sample events (each with a matched control) had status "not pulled". The final SUMMARY.md is generated from the complete pull and its Answer section is built from the final result files.
- Final out-of-sample main events with valid quotes: 52 of 54 planned.
- One out-of-sample event has its control on 2026-06-18, before the out-of-sample boundary; by METHOD.md section 8 a control belongs to its event's segment.
- Amendment timestamps in METHOD.md were typed a few minutes ahead of the clock (amendment 1 says 23:45, committed 23:38; amendment 2 says 23:40, committed 23:39; amendment 3 says 23:50, committed 23:46). The commit times in the table above are the true ones.
- The label changed twice at the coordinating session's request (S16, S17, S16). Commits `d80ff94` and `b8c53ac` carry the S17 label in their message; they belong to this study.
- The analysis and report code were run on the partial cache while the pull ran, to catch code errors. No rule was changed after any result was seen. One addition was made after the first 16 events were visible: the median spread split, which is reported under "Looked at after the run" and enters no verdict.
- Tests: `cd research && .venv/bin/python -m pytest s16_overnight_options/tests -q` gave 21 passed, exit code 0.
- An interim result was committed and pushed at 00:44 (`25abd7e`) when the main sample was complete and the case tiers were still pulling; its SUMMARY.md carried an INTERIM banner. The main-sample numbers did not change between that commit and the final one.
- The pull ended at 01:34 New York time, before the 01:50 hard stop of METHOD.md section 10, so no tier was cut. It ran at 2 requests a second throughout; the recorder's `fetch failed` count was 51 before, at every check during, and after the pull, so the rate was never lowered.
- Pull tiers finished: [1, 2, 3, 4, 5].
- Could not verify: the election date itself (the metadata on disk gives only the questions' end date, 2026-10-05T03:59Z); whether a strike listed today for an expired expiry was already listed on the event morning (if it was not, there is no quote and the ticker-day is dropped, so no fill is invented); dividends inside the put-call parity check (the check is a screen for a wrong contract, not a pricing test).
