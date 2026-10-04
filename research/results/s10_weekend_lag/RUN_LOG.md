# S10 run log (times New York, Sat 2026-10-03)

| Time | Step | Commit |
|---|---|---|
| 22:41 | Read `research/PARALLEL_BRIEF.md`, S9's SUMMARY, code and METHOD | `e8b8a4f` (branch head at start) |
| 22:44 | Checked timestamps only (no prices) of the S5/S4 event caches and S9's crude cache: one reading a minute | |
| 22:45 | METHOD.md and config.py committed and pushed, before any price was read | `b376c9b` |
| 22:47 | Runner and six unit tests committed (tests pass) | `e3bd9c6` |
| 22:47 | Run without prints (2.5 s) | |
| 22:48 | Full run with the print check: 111 markets, about 220 data-API requests at 2.5 a second, no errors (122 s) | |
| 22:49 | Charts and capacity.md (`report.py`) | |
| 22:52 | After-the-run checks (`robust.py`, not pre-registered): drop one weekend; in- and out-of-sample slopes | |

## Data sources

- Event questions: `research/s5_big_moves/.cache/pm_<id>.npz` and `research/s4_linked_assets/.cache/pm_<id>.npz`
  (Polymarket one-minute price history, pulled by S5 and S4). 44 questions; links from `s8_open_referee.run.links()`.
- Price markets: `research/s9_weekend_price_markets/.cache/pm_<id>.npz` (weekend windows only, pulled by S9);
  universe, signs, fees, results from `s9_weekend_price_markets/universe.json`. 192 crude and 77 gold signed markets
  with data.
- Weekend clock: `s9_weekend_price_markets.run.calendar()` (SPY sessions in the S5 cache).
- Public prints: Polymarket data API (`ds.pm_trades`, latest 20,000 prints per market), pulled Sat 2026-10-03 22:47
  to 22:49, cached in `research/s10_weekend_lag/.cache/prints_<id>.json` (not committed).
- Half-spreads: S9's measurement of the live books of Sat 2026-10-03 22:13.

## Anything that went wrong

- One unit test was wrong on first run: it expected a 4-point move over 15 minutes to count as a jump, which is below
  the 5-point rule. The test was fixed; the code was right. This was before the runner was committed.
- The first `git commit` named the empty results folder in the pathspec and failed; recommitted with the package path.
- Commit trailers name Claude Opus 5.5, the model that ran this session (the brief's template names Fable 5.1).
- No amendments to METHOD.md.
