# S11 run log (New York time)

| When | What | Commit |
|---|---|---|
| Sat 22:41 | Brief read. S9 universe, S5 candidates and universe, and the helpers inspected (no prices). | |
| Sat 22:47 | Bundle lists built from catalogue text (`universe.py`): every price field dropped before storing (asserted). | |
| Sat ~22:50 | METHOD.md, config.py, universe, engine, live logger and 13 tests committed before any price was read. | `26af862` |
| Sat 22:51 | Live logger, first snapshot. It showed a 10-point "violation" on the Iran leadership date ladder that was a bug in the year rule (see amendment 1). Snapshot discarded (`.cache/live_v0/`). | |
| Sat 22:54 | Amendment 1: year rule fixed, both lists rebuilt; logger restarted 22:55; history pull started. | `8804b3d` |
| Sat 23:10 | Amendment 2: the price-history server gave about 1.3 requests a second; one-of-many pulls capped (1,400 new markets in all, every ladder leg kept). | `001f1b6` |
| Sat 23:20 | Runner, live report, report, tests. | `3a00564` |
| Sun 00:14 | Pull done: 1,400 markets, 0 failures, 3,548 s; results (YES/NO) for 2,435 markets read from the catalogue. | |
| Sun 00:14 | Half-spread calibrated from the logger's first hour (22:55–23:55): 0.005 for every kind (`calibration.json`). | |
| Sun 00:14–00:34 | Full run with the print check: 4,202 violation episodes, 43,199 jumps, 2,900 trades; prints fetched for 819 markets. | |
| Sun 00:35 | **Bug found and fixed:** the propagation trades were held to "one open trade per bundle" with no exit time, so each ladder could be traded once in the whole year (141 trades). METHOD.md applies that limit to the violation trade only; propagation is capped at 10 a day. Rerun: 3,623 P0 trades. The violation results are unchanged. | this commit |
| Sun 00:38 | Display fix: the drawdown is now divided by the capital base instead of the running equity, because the propagation equity goes below zero. | this commit |
| Sun 07:00 | Live logger stops. `live_report.py` rerun; SUMMARY's live paragraph updated from `live_totals.json` and `live_arbitrages.csv`. | final commit |

## Data sources

- Catalogue: `gamma-api.polymarket.com/events` (by slug for S5's 355 events; open events by 24-hour volume for live).
- One-minute mids: `clob.polymarket.com/prices-history` (fidelity 1). Reused: S5's cache (148 markets) and S9's cache
  (weekend windows only, 391 markets). New: 1,400 markets in `research/s11_bundles/.cache/`.
- Live books: `POST clob.polymarket.com/books`, 888 tokens every 3 minutes (about 9 requests a snapshot).
- Prints: `data-api.polymarket.com/trades`, two pages (20,000 prints) per market, 819 markets.
- No Kalshi calls. Polymarket requests stayed at 2.5 a second or fewer (1 a second for the logger).

## Things that went wrong or limit the result

- The live `/books` call returned a book for about 632 of the 888 tokens. The rest are placeholder members of one-of-many
  sets ("Person H") with no book, so only about 31% of one-of-many checks could be run.
- One snapshot (Sat 22:58–23:13) took 15 minutes and returned 416 books: some `/books` calls timed out and were retried.
- Coverage of the history: 48 of 50 strike ladders, 93 of 100 date ladders, and 10 of 83 one-of-many sets have a price
  for every leg.
- The half-spread comes from tonight's liquid live books. Older and thinner markets had wider spreads, so the 2× rows
  are the safer reading. The print check, not the half-spread, is what separates real violations from empty books.
- The prints API serves only a market's latest 20,000 prints, so 361 of 1,425 violation entries are uncheckable.
