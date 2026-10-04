# S10: inside the weekend, who moves first? (pre-registered)

**Question.** From Friday night to Sunday evening oil futures are shut, but Polymarket is open. S9 found that over a
whole weekend Polymarket's oil price markets ("Will WTI hit $100?") move 0.86 points for every point the oil-linked
event questions (Iran and similar) move (t = 5.85). Nobody has looked minute by minute. If the price markets follow
the event questions with a delay of minutes, that is a trade in a market that is open on a Saturday.

This file and `config.py` are committed **before any price is read for this test**. Every rule is fixed. Changes go
under "Amendments", dated, never rewritten. The run is reported whatever it shows.

## 0. What was known before this commit

- S9's result in full (`research/results/s9_weekend_price_markets/SUMMARY.md`): the weekend co-movement above, measured
  from Friday 20:00 to Sunday 17:55 only (two readings per weekend); the give-back by Monday; the half-spreads of the
  live books of Sat 2026-10-03 22:13 New York time (crude oil 0.5 point, gold 1.25); fees 0.04 × P × (1 − P) on most
  markets.
- The data on disk: 44 oil-linked event questions (S5 and S4 agreed links naming USO, XLE, XOP, XOM, CVX or OXY), all
  with a nonzero net link direction; 391 price markets in S9's universe (crude: 112 "hit high", 92 "hit low", 8
  ranges; gold: 50, 29, 8). **Seen: only the timestamps** of these files, to fix the validity of a reading: every
  series is one reading a minute (median spacing 60 seconds). Because the history is a reading every minute whether
  or not anyone traded, a stale price looks the same as a fresh one; the print check (section 6) is there for that.
- **Not seen:** any price of any of these markets at a resolution finer than S9's two readings a weekend.

## 1. Markets

- **Event questions:** S9's set, built as in `s9_weekend_price_markets.run.build()`: links from
  `s8_open_referee.run.links()` whose ticker is in `OIL_TICKERS`, each question signed by the sign of the sum of its
  link directions (+1: YES means oil up). One-minute prices from the S5 and S4 caches.
- **Price markets:** S9's universe (`universe.json`), crude oil (primary) and gold (variants), signed markets only
  (+1 "hit high", −1 "hit low"; ranges left out). One-minute prices from S9's cache (weekend windows only).
- A question or price market is **live** on a weekend if its price at the start is between 10% and 90%.

## 2. The weekend window (New York time)

From **20:00 on the last session day** before the weekend to **Sunday 17:55**, five minutes before futures reopen
(S9's calendar). Every quantity below lives on a **five-minute grid** inside this window. A price at a grid instant is
the last one-minute reading at or before it, valid for 5 minutes. All windows used by the lead-lag tests and the event
study lie inside the weekend window, so nothing measured is after futures reopen. (The 60-minute trade exit can fall
after 18:00 for a late signal; section 5.)

- **Event index** `X`: at each grid instant, the change in points over the bin ending there, averaged over the live
  event questions valid at both ends, each signed by its link direction.
- **Price index** `Y`: the same for the live signed price markets of a class, each signed by its own sign. So a
  positive `X` says "the news says oil up", a positive `Y` says "the price markets say oil up".

## 3. Tests before costs

**T1, lead and lag slopes.** At each grid instant `t` from start + 15 minutes, and each horizon `h` of 5, 15, 30 and
60 minutes with `t + h` at or before Sunday 17:55:

- *event first:* the change of `Y` over `(t, t + h]` on the change of `X` over the bin `(t − 5 min, t]`;
- *price first:* the change of `X` over `(t, t + h]` on the change of `Y` over `(t − 5 min, t]`;
- and the same-bin slope: `Y` on `X` over `(t − 5 min, t]`.

Through-origin slopes, errors clustered by weekend (`s4_linked_assets.engine.clustered_slope`). Grid instants where
either index is missing are dropped. Crude oil is the primary class; gold is reported the same way.

**T2, event study.** A **jump** is a change of at least **3 points in 5 minutes** or at least **5 points in 15
minutes**, measured at a grid instant `t` over the window ending at `t`, from a price that was between 5% and 95% at
the window's start.

- *Event question first:* a jump in one live event question, signed by its link direction. The response: the change of
  the price index `Y` (crude; gold separately) from `t` to `t + h`, multiplied by the sign of the jump (positive = the
  price markets followed). Also the change from `t + 1 minute` (the tradeable entry) to `t + 1 minute + h`, and the
  change of `Y` over the 15 minutes before `t` (did the price markets move first?).
- *Price market first:* a jump in one live signed price market (signed by its sign). The response: the change of `X`
  from `t` to `t + h`, times the sign of the jump; and the change of `X` over the 15 minutes before `t`.
- If both rules fire, or several questions jump at the same instant, the largest absolute change sets the sign. After
  a jump, no new jump of the same kind is counted on that weekend for 30 minutes (the same news counted once).
- Means with 95% intervals resampling weekends (2,000 draws, seed 0).

## 4. The trade

- **Signal:** an event-question jump (T2, with the 30-minute rule) between start + 15 minutes and **Sunday 17:25**. At
  most **3 signals a weekend**, the first three.
- **Markets:** the live signed price markets of the variant's class whose mid at the entry minute is between 5% and
  95%; at most **5 per signal**, those with the entry mid closest to 50% (ties by market id).
- **Side:** the side the jump implies: buy YES if the market's sign × the jump's sign is positive, sell YES otherwise.
- **Entry:** the mid at the **next minute** after the signal (`t + 60 s`), moved against the trade by the half-spread
  (**crude 0.5 point**, gold 1.25: S9's values), plus the market's own taker fee. 100 contracts.
- **Exit:** 30 minutes after the entry (primary); 60 minutes (variant); Sunday 17:55 (hold variant). The exit fill is
  moved by the half-spread and pays the fee. If the market has no valid price at the exit and the catalogue shows it
  closed by then, it is settled at its result with no spread or fee (S9 amendment 1); otherwise the trade is dropped
  and counted.
- **2× costs:** half-spreads and fees doubled.
- **Capital:** the price paid for the side bought, × 100. Capital base: the largest capital deployed on one weekend.

### Variants (the complete list)

| id | class | exit |
|---|---|---|
| **V0, primary** | crude oil | 30 minutes |
| V1 | crude oil | 60 minutes |
| V2 | crude oil | Sunday 17:55 |
| V3 | gold | 30 minutes |
| V4 | gold | 60 minutes |
| V5 | gold | Sunday 17:55 |

Each at 1× and 2× costs. The deflated Sharpe ratio uses 6 trials.

## 5. Accounting, segments, inference

- Per trade: net P&L in points per contract and dollars for 100 contracts; costs in points and in bp of the trade's
  capital. Book: P&L by weekend ÷ capital base; Sharpe annualised by 52; maximum drawdown; worst month; turnover.
- **In-sample / out-of-sample by weekend:** the weekends with at least one live oil event question and one live crude
  price market; out-of-sample is the most recent 20% of them. Gold uses the same date split.
- Intervals: 95% bootstrap resampling weekends (several markets after one signal are one bet).
- A Sharpe above 3 starts a bug hunt before anything is reported: no price after the entry minute is used to choose a
  trade; costs on both fills; the print check; whether one weekend carries the result.
- Note on the 60-minute exit: a signal after 16:55 on Sunday exits after futures reopen at 18:00. Disclosed, not
  removed.

## 6. The check that decides whether it is real

A thin market's mid can be stale, and a stale mid looks like a lag. For **every entry** of every variant, the public
prints of that market (`ds.pm_trades`, condition id from `universe.json`) within **5 minutes after the signal**
(`[t, t + 300 s]`) at the assumed entry price or better, on the side that proves the fill: a sale of YES needs a taker
who sold YES at or above our price; a purchase needs a taker who bought YES at or below it (S6's rule, NO prints
converted to YES terms). An entry is **checkable** if the prints the API serves reach back before `t`. Reported: the
verified share of all entries and of checkable entries, and the mean net P&L of verified entries with its interval.
Described too: the share of entries whose price market's mid did not change in the 15 minutes before the entry.

## 7. Success criteria (fixed now)

**Who moves first (T1, crude, 5-minute horizon):** "the event question leads" if the event-first slope is positive
with t ≥ 2; "the price market leads" if the price-first slope is positive with t ≥ 2; both or neither are reported as
that.

**The trade (primary V0).** A pass needs all of: at least 30 OOS trades on at least 5 OOS weekends; OOS mean net P&L
per trade above zero with a weekend-bootstrap 95% interval excluding zero at 1× costs; above zero at 2× costs;
in-sample above zero at 1× costs; and the mean net P&L of the print-verified entries above zero. A pass with fewer
than half of the entries verified by prints is reported as "passes on modelled prices, not verified", never as an
edge. Anything else is a null or "too few observations".

## 8. Caveats known in advance

- About 40 weekends, most of the oil moves in March to June 2026: one theme, one spring.
- Prices are one-minute mids; the half-spreads are from one night of much smaller markets.
- Several strikes of one asset after one signal are one bet.
- Link directions are model judgements (S4, S5).

## Outputs

`research/results/s10_weekend_lag/`: `SUMMARY.md`, `metrics.csv`, `trades.csv`, `leadlag.csv`, `events.csv`,
`equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

**Amendment 1, 2026-10-04 03:00 UTC (Sat 23:00 New York time), after Part 1's run, before any price of the Part 2
pairs is read: Part 2, the mechanism.** Theo's instruction after Part 1: stop looking at one asset or one question,
look at the mechanism. Part 1 is unchanged and stays the pre-registered result for oil.

*What Part 1 showed that motivates this.* The crude price markets follow the oil event questions over 5 to 60
minutes. The price markets also lead the questions, more weakly. 68% of the trade's entries were in a price market
whose price had not changed for 15 minutes, and 4% were print-verified. One explanation covers both directions: news
reaches the **active** market first, and the **thin** market's price catches up later, whichever of the two is the
"news" question. If so, the lead is about activity, not about news against price. That also links the earlier
studies: the asset opens where the odds moved (S4, S5) because the asset was shut, which is the extreme case of a
thin market.

*Pairs.*
- **Type B (primary): two event questions linked to the same ticker** (links from `s8_open_referee.run.links()`;
  SPY already dropped). The pair's sign is the product of the two link directions; a pair linked through several
  tickers with conflicting signs is dropped. All hours, the whole history in the S5 and S4 caches (one-minute). Not
  seen before this amendment at a resolution finer than the overnight readings of S4, S5 and S8.
- **Type A: an event question and a price market on the asset its link names**: crude (the oil tickers), gold (GLD),
  and the six stocks with price markets (MSFT, AMZN, GOOGL, NVDA, TSLA, META). Sign = link direction × the market's
  sign. Weekend windows only (the S9 cache), Part 1's window. The crude pairs were seen in Part 1 as an index; here
  they enter pair by pair.

*Definitions on the five-minute grid.* A pair-bin at `t` counts if both prices are valid (5-minute validity) and
between 5% and 95% at `t − 5 min`. **Activity** of a market at `t`: the number of minutes in the hour before `t`
in which its one-minute price changed. The **active** member of a pair-bin is the one with more activity (ties
dropped); the other is the **thin** member. A market is **stale** at `t` if its price did not change in the 15
minutes before `t`.

*Tests (before costs).* Through-origin slopes, errors clustered by New York date (type B) or weekend (type A):
- **M1, activity decides the direction.** The thin member's change over `(t, t + h]` on the active member's change
  over `(t − 5 min, t]` (signed by the pair's sign), and the reverse, for h = 5, 15, 30 minutes. The difference
  between the two slopes, with a 95% interval from resampling clusters (1,000 draws, seed 0).
- **M2, staleness carries the lag.** The active → thin slope split by whether the thin member is stale at `t`; and
  the same-bin slope (thin's change over `(t − 5 min, t]` on active's) in the same two groups. The prediction: a stale
  follower shows little same-bin response and more later; an active follower responds mostly in the same bin.
- Reported for type B and type A separately, and for type B by the news-versus-news direction too (no change in
  rules).

*M3, can the stale side be picked off?* Type B (primary) and type A (variant). Signal: the active member of a pair
jumps (3+ points in 5 minutes or 5+ in 15, from a price between 5% and 95%) while the other member is stale.
Trade the stale member on the side the jump implies, at its mid one minute later, moved by the half-spread (event
questions 0.5 point, S8; price markets Part 1's class values, stocks 2.5) plus a 0.04 × P × (1 − P) taker fee
(event questions, as S8; price markets their own fee). Exit 30 minutes later on the same terms. One trade per pair
per 30 minutes; at most 10 trades per New York date (type B) or weekend (type A), in time order. 1× and 2× costs.
Out-of-sample: the most recent 20% of dates (type B) or weekends (type A) with a trade. **Print check** on every
entry exactly as in section 6 (condition ids from Polymarket's catalogue by market id). Success criterion: the same
as section 7's trade criterion, with "OOS weekends" read as "OOS dates" for type B (at least 10).

*Success criteria for the mechanism (type B, fixed now).* **M1 holds** if the active → thin slope at 5 minutes is
positive with t ≥ 2 and its difference from the thin → active slope is positive with an interval excluding zero.
**M2 holds** if the active → thin slope at 15 minutes is larger for stale followers than for active ones, with an
interval of the difference excluding zero. Type A is reported against the same rules. Anything else is reported as a
null.

*Caveat known now.* "Stale" is read from a one-minute price history that Polymarket fills in every minute. A price
that does not change can be a quote nobody moved, or no quote worth trading. The print check is what tells them
apart, and only for recent prints (the latest 20,000 per market).
