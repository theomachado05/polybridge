# S4 run log

All times UTC, 2026-10-04 (Sat 2026-10-03 evening in New York). Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 00:19 | Looked at the existing map `backend/app/data/ai_map.json` (text only) | 230 markets, 133 linked, 404 links, never checked against prices |
| 00:21 | **Motivating example looked at:** Brazil first-round markets against EWZ, 18 sessions | Seen before the method; excluded from every test figure |
| 00:23 | `METHOD.md` and `config.py` committed (`603f2e8`) | Before any test-sample price was pulled |
| 00:24 | Three blind critic agents started, 58 questions each (question text and the ticker menu only) | 174 questions answered; none read the original map |
| 00:25 | Amendment 1 committed (`8c0e887`): 5-minute equity bars | Before any test-sample price was pulled |
| 00:25 | `python -m s4_linked_assets.data` | 268 s: odds for 120 markets, 5-minute and daily bars for 58 tickers and SPY, 0 failures |
| 00:29 | Critic answers and code committed (`25ea1aa`), then `python -m s4_linked_assets.run` | 2.5 s. The numbers in `SUMMARY.md` |
| 00:31 | `python -m s4_linked_assets.report` | `SUMMARY.md`, charts, `capacity.md` |

| 00:33 | Amendment 2 committed (`41633ca`): exploratory pre-market follow-up S4c | After the S4 run, before its own data was pulled |
| 00:35 | `python -m s4_linked_assets.premarket --pull` | 114 s. Pre-market bars (08:00 to 09:25) for 58 tickers and SPY; the S4c tables in `SUMMARY.md` |

The S4 run was made once and no rule was changed after it. `run.py` was re-run once afterwards, unchanged in its
rules, only to save the gate by link and day (`gate_days.csv`) for S4c; its numbers are identical.

## The link agent, stage by stage

| Stage | Input | Output |
|---|---|---|
| Proposer (existing) | question text | 380 links on 117 Polymarket markets, 58 tickers (the 3 Brazil markets with links and the 13 Kalshi markets are left out) |
| Blind critic | question text and the 65-ticker menu; not the proposer's answers | agreed 194; ticker not named 186; opposite direction 0 in the test set (1 on a Brazil link) |
| Data gate | 30-minute bins of the regular session, earlier days only | 21 agreed links confirmed at some point: 15 on Bitcoin and Ethereum price questions, 6 on event questions |

- Families by market (critic): event 59, spot proxy 52, none 6.
- The gate needs history: the median link has 4 sessions of odds inside the window, and 153 of 380 links have the 60
  bins the gate asks for.
- Each critic also reported questions where it judged an asset would move but would not sign the direction (Iranian
  regime change, "Fed holds", "Trump out"). Those carry no link and are not traded.

## Data

- **Window:** 189 sessions, 2026-01-02 to 2026-10-02. Out-of-sample: the last 38, from 2026-08-11.
- **Odds:** Polymarket CLOB `prices-history`, 1-minute, each market's life inside the window; as-of rule 30 minutes.
- **Equities:** Massive 5-minute regular-session bars and daily bars. Beta from the 60 sessions before each day.
- **Costs:** round trip 4.9 to 8.0 bp on the primary's trades at 1× (equity leg 2 or 5 bp a side, SPY hedge 1 bp a
  side times beta).

## Checks

- `python -m pytest s4_linked_assets/tests -q`: 11 passed (prices use only bars before each boundary; beta and the
  gate use earlier days only; the signal stops at 09:29; costs on both legs).
- No Sharpe ratio above 3. The primary's out-of-sample Sharpe is −5.0 on 12 trades. A large negative figure can mean
  a sign error, so the sign was checked: the same signed odds move has a **positive** relation with the opening gap
  (t = 4.0) and none with the move after the open, so the loss is the absence of follow-through, not an inverted
  trade.
- The opening-gap relation holds in both segments on agreed event links: in-sample +5.7 bp per pp (t = 3.7),
  out-of-sample +2.7 (t = 2.5).
