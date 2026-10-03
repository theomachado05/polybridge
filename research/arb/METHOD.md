# Options-arbitrage scan: method (written and committed before any market, quote or chain was fetched for this scan)

Question: when a prediction market (PM) lists a threshold contract on an equity or index ("NVDA closes above $230 on Oct 5", "S&P 500 above 7,795 at 4pm"), does its YES price differ from the probability implied by listed options on the same underlying, and does any gap survive trading costs?

Status of the evidence: **a descriptive scan, not a backtest of a strategy and not proof of anything.** "Zero genuine gaps" is an acceptable and fully expected answer. Everything below is fixed before the run. Later changes go in the **Amendments** section at the bottom; the original text stays in git history.

Scope note: this scan uses no 8-K filing data. Option and equity data come from Massive through `research/polybridge_research/massive.py`. PM data comes from public endpoints (Polymarket gamma and CLOB, Kalshi public market data). Paper analysis only; nothing is traded.

## 1. Universe and matching rules

**Polymarket.** Events carrying the `Equities` tag (id 102676) whose resolution time falls in 2026-08-15 .. 2026-10-12 (about seven weeks of resolved markets plus the live ones). A market is in scope only if its question matches a "close/finish ... above $K" pattern: daily ("closes above $K on D"), weekly ("finish week of ... above $K") and month-end ("close above $K end of Month"). Out of scope and counted as such: "up or down" (the strike is a reference price, not a listed level), "hit/touch/reach" (path dependent), "between"/range buckets, market cap, earnings, and any crypto or "Bitcoin ETF" contract. Ticker = the symbol in parentheses in the event title. Strike K = the dollar amount in the question. Resolution time = the market `endDate`; resolution date = that instant converted to America/New_York.

**Kalshi.** Series `KXINXU` (S&P 500 above/below) and `KXNASDAQ100U` (Nasdaq-100 above/below), only the events whose settlement time is 16:00 ET (event ticker ending `H1600`). Only those settle at the same moment as a PM-style close and as PM-settled index options. The 10:00 and other intraday hourlies are excluded because no listed option expires at that instant (the time mismatch cannot be fixed with a call spread). `INXU`, `KXINXAB`, `INXAB` and `NASDAQ100U` are queried too and used if they return markets. Underlying mapping: S&P 500 -> SPX (SPXW weeklies, European, PM-settled); Nasdaq-100 -> NDX (NDXP). Strike K = `floor_strike` (Kalshi writes 7794.9999 for "7,795 or above"; the index is continuous so it is the same level).

**Expiry choice.** For each in-scope market, the option expiry is the **nearest listed expiry on or after the resolution date** (listed = appears in the Massive reference contracts for that underlying). `expiry_gap_days` = expiry minus resolution date. Only `expiry_gap_days = 0` rows are **clean** and feed the headline counts. Rows with a gap are kept in the CSV, labelled `expiry_mismatch`, and never counted as gaps (the option then prices a later date).

**Index vs ETF proxy.** SPX and NDX options are used directly for the Kalshi index contracts (no proxy). Polymarket's "S&P 500 (SPY)" contracts are on the SPY ETF price and use SPY options (American exercise, small dividend effect; flagged). No ETF is ever substituted for an index and no index for an ETF.

## 2. Snapshot times (fixed)

Each resolved market is scanned at fixed instants chosen from the calendar, not from outcomes:

| Venue | Snapshot | Why |
|---|---|---|
| Polymarket | `S1` = 15:45 ET on the trading day before the resolution date (about 24h to go) | the markets are listed and the options are in their most liquid minutes |
| Polymarket | `S2` = 12:00 ET on the resolution date (about 4h to go) | same-day check |
| Kalshi H1600 | `S2` = 12:00 ET on the resolution date | the H1600 markets only open the previous evening, so `S1` would find no book |

Live (still open) markets are scanned once, now, with their current order book (section 4).

## 3. Option-implied probability

For a threshold K and expiry T, the risk-neutral probability P(S_T > K) equals e^{rT} * (-dC/dK). The listed-option version is a **call spread**: long the call at K1, short the call at K2 (K1 < K2), width w = K2 - K1:

`p = e^{rT} * (C(K1) - C(K2)) / w`, r = 4% a year (the correction is below 0.05 points for horizons of a week, it is only there so the formula is complete), T = time from the snapshot to the expiry close.

- **Width rule.** If K is itself a listed strike, use its immediate neighbours (K1 = previous listed strike, K2 = next listed strike), a central difference. If K is not listed, use the listed strikes immediately below and above K. This is the **narrow** spread. A **wide** spread uses one more listed strike on each side. Both are reported; the wide one is a robustness check, not a second chance.
- **Leg quotes.** Each leg's quote is the last NBBO quote at or before the snapshot (`/v3/quotes/{option}`, `timestamp.lte`, newest first). A leg is **valid** only if bid > 0, ask >= bid and the quote is no more than 10 minutes older than the snapshot (live: no age filter, but the row is labelled by how old it is). If a leg is invalid, the pair is `no_chain` and is not counted anywhere as a gap.
- **Bounds from bid and ask.** Long spread (buy C(K1) at the ask, sell C(K2) at the bid): `p_hi = e^{rT} * (ask1 - bid2) / w`. Short spread (sell C(K1) at the bid, buy C(K2) at the ask): `p_lo = e^{rT} * (bid1 - ask2) / w`. Mid: `p_mid = e^{rT} * (mid1 - mid2) / w`. All three are clamped to [0, 1]; a mid outside [0, 1] before clamping is flagged `noarb_violation` (quote noise).
- **What the estimate is.** The spread measures the *average* risk-neutral probability across [K1, K2], which equals P(S_T > K) only when the density is smooth over the width. The wider the spread relative to one standard deviation of the move, the cruder it is. The column `w_over_sigma` reports w divided by the one-sigma dollar move implied by the narrow spread; rows with `w_over_sigma > 1` are flagged `coarse`.

## 4. PM prices and sizes

- **Live Polymarket:** CLOB `/book` for the YES token: best bid, best ask and the size at each (shares). Min order 5 shares.
- **Live Kalshi:** the market's `yes_bid_dollars`, `yes_ask_dollars` and `yes_bid_size_fp` / `yes_ask_size_fp`.
- **Resolved Polymarket:** CLOB `prices-history` (fidelity 1) gives one price per minute at best, no book. YES mid = the last point at or before the snapshot; the row is `pm_stale` if that point is older than 15 minutes. **Bid and ask are not recorded historically**, so they are *assumed*: mid -/+ `h`, where `h` is the median half-spread observed across the live PM books of the same run (floor 0.01, one tick). Every resolved-PM row is labelled `pm_spread_assumed`. Sizes are unknown for these rows.
- **Resolved Kalshi:** 1-minute candlesticks carry the real yes_bid and yes_ask (close of each minute). Use the last candle at or before the snapshot with both present. Sizes are unknown.
- A row is **informative** if the PM mid is in [0.02, 0.98] (outside it, rounding to the cent alone decides the gap).

## 5. Cost model (per $1 of YES payoff, every spread crossed)

1. **Polymarket taker fee:** `shares * rate * p * (1 - p)` at the traded price p, with `rate` from the market's own `feeSchedule` (`feesEnabled`, takerOnly; the equity markets show rate 0.04). Maker rebates are ignored (we cross).
2. **Kalshi taker fee:** `ceil_to_cent(0.07 * C * p * (1 - p))` for C contracts at price p, `fee_multiplier` 1 (the series' own field). Rounded up per order, so it is computed per order of the executable size, or per 100 contracts when size is unknown.
3. **Option half-spreads:** already inside the bounds (the long spread is priced at ask1 - bid2, the short spread at bid1 - ask2), so the option side is always charged the full bid/ask cross on both legs.
4. **Option commission:** $0.65 per contract per leg (an assumption; a flat retail-broker figure), two legs, one contract hedges `100 * w` PM shares: `0.65 * 2 / (100 * w)` per share. Exercise or assignment fees are ignored.
5. **PM resolution and hedge basis:** none assumed away; see section 7.

Edge per share, after costs:
- **Trade A, PM YES rich** (sell YES at the PM bid, buy the call spread): `edge_A = pm_bid - fee_pm(pm_bid) - p_hi - comm`.
- **Trade B, PM YES cheap** (buy YES at the PM ask, sell the call spread): `edge_B = p_lo - pm_ask - fee_pm(pm_ask) - comm`.
- `edge = max(edge_A, edge_B)` (the sign tells which trade).
Also reported, before costs: `mid_gap = pm_mid - p_mid`, and the gap against the bounds only (zero when the PM mid sits inside [p_lo, p_hi]).

## 6. What counts as a gap

Labels in increasing strictness (each row gets the strictest it earns):

1. **gap_mid:** |mid_gap| >= 0.05 on a clean, informative, fresh row. A screening statistic only; it says nothing about tradability.
2. **gap_beyond_bounds:** the PM mid lies outside [p_lo, p_hi] of the narrow spread.
3. **gap_net:** `edge >= 0.01` (one cent per $1 of payoff) after every cost in section 5, using the narrow spread.
4. **gap_robust:** gap_net, and the wide spread also gives `edge > 0` on the same trade.
5. **gap_executable:** gap_robust on a **live** row where the options market is open (the option quote is no older than 10 minutes), both legs have size, and the PM side can fill at least one whole spread (`PM size at the touch >= 100 * w` shares, since one option contract is the smallest hedge). Resolved rows can never be executable (no historical book, no way to trade them).

The headline answer ("how many genuine gaps survive costs") is the count of **gap_robust** rows among clean, informative, fresh rows, split into resolved (spread assumed unless Kalshi) and live, with the executable count shown separately. Counts are per (market, snapshot) row, so one mispriced ladder counts several times; the report also gives the number of distinct events involved.

## 7. Caveats the report must carry

- **The hedge is not riskless.** A call spread replicates the PM digital only outside [K1, K2]. Inside the strip, a short YES against a long spread can lose up to `(K2 - K)/w` per share (half a dollar for a centred spread). Net edge is therefore edge against an approximating hedge, not a locked arbitrage. The report prints this worst-case strip loss next to every edge.
- **Timing mismatch.** PM points are last trades, option quotes are NBBO, taken at the same wall-clock instant but not the same tick. PM resolves on the Pyth 1-minute close at 16:00 ET, options settle on the official closing price; Kalshi uses the index value at 16:00 ET.
- **Expiry mismatch** (section 1), **ETF vs index** (section 1), **American vs European exercise** (SPY and single names).
- **Assumed spread** on resolved Polymarket rows (section 4): those rows can show a *screening* gap but not a verified executable edge.
- **Thin books.** PM books are often a handful of shares at the touch. A positive edge at 5 shares is a few cents.
- **Selection.** The universe is whatever the venues listed in the window; strike ladders include many far-from-the-money markets that are filtered by the informative rule, not by outcome.
- **Calibration check (resolved rows only).** Brier score of the PM mid vs the option mid against the realized result of the market (from the market's own resolution), reported as descriptive; small samples, overlapping strikes and a shared underlying path make the rows strongly correlated, so no significance test is claimed.
- **Run date** is 2026-10-03 (Saturday). Live equity options are closed, so live rows use the Friday close quotes against weekend PM books and can never be executable. The command in `RUN_LOG.md` re-runs the live part when the market is open.

## 8. Outputs

- `research/results/arb/arb_gaps.csv`: one row per (market, snapshot) with every field above.
- `research/results/arb/SUMMARY.md`: counts funnel, table of the largest gaps with all labels, calibration, caveats.
- `research/results/arb/arb_gap_chart.png`: PM mid vs option-implied mid with the bound band.
- `research/results/arb/RUN_LOG.md`: commands, request counts, timings, skipped and failed items.
- Tests on synthetic chains in `research/arb/tests` (no network).

## Amendments

1. **Before any scan data was fetched (only feasibility probes of the endpoints had been run):** the `w_over_sigma` coarseness flag in section 3 is replaced by `width_sens = |p_mid(narrow) - p_mid(wide)|`, with `coarse` set when `width_sens > 0.05`. Reason: `w_over_sigma` needs an extra volatility estimate (extra quotes) while the narrow-vs-wide disagreement measures the same smoothing error directly from data already fetched.
2. **Same time:** Kalshi fee rounding is applied to the order size where a size is known and to 100 contracts otherwise, as stated in section 5; the code computes the per-share figure as `total / C`.
3. **After the first full run, after seeing its results (so this is a post-hoc change, disclosed as such).** The first run, scored exactly as sections 1 to 7 prescribe, reported 247 resolved Polymarket rows at `gap_robust` and 0 for Kalshi and for the live books. Inspection showed the 247 are mostly an artifact of the assumed-spread rule in section 4: Polymarket's `prices-history` is sampled every minute whether or not anything traded (the 15-minute age check in section 4 is therefore vacuous for it), and for thin markets its value is the midpoint of a book that may be 0.01 bid / 0.99 ask (17 of the candidates sit at exactly 0.50). A fixed +/-4.5 cent spread around such a midpoint invents an edge. Two changes, both only making the test stricter:
   - A new label **`gap_verified`** sits between `gap_robust` and `gap_executable`. A resolved Polymarket `gap_robust` row is promoted only if a public trade print (Polymarket data-api `/trades` for the market's condition id) within +/-10 minutes of the snapshot shows a Yes-equivalent price at least as good as the row's breakeven price (the PM sell price that gives edge >= 1 cent for trade A, the buy price for trade B), on the correct side (a No trade at q is a Yes trade at 1 - q on the opposite side). Resolved Kalshi rows use real bid/ask candles, so their `gap_robust` is promoted automatically.
   - The headline answer is now the count of `gap_verified` plus `gap_executable` rows. The pre-registered `gap_robust` counts are still printed next to it so the effect of the amendment is visible.
   The breakeven price is a trade-print check only: it shows a price existed, not the depth at it, and prints lie outside the option snapshot instant by up to 10 minutes.
