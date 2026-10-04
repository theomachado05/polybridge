# S5 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 00:45:18 | `METHOD.md`, `config.py` and the universe rule committed (`3f0539e`) | Before any S5 price was pulled |
| 00:46 | `python -m s5_big_moves.universe` (names, dates and volume only) | 2,400 events read, 1,846 dropped by tag, 892 markets eligible, 240 kept (224 resolved, 16 open), 129 events |
| 00:47 | Four blind labelling agents started: two per half of the list, question text and the ticker menu only | 240 questions labelled twice |
| 00:49:02 | Runner, report, tests and the scan-depth note committed (`31a2fac`) | Before any S5 price was pulled |
| 00:52:00 | Amendment 1 committed (`6cc96d9`): hindsight check | Before any S5 price was pulled |
| 00:53:13 | Universe and all four label files committed (`a98de9c`) | 220 agreed links on 93 markets, 27 tickers |
| 00:53 | `python -m s5_big_moves.run pull` | 213 s. Odds for 93 markets, 5-minute and daily bars for 27 tickers and SPY, 0 failures |
| 00:56:52 | `python -m s5_big_moves.run` | 1.9 s. The numbers in `SUMMARY.md` |
| 00:57 | `python -m s5_big_moves.report` | `SUMMARY.md`, charts, `capacity.md` |

The run was made once. No rule was changed after it.

## The links

- Both labellers of a question called it an event for 124 of 240 questions.
- 220 links (ticker and direction) were named by both; 47 times one labeller named a ticker the other did not; no
  ticker was named with opposite directions.
- All four labellers reported questions where they judged an asset would move but would not sign the direction
  (Iranian regime change, "Fed holds", Netanyahu out, Greenland). Those carry no link.
- **Hindsight.** Two labellers said they drew on their memory of 2026 events and of how markets reacted. Amendment 1
  was written for that, before any price was pulled: every figure is also given on sessions from 2026-07-01, after
  the labelling models' knowledge ends.

## Data

- **Window:** 253 sessions, 2025-10-01 to 2026-10-02. "Recent" is the last 20% of sessions, from 2026-07-23.
- **Odds:** Polymarket CLOB `prices-history`, 1-minute, each market's life inside the window; as-of rule 30 minutes.
- **Equities:** Massive 5-minute regular-session bars and daily bars; beta from the 60 sessions before each day.
- 14,439 link-days on 93 markets and 27 tickers. Only 693 fall on sessions from 2026-07-01, because most of these
  markets had resolved by then.

## Checks

- `python -m pytest s5_big_moves/tests -q`: 6 passed. The engine is S4's (`s4_linked_assets/tests`, 11 passed).
- No Sharpe ratio above 3 on any variant with more than a handful of trades.
- The replication's t-statistics are large (6 to 8), so the obvious artifacts were ruled out: the odds and the equity
  come from different sources (Polymarket and Massive); the signal ends at 09:29 and the gap ends at the 09:30 open;
  the result holds with one observation per ticker and day (t = 6.5), without crypto-linked equities (t = 5.9), and
  on sessions the labelling models cannot have seen (t = 6.5).
- The same signed move that lines up with the gap has no relation with the move after the open (t = −0.7), so the
  failed trade is an absence of follow-through, not a sign error.
