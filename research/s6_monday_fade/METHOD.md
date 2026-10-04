# S6: on Monday morning, bet with the options against the prediction market (pre-registered)

**Question.** Over a weekend Polymarket keeps trading its "stock closes above $K" contracts while listed options are
shut. On Monday at 09:45 the options have reopened and give their own probability for the same event. When the two
disagree by more than the cost of trading Polymarket, does taking the options' side **on Polymarket**, and holding to
resolution, make money?

The earlier study R3 asked the opposite trade (buy the options toward Polymarket) and found nothing after option
costs. Its side results point the other way: the options were better calibrated than Polymarket at the open, and
Polymarket gave back part of its weekend move. S6 tests that directly.

This file and `config.py` are committed **before any P&L of this trade is computed**. Every rule is fixed. Changes
go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- `research/results/open_options/SUMMARY.md` (R3): 1,535 events over 44 closures; options at Monday 09:45 reflected
  0.44 of Polymarket's closure move; the gap before costs, signed by the Polymarket move, was +7.34 points; Polymarket
  gave back 3.48 points by the end of the reopening day; Brier score 0.146 for Polymarket at 09:30 against 0.120 for
  the options at 09:45. These numbers are the reason for the test and they favour it.
- The column names and the first row of `events.csv`.
- From S1: a Polymarket history price is a midpoint or a last trade, not an executable price, and an assumed spread
  around it can manufacture profit. The trade-print check below exists for that.
- **Not seen:** the P&L of any trade on Polymarket against the options' probability, on any subset.

## 1. Data

- `research/results/open_options/events.csv` as committed: each row is a (market, closure) pair with the Polymarket
  price at 09:45 (`pm_0945`) and at the end of the reopening day (`pm_eod`), the option-implied probability band at
  09:45 (`oo_lo`, `oo_hi`: sell and buy the call spread at real NBBO quotes), and the market's result (`outcome`).
- Rows: R3's **events** (Polymarket moved 3 points or more over the closure and every measurement is valid). Rows
  without a result are dropped.
- Nothing is pulled for the trade itself. The trade-print check (section 4) pulls Polymarket trade prints for the
  markets traded.

## 2. The trade

With `p` = Polymarket at 09:45, half-spread `h`, fee `f(x) = 0.04 × x × (1 − x)`, cost multiplier `c`:

- **Sell YES** (buy NO) when `(p − c·h) − c·f − oo_hi ≥ θ`. Price received `b = p − c·h`. P&L per contract
  `b − c·f(b) − outcome`.
- **Buy YES** when `oo_lo − (p + c·h) − c·f ≥ θ`. Price paid `a = p + c·h`. P&L per contract `outcome − a − c·f(a)`.
- Held to the market's own resolution. 100 contracts per trade. No hedge: the options are the reference, not a leg.
- **Half-spread `h`.** Historical Polymarket books are not published. `h` is measured, before the run, on this
  weekend's recorded books of the same kind of market: the median across markets of each market's median half-spread,
  over two-sided books with a mid between 0.05 and 0.95, in the slice 2026-10-03 23:09:48 to 2026-10-04 00:00:00 UTC
  of `research/forward/raw/thresholds/`. It is written to `run_meta.json`. These are weekend books, which should be
  no tighter than Monday morning's.

## 3. Variants (the complete list)

| id | θ | rows | exit |
|---|---|---|---|
| **V0, primary** | 2 points | R3 events | resolution |
| V1 | 5 points | R3 events | resolution |
| V2 | 2 points | every pair with valid measurements, whatever the closure move | resolution |
| V3 | 2 points | R3 events | end of the reopening day, at `pm_eod` less another half-spread and fee |

Each at 1× and 2× costs (`h` and the fee doubled). The deflated Sharpe ratio uses 4 trials.

## 4. Accounting, segments, checks

- **Capital:** a trade locks `100 × a` (buy YES) or `100 × (1 − b)` (buy NO). The capital base `K` is the largest
  capital deployed on one closure. Return of a closure = its net P&L ÷ `K`; a trade's P&L is booked to its closure.
- **Metrics:** trades, closures traded, net P&L, mean net P&L per trade, hit rate, Sharpe on closure returns
  (annualised by the number of closures a year), maximum drawdown, worst month, turnover, costs in bp of capital.
- **Inference:** mean net P&L per trade with a 95% bootstrap interval that resamples **closures** (a ladder of
  strikes on one stock shares one outcome path).
- **In-sample / out-of-sample:** by closure date, OOS is the most recent 20% of closures. Nothing is fitted.
- **Trade-print check:** an entry is print-verified if a public Polymarket trade within ±10 minutes of 09:45 shows a
  price at least as good as the one assumed: for a YES sale, a taker sold YES at or above `b`; for a YES purchase, a
  taker bought YES at or below `a`. Verified size is the printed size, capped at 100.
- **Capacity:** from the printed sizes, and from the size at the touch in this weekend's recorded books.
- A Sharpe above 3 starts the bug hunt before anything is reported: the signal uses only 09:45 prices; the result is
  never an input; costs on every trade; R3's filter for the 0.50 placeholder; the print check.

## 5. Success criterion (primary V0, fixed now)

A pass needs all of: at least 30 OOS trades on at least 5 OOS closures; OOS mean net P&L per trade above zero with
a closure-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs; in-sample above zero; at least
half of the OOS entries print-verified and the verified ones above zero. Anything else is a null or "too few
observations" and is reported as that.

## 6. Caveats known in advance

- The Polymarket price is a history point; its spread is measured on other days. The print check is the guard.
- These markets are thin: R3's sister scan found prints of 5 to 100 shares. Capacity is expected to be small.
- Unhedged: a closure's trades win or lose together when the stock moves through its strikes.
- The window is one year, 44 closures; out-of-sample is 9 of them.

## Outputs

`research/results/s6_monday_fade/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `trades.csv`,
`capacity.md`, `RUN_LOG.md`, `run_meta.json`.

## Amendments

None.
