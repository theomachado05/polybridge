# S23: how much of the Monday fade exists at prices that really traded (pre-registered)

**Question.** S6 ("Monday fade") takes the options' side against Polymarket on "close above $K" markets at 09:45 on
the first session after a weekend or holiday, and holds to the result. Its modelled Sharpe is 4.18 in-sample, 7.70
out-of-sample and 4.27 overall. 166 of its 187 entries have no public trade print at the price the model assumed.
How much of that result is left at prices and sizes that printed, and what is the largest figure that can be
defended?

This file and `config.py` are committed **before any P&L of this study is computed**. Every rule is fixed here.
Changes go under "Amendments", dated. The run is reported whatever it shows.

**Status: a pre-registered re-analysis, not a confirmation.** Both data sets (S6's entries and prints; the partner's
reopening-day taker trades) were already seen by earlier studies. A pass here is a **lead that needs replication on
new data**, not an edge.

No network call is made. Every input is on disk or committed in git.

## 0. What was known before this commit (none of it can be a discovery)

From S6's committed `trades.csv`, primary variant, looked at by the coordinating session on 2026-10-03/04:

- 187 entries on 36 closures; 21 verified by a print. The verified entries made $294.43 in total. One closure,
  2026-03-09, made $298.2 of it: four "buy YES" entries on AMZN, GOOGL, TSLA and NVDA daily markets that all resolved
  YES, which is one bet. The other 17 verified entries net about -$4.
- All 63 entries whose gap beyond the options band is above 20 points have no print at all. Verified entries exist
  only for gaps of 5 to 20 points: 10 at 5 to 10 points (+$31.68 each), 11 at 10 to 20 points (-$2.03 each).
- 17 of the 21 verified entries are in daily markets. The 9 verified "sell YES" entries averaged -$5.80; the 12
  "buy YES" entries +$28.89.
- 54 entries have a Polymarket price between 45% and 55%; 3 of them are verified.
- S6's published table: all 187 entries +$20.14 per trade [15.08, 26.28], Sharpe 4.27 (51 closures a year); verified
  +$14.02 per trade [-3.99, 36.94].

From the partner's `reopen_taker` study (branch `r/thesis-pass-2`): 402 trades at tau 0.05 on 44 closures, mean
-0.40 points per contract [-4.68, +3.74], a null. tau 0.03: +0.24 points (461 trades). tau 0.10: +0.96 (291). Daily
only: -0.93 (275). Weekly: +11.29 [+0.88, +24.67] on 25 trades and 5 closures. The coordinating session counted the
402 trades by time since 09:45 as 82 / 118 / 140 / 62 (within 15 minutes, 15 to 60, 60 to 180, later).
**Their P&L by time has not been looked at by anyone, including this session.**

Looked at by this session before this commit, with the result and P&L columns left unread (`y`, `pnl_t1`, `pnl_t2`
were excluded from the load):

- The partner's file has 1,154 rows: 461 at tau 0.03, 402 at tau 0.05, 291 at tau 0.10. One row per market and
  reopening day at each tau: the **first** print from 09:45 that qualified. `closure` (the last session before the
  break) maps one-to-one to `open_day` (the reopening day).
- **The brief's counts 82 / 118 / 140 / 62 use whole clock minutes** (every print stamped up to 10:00:59 counts as
  "within 15 minutes"). On exact seconds the same 402 trades fall **74 / 121 / 145 / 62**. Section 2 fixes exact
  seconds as the primary reading and whole clock minutes as a reported variant.
- On exact seconds the first 15 minutes hold 74 trades on 32 closures (60 daily, 8 monthly, 6 weekly; 41 "sell",
  33 "buy"; median print 18.5 shares). **Only 6 of them, on 4 closures, are on or after 2026-08-03.** The T1 pass
  line below needs 30 recent trades, so **T1 cannot pass on this data, and that was known before any P&L was read**.
  T1 is therefore a test of H1 and H2; its verdict can be at best "too few recent observations".
- Other counts on exact seconds: tau 0.03 has 111 trades in the first 15 minutes, tau 0.10 has 36; at tau 0.05 the
  first 30 minutes hold 139 trades; daily markets in the first 15 minutes, 60.
- 43% of the tau 0.05 trades are in markets with the fee switched on; the fee is 0.04 × q × (1 − q) where it is on.
- How the partner defined its P&L columns (read from its code, `reopen_taker/core.py::net`): per $1 contract, held
  to the result, `win − (q + tick) − fee(q)` with `q` the print price on the side bought, the fee only where the
  market charges one. `pnl_t1` uses one tick (1 cent) and is the partner's **primary**; `pnl_t2` uses two ticks.
- S6's print cache: 180 files, 10,965 prints, the largest file 919 prints. S6 pulled one page of 10,000 per market,
  so no file is cut off: each holds the market's whole print history. Prints carry `side` (the taker's side),
  `outcome` (Yes or No token), `price`, `size`, `timestamp`.
- S6's `verify` (run.py line 101) needed a print within ±10 minutes of 09:45 at a price at least as good as the
  modelled one (`PRINT_WINDOW_S = 600`).

**Not seen by this session:** any P&L by time window in the partner's file; any P&L of S6's entries at printed
prices other than the verified-set facts above.

## 1. Data

| Input | Where | Used for |
|---|---|---|
| S6 entries | `research/results/s6_monday_fade/trades.csv`, rows `variant == V0`, `cost_mult == 1.0` (187) | T2, T3 |
| S6 prints | `research/s6_monday_fade/.cache/prints_<market>.json` (on disk, not in git) | T2 |
| Partner's trades | `git show fb66dc7a:research/results/reopen_taker/trades.csv` (blob `78a25dad`) | T1 |
| Closure calendar | `open_day` of `research/results/open_options/events.csv` (45 reopening days) | Sharpe, split |

S6's and the other branch's folders are read only.

## 2. T1 (primary): the decay curve at real prices

**Sample.** The partner's 402 trades at tau 0.05. Each copied a real taker print that traded at least 5 points away
from the options' 09:45 probability, on the side toward it, and held to the result.

**P&L.** `pnl_t1`: net of one cent of slippage and the market's own fee, per $1 contract. One contract per trade,
equal weight. Reported in points (1 point = 1 cent per $1 contract).

**Windows.** Minutes since 09:45:00 New York on the reopening day, from the print's timestamp in exact seconds:
0 to 15 (0 ≤ m < 15), 15 to 60, 60 to 180, 180 and later. Lower bound in, upper bound out.

**Intervals.** 95% percentile bootstrap over **closures** (10,000 draws, seed 20261004): closures are resampled
whole and the pooled mean recomputed. No interval is given for fewer than 5 closures.

**Hypotheses, fixed now.**
- **H1:** the mean P&L of the first 15 minutes is above zero and its interval excludes zero.
- **H2:** the mean of the first 15 minutes minus the mean of all later trades (15 minutes onward, pooled) is above
  zero and the interval of the difference excludes zero. Closures are resampled jointly for both sides. The
  difference against each later window is also reported.

Reasoning: the options price is fresh at 09:45 and goes stale afterwards. If the trade is real it should be there
early and fade.

**Variants, all reported, none of them the test:** tau 0.03; tau 0.10; the first 30 minutes; daily markets only;
whole clock minutes (the brief's 82 / 118 / 140 / 62 reading); 2× costs (two cents of slippage and twice the fee,
recomputed from the file's price, side, fee flag and result; the 1× recomputation must reproduce `pnl_t1` exactly
or the run stops).

**In-sample and out-of-sample.** By reopening day: out-of-sample is 2026-08-03 onward (S6's split: the most recent
9 of 45 reopening days). Nothing is fitted.

**Pass line.** H1 holds, **and** the first-15-minute book is above zero in the earlier 80% of closures and in the
most recent 20%, with at least 30 trades in the recent part. (Known before the run: the recent part has 6 trades.)

## 3. T2: S6 replayed at prices that printed

For each of S6's 187 primary entries (S6's side, S6's options band `opt_lo`, `opt_hi`, S6's result):

1. Take S6's cached prints of that market with 09:45:00 ≤ time ≤ 10:15:00 New York on the reopening day. Convert to
   YES terms as S6's `verify` does: a taker buying NO at `x` is a taker selling YES at `1 − x`, and so on.
2. **Reachable price.** "Buy YES": the lowest price at which a taker **bought** YES in the window (an offer that
   existed and was lifted), **plus one cent**. "Sell YES": the highest price at which a taker **sold** YES (a bid
   that existed and was hit), **minus one cent**. No such print: no trade.
3. **Still worth it.** Trade only if the reachable price is at least 2 points beyond the options band after the fee:
   buy when `opt_lo − a − fee(a) ≥ 0.02`, sell when `b − fee(b) − opt_hi ≥ 0.02`, with `fee(x) = 0.04·x·(1 − x)`
   charged on every trade (S6's rule; some of these markets had the fee off, so this errs against the trade).
4. **Size.** The total size printed at that best price on that side in the window, at most 100 contracts.
5. **P&L**, held to the result: buy `n·(result − a − fee(a))`, sell `n·(b − fee(b) − result)`. Capital locked:
   `n·a` for a buy, `n·(1 − b)` for a sale.

This is stricter about price than S6's model (a price must have printed) and looser than S6's check (which needed a
print at the modelled price).

**Reported.** Entries with any print in the window on the needed side; entries that trade; P&L per trade in dollars
with a closure-bootstrap interval; points per contract; by closure; with the best closure (largest total P&L)
removed; in-sample and out-of-sample; by side and by kind.

**Variants, all reported:**
- **T2b, no hindsight inside the window:** the **first** print in time order on the needed side whose price, one
  cent worse, still meets step 3; size is that print's size, at most 100. (Picking the best print of 30 minutes uses
  knowledge of the whole window. T2b does not.)
- **2× costs:** two cents and twice the fee, in the condition and in the P&L.

**Pass line.** Mean P&L per trade above zero, interval excluding zero, and still above zero with the best closure
removed. If T2 passes and T2b's mean is not above zero, the pass is reported as resting on hindsight inside the
window, and it is not the number for the paper.

## 4. T3: the staircase (the exhibit)

One table (`staircase.csv`, and in the summary) and one chart (`staircase.png`). Rows, in this order:

1. S6 as modelled (187 entries, 100 contracts each, S6's `pnl`).
2. S6 at printed prices (T2).
3. S6's own verified set (21 entries, S6's `pnl_verified`: the modelled price, the printed size up to 100).
4. S6's verified set with its best closure removed.
5. T2 with its best closure removed.

Columns: trades, closures traded, P&L per trade, total P&L, **Sharpe on closure returns**, and the **dollars of
printed size** behind the row (the capital of the contracts that had a print: for row 1 this counts only the 21
verified entries, because nothing printed behind the other 166).

**Sharpe on closure returns, one definition for every book in this study.** The P&L of each reopening day in the
45-day calendar (zero when the book did not trade), divided by the book's capital base (the largest capital locked
on one closure); mean ÷ standard deviation (n − 1) × √52. With a closure removed the calendar has 44 days. S6
published 4.27 with 51 closures a year; at 52 the same series gives about 4.31, and both are shown.

## 5. T4: the number for the paper

From T1 and T2, the best book that passes its own line: its mean with the interval, its number of independent
closures, its capacity in dollars (the printed size behind it), and its Sharpe on closure returns. If both pass, the
headline is the book with more closures traded and the other is shown beside it.

If nothing passes, the summary says so in its first sentence. The figure offered instead is fixed now: **the T2
book** (what is left of S6 at prices that printed) with its interval, closures, printed dollars and Sharpe, and
beside it the T1 first-15-minute mean with its interval, each with the reason it failed. A Sharpe of a book that
failed its line is never offered as performance without its interval and the count of closures.

A Sharpe above 3 on any book starts the bug hunt before anything is reported: the result never enters a signal;
times are New York with daylight saving handled; the print side conversion matches S6's tested `verify`; costs are
on every trade; the Sharpe is on closures, not trades; one closure is not carrying the figure.

A pass is a **lead needing replication**, not an edge.

## 6. Charts and files

`research/results/s23_monday_fade_real/`: `SUMMARY.md` (answer first), `metrics.csv` (every test, variant and
segment), `trades.csv` (every T1 and T2 trade), `staircase.csv`, `decay.png`, `staircase.png`, `equity_curve.png`
and `drawdown.png` (the T2 book and the T1 first-15-minute book, each labelled pass or fail), `capacity.md`,
`RUN_LOG.md`, `run_meta.json`.

## 7. Forward section: rules fixed now, not run by this study

For the next reopening, **Monday 2026-10-05**, to be run later on new data:

- **Markets:** Polymarket "close above $K" markets on stocks and SPY with a usable options band at 09:45 New York
  (band no wider than 20 points, options probability between 3% and 97%), as in the partner's study.
- **Trade:** copy the first taker print with 09:45:00 ≤ time < 10:00:00 whose YES-equivalent price is at least
  5 points from the options' 09:45 probability, on the side toward the options (buy YES after a YES purchase at or
  below `p − 0.05`; buy NO after a YES sale at or above `p + 0.05`). One trade per market, one contract, one cent
  worse than the print, the market's own fee, held to the result.
- **Read-out:** mean P&L per contract and the count. One morning is one closure: it adds one observation to the
  closure count, and by itself decides nothing.

## 8. Caveats known in advance

- Both data sets were seen before; this is a re-analysis.
- T1 copies a taker: being able to trade at the print's price right after it is assumed. T2 assumes the offer that
  was lifted (or the bid that was hit) could have been taken by us, one cent worse.
- The options band is measured once, at 09:45. T2's prints are up to 30 minutes later.
- Trades of one closure share the market's move that day: the count of closures is the count of independent bets.
- The fee flag per market is not in S6's file; T2 charges the fee everywhere.
- Capacity is bounded by printed sizes, which are small (S6: median verified print 220 shares; partner: 20 shares).

## Amendments

None.

**Amendment 1, 2026-10-04 00:52 New York, after the run.** No rule, threshold or verdict changed. Two files were added
after the results were read: `after.py`, which writes `after_run.json` (checks on the T2 book that passed: an interval
for its Sharpe, the plain t-statistic, print timing, concentration, duplicated records, an independent replay from the
raw records), and `report.py`, which writes `SUMMARY.md` and `capacity.md` from the result files. Everything from
`after.py` is reported under the heading "Looked at after the run". The chart code was changed once to stop labels
colliding; the result files were byte-identical before and after.
