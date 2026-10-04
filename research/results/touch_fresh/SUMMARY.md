# touch_fresh: the S21 seller rule on fresh "will it hit" markets

Method, pre-registered before any print, result or quote of these markets was pulled: [`research/touch_fresh/METHOD.md`](../../touch_fresh/METHOD.md) (commit `e236e24`). Forward protocol: [`FORWARD.md`](../../touch_fresh/FORWARD.md) (commit `dcffa67`). Files: [`markets.csv`](markets.csv), [`books.csv`](books.csv), [`exposure.csv`](exposure.csv), [`counts.json`](counts.json), [`RUN_LOG.md`](RUN_LOG.md).

## Answer

**INSUFFICIENT on both samples. The fresh data neither confirms nor rules out the S21 result, and its point estimates go the wrong way.**

**S21-eligible fresh sample (the verdict of record): INSUFFICIENT.** Closed stock and S&P 500 "will it hit" markets under Polymarket's `hit-price` tag that appear in no S9, S15, S18, S19 or S21 list and pass S21's rules (S15's $10,000 market and $100,000 event floors, S21's parser, a live window at the first weekend): **32 markets in 4 events** (ABNB 13, SPY 10, COIN 9), against the fixed minimum of 30 markets in 15 events. The count was made from metadata before any price was read. After the pull, 9 of the 32 had a first-weekend taker sale (3 events) and 1 entered B0 (+39.04 points; it resolved NO).

**Sample R (S21's rules without the event floor, pre-registered as secondary): INSUFFICIENT by its book minimum.** 142 markets in 85 events passed the metadata rules and 141 got an options anchor. But these are thin markets: only 38 markets in 28 events had a first-weekend taker sale inside the 2 to 98% band, and B0 took **7 markets in 7 events**, against the fixed minimum of 10 markets in 5 events. B0 (sell YES at the traded bid when it is 5 or more points above the horizon-matched central anchor, held to the result): **−15.38 points per contract [−48.82, +21.82]**, with the fee doubled −16.20 [−49.61, +21.03]. B0 sold at 56.9% on average against an anchor of 35.4%, and 5 of the 7 resolved YES. S21's +22.27 lies just above this interval. Seven markets cannot carry a verdict either way.

## Sample R, every book

| Book | P&L | Markets | Events | Mean sell price, % | Mean anchor, % | Resolved YES, % | Mean, points | 95% interval |
|---|---|---|---|---|---|---|---|---|
| B0 (matched anchor, gap ≥ 5) | fee 1× | 7 | 7 | 56.9 | 35.4 | 71.4 | −15.38 | [−48.82, +21.82] |
| B0 | fee 2× | 7 | 7 | 56.9 | 35.4 | 71.4 | −16.20 | [−49.61, +21.03] |
| B0, delta-hedged | fee 1× | 7 | 7 | 56.9 | 35.4 | 71.4 | +6.27 | [−14.29, +23.99] |
| B0, delta-hedged | fee 2× | 7 | 7 | 56.9 | 35.4 | 71.4 | +5.45 | [−15.19, +23.15] |
| U (every anchored market with a taker sale) | fee 1× | 38 | 28 | 26.9 | 27.5 | 29.0 | −2.60 | [−18.95, +11.52] |
| U | fee 2× | 38 | 28 | 26.9 | 27.5 | 29.0 | −3.15 | [−19.50, +11.01] |
| U, delta-hedged | fee 1× | 37 | 27 | 25.3 | 25.5 | 27.0 | +10.50 | [−0.10, +20.00] |
| U-left (not taken by B0) | fee 1× | 31 | 23 | 20.1 | 25.7 | 19.4 | +0.28 | [−14.34, +13.84] |
| B0 taken minus left | fee 1× | 38 | 28 | | | | −15.66 | [−51.74, +24.75] |
| B0, forward-start window | fee 1× | 6 | 6 | 59.7 | 35.6 | 83.3 | −24.45 | [−55.87, +16.22] |
| B0, window already started | fee 1× | 1 | 1 | 40.0 | 34.1 | 0.0 | +39.04 | n/a |
| B0, weekly events | fee 1× | 5 | 5 | 63.1 | 42.1 | 80.0 | −17.66 | [−53.34, +26.12] |
| B0, monthly events | fee 1× | 2 | 2 | 41.3 | 18.7 | 50.0 | −9.68 | n/a |

Intervals resample events (2,000 draws, seed 0); under 5 events, none. B0 with S21's unmatched anchor (2 × p_T) takes exactly the same 7 markets: the nearest expiry equals the window's last session for 24 of the 38 markets and is within 3 days for 36, so matching the horizon moved no market across the 5-point line here.

## Secondary results

**Hedged.** Holding Δ shares of the underlying per contract (Δ from the matched touch formula at the anchor-instant NBBO mid, paid at the NBBO half-spread in and out, exit at the level on a YES and at the window's last close on a NO) turns B0 into +6.27 [−14.29, +23.99] and the unfiltered seller book U into **+10.50 [−0.10, +20.00]** on 37 markets in 27 events. The hedge removes most of the loss from the markets that hit; the hedged U interval touches zero.

**Market exposure.** U's seller P&L on the underlying's log move toward the level over the ticket window (36 markets, 26 events, errors clustered by event): slope **−2.31 points per 1% move [−4.56, −0.05]**, intercept +6.01 [−9.31, +21.32]. A seller loses about 2.3 points for each 1% the stock moves toward the level, and the P&L at zero move is positive but not distinguishable from zero. For B0 the regression was not run: 5 markets have the move (two "Week of June 15" markets lack the close because 2026-06-19 was a market holiday).

## How many markets

- Closed `hit-price` events served: 1,941. Stock and S&P 500 markets in them, not in a frozen list, closed, at least $10,000 traded, parsed, with a live window at the first weekend: 142 in 85 events (177 dropped as already used by S9 to S21; 9,828 under the market floor; 16 whose window ended by the first Friday). Of these, 32 in 4 events also pass the $100,000 event floor.
- Anchored: 141 (1 had no usable pair of leg quotes). Every leg quote is at most 298 seconds older than the anchor instant. One anchor in the tested base used a zero-bid leg.
- First weekend: 53 markets printed at all, 39 had a taker sale, 38 of those inside the 2 to 98% band with a result. 31 of the 38 have a window that starts after the entry weekend (`forward_start`).
- First weekends from 2026-03-27 to 2026-09-25; every market charges the 4% taker fee schedule. Median first-weekend taker-sale size in the base: 52 contracts; B0's seven: 8, 20, 40, 257, 1,047, 52, 20.

## Caveats

- **Power.** Neither fresh sample reaches its fixed minimum. The fresh population that S21's floors admit is almost empty because S9 and S15 already took nearly every heavily traded stock "hit" event; what remains is weekly strikes with a few prints each weekend.
- **Different population.** Sample R is mostly weekly events and forward-start windows (31 of 38), thinner than S21's. A null or negative there would not refute S21 on its own population, and a positive would not confirm it.
- **The conversion.** The touch anchor still assumes a driftless lognormal and reads American options as European. For forward-start windows it counts touches from the anchor, which overstates the in-window touch probability, so it should make B0 more conservative there, not less; B0's losses came mostly from those markets.
- **Hedge exits.** The hedge exits at the level when the market resolved YES; Polymarket's touch rule (intraday print vs close) and the exact touch time are not checked, and the exit half-spread is assumed equal to the entry one.
- **Frame.** The fresh frame is the `hit-price` tag listing; events missing that tag are not in it.
