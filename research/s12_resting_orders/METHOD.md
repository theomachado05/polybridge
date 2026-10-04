# S12: could a resting order have earned the give-back?

Pre-registered Sat 2026-10-03, about 23:00 New York time, before any trade print for this study was pulled.
Every number below is fixed in [`config.py`](config.py), committed with this file. Changes after the first pull go
under "Amendments", dated, and are never rewritten.

## What is already known (and so cannot be a discovery here)

- S8: after an overnight move of 10+ points the odds give back 2.63 points between 09:40 and the close (interval
  -3.90 to -1.47, 232 market-mornings). A taker who sells at 09:40 and buys back at the close pays 2.62 points and keeps
  nothing (-1.47 per trade on the primary).
- S9: after a weekend move of 5+ points the price markets give back 2.94 points by Monday 09:40 (interval -4.66 to
  -1.14; oil 4.18). The round trip costs 3.29 points: -0.01 per trade, -3.77 out-of-sample, and out-of-sample the
  give-back itself is absent before costs (-1.07). The give-back sits on markets that rose; markets drift down 1.05
  points over a weekend morning anyway.
- S9's print check: 62 of 295 reachable primary entries had a print at the taker's assumed price within 10 minutes.
- Polymarket's fee is charged to takers only (feeSchedule.takerOnly is true). A resting (maker) fill pays no fee and
  no spread. Maker rebates exist on some markets; none is counted here.
- I have read S8's and S9's summaries and their trades/mornings files (entry instants, sides, mids, outcomes at
  mid). I have not seen a single trade print near any of these instants except S9's 10-minute entry check above.

## The question

A taker who fades a large move pays the spread and the fee twice and keeps nothing. A resting order pays neither.
But a resting order only fills when someone trades against it, and the people most eager to buy what you are selling
after a big rise may be the ones who know it is going higher. So: how many resting orders would have filled, what
did a filled order earn, and do the orders that fill do worse than the ones that did not (adverse selection)?

**This is evidence on whether those prices were reachable, judged against public prints. It is not a live
market-making record:** we did not have orders in the book, we cannot see the queue, and our order would have
changed what others did.

## Samples (no new selection)

- **S9 (primary sample):** every S9 primary trade (`variant == V0`, `cost_mult == 1`) in
  `results/s9_weekend_price_markets/trades.csv`: 307 orders. Side as S9 (sell YES after a rise, buy YES after a fall).
  Mid at entry = `p_entry` (Sunday 17:55 New York). Exit instant = 09:40 of the next stock-market session (S9's
  calendar); mid at exit = `p_out` (the settlement value when S9 settled the market before the exit). Segment
  (IS / OOS, OOS = 9 weekends from 2026-08-03) as S9. Fee schedule per market from `weekends.csv`. Half-spread per
  asset class as S9.
- **S8 (second sample):** every row of `results/s8_open_referee/mornings.csv` with |overnight move| >= 10 points
  and `p_0940` in [0.05, 0.95], whatever the asset's vote: the mornings behind the 2.63-point give-back. Sell YES
  after a rise, buy YES after a fall. Mid at entry = `p_0940`; exit instant = the session close; mid at exit =
  `p_close`. Segment as S8 (OOS from 2026-07-23). Fee 0.04 x P x (1 - P); half-spread 0.5 point.
- Condition ids: S9 from `s9_weekend_price_markets/universe.json`; S8 from gamma `/markets/<id>`.

## Prints

`data-api.polymarket.com/trades?market=<condition>&takerOnly=true`, newest first, two pages of 10,000 (the API
serves only the latest 20,000 prints of a market), at most 3 requests a second. A copy of `ds.pm_trades` with
`takerOnly=true` passed explicitly. Kept on disk (`.cache/`, not committed): only prints inside
[entry, entry + 120 min] or [exit, exit + 120 min] of some order of that market, plus how far back the API reached.

**Reachable:** an order is judged only if the oldest print served is at or before its entry instant, or the API
served the market's whole history (fewer prints than the page cap). Unreachable orders are counted and left out of
every statistic.

Every print is put in YES terms: a taker BUY of YES at p is a taker BUY at p; a taker SELL of NO at p is a taker
BUY at 1 - p; a taker BUY of NO at p is a taker SELL at 1 - p; a taker SELL of YES at p is a taker SELL at p.

## The fill rule (fixed, strict)

A resting **sell** at price q, posted at instant t, for 100 contracts, resting for W minutes:

- Posting price: the mid at t rounded **up** to the cent (the passive side; a sell at the mid of a 1-cent spread
  joins the ask). Variant "one tick better": that price minus 1 cent.
- Qualifying volume, counted over taker **BUY** prints (YES terms) with t < time <= t + W, in time order:
  - every print at a price **above** q counts in full (price priority: an order at q is consumed before any trade
    above it);
  - prints **at** q count only once the cumulative size at q since t exceeds the queue allowance of 500 contracts;
    only the excess counts.
- Filled fraction = min(1, qualifying volume / 100). A partial fill is a smaller position, never rounded up. The fill
  instant is when the cumulative qualifying volume first reaches the filled amount.
- The mirror for a resting **buy**: posting price rounded **down**; taker **SELL** prints below q count in full, at q
  beyond the allowance.
- At 2x costs the price must trade one tick further: the rule is applied with q + 1 cent for a sell (q - 1 cent for
  a buy) as the threshold, while the order still trades at q.

## The exit

- At 1x: at the exit instant T, a resting order closes the position (buy YES back after a sale; sell YES after a
  purchase) at the mid at T rounded to the passive cent, under the same rule and the same window W. What is not filled
  by T + W crosses the spread at T + W: the mid at T + W (one-minute history, at most 30 minutes old) plus
  (minus) the half-spread, plus the taker fee of that market at that price.
  - Mid at T + W: S8 from the S4/S5 one-minute caches; S9 from S9's weekend cache where it covers T + W (to 10:10),
    otherwise pulled with `ds.pm_history` for [T, T + W + 5 min] only.
  - If S9 settled the market before T (4 S9 trades), the position settles at the result: no exit order, no fee.
- At 2x: no resting exit. Every exit crosses at T: the mid at T plus (minus) 2x the half-spread and 2x the taker fee.
- No stop, no early exit. Between the fill and T the position is held.

P&L of an order, in points per contract of the 100: filled fraction x (signed price change from q to the exit price,
less exit costs). An unfilled order earns 0.

## Variants (every one reported)

| id | window W | posting price | note |
|---|---|---|---|
| R0 | 30 min | mid, passive cent | **primary** |
| R1 | 120 min | mid, passive cent | |
| R2 | 30 min | one cent better | |
| R3 | 120 min | one cent better | |

Each on both samples, at 1x and 2x, for IS, OOS and ALL. Nothing else is tried. The primary is R0 on S9 at 1x.

## What is reported

1. **Fills:** orders posted, reachable, filled (any fraction), fully filled; mean filled fraction; median minutes to
   the fill.
2. **P&L per filled order** (points per contract, net), weekend-bootstrap (S9) or date-bootstrap (S8) 95% interval;
   before costs; costs in points and bp of capital. Also P&L per reachable order posted (unfilled = 0).
3. **Adverse selection, the deciding check:** for every reachable order, the mid-to-mid result
   m = signed (mid at entry - mid at exit) for a sale (the reverse for a purchase), in points: what the order would
   have earned at mid with no costs. Reported:
   - mean m of filled orders minus mean m of never-filled orders, bootstrap interval (same resampling unit;
     `s7_weekend_straddle.run.boot_diff`). Negative means the fills are selected against us.
   - filled orders' actual net P&L per contract against never-filled orders' m.
4. Equity curve and drawdown of the primary (S9, R0, 1x; P&L per weekend), Sharpe on weekend returns (52 a year), max
   drawdown, worst month, turnover, with S8 and S9's capital convention (capital = 100 x price paid for YES, or
   100 x (1 - price) for a sale; base = the largest amount deployed in one weekend). A Sharpe above 3 sends me
   hunting for a bug before reporting.
5. Capacity: for each reachable order, the qualifying volume in the window; share of orders that would fill fully at
   100, 500, 2,000 and 10,000 contracts.
6. In-sample against out-of-sample for everything above.

## Success criterion (S9, R0, 1x unless stated)

Pass needs all four:

1. at least 15 filled orders out-of-sample on at least 5 weekends;
2. in-sample net P&L per filled order above zero, weekend-bootstrap 95% interval excluding zero;
3. out-of-sample net P&L per filled order above zero;
4. whole-sample net P&L per filled order above zero at 2x.

S8 is judged by the same four lines (dates instead of weekends) and reported beside it; it does not rescue a failed
primary. The adverse-selection difference is reported whatever it shows; it explains the verdict, it does not decide it.

## Limits stated now

- The prints are takers' trades, not the book. We do not see our queue position, hidden size, or whether our order
  would have scared anyone off. The queue allowance is a guess (500 contracts); fills through our price are the
  strong evidence.
- A one-cent-better order may in reality have crossed the spread (if the true spread was one cent); it is assumed
  posted as a post-only order that rests.
- The mid at entry is the one-minute history, not a quote. Rounding to the passive cent is our only defence; prints
  through the price are the check.
- About 4% of S9 entries and most S8 entries are unreachable (the 20,000-print limit). S8 will be small.

## Amendments

**Amendment 1, Sat 2026-10-03 23:05 New York time (after the first pull, before any result was computed). A code
bug, not a change of rule.** The first pull asked the data API for S8's 60 markets with a missing condition id (a
pandas NaN passed as true), so every S8 market came back empty. Fixed (`run.py`, the condition lookup), S8's print
files deleted and pulled again. S9 was unaffected.

**Amendment 2, Sat 2026-10-03 23:10 New York time (after the first run). A case the method did not cover.** The
method says the deadline mid must be at most 30 minutes old but not what happens when it is missing. It is missing
for 5 S9 orders on the weekend of 2026-04-20, only at the 120-minute deadline (variants R1 and R3), because the
one-minute history has a gap that Monday morning. Those rows use the mid at the exit instant instead (flag
`deadline_mid_missing` in `trades.csv`). The primary (R0, 30 minutes) is not touched.

**Note, not an amendment.** Some S9 markets trade on a tenth-of-a-cent grid. The pre-registered rule posts on the
cent (rounded on the passive side), as fixed. On those markets the order sits up to half a cent further from the mid
than it needed to: fewer fills, and up to 0.5 point more per fill than a tighter order would have earned.
