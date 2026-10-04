# S5: do the S4 findings hold on markets S4 never used? (pre-registered)

**Two questions, both taken from S4 and tested on fresh markets.**

1. **Replication.** S4 found that a linked equity's opening gap lines up with the overnight move in prediction-market
   odds (+4.69 bp of excess gap per point, t = 4.01). Does that hold on markets S4 did not use?
2. **The trade.** In S4, after an overnight move of 10 points or more, the equity went on to move +39 bp in the same
   direction between the open and the close, with an interval of −50 to +122 on 70 cases: a hint, not a result. Does
   buying (or shorting) the linked equity at the open after such a move make money, net of costs, on fresh markets?

This file and `config.py` are committed **before any price is pulled for S5**. Every rule is fixed. Changes go under
"Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- Everything in `research/results/s4_linked_assets/SUMMARY.md`, including its size tables. The 10-point threshold and
  the open-to-close holding period come from there: they were chosen on S4's sample, which is why S5 uses none of it.
- The names of five high-volume resolved markets seen while checking the market list (a MicroStrategy question, two
  Iran questions, two Fed questions). No price of any S5 market has been seen.

## 1. Universe (a rule, not a choice)

- Polymarket events from the gamma API, open or resolved, ending between 2025-11-01 and 2027-12-31, in descending
  order of volume.
- **Dropped by tag:** events tagged as sports, e-sports, or crypto price markets, and recurring "up or down" markets.
- **Dropped by rule:** any market in S4's sample (`ai_map.json`) and any Brazil market (S4's motivating example); a
  market with fewer than 20 trading sessions of life inside the window; a market with under $1 million of volume.
- The **240 markets with the largest volume** that remain, at most 6 per event (the highest-volume ones), so that one
  event's ladder of outcomes cannot fill the list.

## 2. Links (two blind labellers)

- Two independent models each read the question and a fixed menu of US-listed tickers (`config.py`), and nothing
  else. Neither sees the other's answer, S4's map, or any price.
- For each question a labeller names up to three tickers with a direction, or none, and classes the question as
  event, spot proxy or none (S4's definitions).
- A **link** is a (ticker, direction) both labellers named, on a question both classed as an event.
- Reported too: links that also pass S4's walk-forward data gate.

## 3. Data and measures

As S4 (`research/s4_linked_assets/METHOD.md` sections 2 and 3, with its amendment 1):
- Window: sessions from 2025-10-01 to 2026-10-02. Odds: Polymarket 1-minute history, as-of rule 30 minutes.
  Equities: Massive 5-minute regular-session bars and daily bars. Excess return over `β ×` SPY, `β` from the 60
  sessions before the day.
- `x_night` = the direction-signed change in odds from the previous close to 09:29, in points. One signal per ticker
  per day: the mean of `x_night` over its links.

## 4. P1, the replication

The through-origin slope of the equity's excess opening gap (bp) on `x_night` (points), over all link-days, errors
clustered by date. **Replicates** if the slope is above zero with t ≥ 2. Also reported: one observation per ticker
and day, weekends alone, and the result without crypto-linked equities.

## 5. P2, the trade

- **Entry:** when a ticker's signal is at least 10 points in absolute value, at the 09:30 open take the equity in the
  direction of the signal, $10,000, against `β × $10,000` of SPY the other way. At most 10 tickers a day, largest
  signal first.
- **Exit:** the 16:00 close.
- **Costs per side, bp:** SPY 1; liquid ETFs and stocks above $50 billion 2; all others 5 (S4 section 3). 2× doubles
  them.
- **Capital base:** $100,000. Sharpe on daily returns, 252 days; maximum drawdown; worst month; turnover.
- **Capacity:** 5% of the median dollar volume of the first 30 minutes on the days traded.

## 6. Variants (the complete list)

| id | threshold | exit | closures |
|---|---|---|---|
| **V0, primary** | 10 points | close | all |
| V1 | 10 points | 10:00 | all |
| V2 | 5 points | close | all |
| V3 | 10 points | close | weekends and holidays only |

Each at 1× and 2× costs. The deflated Sharpe ratio uses 4 trials.

## 7. Segments and success criterion

- The whole S5 sample is out-of-sample for the rule, because the rule was fixed on S4's markets. As the track asks,
  it is also split by time: the most recent 20% of sessions, and the rest.
- **P2 passes** only with all of: at least 30 trades on at least 15 dates and 8 tickers; mean net return per trade
  above zero with a date-bootstrap 95% interval excluding zero at 1× costs; mean net return above zero at 2× costs;
  mean net return above zero in both time segments.
- Anything else is a null or "too few observations" and is reported as that.
- A Sharpe above 3 starts the bug hunt of S4 section 6 before anything is reported.

## 8. Caveats known in advance

- Links are model judgements. Two models agreeing is not truth.
- Resolved markets pin at 0 or 1 once the outcome is known; their last big move is the news itself. That is the case
  the trade is about, and it is also when the equity's own news flow is heaviest.
- Fills at the first regular bar's open stand for the opening auction.
- S4 and S5 overlap in calendar time, so they share market regimes even though they share no market.

## Outputs

`research/results/s5_big_moves/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `trades.csv`,
`capacity.md`, `RUN_LOG.md`, `links.csv`, `universe.csv`.

## Amendments

**Note, 2026-10-04 00:49 UTC, before any S5 price was pulled: how deep the event scan went.** The gamma API refuses
event offsets above 2,000. The scan of resolved events stopped there, at an event volume of $3.5 million; open events
ran out on their own. A market cannot have more volume than its event, and the last of the 240 kept markets has $6.5
million, so nothing below the cut-off could have entered the list. Scan counts are in `universe.json`: 2,400 events
read, 1,846 dropped by tag, 892 markets eligible, 240 kept (224 resolved, 16 open) from 129 events.

**Amendment 1, 2026-10-04 00:52 UTC, before any S5 price was pulled: a hindsight check on the links.** One labeller
reported that several of its links draw on its memory of how markets reacted at the time (gold and the dollar on a
Fed-chair nomination, Chevron on Maduro, airlines on the shutdown deal), not only on the question text. Most S5
markets have resolved, so a model can know the reaction it is asked to predict the direction of. That would inflate
P1. The labelling models' knowledge ends in June 2026. So:
- every P1 and P2 figure is also reported on **sessions from 2026-07-01**, which no labeller can have seen;
- **P1 replicates only if the slope is above zero with t ≥ 2 on all link-days and on the sessions from 2026-07-01**;
- the P2 criterion already requires a positive result in the most recent 20% of sessions, all of which fall after
  that date.
S4 is less exposed (its markets were open and unresolved when linked), but not immune: the same models may know how
those equities moved with the news before June 2026.

**Amendment 2, 2026-10-04 00:59 UTC, after the S5 run: an exploratory follow-up on who moves first inside the session
(S5b).** S5 showed that by the open the equity has absorbed the overnight move in odds. That leaves one question the
closure tests cannot answer: when both trade at the same time, which one moves first, and by how many minutes? S5b
was designed after seeing S5, so it is **exploratory** and outside the success criterion. Its rules, fixed before
anything is computed:
- Same links, same data, regular session only, 5-minute bins. In each bin: the equity's excess return (bp) and the
  direction-signed change in odds (points, as-of at the bin's edges).
- **Odds first?** After a bin in which the odds move by 3 points or more, the equity's excess return, signed by the
  odds move, over the next 5, 15, 30 and 60 minutes.
- **Equity first?** After a bin in which the equity's excess return is 50 bp or more, the change in odds, signed by
  the equity move, over the next 5, 15, 30 and 60 minutes.
- Both with date-bootstrap 95% intervals, and the pooled through-origin slopes with errors clustered by date.
- **A trade, only for the odds-first direction** (equity prices are executable; historical Polymarket prices are
  not): enter the equity at the open of the next bin after a 3-point odds jump, hold 30 minutes, hedge with SPY,
  costs as section 5. One position per ticker at a time.
- The equity-first direction is reported in points of odds and set against what a Polymarket round trip costs. It is
  not turned into a P&L.

**Amendment 3, 2026-10-04 01:00 UTC, after S5 and S5b: one more exploratory check, on the prediction market itself.**
The equity is efficient to the odds at every horizon tested. An earlier study (R3) saw Polymarket give back part of
its weekend move after the stock market opened. If the odds overshoot while equities are closed, the trade is on the
odds, not the equity. Rules, fixed before computing:
- The 93 S5 markets, odds only. `x` = the change in the YES price from the previous close to 09:29, in points. `y` =
  the change from 09:29 to the close of the same session, and to the next 09:29.
- Reported: the through-origin slope of `y` on `x` (a negative slope is a give-back), errors clustered by date; and
  the mean of `y` signed by `x` after moves of 5 points or more and of 10 points or more, all closures and weekends.
- Not a P&L: historical Polymarket prices are not executable. The result is set against a round-trip cost of about
  2 to 4 points on liquid markets (two half-spreads plus the 0.04 × P × (1 − P) fee each way).
