# Ladder replay: the S11 ladder-violation trade with simultaneous taker fills

Method: [`research/ladder_replay/METHOD.md`](../../ladder_replay/METHOD.md), pre-registered in commit `08a0236` before any
new data pull, amendments 1 to 4 before any print was analysed, amendments 5 and 6 after a first run (see below).
Parameters: [`config.py`](../../ladder_replay/config.py). Run log: [`RUN_LOG.md`](RUN_LOG.md).

## Answer

**The trade survives a strict, causal replay, but only once a rung-dating error inherited from S11 is fixed, and that
fix was found after looking.** Under the rule as registered before any result, the fresh-universe test is **NULL**:
+2.47 points per trade, date-clustered 95% interval [−1.14, +6.26], 650 trades on 221 dates. Every losing trade in that
run (74 trades, −$904) came from three ladders whose rungs S11's year rule put in the wrong order (two more such ladders
cause all 88 losing trades on S11's own pairs) ("by December 31?" in a
market created in March 2026 read as 2025-12-31). Such a pair is not nested by the definition in step 1. With a check that
re-derives each rung's year (amendment 5, post hoc), the fresh universe gives **+8.82 points per trade [+6.73, +11.13],
562 trades on 211 dates, no losing trade**, which would be a PASS. Because the check was added after seeing the losers,
that number is not confirmatory.

**Small money.** At the 100-contract cap the fresh universe made $1,480 in a year ($1,704 at full print size); the
guaranteed part, the edge locked in at entry, was $530. The rest came from 30 trades where the event fell between the
two dates and the pair paid $2. Median trade size is 19 contracts, set by the smaller of the two prints.

**Live, now: no violations.** At 01:57 New York time, 61 adjacent pairs in 34 open date ladders, 60 with books on both
legs: 0 violations net of fees. The median pair was 10.5 points from an arbitrage.

## 1. Settlement-rule check

Rule in `config.py` (amended 2, 4, 5). Counts per universe ([`settlement_check.csv`](settlement_check.csv) registered
rule, [`order_check/settlement_check.csv`](order_check/settlement_check.csv) with amendment 5):

| | S11 pairs (date + strike) | Fresh pairs (date) |
|---|---|---|
| Pairs | 918 | 861 |
| Nested, registered rule | 727 | 680 |
| Nested, with the year check | 720 | 676 |
| Not nested: descriptions or sources differ | 89 (73 with the year check) | 109 (66) |
| Not nested: window starts at market creation and the cheap rung was created later | 102 | 70 |
| Not nested: rung order wrong once each year is re-derived (amendment 5) | 23 | 47 |
| No gamma record | 0 | 2 |

Hand check of 20 random pairs ([`manual_check.md`](manual_check.md)): 17 of 20 agree. The 3 disagreements are pairs the
rule excludes that a reader would call nested (a spelling variant, a stricter rich rung, a wider later window). No pair
the rule calls nested was found not nested by hand. The year error was not in the sample, which is why the hand check
did not catch it.

## 2. Replay on S11's pairs (mechanics check on seen data)

Entry only when a taker sold YES on the rich rung and a taker bought YES on the cheap rung within 60 seconds of each
other (median gap between the two prints: 6 to 14 seconds), at prices that clear one tick each side plus both taker
fees; fill at those prices moved one tick against us; size min(print sizes, 100); held to resolution. Points are cents
per contract.

| S11 pairs | Rule | Trades | Pairs | Dates | Net, points per trade | 95% interval (dates) | Total $ | Capital-weighted return | Annualized on locked capital | Sharpe (resolution months) | Max drawdown | Losers |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| All | registered | 691 | 231 | 211 | +5.16 | [+2.31, +8.30] | $1,251 | 5.4% | 52% | 3.26 | $623 (9.6% of peak capital) | 88 |
| All | year check | 575 | 228 | 189 | +9.40 | [+6.54, +12.48] | $1,818 | 8.4% | 83% | 3.85 | $0 | 0 |
| Date ladders | year check | 385 | 137 | 114 | +9.36 | [+6.04, +13.82] | $1,071 | 8.5% | 181% | 3.08 | $0 | 0 |
| Strike ladders | either | 190 | 91 | 111 | +9.48 | [+5.71, +13.65] | $747 | 8.2% | 47% | 2.55 | $0 | 0 |
| From 2026-07-22 | either | 48 | 16 | 32 | +8.27 | [+1.88, +16.77] | $107 | 5.2% | 18% | 2.59 | $0 | 0 |

Of S11's 98 print-verified monotone trades, **65 survive** the 60-second rule (a qualifying pair of prints within ±10
minutes of S11's entry), **19 fail**, and 14 sit on pairs that step 1 calls not nested. The replay finds far more
trades than S11 (575 against 98) because it reads every print instead of one-minute mids, and pages prints back by
time instead of stopping at the latest 20,000.

## 3. Fresh universe (confirmatory)

373 date ladders that S11 did not include, built from catalogue text at 01:56 before any print was read
(`ladder_replay/fresh_universe.json`).

| Fresh pairs | Rule | Trades | Pairs | Dates | Net, points per trade | 95% interval (dates) | Total $ | Capital-weighted return | Annualized on locked capital | Sharpe (resolution months) | Max drawdown | Losers | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| All | **registered** | 650 | 274 | 221 | +2.47 | [−1.14, +6.26] | $627 | 3.4% | 41% | 0.42 | $649 (20.7%) | 74 | **NULL** |
| All | year check (post hoc) | 562 | 270 | 211 | +8.82 | [+6.73, +11.13] | $1,480 | 8.5% | 111% | 4.20 | $0 | 0 | (PASS) |
| Before 2026-07-22 | year check | 460 | 209 | 170 | +8.74 | [+6.51, +11.45] | $1,234 | 8.2% | 99% | 3.68 | $0 | 0 | |
| From 2026-07-22 | year check | 102 | 65 | 41 | +9.20 | [+4.86, +14.01] | $245 | 10.4% | 272% | 2.86 | $0 | 0 | |

The losing trades under the registered rule: "Will anyone be charged over Daycare fraud in Minnesota by December 31?"
against "... by January 31?" (57 trades, −$599), "Another US strike on Venezuela by December 31?" against "... by January
10?" (10, −$169), "US strike on Syria by December 31?" against "... by December 14?" (7, −$137). In each the "December 31"
rung is the later one.

What the +8.82 is made of (year check): the median edge locked in at entry is 1.6 points (mean 3.5); 30 of 562 trades
paid $2 because the event fell between the two dates, and those carry about two thirds of the dollars. Without them the
mean is 3.4 points. Every trade made money, as a nested pair held to resolution must. 39 trades are on markets not yet
resolved and are valued at their guaranteed floor.

Sensitivity (labelled, not confirmatory): adding back pairs whose window starts at market creation and whose later rung
was created later gives 60 more fresh trades, all winners, +2.50 points ([+1.67, +3.85]). The written-rule gap never
cost money in this sample.

## Capacity

| | Fresh, year check | S11 pairs, year check |
|---|---|---|
| Net $ in the year at the 100-contract cap | $1,480 | $1,818 |
| Of which locked in at entry | $530 | $687 |
| At full simultaneous print size (no cap) | $1,704 | $5,632 |
| Most capital locked at once | $2,970 | $6,011 |
| Median size, contracts | 19 | 25 |
| Trades below Polymarket's 5-contract minimum order | 58 | 49 |
| Median days locked | 5.6 | 10.2 |

Both universes together come to about $3,300 a year at the cap, on a few thousand dollars of capital. The day cap of 10
trades bound on 9 days (fresh) and 18 days (S11).

## Caveats

- The confirmatory verdict under the registered rule is NULL. The PASS-sized result depends on a check added after
  seeing which trades lost. The check is mechanical (it re-reads the year of each rung) and removes winners as well as
  losers, but it is still a choice made after looking.
- A print shows that a taker traded at that price, not that a second trader could have. Our order would have competed
  for the same liquidity; one tick of slippage and the print-size cap are the only allowance.
- 58 fresh trades are smaller than Polymarket's minimum order of 5 contracts. Dropping them leaves the year-check result
  at +9.24 [+7.02, +11.70] (504 trades); under the registered rule it would be +4.41 [+1.19, +7.64] (565 trades). This
  filter was not registered.
- The trade-weighted mean gives a 1-contract trade the same weight as a 100-contract one. Dollar-weighted, the fresh
  year-check result is +8.2 points per contract.
- No data-API page cap was hit (0 truncated markets), so the reachable print history is complete for these markets.
- The live snapshot classified nesting with the rule before amendment 4; this does not matter because no pair was in
  violation.
- The first run (02:00 to 02:07) mapped prints with the data API's `outcomeIndex`, which is wrong on many prints; it
  is void and kept in `v0_void/` only for the record.
