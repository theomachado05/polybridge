# S3 run log

All times UTC, 2026-10-03. Commands are run from `research/`.

| Time | What | Result |
|---|---|---|
| 23:38 | `METHOD.md` and `config.py` committed (`83ce137`) | Before any S3 data was pulled |
| 23:41 | `python -m s3_three_way.run --rate 0.0417`, first attempt | Stopped: Massive answered 403 for the index `I:SPX`. No set had been built |
| 23:42 | Amendment 1 committed (`6c3b753`): S&P 500 close from Kalshi's settlement value | Before any result |
| 23:42 | `python -m s3_three_way.run --rate 0.0417` | 42 s. Part H: 60 matched sets on 33 dates; primary V0: 0 entries at 1× and 2× |
| 23:44 | `python -m s3_three_way.report` | `SUMMARY.md`, `metrics.csv`, charts, `capacity.md` |

## Data pulled

- Polymarket SPY rows and the options band: the committed `research/results/arb/arb_gaps.csv` (96 resolved, scored,
  clean-expiry rows at 12:00 ET on 34 dates).
- SPY daily closes and SPY dividends: Massive. Ex-dividend date in range: 2026-09-18 (4 rows dropped).
- Kalshi: the 16:00 `KXINXU` event of each date (strikes, results, settlement value) and 1-minute candles for each
  mapped strike over the 6 hours before the snapshot. Throttled to 3 requests a second; the forward recorder logged no
  failed cycle during the pull.
- Kalshi fee: `fee_type` quadratic, `fee_multiplier` 1 (from the series record).

## Rows dropped, with reasons

| Reason | Rows |
|---|---|
| SPY ex-dividend date (2026-09-18) | 4 |
| No Kalshi strike within 2.5 index points of ratio × K | 13 |
| No two-sided Kalshi quote within 6 hours before 12:00 ET | 19 |
| Kept | 60 |

## Checks

- `python -m pytest s3_three_way/tests -q`: 11 passed (strike map, as-of quote, outlier rule, leg-by-leg payoff with a
  split resolution, print check direction).
- No Sharpe ratio above 3 on the primary (no trades). The Sharpe figures printed for V2 and V3 come from one or two
  trades and carry no meaning.
- Part F (the weekend recording) has not been read: the window closes Sun 2026-10-04 11:00 UTC. The strike map for
  Monday was built from names and Friday's closes only: SPY 750, 755, 760, 765, 770, 775 against S&P 7525, 7575,
  7625, 7675, 7725, 7775 (ratio 10.0342 = 7722.72 / 769.64).
