# S15 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 02:51:31 | `python -m s15_weekend_scare.universe` (catalogue only) | 2,128 events seen, 466 match the title rule, 133 kept, 871 markets kept; S9's 391 markets excluded, none in common |
| 02:51:58 | `METHOD.md`, `config.py`, `universe.py`, `universe.json` committed (`c1a41ea`) | Before any price of these markets was pulled |
| 02:53:14 | Runner and tests committed (`bbd5b2a`) | Before any price was pulled |
| 02:53 to 03:14 | `python -m s15_weekend_scare.run --pull` (6 workers, 5 requests a second) | Stopped by hand with 435 of 871 markets on disk. See "The interrupted pull" |
| 03:17 to 03:27 | `python -m s15_weekend_scare.run --pull --gentle` (1 worker, 2 requests a second, skipping markets on disk) | 586 s. 436 markets pulled, 0 failures. 871 markets on disk, 843 with prices inside weekend windows, 16,115,850 one-minute points kept |
| 03:20:33 | The gentle, resumable pull and the report generator committed (`3bc7f2c`) | While that pull was running and before the test was run. No rule of the test changed |
| 03:27 | `python -m s15_weekend_scare.run --no-prints` | The test and every variant on mid prices |
| 03:28 | `python -m s15_weekend_scare.run` | 64 s. The same with the print check on the primary trade's 170 markets. The numbers in `SUMMARY.md` |
| 03:29 | `python -m s15_weekend_scare.report` | `SUMMARY.md`, charts, `capacity.md` |

The two runs use identical rules; the second only adds the print check. After the first report, the opening sentence
of the summary was changed to say that the pattern holds in quoted prices and cannot be shown in traded ones; no
number changed.

## The interrupted pull

Between 02:57 and 03:14 this machine could not reach Polymarket or Kalshi (name resolution and connections failed
for every process; the live recorder has no snapshot in that window, see `research/forward/`). The first pull was
running and retrying through it, alongside another session's pull. I stopped it at 03:14, after the network had come
back, and restarted it at a third of the load with a guard that would have stopped it at the first failed fetch in
the recorder's log. None occurred. Files written before the stop were kept only if they could be read back.

## Data

- **Universe:** 871 markets in 133 events, none of them in S9: 463 stocks, 102 S&P 500, 112 crude oil, 83 silver, 66
  gold, 45 natural gas. 766 are in events S9 did not use (692 tagged "other event", 74 "weekly"),
  105 are smaller strikes of S9's events.
- **Weekends:** 48 with at least one live market, from the weekend before 2025-11-03 to the one before 2026-09-28.
  Out-of-sample is the last 10, from 2026-07-27.
- **Market-weekends:** 2,158 on 710 markets: 256 risers (a rise of 5 points or more), 480 fallers, 979 quiet (a move
  under 2 points), 443 in between. By class: stocks 918, S&P 500 501, silver 291, crude oil 197, gold 144, natural
  gas 107. No exit price was missing.
- **Trade prints:** up to 20,000 per market for the 170 markets the primary trade sells; none hit the limit; 53
  prints within 10 minutes of an entry. 201 of the 235 entries could be checked, 9 are confirmed.

## Limits

- 4% of checkable entries have a print at the assumed price: on these thin markets the Sunday 17:55 mid is almost
  never a price someone traded at.
- The same weekends as S9.
