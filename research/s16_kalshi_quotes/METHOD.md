# S16: the give-back at real quotes, on Kalshi (pre-registered)

**Question.** Four studies found that Polymarket gives back about 3 points of a large move (S5, S8, S9, S15). All
four rest on Polymarket's price history, which is a mid price and sometimes not even a quote, and the print checks
confirmed few of the prices. Kalshi publishes its historical best bid and ask. Two questions:

1. **Is the give-back real, or is it produced by Polymarket's price history?** On the questions that trade on both
   venues, does Kalshi's quoted mid give the overnight move back as Polymarket's history does, on the same nights?
2. **Can it be taken at Kalshi's real bid and ask, after Kalshi's fee?**

This file and `config.py` are committed **before any give-back or P&L is computed on Kalshi's quotes**. Every rule is
fixed. Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- The Polymarket give-backs: 2.63 points after an overnight move of 10 points or more (S8), 1.35 after 5 or more.
- S1 used these same Kalshi quotes for a different question (the gap between the two venues).
- **Counts only, made from Kalshi's quoted mids before this commit, no outcome computed:** with a quote allowed to
  stand for up to 6 hours, 104 market-sessions on 18 markets have an overnight move of 5 points or more with the 09:40
  mid between 5% and 95% (203 at 3 points, 34 at 10). With quotes at most 30 minutes old: 50, 103 and 15. The quoted
  spread at 09:40 is 1 cent at the median (quartiles 1 to 2 cents).
- **Not seen:** what Kalshi's quotes do after 09:40 on those sessions; the same sessions on Polymarket.

## 1. Data

Nothing is pulled. S1's cache (`research/s1_twin_spread/.cache`): one-minute Kalshi candles with the closing best
bid and ask of 33 markets, and the one-minute Polymarket history of their twins, over the span the two overlap (up to
a year, to 2026-10-03). Each market's Kalshi fee multiplier is in the cache's `pull_meta.json`. Stock-market sessions
come from the SPY calendar of the S5 cache.

Kalshi writes a candle only when the best bid or ask changes or a trade prints, so a quote stays in force until the
next candle. A Kalshi quote is used if it is two-sided (bid above 0, ask below 1, ask above bid) and its candle is
at most **6 hours** old (primary; this is the rule S1 used as its sensitivity check) or at most 15 minutes old
(strict variant, S1's primary rule).

## 2. The clock (S8's)

For each market on each session: `x` = the Kalshi mid at 09:29 minus the mid at the previous session's close, in
points. Entry instant 09:40. Exit instant: the close of the same session. New York time.

## 3. Tests before costs

- **K1, the give-back on Kalshi.** The mean change in Kalshi's mid from 09:40 to the close, signed by `x` (negative
  = given back), after overnight moves of 5 points or more (primary), 3 and 10. Date-bootstrap 95% interval.
- **K2, the same nights on Polymarket.** For the same market-sessions, the mean signed change of the twin's
  Polymarket history price over the same window (a reading at most 30 minutes old), and the difference Polymarket
  minus Kalshi, paired by market-session, date bootstrap. If Polymarket shows a give-back that Kalshi's quotes do
  not, the give-back is at least partly produced by Polymarket's price history.

## 4. The trade, at real quotes

- **When:** |`x`| ≥ the variant's threshold and the 09:40 mid is between 5% and 95%.
- **Entry at 09:40, fade:** if the mid rose overnight, sell YES at the **bid**; if it fell, buy YES at the **ask**.
  100 contracts. **Exit at the close:** buy back at the ask, or sell at the bid. Quotes as in section 1, at both
  instants; a trade with no valid quote at the exit is dropped and counted.
- **Fee:** Kalshi's taker fee on each fill: 0.07 × multiplier × contracts × P × (1 − P), rounded up to the cent.
- **2× costs:** each fill is moved against the trade by a further half of the quoted spread, and the fee is doubled.
- **Capital:** the price paid for the side bought, times 100. Capital base: the largest capital deployed in a session.

| id | overnight move | quote age allowed |
|---|---|---|
| **V0, primary** | 5 points or more | 6 hours |
| V1 | 3 points or more | 6 hours |
| V2 | 10 points or more | 6 hours |
| V3 | 5 points or more | 15 minutes |

Each at 1× and 2× costs. The deflated Sharpe ratio uses 4 trials.

## 5. Accounting, segments, inference

Net P&L per trade in points per contract; date-bootstrap intervals; Sharpe on session returns (252 a year), maximum
drawdown, worst month, turnover; costs in points and in bp of capital, split into spread and fee. Capacity: the size
is not in the candles, so only the quoted spread is reported. In-sample / out-of-sample: by session, OOS is the most
recent 20% of the sessions that have at least one live market.

## 6. Success criterion (primary V0, fixed now)

A pass needs: at least 30 OOS trades on at least 10 OOS dates; OOS mean net P&L per trade above zero with a
date-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs; in-sample above zero. With 104
candidate trades in all, the out-of-sample count will fall short; the verdict will then be "too few observations",
and the tests of section 3 are what this study can answer.

## 7. Caveats known in advance

- 33 markets, most of them on a few themes (Fed decisions, IPOs, a handful of political questions), and a span as
  short as a few months for some.
- A quote standing for hours may not be fillable at size; the candles carry no size.
- Fee types differ by series; the taker formula above is applied to every market with its own multiplier.

## Outputs

`research/results/s16_kalshi_quotes/`: `SUMMARY.md`, `tests.csv`, `metrics.csv`, `trades.csv`, `sessions.csv`,
`equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
