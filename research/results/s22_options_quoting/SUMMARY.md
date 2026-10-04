# S22: quoting around the options price (the market-maker reading of the taker prints)

## The answer

**A maker quoting 5 points outside the options band would have been filled 74 times in five months and earned
+24.51 points per contract, 95% interval +8.57 to +37.52** (74 fills, 27 resolution dates, 46 markets; held to the
result; resting orders pay no fee).

That number is significant. It does **not** yet support the market-maker idea, and the reasons are in the same tables:

1. **It is one-sided.** Buying from takers who sold below the band earned **+32.33 points [+14.32, +48.45]** on 59
   fills. Selling to takers who bought above the band **lost 6.24 points [-28.90, +13.04]** on 15 fills.
2. **In this window, buying YES paid whoever did it, with or without options.** The benchmark (registered before the
   data was read) is the other side of all 970 prints at the print's own price, with no options band at all: buying
   from every seller earned **+21.63 [+7.33, +32.19]**; selling to every buyer lost **16.09 [-25.88, -3.28]**. Much of
   the +32 on our bid is the direction of the window, not the options. Our bid fills beat the blind buyer by +10.70
   points [-3.80, +23.67] (looked at after the run), which does not exclude zero.
3. **The further the print was from the band, the less it earned.** If the options were simply right, bigger gaps
   should pay more. They paid less: 5 to 10 points beyond the band +34.65 (53 fills); 10 to 20 points -5.24 (7 fills);
   beyond 20 points +1.02 (14 fills). Quoting 10 points out instead of 5: +3.93 [-17.09, +21.11] on 21 fills.
4. **The stress case is not distinguishable from zero and loses money in dollars.** Quote 7 points out and require
   the print to be a cent through us: +6.01 per fill [-11.27, +20.72] on 29 fills, and the dollar book is **-$37.15**.

**Pre-registered pass rule: FAIL, on sample size.** Line 1 failed (74 fills, 100 needed) and line 2 failed (27
resolution dates, 30 needed). The five sign lines held: whole sample above zero with the interval excluding zero,
in-sample +27.39, out-of-sample +3.77, stress +6.01. Even a pass would have been a lead needing replication on other
markets, not an edge.

## The numbers (primary rule, m = 5 points)

P&L in points per contract (1 point = $0.01 on a $1 contract). Intervals are 95% bootstrap intervals that resample
resolution dates, 10,000 draws.

| | fills | dates | markets | mean per fill | 95% interval | equal weight per day |
|---|---|---|---|---|---|---|
| **All fills** | 74 | 27 | 46 | **+24.51** | [+8.57, +37.52] | +13.28 [-1.26, +26.66] |
| Offer side (we sell YES above the band) | 15 | 13 | 14 | -6.24 | [-28.90, +13.04] | -7.83 [-31.98, +14.31] |
| Bid side (we buy YES below the band) | 59 | 22 | 35 | +32.33 | [+14.32, +48.45] | +22.83 [+5.68, +38.98] |
| In-sample (first 38 dates) | 65 | 21 | 38 | +27.39 | [+9.70, +40.71] | +14.65 [-4.15, +31.29] |
| Out-of-sample (last 10 dates, 2026-07-07 to 08-14) | 9 | 6 | 8 | +3.77 | [-5.64, +18.08] | +8.49 [-2.79, +18.75] |
| Stress (7 points out, print a cent through) | 29 | 18 | 24 | +6.01 | [-11.27, +20.72] | +0.41 [-19.55, +19.56] |

Weighted by contracts instead of by fill: +26.16 [+0.52, +44.51]. The out-of-sample fifth of the dates holds only 41
of the 970 prints, so it is a weak test.

### Dose: how far the print was beyond the band

| distance beyond the band | fills | dates | markets | mean | 95% interval | offer side | bid side |
|---|---|---|---|---|---|---|---|
| 5 to 10 points (m to 2m) | 53 | 20 | 31 | +34.65 | [+17.02, +51.39] | +18.50 (2 fills) | +35.28 (51 fills) |
| 10 to 20 points (2m to 4m) | 7 | 6 | 6 | -5.24 | [-37.41, +22.58] | -15.70 (6 fills) | +57.49 (1 fill) |
| beyond 20 points (4m) | 14 | 9 | 12 | +1.02 | [-24.71, +21.23] | -5.20 (7 fills) | +7.24 (7 fills) |

### By ticker and by where the options put the probability

| ticker | fills | dates | markets | mean | 95% interval |
|---|---|---|---|---|---|
| SPY | 24 | 16 | 18 | +12.20 | [-7.64, +30.32] |
| NVDA | 20 | 7 | 8 | +43.03 | [+1.40, +59.12] |
| AAPL | 10 | 8 | 8 | +30.44 | [-10.63, +57.77] |
| AMZN | 7 | 3 | 4 | +63.63 | [+41.80, +73.53] |
| TSLA | 7 | 5 | 6 | +6.60 | [-26.85, +24.00] |
| GOOGL | 5 | 1 | 1 | -25.88 | one date |
| MSFT | 1 | 1 | 1 | -6.00 | one date |

META had no fill. An interval built on fewer than about ten dates is not reliable.

| options mid (`p_mid`) | fills | dates | markets | mean | 95% interval |
|---|---|---|---|---|---|
| below 10% | 4 | 3 | 3 | +9.88 | [+9.00, +11.50] |
| 10 to 25% | 14 | 9 | 11 | +15.62 | [-7.84, +34.65] |
| 25 to 75% | 46 | 16 | 27 | +31.06 | [+9.07, +47.52] |
| 75 to 90% | 10 | 8 | 8 | +12.69 | [-14.70, +28.14] |
| above 90% | 0 | 0 | 0 | | |

### Every variant tried (all registered before the data was read; none replaces the primary rule)

| variant | fills | dates | markets | mean | 95% interval | offer side | bid side | out-of-sample |
|---|---|---|---|---|---|---|---|---|
| m = 2 points | 300 | 39 | 137 | +17.52 | [+8.56, +23.07] | -14.76 (81) | +29.47 (219) | -7.00 (18 fills) |
| **m = 5 points (primary)** | 74 | 27 | 46 | +24.51 | [+8.57, +37.52] | -6.24 (15) | +32.33 (59) | +3.77 (9 fills) |
| m = 10 points | 21 | 13 | 18 | +3.93 | [-17.09, +21.11] | -5.04 (13) | +18.52 (8) | +11.10 (5 fills) |
| stress: m = 7, a cent through | 29 | 18 | 24 | +6.01 | [-11.27, +20.72] | -8.04 (13) | +17.42 (16) | +5.38 (6 fills) |
| m = 5 on the cent grid | 68 | 27 | 43 | +25.46 | [+10.80, +37.48] | -5.53 (15) | +34.23 (53) | +4.44 (9 fills) |
| m = 5, first fill per market | 46 | 27 | 46 | +20.07 | [+5.94, +31.73] | -1.89 (13) | +28.72 (33) | +3.11 (8 fills) |
| benchmark: other side of every print at its price, no options | 970 | 48 | 324 | +2.89 | [-0.71, +5.90] | -16.09 (482) | +21.63 (488) | +3.05 (41 fills) |

The offer side loses in every row. By equal weight per day the benchmark is +1.83 [-3.25, +6.76]; its bid side is
+9.34 [-1.12, +19.20] and its offer side -1.80 [-11.56, +8.58].

## The book (primary rule)

Each fill is the print's size capped at 100 contracts. Capital is the cash locked: the price for a purchase, 1 minus
the price for a sale.

| | primary (1x) | stress (2x) |
|---|---|---|
| Total P&L | +$623.97 | -$37.15 |
| Cash locked over all fills | $1,036.54 | $540.27 |
| P&L on cash locked | +60.2% | -6.9% |
| Bankroll (most cash locked for one resolution date) | $181.19 | $86.50 |
| Sharpe on P&L by resolution date (48 dates, 128.9 a year) | 2.82 | -0.40 |
| Maximum drawdown | $145.88 (80.5% of bankroll) | $151.46 (175.1% of bankroll) |
| Worst month | June 2026, -$50.69 (28.0% of bankroll) | May 2026, -$78.75 (91.0% of bankroll) |
| Dates with fills: winning / losing | 21 / 6 | 11 / 7 |

By month (primary): April +$298.65 (31 fills), May +$265.57 (26), June -$50.69 (6), July +$97.93 (9), August +$12.51
(2). Turnover: the cash locked over the window is 5.7 times the bankroll. Charts: `equity_curve.png`, `drawdown.png`.

**Costs.** A resting order pays no fee on Polymarket (fees are charged to the taker only; source: the partner's
METHOD and PARALLEL_BRIEF section 2). The 1x case is the primary rule. The 2x case is the stress: the quote 2 points
(200 bp of the $1 payoff) further out and the print at least 1 cent (100 bp) through it.

**The Sharpe of 2.82 is under the "above 3, hunt for the bug" line, but close, so the checks were run anyway.**
(a) The headline was recomputed from the raw file in plain pandas without the runner's fill code: 74 fills, 27 dates,
46 markets, +24.51, offer 15 at -6.24, bid 59 at +32.33, $623.97 on $1,036.54. It matches. (b) Three fills were
checked by hand against the raw rows. (c) No fill was dropped: every `y` is 0 or 1, no size is zero. (d) A unit test
shows the code gives a loss when the takers are right and a gain when the options are right, so it has no built-in
sign. (e) The option quotes have no look-ahead (next section). The Sharpe is high for reasons that are not an edge:
only 27 days had a fill, the book was mostly long YES in a window where YES kept winning, and one market made 40.7% of
the dollars (NVDA above $200 on 2026-05-06, nine fills, +$254.06). Without the best date the Sharpe is 2.44.

## Timing of the option quotes: no look-ahead found

Read from the partner's code (`pm_taker_v2/core.py`, `arbscan/datasrc.py`, `arbscan/implied.py`), not inferred from
the data. For a print stamped at second `t`, each option leg uses the last national best bid and offer stamped **at or
before `t - 1` second** (`snap = t - QUOTE_LAG_SEC`, `QUOTE_LAG_SEC = 1`; the request is `timestamp.lte = snap`,
newest first, one row). A leg older than 300 seconds is rejected. So `p_lo` and `p_hi` never use a quote from the
print's own second or later. The result `y` was joined after the list of prints was frozen. One thing the code cannot
settle: Polymarket's print time is when the trade settled on-chain, which can be a second or two after the orders
matched, so an option quote could in principle be that much later than the match. The one-second lag covers part of
it.

## Limits

- **We had no orders in the book.** A print proves a taker was willing to pay that price. It does not prove the taker
  would have traded the same way with our quote present, or that we would have been first in the queue.
- **The option band must be known at the print's instant.** This assumes a quoting engine that reprices from the live
  option chain every second. The band here can be up to 300 seconds old.
- **Printed sizes are small.** Median print among the fills: 12.19 contracts. 2,385 contracts filled in five months,
  $842.79 of notional, $1,036.54 of cash locked (`capacity.md`).
- **One window of five months**, megacap stocks and SPY, resolution days Tuesday to Friday, prints from 10:00 to 15:55
  New York time the day before the result.
- **One direction of market.** In this window "close above" resolved YES far more often than either market priced
  (see below). A maker who mostly buys YES looks good in such a window for a reason that will not repeat on demand.
- **The file is not every print.** It keeps the first buy and first sell print per market per minute; evaluates buys
  only up to 0.94 and sells only down to 0.06, so some far-away fills are missing; stops a market at the first print
  that traded 10 points toward the options; and keeps a print only when the option band is at most 20 points wide.
- **Second look at one file.** The same 970 prints were used for the partner's taker study.

## What did not work

- The offer side: negative at every margin (m = 2: -14.76 on 81 fills; m = 5: -6.24 on 15; m = 10: -5.04 on 13).
- Fills 10 points or more beyond the band: -5.24 on 7 fills and +1.02 on 14.
- The stress in dollars: -$37.15; weighted by contracts -3.82 points [-32.21, +28.31].
- Equal weight per day, the interval includes zero: +13.28 [-1.26, +26.66].
- Out-of-sample: +3.77 on 9 fills, interval [-5.64, +18.08]; at m = 2 it is negative (-7.00 on 18 fills).
- Sample size: 74 fills on 27 dates, under the 100 and 30 the rule needs.

## Looked at after the run (not pre-registered; describes, does not test)

Every number here is in `post_run.csv`, written by `post_run.py`.

- **Direction of the window.** Over the 970 prints YES resolved 67.9% of the time; the mean print price was 49.1% and
  the mean options mid 50.1%. Counting each market once (its first print): 61.1% YES against an options mid of 48.8%.
  Equal weight per date: 53.9% against 51.1%. Both markets under-priced YES in this window.
- **Our fills against that backdrop.** Bid fills: mean bid 0.372, mean options mid 0.432, and 41 of 59 resolved YES
  (69.5%). Offer fills: mean offer 0.338, mean options mid 0.281, mean print price 0.537, and 6 of 15 resolved YES
  (40.0%).
- **Is the options band adding anything beyond being the other side?** Our fills minus the benchmark on the same side:
  bid +10.70 points [-3.80, +23.67]; offer +9.85 [-12.30, +27.62] (day bootstrap of the difference). Both point the
  right way; neither excludes zero.
- **Concentration.** The best date (2026-05-06, 13 fills) made $288.53 of the $623.97. Without it: 61 fills, +17.42
  per fill, $335.44. Without the best market: 65 fills, +17.74 per fill, $369.91. No intervals were computed for these.
- **The same fills at the print's price instead of our quote** (what the real counterparties earned): +32.24 per
  fill; bid side +36.96, offer side +13.68. On the offer side the takers paid well above where our quote would have
  been, so our cheaper offer gives that difference away.

## Files

`metrics.csv` (every pre-registered number above), `post_run.csv` (the looks after the run), `trades.csv` (one row
per primary fill), `trades_variants.csv` (fills of the other variants and the benchmark), `daily.csv`,
`equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`. Method: `research/s22_options_quoting/METHOD.md`.
Rerun: `cd research && .venv/bin/python -m s22_options_quoting.run`, then `-m s22_options_quoting.post_run`.
