# S20: are Polymarket's price markets most overpriced when the reference market is shut? (pre-registered)

**The thesis (the project owner's).** A Polymarket price market ("Will NVIDIA dip to $192 in March?", "Will WTI hit
$100 in April?") is an option sold to retail. Its professional reference, the stock, futures and listed options
markets, is shut most of the week while Polymarket trades around the clock. The claim: these tickets are most
overpriced when the reference market is shut, because nobody is anchoring them.

S18 measured the overpricing at prices that really traded, but only on each market's first weekend (reference shut).
Nobody has compared it with prints made while the reference market is **open**. That comparison is this study.

This file and `config.py` are committed **before any print outside S18's first-weekend window is pulled**. Every rule
is fixed. Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- **Everything in S18's `SUMMARY.md`.** Takers who bought YES during a market's first weekend (Friday 20:00 to Sunday
  20:00 New York) lost 8.87 points per contract held to the result (interval -11.94 to -5.93; 606 markets, 97
  events). Takers who sold YES into a bid earned +3.63 (+0.72 to +6.57; 657 markets, 101 events), +3.29 with the fee
  doubled; in-sample +4.69 (+2.10 to +7.35), out-of-sample -0.99 (-10.96 to +9.28; 123 markets, 20 events). As a
  book: +$2,378 in-sample, -$207 out-of-sample. The sellers' gain was largest for tickets traded between 50% and 75%
  (+13.30) and absent at 2 to 10% (-1.05). The out-of-sample segment was flat.
- **So one outcome is already ruled out.** The strongest verdict below needs the first-weekend sellers' book above
  zero out-of-sample. S18 already showed it is not. The best this study can return is "a lead".
- **Mid prices do not rise on weekends.** The coordinating session computed, from the committed `weekends.csv` of S9
  and S15, that mid prices fall on average over the weekend (-0.55 and -2.38 points) and from Sunday to Monday (-1.05
  and -0.64). Mids of young markets are known to be unreliable (S18's bug hunt), so this is weak evidence.
- **From catalogue metadata only (result times against the calendar; no print):** of S18's 1,092 markets, 2 resolved
  during their first weekend (both YES); 113 resolved during the following week's sessions window (106 of them YES,
  94%); 23 resolved during the second weekend (3 YES). Section 3 explains why this matters.
- **Not seen by anyone:** any print outside the first weekend; any comparison between windows.

## 1. Markets and the three windows

- **Markets:** S18's exactly: the 1,092 markets of `results/s18_price_market_calibration/entries.csv` (S9's and
  S15's universes with a result, S18's entry instants, its in-sample and out-of-sample split by event). An **event**
  is one Polymarket event (one asset, one horizon); its strikes are one bet.
- **W1 (shut):** S18's first weekend: 48 hours from the market's entry instant (20:00 New York on the last session
  day before the weekend; Friday for 1,082 markets, the Thursday before a holiday Friday for 10). Read from S18's
  cache, read only. Not pulled again.
- **W2 (shut again):** 48 hours from the next weekend start of the same calendar (20:00 New York on the last session
  day of the following week). For nearly every market that is exactly one week after W1.
- **D1 (open):** the regular sessions, 09:30 to 16:00 New York (to 13:00 on an early close), of the trading days
  between W1 and W2: five in an ordinary week, four in a week with a holiday (313 markets). Only prints stamped
  inside those hours.
- The calendar is the one S9 and S18 used (SPY's sessions on disk, 2025-10-01 to 2026-10-02). A window that had not
  ended when the prints were pulled is left out.
- "Shut" and "open" are the stock market's clock. Commodity futures trade from Sunday 18:00, so the last two hours of
  W1 and W2 are not shut for commodities, and the futures are open at night during the week. That is why everything
  is also reported for stocks and the S&P 500 apart from commodities.

## 2. One observation per market, window and taker side (S18's formulas)

- A print on the NO token at price q is read as a YES price of 1 - q with the side reversed (S18's `yes_terms`).
- **Buyers:** the prints in which the taker bought YES. `pb` = their size-weighted mean price in the window. P&L per
  contract held to the result = result - `pb` - fee.
- **Sellers:** the prints in which the taker sold YES (hit a bid). `ps` likewise. P&L = `ps` - fee - result.
- Fee: the market's own taker fee, rate × P × (1 - P), once; nothing at the result. The 2× case doubles the fee.
- No spread is assumed: the price is the print.
- A window whose prints lie beyond the 20,000 the API keeps for a market is counted and left out, as in S18.

## 3. Which markets count in a window: the briefed rule and its known bias

The brief says: **a market that resolved before or during a window is left out of that window** (rule A).

Before pulling anything I checked what that rule does, from result times alone. A "will it hit" market resolves early
only when it is hit, that is, when YES wins. Rule A therefore removes from D1 the 113 markets that resolved during
that week, 94% of them YES. The markets it keeps for D1 resolved YES 17.1% of the time; the markets of W1 resolved
YES 26.0% of the time. Under rule A the buyers of the open week are stripped of their winners **by a choice that
uses the future** (on Monday nobody knows which market will be hit by Friday). Two consequences, known now:

- **T1 and T4 under rule A are biased against the thesis.** D1 buyers look worse and D1 sellers look better than any
  trader's experience. A D1 or W2 sellers' book under rule A could not have been traded.
- **T3 under rule A is biased for the thesis.** Tickets that survive a week unhit have decayed; a fair ticket would
  show "dearer on the weekend than in the following week" among survivors.

So a second rule is fixed here, with no look-ahead:

- **Rule B:** a market counts in a window if its result came after the window's **start**. Every print in the window
  counts (a closed market prints nothing). For W1 this is exactly S18's own test.

**Both rules are run and reported side by side for every test. The verdict is read from rule B.** Rule A is reported
in full "as briefed". This departs from the brief, is decided before any print outside W1 is pulled, and is flagged
at the top of the summary and in my report.

A bias that rule B keeps, in the other direction: a market that is hit on Monday keeps trading near 99% until it is
closed. Those prints are real, but they are not lottery tickets, and they pull D1's average loss toward zero. For
that reason every test is also reported for **tickets traded between 2% and 98%** (the union of S18's buckets) and
bucket by bucket. If "all markets" and "2 to 98%" disagree, the summary says so.

## 4. The tests, each with its own pass line

Intervals resample **events** (2,000 draws, seed 0; S7's `boot_mean` and `boot_diff`, as S18).

- **T1 (the clock).** Buyers' mean P&L in W1 minus buyers' mean P&L in D1, each over its own markets.
  **Pass:** below zero, interval excluding zero (a bigger loss when shut).
- **T2 (shut, or just new?).** The same for W2 minus D1, and W1 minus W2.
  - "Shut matters": W2 minus D1 below zero, interval excluding zero.
  - "Just new": W2 minus D1 not below zero with its interval, **and** W1 minus W2 below zero, interval excluding zero.
  - Anything else: "cannot tell".
- **T3 (the price path; needs no result).** Over markets with buyer prints in both windows: the mean of
  (`pb` in W1 - `pb` in D1), and of (`pb` in W2 - `pb` in D1), in points. **Pass, each:** above zero, interval
  excluding zero (the ticket is dearer on the weekend than in the open week). A fairly priced probability does not
  drift on average. On the same markets the P&L difference of T1 is exactly minus this price difference (the result
  cancels), so T3 is T1 like for like.
  - *Reported with it, no pass line:* the same two differences for `ps` (bids hit). If buyers pay more on the weekend
    and sellers receive less, the weekend has a wider spread, not a dearer ticket.
- **T4 (the trade).** Sell YES at traded bids and hold to the result, separately in W1, D1 and W2, as a book with
  S18's book function: up to 100 contracts per market, never more than the printed size; P&L booked in the month of
  the result; capital locked from the window's start to the result; capital base = the largest capital locked at one
  time. Reported: P&L, monthly Sharpe, maximum drawdown, worst month, at the fee and at the fee doubled, in-sample
  and out-of-sample exactly as S18 split its events. Also the sellers' mean P&L per contract with its interval, and
  sellers' W1 minus D1 and W2 minus D1.

**Splits (the only ones):** all markets; tickets traded 2 to 98%; S18's six price buckets (by the window's own traded
price of that side; for T3 by the mean of the two prices, so that neither window's noise picks the bucket); stocks and
the S&P 500 together; commodities together; in-sample and out-of-sample events. No other variant.

## 5. What a pass means (fixed now)

- **T1 holds and the W1 sellers' book is above zero in-sample and out-of-sample:** the closed-market premium is an
  edge candidate. (Already ruled out by S18's out-of-sample result; kept for completeness.)
- **T1 holds, out-of-sample does not:** a lead.
- **T1 does not hold:** the overpricing does not depend on the clock. Said plainly.
- "T1 holds" is read from rule B, all markets. If rule A, or the 2 to 98% scope, gives a different sign or a
  different answer on whether the interval excludes zero, the summary states it next to the verdict.
- A Sharpe above 3 starts a bug hunt before anything is reported.

## 6. Counts reported

Per window and rule: markets counted, markets left out and why (resolved, window not over, beyond the API's 20,000
prints, no print served), markets with any print, with a taker purchase, with a taker sale, and events.

## 7. The pull

- Polymarket data API, the same endpoint and parameters as S18's `prints.py` (`s1_twin_spread.data.pm_trades`:
  `market`, `limit` 10,000, `offset` 0 then 10,000), paged back to the market's D1 start.
- One worker, at most one request a second. Cached per market in `research/s20_closed_vs_open/.cache/`, resumable.
  Only prints inside D1 and W2 are kept.
- The live recorder is protected: `fetch failed` lines in `research/forward/recorder.log` are counted before and
  during the pull (read only). More than 5 new ones: pause two minutes, then one request every two seconds.
- No Kalshi call. No other source.

## 8. Caveats known in advance

- **One year, one oil shock in it** (S18's caveat). Resampling events does not cure shared weather.
- **Different takers.** Weekend takers and weekday takers may differ; the test measures the price paid, not who paid.
- **Age and clock are tied together.** W1 is always the youngest window. T2 is the only handle on that, and it has
  one more week of age, not a random assignment.
- **D1 is 32.5 hours of sessions; W1 and W2 are 48 hours each.** Nights during the week (reference shut, 16:00 to
  09:30) are in no window.
- **Size-weighting inside a market** follows where the volume was, as in S18.
- The buyers' loss is not a seller's gain unless the seller's order is the one lifted (S12).

## Outputs

`research/results/s20_closed_vs_open/`: `SUMMARY.md`, `metrics.csv` (every test, scope, rule), `trades.csv` (one row
per market, window and rule), `books.csv`, `equity_curve.png`, `drawdown.png`, `buyers_loss_by_window.png`,
`capacity.md`, `RUN_LOG.md`.

## Amendments

**Amendment 1, 2026-10-04 04:52 UTC, after the run. No rule was changed.**

- *A bias that section 3 missed.* T3's second comparison (W2 minus D1 on the same markets) keeps only markets that
  still traded on their second weekend, that is, markets that were not hit during the week. Those tickets have
  decayed, so that difference is pushed below zero under rule B as well as under rule A. Section 3 flagged this for
  rule A only. The number is reported as it came out and labelled so in the summary.
- *Looked at after the run,* reported under that heading in the summary and part of no pass line: the gap between
  buyers' and sellers' traded prices in the same market and window; open-week buyers split by whether their market
  resolved during that week; the bug hunt on every book with a Sharpe above 3 (`after.py`, `after_the_run.csv`).
- *Reach of a window (section 2), as coded in the runner committed before any pulled print was read (`f358817`).* W1
  uses S18's rule on S18's cache. D1 and W2 count as covered when the last page served was short (every print of the
  market came) or a print older than the window's start came. With 20,000 prints served and none older this is
  S18's rule; it is stricter only if a page came back full and the next one failed, which did not happen.
- *Outputs also written:* `counts.csv` (section 6), `books.csv` and `equity.csv` (T4), `run_meta.json` (the check
  that W1 under rule B returns S18's committed numbers; it does, to the last digit).
- *A test added while the pull ran,* before the run: `test_cached_prints_lie_inside_their_windows`, an integrity
  check of the cache. It is committed with the results.
