# S25: sell the ticket on Polymarket, buy the matching option spread. What is left, and how much risk goes?

Pre-registered Sun 2026-10-04, about 02:00 New York time (git's timestamp is the record). This file and `config.py` are
committed **before any Monday option quote or any underlying close is pulled and before any hedged P&L is computed**.
Changes afterwards go under "Amendments", dated, never rewritten.

## 1. Why

S21 found that Polymarket "will it hit" tickets on stocks and the S&P 500 that trade 5 or more points above the price
the listed options chain puts on the same payoff are the ones whose buyers lose. Selling them at traded bids earned
+22.27 points per contract (interval +10.35 to +33.14, 60 markets, in-sample; 2 markets out-of-sample). In S21 the
options were a yardstick only: nothing was traded in them. Selling these tickets unhedged is selling insurance.

The project owner's point: a strategy built on options should trade options. S25 sells the ticket **and buys the
matching option spread as a hedge, at real option quotes**, and asks what is left and how much risk the hedge removes.
With the hedge the trade is a relative-value trade between two venues; without it, it is an insurance book.

## 2. Markets (no new choice: all from S18 and S21)

- S21's anchored markets (`research/results/s21_options_anchor/anchors.csv`, `status` = ok) that have a first-weekend
  taker sale in S18's file (`prints_markets.csv`, `sell_pnl_points` present): **277 markets, 62 events** (263 in-sample,
  14 out-of-sample), 17 Fridays from 2025-10-31 to 2026-09-25. Tickers: NVDA 59, TSLA 41, SPY 28, GOOGL 24, AMZN 21,
  AAPL 20, META 20, SPX 20, MSFT 11, PLTR 10, OPEN 9, HOOD 7, NFLX 6, RKLB 1.
- Ticker, level, direction, expiry and **the two option contracts** are S21's, unchanged: `leg_lo` (strike `k_lo`) and
  `leg_hi` (strike `k_hi`). 149 of the 277 had a leg moved outward by S21; the same strikes are used here.
- **Rule subset** = S21's B0: the ticket's traded bid is 5 or more points above S21's central anchor:
  100 × (`sell_price` − `anchor_central`) ≥ 5. **60 markets** (58 in-sample, 2 out-of-sample). The **left** markets are
  the other 217. The full set and the rule subset are reported separately.
- In-sample and out-of-sample: S18's `segment` column, unchanged.

## 3. The ticket leg (exactly S18 and S21)

Sold at the traded bid during the first weekend (`sell_price`: the size-weighted price of takers who sold YES, Friday
20:00 to Sunday 20:00 New York), held to the result, after the market's own taker fee: `sell_pnl_points` per contract.
At 2× costs: `sell_pnl_points_2x_fee`. Capital tied up per contract: 1 − `sell_price`, from the first weekend to the
result.

## 4. The hedge leg

- **The spread.** A vertical spread on S21's two strikes in the direction of the ticket. "Reach / hit high": a call
  spread, long the call at `k_lo`, short the call at `k_hi`. "Dip / hit low": a put spread, long the put at `k_hi`,
  short the put at `k_lo`. Width W = `k_hi` − `k_lo`.
- **The unit.** One unit is 1/W of a spread per share, so that one unit pays $1 when the underlying finishes beyond the
  far strike. Payoff per unit at expiry, with C the underlying's official close on the expiry date:
  up = clip((C − `k_lo`)/W, 0, 1); down = clip((`k_hi` − C)/W, 0, 1).
- **The price paid.** The long leg at its ASK, the short leg at its BID: cost per unit = (ask_long − bid_short)/W, plus
  the commission: $0.65 per contract per leg (the existing cost model's figure), which is 2 × 0.65 / (100 × W) per unit.
  A cost below zero before commission (a crossed pair of quotes) is set to zero and counted. A cost above 1 is kept and
  counted. No financing cost on the premium. Nothing is charged at expiry.
- **Held to expiry.** The spread is read as European, as S21 read it: early exercise of the short leg is ignored, and a
  finish between the strikes is settled at the close.
- **Size.** h units per ticket contract. Hedge P&L per ticket, in points = 100 × h × (payoff − cost).
  **Hedged P&L = ticket P&L + hedge P&L.**
- **Primary (P): h = 2, bought at 09:35:00 New York on the first session after the ticket's weekend** (the first session
  day after the anchor Friday in the SPY session calendar; a Tuesday when Monday is a holiday). It is the first moment
  options trade after the ticket was sold. h = 2 is the reflection rule S21 used for its central anchor.
- **Usable quote on Monday:** the last NBBO at or before 09:35:00, timestamped at or after 09:30:00 of that session (so
  at most 5 minutes old), with an offer above zero and a bid of zero or more not above the offer. **No leg is moved to
  another strike:** a market with a leg that has no usable quote is dropped and counted by reason. No modelled price is
  substituted anywhere. The hedge is bought on every market, whatever happened over the weekend.
- **Variant A: h = 1** (the lower-bound replication), same quotes.
- **Variant B: h = 2 at Friday 15:55 quotes**, the quotes S21 already holds (`leg_*_bid`, `leg_*_ask` in `anchors.csv`),
  same price rule. **Not executable in that order:** the ticket is sold after Friday's close. It is reported as the gap
  locked on paper. Reported on the primary's markets, and on every market with a verified close.
- **Costs at 2×:** each option leg is moved a further half-spread against us (long at ask + (ask − bid)/2, short at
  bid − (ask − bid)/2, never below zero), the commission is doubled, and the ticket's fee is doubled.

## 5. The underlying's close, and splits

- Massive daily bars, **unadjusted** (`adjusted=false`): the price that traded on the expiry date, which is the basis of
  the strikes of options expiring that day. The index questions (SPX) use the index's own close (`I:SPX`); if it is not
  served those markets are dropped and counted. The adjusted series and the list of splits are pulled as well.
- A market is **dropped and counted** when any of these holds:
  1. the ticker has a split with an execution date after the anchor Friday and on or before the expiry date (the
     contract bought is adjusted on the way; its terms at expiry are not verified here);
  2. there is no unadjusted close on the expiry date;
  3. the adjusted and the unadjusted close on the expiry date do not reconcile with the listed splits after that date
     (to 0.5%);
  4. the unadjusted close on the anchor Friday divided by the question's level is outside 0.2 to 5 (a level and a
     price on different split bases).
- The index (SPX) has no splits and one price series: rules 1 and 3 do not apply to it; rules 2 and 4 do.
- If the list of splits or the daily bars of a ticker are not served, its markets are dropped and counted.
- Nothing is repaired. Known in advance: Netflix split 10-for-1 in November 2025 and S21 dropped most of it.

## 6. What is measured

Per market, in points per ticket contract: ticket P&L, hedge cost, hedge payoff, hedge P&L, hedged P&L.
As a book: S18's book function for the unhedged leg (up to 100 contracts per market, never more than the printed size;
P&L booked in the month of the result; capital locked from the first weekend to the result; Sharpe on monthly P&L). For
the hedged book the same function is copied and given two legs per market: the ticket leg as S18 books it, and the
hedge leg with its premium locked from the hedge instant to 16:00 New York on the expiry date and its P&L booked in the
month of the expiry. A test asserts that the copy reproduces S18's function on the ticket leg alone.

For the full set, the rule subset and the left markets; whole sample, in-sample, out-of-sample; unhedged and each
variant, **always on the same markets** (those the primary hedge could be built for):

- mean P&L per ticket contract with its interval (events resampled: `boot_mean`, 2,000 draws, seed 0; under 5 events no
  interval);
- risk: standard deviation of P&L per market, worst market, skew of P&L per market; and from the book: worst month,
  maximum drawdown, monthly Sharpe;
- the four outcome cells, counted, with unhedged, hedge and hedged P&L: never touched; touched and finished beyond;
  touched and came back (the case the hedge does not cover); finished beyond without a recorded touch. "Touched" is the
  ticket's result (YES). "Finished beyond" is the close on the expiry date at or beyond the question's level in its
  direction. The last cell should be empty when the option expires on the window's last session; S21's expiry is up to
  17 days later for some markets, so any such market is listed with that gap;
- the cost of the hedge in points per ticket, and the capital each leg ties up.

## 7. Hypotheses (each has its own line in the summary; judged on the primary P at 1× costs, whole sample)

- **H1, the premium survives the hedge.** On the rule subset, mean hedged P&L per ticket is above zero and its interval
  excludes zero. In-sample, out-of-sample and 2× costs are reported next to it.
- **H2, the hedge cuts risk.** On the rule subset, same markets: (a) the standard deviation of hedged P&L per market
  divided by the unhedged one is below 1, with an event-bootstrap interval (2,000 draws, seed 0) that excludes 1; and
  (b) the hedged book's worst month is not worse than the unhedged book's (dollars, same contracts). The event-bootstrap
  interval of the difference in worst month is reported. The same two lines are reported on the full set.
- **H3, the anchor still sorts.** Mean hedged P&L on the rule subset minus mean hedged P&L on the left markets, with its
  interval (`boot_diff`); passes if the interval excludes zero on the positive side.

**A pass on H1 and H2 would be a lead needing replication, not an edge.** Variants A, B and the 2× case are reported
whatever they show; none replaces the primary. No rule, threshold or size is changed after the quotes are seen. Anything
looked at after the run goes under a heading that says so. A Sharpe above 3 means hunt for the bug before reporting.

## 8. What is already known (we are not blind to the tickets)

- Everything in S18's and S21's summaries and files: every market's result, its traded prices, its Friday option quotes
  and its anchor. Selling the rule subset unhedged earned +22.27 points per contract [+10.35, +33.14] on 60 markets;
  18.3% of them resolved YES; the tickets were priced 40.9% on average against a central anchor of 28.9%. The 217 left
  markets earned +3.08 [−1.54, +7.91]. The full set earned +7.24 [+2.93, +11.56]; 26.0% resolved YES.
- **Out-of-sample has almost no markets:** 14 of the 277, and 2 of the 60 in the rule subset. Nothing can be confirmed
  out-of-sample here; S21 already found this.
- **Known before the run about H2(b):** S21's B0 book had no losing month in 10 (monthly Sharpe 2.70, drawdown 0.0%).
  On the rule subset the hedged book can at best tie the unhedged worst month. The unhedged full-set book had one losing
  month (−1.4% of its capital base; Sharpe 3.24, which S21 traced to the sample: 11 months, insurance sold in months
  when the insured move did not come).
- S21 noted that its central anchor sat about 7 points above realised outcomes (mean central anchor 33.8% against 26.6%
  resolved YES on its T2 set), that 214 of its 387 anchors moved a leg outward by one or two strikes (149 of these 277),
  that the band from bid to ask is a median of 6 points wide on the finish-beyond probability, and that Netflix was
  mostly dropped for its split.
- From Friday's quotes alone the cost of variant B is already computable; it has not been computed.
- **Not seen by anyone:** any option quote on the Monday after the ticket's weekend, the underlying's close at any
  expiry, or any hedged P&L.

## 9. Data and operations

- Massive only. `/v3/quotes/<option>` (last NBBO at or before 09:35:00 on the hedge day) for the two legs of each
  market: 554 requests. `/v2/aggs/ticker/<ticker>/range/1/day/...` unadjusted and adjusted for each of the 14 tickers
  (the index as `I:SPX`), and `/v3/reference/splits` for each. For `capacity.md` only, and last: each leg's daily bar on
  the hedge day (its volume). One worker, at most 2 requests a second, one small cache line per request in
  `research/s25_ticket_option_hedge/.cache/`, resumable. No call to Polymarket or Kalshi. S21's cache is not written.
- The recorder's log (`research/forward/recorder.log`) is read, never written: `fetch failed` lines are counted before
  and during the pull; more than 5 new ones and the pull drops to 1 request a second.
- Events are pulled in a seeded random order and the pull stops at 02:50 New York, so that a pull cut short leaves a
  random sample; whatever is not pulled is reported as not pulled.
- **If Monday quotes are not available for these contracts the study stops and reports the exact error.**

## 10. Deliverables

`research/results/s25_ticket_option_hedge/`: `SUMMARY.md` (written by `report.py` from the result files), `trades.csv`
(one row per market with both legs, every variant), `metrics.csv`, `hypotheses.csv`, `cells.csv`, `equity.csv`,
`equity_curve.png`, `drawdown.png`, `pnl_distribution.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

(none yet)
