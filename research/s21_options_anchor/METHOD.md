# S21: does the options chain tell which "will it hit" tickets are overpriced?

Pre-registered Sun 2026-10-04, about 00:45 New York time. This file and `config.py` are committed **before any option
quote for these markets is pulled**. Changes afterwards go under "Amendments", dated, never rewritten.

## 1. The thesis (the project owner's)

A Polymarket price market on a stock or the S&P 500 ("Will NVIDIA dip to $192 in March?", "Will S&P 500 (SPY) hit (LOW)
$680 in June?") is an option sold to retail. The listed options chain prices the same payoff professionally: same
underlying, same level, same month. The claim: **the further a ticket trades above what the options chain says it is
worth, the more its buyers lose, and a rule that sells only the tickets priced above the options anchor is the edge.**

S18 measured these tickets against their results and used no options. S21 adds the anchor.

## 2. Markets and parsing (rules fixed here; no option data is used to parse)

The rows of `research/results/s18_price_market_calibration/prints_markets.csv` with `asset_class` `stock` or `sp500`:
424 markets, 76 events. Each is joined to its universe record (`s9_weekend_price_markets/universe.json`,
`s15_weekend_scare/universe.json`) and to S18's `entries.csv` (the entry instant, the result time).

- **Ticker:** the single symbol in parentheses in the event title ("What will NVIDIA (NVDA) hit in March 2026?"). If the
  question carries its own symbol it must be the same.
- **Underlying of the options:** the ticker itself. S&P 500 questions written on SPY use SPY options at the SPY level
  the question names. S&P 500 questions written on the index ("S&P 500 (SPX) hit $6,900") use the index's own PM-settled
  options (root SPXW) at the index level named. No level is converted from the index to SPY or back: that would be a
  model. If index option quotes are not served, those markets are counted and dropped.
- **Level:** the number after "reach", "dip to" or "hit" (after an optional "(HIGH)"/"(LOW)" and "$"). It must equal the
  number in the universe label ("↑ $960").
- **Direction:** "reach" or "(HIGH)" = up; "dip" or "(LOW)" = down; a question with neither ("hit $200 before 2026")
  takes the arrow of the universe label. It must equal the universe's `sign`.
- **Window end:** from the event title. "in <Month> <Year>" or "by end of <Month>": the last calendar day of that month
  (no year named: the first such month-end on or after the market's listing day). "before 2026": 2025-12-31. "Week of
  May 4 2026": the Friday of that week. The **end session day** is the last weekday on or before that day.
- A market that fails any of these is counted by reason and dropped.

Checked on catalogue metadata only, before this commit: all 424 parse (0 dropped). Tickers: NVDA 79, TSLA 59, SPY 41,
GOOGL 39, AMZN 30, SPX 30, META 28, NFLX 26, AAPL 24, MSFT 22, PLTR 20, OPEN 16, HOOD 7, RKLB 3. Every S18 entry instant
is a Friday 20:00 New York; 18 distinct Fridays from 2025-10-31 to 2026-09-25.

## 3. The anchor

- **Instant:** 15:55 New York on the last session day before the market's first weekend, which is the Friday S18's entry
  instant (20:00) belongs to. On a half session (2025-11-28, close 13:00) the instant is 12:55.
- **Expiry:** the listed expiry nearest on or after the end session day. Weekdays are walked forward from the end session
  day, at most 45 calendar days. An expiry counts only if it gives two usable legs at the instant (a weekly that was not
  yet listed on the anchor Friday has no quote); at most three listed expiries are tried, in order.
- **Strikes:** the two listed strikes that bracket the level, by the existing rule (`arbscan.implied.bracket_indices`):
  if the level is itself a listed strike, its two neighbours; otherwise the strikes just below and just above.
- **The probability of finishing beyond the level**, with its band, by the existing code (`arbscan.implied.Spread`,
  imported unchanged): up = the call spread (long the lower strike); down = the put spread (long the higher strike).
  `p_mid` from the two mids, `p_lo` from long-leg bid minus short-leg ask, `p_hi` from long-leg ask minus short-leg
  bid, each divided by the strike width, grossed up by exp(0.04 × years to expiry), clamped to 0..1.
- **Usable leg quote:** the last NBBO at or before the instant, at most 10 minutes old, with an offer above zero and a
  bid of zero or more not above the offer. A leg without one moves outward by one listed strike, at most twice (the
  existing rule). **One stated difference from the existing code:** it requires a bid above zero; here a zero bid is
  accepted, because far-from-the-money legs often show "0 bid, 2 cents offered" and dropping them would drop exactly
  the cheap tickets. The anchor file flags every anchor with a zero-bid leg, and one fixed robustness row (R1) reruns
  the primary book without them.
- **Two anchors, both reported:**
  - **lower bound** = `p_mid` (touching the level at any time is at least as likely as finishing beyond it);
  - **central estimate** = min(1, 2 × `p_mid`), the reflection rule for a touch. It is an approximation: it ignores
    drift, and the expiry is at or after the question's end, which makes the anchor a little high. Stock and SPY options
    are American; the spread is read as if European, as the existing code does.
- A market with no listed expiry in range, no bracketing strikes, or no usable pair of legs is counted by reason and
  dropped. No modelled price is substituted anywhere.

## 4. Prices, gaps, results (all from S18, unchanged)

- Buyers' traded price `buy_price` and sellers' traded price `sell_price`: the size-weighted price of takers who bought
  (sold) YES during the market's first weekend, Friday 20:00 to Sunday 20:00 New York.
- Held-to-result P&L per contract after the market's own taker fee: `buy_pnl_points`, `sell_pnl_points`; with the fee
  doubled: the `_2x_fee` columns. (Many of these markets charge no fee; doubling zero is zero.)
- **Gap** = 100 × (traded price − anchor), in points, per side (buyers' price for buyers, sellers' price for sellers).
- The option side is a yardstick only. Nothing is traded there.
- In-sample and out-of-sample: S18's `segment` column, unchanged (the most recent 20% of S18's 130 events).

## 5. Tests. Every interval resamples events (S7/S18's `boot_mean`, 2,000 draws, seed 0; under 5 events: no interval)

**T1, dose and response.** Markets with a first-weekend taker purchase and an anchor. Buyers' held-to-result P&L by
bucket of the gap against the central anchor: below −5, −5 to 0, 0 to +5, +5 to +10, +10 or more (lower edge included).
Per bucket: markets, events, mean traded price, mean anchor, share resolved YES, mean P&L with its interval. One summary
number: the slope of buyers' P&L on the gap (least squares, errors clustered by event, and the event-bootstrap interval
of the slope). **The thesis predicts a negative slope: the loss grows with the gap.** The same table against the
lower-bound anchor is reported as secondary.

**T2, which price knows more.** Markets with an anchor and any first-weekend print. The traded price is the
size-weighted mean of both sides' prints. (a) Linear probability regression of the result on the central anchor and the
traded price together, errors clustered by event; repeated with the lower-bound anchor. (b) Brier scores of the central
anchor, the lower-bound anchor and the traded price; the difference (traded price minus anchor; positive = the anchor is
the better forecast) with its event-bootstrap interval. **The thesis predicts the anchor carries the weight:** its
coefficient is above zero with an interval excluding zero and larger than the traded price's, and its Brier score is
lower.

**T3, the PolyBridge rule, the trade.** Books built with S18's own book function (`s18_price_market_calibration.report.book`:
up to 100 contracts per market, never more than the printed size; P&L booked in the month of the result; capital locked
from the first weekend to the result; Sharpe on monthly P&L):

| Book | Rule |
|---|---|
| **B0 (primary)** | sell YES at the traded bid (`sell_price`) when it is 5 points or more above the central anchor; hold to the result |
| B1 | the same at 10 points or more |
| B2 | buy YES at the traded ask (`buy_price`) when it is 5 points or more below the lower-bound anchor; hold to the result |
| U (benchmark) | S18's unfiltered book: sell YES at the traded bid on every anchored market with a taker sale |
| U-all (benchmark) | the same on every stock and S&P market with a taker sale, anchored or not |
| R1 (robustness) | B0 without the anchors that used a zero-bid leg |

For each: markets, events, mean P&L per contract with its interval, P&L in dollars, monthly Sharpe, maximum drawdown,
worst month; whole sample, in-sample, out-of-sample; fee at 1× and 2×. **Does the anchor improve S18's book?** The mean
P&L per contract of the markets B0 takes minus that of the anchored markets with a taker sale it leaves, with its
event-bootstrap interval (`boot_diff`).

## 6. Pass rule

B0 passes only if all hold: (1) in-sample mean P&L per contract above zero with the interval excluding zero; (2) the same
out-of-sample; (3) above zero with the fee doubled, in-sample and out-of-sample; (4) at least 30 out-of-sample markets in
the book. Otherwise the summary says exactly which line failed, including "too few". **A pass would be a lead needing a
replication, not an edge.** No rule, threshold or bucket is changed after the quotes are seen; every variant is reported.
A Sharpe above 3 means hunt for the bug before reporting.

## 7. What is already known (we are not blind to the results, only to the anchor)

- Everything in S18's `SUMMARY.md` and `prints_markets.csv`, including every market's result and traded prices.
  First-weekend buyers of YES in price markets lost 8.87 points per contract held to the result [−11.94, −5.93]; sellers
  into bids earned +3.63 [+0.72, +6.57], in-sample +4.69, out-of-sample −0.99 [−10.96, +9.28]. Sellers earned most at
  traded prices of 50 to 75% (+13.30 [+5.16, +21.33]). At history mids, stock markets resolved YES 10.91 points less
  often than priced [−14.62, −6.94] and S&P markets 20.23 points less often [−28.34, −12.62].
- **Known before the pull: line (4) of the pass rule cannot be met.** Of the 424 markets only 30 are in S18's
  out-of-sample events, and only 15 of those have a taker sale (25 have a taker purchase). B0 can hold at most 15
  out-of-sample markets, so the verdict will be "not a pass: too few out-of-sample" whatever the anchor shows. What the
  study can still answer honestly: whether the anchor sorts the tickets (T1, T2) and whether the filtered book beats the
  unfiltered one in-sample.
- On a different set of markets ("close above" questions) the options-implied probability was a more accurate forecast
  than the Polymarket price (Brier difference +0.0108, interval +0.0064 to +0.0158), and trading toward the options at
  printed prices earned +15 points per trade on 110 trades (interval +5 to +25) in one small test and nothing on another
  (−0.40 on 402 trades).
- Netflix split 10-for-1 in November 2025. Options listed across a split have adjusted strikes; where the question's
  level has no bracketing listed strikes, or the legs have no quote at the instant, the market is dropped by the rules
  above, not repaired.
- No option quote for any of these markets has been seen by anyone.

## 8. Data and operations

- Massive only: `/v3/reference/options/contracts` (calls of one underlying and one expiry; the put of the same strike by
  its OCC symbol) and `/v3/quotes/<option>` (last NBBO at or before the instant). One worker, at most 2 requests a
  second, one small cache line per request in `research/s21_options_anchor/.cache/`, resumable. No call to Polymarket or
  Kalshi.
- The recorder's log (`research/forward/recorder.log`) is read, never written: `fetch failed` lines are counted before
  and during the pull; more than 5 new ones and the pull drops to 1 request a second.
- Events are pulled in a seeded random order and the pull stops at 02:05 New York, so that a pull cut short leaves a
  random sample; whatever is not pulled is reported as not pulled.
- If option quotes for these dates or tickers are not available, the study stops and reports the exact error.

## 9. Deliverables

`research/results/s21_options_anchor/`: `SUMMARY.md`, `anchors.csv` (one row per market: parse, legs, quotes, anchor or
the reason it was dropped), `t1_buckets.csv`, `t2_regression.csv`, `metrics.csv` (the books), `trades.csv`,
`gap_buckets.png`, `equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

(none)
