# S22: quoting around the options price (the "market maker" reading of the taker prints)

Registered Sun 2026-10-04, about 00:45 New York time, **before any row of the input file was read**. Everything below
is fixed. Later changes go under **Amendments** at the bottom, dated, never rewritten. A null is an acceptable answer
and is reported as one.

## 1. The question, in plain words

Earlier studies found large modelled profits from trading Polymarket toward the price that listed options imply. Those
"prices" were midpoints of empty books that no taker could reach.

A market maker reads an empty book differently: nobody is quoting there, so be the quote. Post a resting offer just
above what the options chain says the contract is worth, and a resting bid just below. Let impatient takers trade
against us.

The public trade prints show what takers really paid. If a taker bought YES at a price above our offer, our offer was
the better price and would have been taken first. So every print that traded **away** from the options, by more than
our margin, is a fill we would have received.

**Question: over the partner's 970 evaluated prints, do the fills a maker quoting around the options band would have
received make money when held to the result?**

## 2. Data (one file, no network)

- `research/results/pm_taker_v2/prints_evaluated.csv` on branch `origin/r/thesis-pass-2`, read with `git show` at
  commit `fb66dc7a07ff32e47293bc1d4f9c265ed9080d4c` (git blob `7597b31fedf18fde85e6aab1c04775dae7bbb1dc`). The run
  refuses to start if the blob id differs.
- 1,155 public Polymarket trade prints on stock and SPY "close above $K on D" markets, resolution dates April to
  August 2026. Columns used: `market_id, tk, k, res_date, ts, side, px, size, status, p_mid, p_lo, p_hi, y`.
  `side` is the taker's side in YES terms. `px` is the traded price. `p_lo, p_mid, p_hi` are the options-implied
  probability band from a call spread quoted at the print's instant. `y` is the result (1 = YES).
- **Sample: the 970 rows with `status == ok`. No other filter.** Two bookkeeping exclusions, both counted in the log:
  a fill with no result (`y` missing) cannot be scored and is dropped; a print with size missing or not above zero is
  not a trade and gives no fill.

How the partner built the file (read from their code, section 9 below) matters for what the file can show. It is
listed under Limits in section 8.

## 3. Our quotes

- **Offer** (we sell YES) at `p_hi + m`. **Bid** (we buy YES) at `p_lo - m`.
- **m = 5 points (0.05) is the primary rule.** Variants: m = 2 points and m = 10 points.
- A quote outside [0.02, 0.98] is not posted.
- Each quote rests for 100 contracts and is refilled after every fill. No inventory limit.

## 4. Fills and P&L

- A taker **BUY** print with `px >= our offer` fills our offer. We sell YES at **our offer price**, not at `px`, for
  `min(print size, 100)` contracts.
- A taker **SELL** print with `px <= our bid` fills our bid. We buy YES at **our bid price**, for
  `min(print size, 100)` contracts.
- A resting order pays no fee on Polymarket (fees are charged to the taker only). So the cost here is not a fee. It is
  the risk that the taker who trades against us knows more than the options do. That risk is exactly what the P&L
  measures.
- Held to the result. A sale earns `offer - y`. A purchase earns `y - bid`. Per contract, in points (1 point = $0.01
  per $1 contract).
- Every print that qualifies is a fill. A market can give several fills.

## 5. Statistics

- **Primary estimator:** mean P&L per contract over fills, every fill counted once. Reported for all fills, for the
  offer side and for the bid side.
- **Interval:** 95% percentile bootstrap that resamples **resolution dates** (10,000 draws, seed 20261004). All markets
  resolving on one day share one market move, so a day is one bet.
- **Equal weight per day:** the mean of daily means, with the same bootstrap.
- **Out-of-sample:** the most recent 20% of resolution dates. The dates are the distinct `res_date` values of the 970
  rows, sorted; the last `ceil(0.20 x number of dates)` are out-of-sample. The cut comes from the dates in the file,
  not from the fills, and is written to the log before any fill is computed.
- **Also reported:** number of fills, resolution dates and markets. The same by ticker, by `p_mid` region (below 10%;
  10 to 25%; 25 to 75%; 75 to 90%; above 90%) and by dose. **Dose** = how far the print was beyond the band:
  `px - p_hi` for an offer fill, `p_lo - px` for a bid fill, in three bins: m to 2m, 2m to 4m, beyond 4m.
- **Secondary rows (reported, never change the verdict):**
  1. m = 2 and m = 10.
  2. Weighted by contracts instead of by fill.
  3. First fill per market only (so one busy market cannot count many times).
  4. Tick grid: Polymarket prices move in cents, so the offer is rounded **up** to the cent and the bid **down**; fills
     and prices use the rounded quote.

## 6. The book

- Dollar P&L per fill = P&L per contract x contracts. **Capital = the cash locked per fill:** `price x contracts` for a
  purchase, `(1 - price) x contracts` for a sale.
- **Daily series:** dollar P&L summed by resolution date, over every resolution date of the 970 rows (zero on a date
  with no fill).
- **Sharpe** = mean / standard deviation (n - 1) of that daily series, times the square root of the resolution days a
  year in the sample: `number of dates x 365.25 / (calendar days from the first to the last date, inclusive)`.
- **Maximum drawdown:** the largest peak-to-trough fall of cumulative dollar P&L (the curve starts at zero), in dollars
  and as a share of the bankroll. **Bankroll** = the largest cash locked for any one resolution date.
- **Worst month:** the calendar month of resolution with the lowest summed P&L.
- **Return on capital:** total P&L / total cash locked over all fills.
- **A Sharpe above 3 means hunt for the bug** and write up what was checked.

## 7. Stress (the 2x case) and the pass rule

**Stress.** The quote is widened to `m + 2 points`, and a print fills us only when it is **at least one cent beyond**
the widened quote (a print exactly at our price was somebody else's order, ahead of us in the queue). The fill is at
the widened quote.

**Pass, on the primary rule (m = 5 points). All seven lines must hold:**

1. At least 100 fills.
2. Fills on at least 30 resolution dates.
3. Mean P&L per contract above zero on the whole sample.
4. The 95% interval on the whole sample excludes zero (lower bound above zero).
5. Mean above zero in-sample.
6. Mean above zero out-of-sample (no out-of-sample fills = fail).
7. Mean above zero under the stress.

Otherwise the report says exactly which lines failed. **A pass is a LEAD that needs replication on other markets, not
an edge.** The variants are disclosed in full and none of them can replace the primary rule.

## 8. Limits the summary must state

- **We had no orders in the book.** A print proves a taker was willing to pay that price. It does not prove the taker
  would have traded the same way with our quote present, or that we would have been first in the queue.
- **The option band must be known at the print's instant.** This assumes a quoting engine that reprices from the live
  option chain every second.
- **Printed sizes are small.**
- **One window of five months.** Megacap stocks and SPY only; resolution days Tuesday to Friday after an ordinary
  weeknight; prints from 10:00 to 15:55 New York time on the day before the result.
- **The file is not every print.** The partner's code (section 9) keeps only the first YES-buy and the first YES-sell
  print per market per clock minute; evaluates buys only up to a price of 0.94 and sells only down to 0.06, so some
  far-away fills are missing; stops evaluating a market at the first print that traded 10 points **toward** the
  options; and marks a print `ok` only when the option band is at most 20 points wide and `p_mid` is between 0.03 and
  0.97. These selections use prices only, never results, but they shape the sample.
- **The same 970 prints were already used once**, for the partner's taker study. This is a second look at one file from
  the other side of the trade.

## 9. What was already known when this was written

Seen before registration: the partner's `SUMMARY.md`, their `METHOD.md`, `config.py`, `core.py`, `run.py`, `report.py`,
the progress lines of their `RUN_LOG.md`, and `arbscan/implied.py` and `arbscan/datasrc.py`. **Not seen: any row of
`prints_evaluated.csv`, their `trades.csv` or `stats.json`.**

From the partner's `SUMMARY.md` (study `pm_taker_v2`, verdict INSUFFICIENT on sample size):

- They copied the takers who traded **toward** the options. Primary rule (5-point threshold, entry at the print plus
  one cent, Polymarket fee, held to the result): **+29.79 points per contract, interval +13.01 to +44.58, 40 trades on
  21 resolution days.** Their pass rule needed 100 trades on 30 days.
- Other rows: 3-point threshold +15.18 [+5.33, +25.29], 110 trades on 35 days. 10-point threshold +39.88, 5 trades on
  3 days. Two cents of slippage +28.79. No tick +30.79. Gross +31.28. Equal weight per day +27.05 [+10.01, +42.57].
  Mid variant +21.86 [+13.64, +29.46], 112 trades on 38 days.
- **31 of the 40 primary trades were buys** (+28.38) and 9 were sells (+34.62, interval -19.49 to +69.42).
- By ticker: SPY 15 trades +22.21; NVDA 6, +63.15; AAPL 5, +57.26; GOOGL 4, +35.35; TSLA 4, -32.99; AMZN 3, +1.78;
  MSFT 2, +67.14; META 1, +44.01.
- **Over the 970 prints (324 markets) the options mid had a Brier score of 0.2145 against 0.2257 for the print price.**
  So on average the options were closer to the result than the traded price.
- Capacity: taking half of each qualifying print gave 2,881 shares, $747 deployed and $1,535 net; median print size
  19.5 shares.
- Scope: 2,012 markets on 68 resolution days; 2,293 raw prints; 1,962 kept after thinning; 970 `ok`, 177 unusable
  band, 8 no option pair. No unresolved trades; no disagreement between Polymarket's result and the closing price.
- Their own caveat: the estimate sits near the smallest effect the sample could detect, so it probably overstates the
  true size.

**What that implies and what it leaves open.** The Brier result already says that betting toward the options was
right on average over all prints together. What is **not** known is whether that holds for the prints that traded
**away** from the options. Those are the maker's fills, and they are the prints where the taker chose to pay more than
the options said. That taker may know something the options do not (this is the usual cost of quoting, "adverse
selection"). Nobody has computed it. The two sets do not overlap: the partner's trades are prints at least 5 points
on the cheap side of the options mid; the fills here are prints at least m points on the dear side of the band.

No expectation of size is registered. The number of fills is not known; if it is under 100 the pass rule fails on
line 1 and the answer is "too few fills to say".

**Timing of the option quotes (read from the code, not from the data).** For a print stamped at second `t`, each
option leg uses the last national best bid and offer stamped **at or before `t - 1` second**
(`core.option_spread`: `snap = t - QUOTE_LAG_SEC`, `QUOTE_LAG_SEC = 1`; `datasrc.OptionSource.quote` asks Massive for
`timestamp.lte = snap`, newest first, one row). A leg older than 300 seconds at that instant is rejected. So the band
never uses a quote from the print's own second or later: **no look-ahead in the option quotes.** The result `y` was
joined after the list of prints was frozen. One thing the code cannot settle: Polymarket's print time is the time the
trade settled on-chain, which can be a second or two after the orders matched, so the option quote could in principle
be up to that much later than the match. The 1-second lag covers part of it.

## 10. Outputs

`research/results/s22_options_quoting/`: `SUMMARY.md` (answer first), `metrics.csv`, `trades.csv` (one row per primary
fill), `trades_variants.csv` (fills of every other variant), `daily.csv`, `equity_curve.png`, `drawdown.png`,
`capacity.md`, `RUN_LOG.md`. Code: `research/s22_options_quoting/run.py`; tests on synthetic rows in `tests/`.

## Amendments

None.
