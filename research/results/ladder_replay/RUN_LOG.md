# Ladder replay run log (New York time, Sun 2026-10-04)

Commit times are authoritative; the times written in METHOD.md's amendment headings were estimates and run up to five
minutes late.

| When | What | Commit |
|---|---|---|
| 01:47 | Worktree `r/ladder-replay` from origin/main; S11 METHOD, config, universe, SUMMARY, capacity read. | |
| 01:50 | METHOD.md and config.py committed alone, before any new data pull or computation. | `08a0236` |
| 01:51 | API probes, format only: data-api honours `end` (three prints of one S11 market); gamma `/markets` needs `closed=true` for closed markets; `/events/keyset` with `after_cursor` for deep paging. One gamma description seen ("after market creation"). | |
| 01:51 to 01:56 | Fresh catalogue built from gamma text: 68,571 events, 373 date ladders, 861 pairs, 1,234 markets. | |
| 01:56 | Engine, runner, 6 unit tests, frozen `fresh_universe.json`, amendments 1 to 3. | `864af49` |
| 01:57 | Live check (step 4), one `/books` sweep: 61 pairs, 0 violations net of fees. | |
| 01:57 | The rule run on gamma records only: 1,232 of 1,779 pairs "key not found" because the date lives in the title. Amendment 4. | `3b7dbe2` |
| 02:00 to 02:07 | First full run. Prints for 2,087 markets pulled (paged by time, none truncated). | |
| 02:08 | Losing trades on supposedly nested pairs, all from 5 ladders with the rung year misread by S11's rule. Amendment 5 (post hoc year check). | |
| 02:10 | Bug: a high-edge trade (Starmer, 62 points) showed YES and NO prints mixed in one second. The data API's `outcomeIndex` is wrong on many prints. Fixed to map by `asset`; first run declared void (`v0_void/`). | `a876979` |
| 02:11 to 02:18 | All prints pulled again; registered-rule run and year-check run, both universes. | |
| 02:18 to 02:21 | Checks: high-edge trades read print by print (Starmer now prints YES at 0.12 to 0.14), losers traced to rung order, manual sample of 20 pairs read, SUMMARY written. | this commit |

## Data sources

- Gamma: `/events/keyset` (catalogue), `/markets?id=...&closed=true|false` (texts, fee schedules, ticks, results).
- Prints: `data-api.polymarket.com/trades`, taker prints, paged back with `end`, 10,000 a page, 2,087 markets.
- Books: `POST clob.polymarket.com/books`, once.
- No CLOB price history was read. Requests stayed at about 3 a second per process (two processes during the pull).

## Things that went wrong or limit the result

- The first run was void (outcomeIndex bug). Strike-ladder and post-July results did not change after the fix, which
  suggests the API's index was wrong mainly on older prints.
- The year check (amendment 5) was added after seeing which trades lost. The registered rule's verdict is NULL; the
  year-check result is reported beside it and labelled post hoc.
- The live snapshot used the nesting rule before amendment 4 (no effect: zero violations).
