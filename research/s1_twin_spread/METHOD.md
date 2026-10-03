# S1: Polymarket–Kalshi twin spread (pre-registered)

**Question.** The same question trades on Polymarket and on Kalshi. When one venue's YES is cheaper than the other's by
more than every cost, buy YES on the cheap venue and NO on the rich one: the two together pay exactly $1 at resolution.
Net of fees, both spreads and the cost of capital locked until resolution, does this rule make money on the 33 verified
twin pairs, in history and on this weekend's recorded order books?

This file and `config.py` are committed **before any price history is pulled for S1 and before the forward recording
is analysed**. Every rule below is fixed. A later change goes under "Amendments" with its date and reason; the original
stays in git history. Each run is reported whatever it shows, and every variant listed in section 7 is reported.

## 0. What was known before this commit

- **Not seen:** any Kalshi candlestick or Polymarket price history for any twin pair; any cross-venue gap for any
  pair; any equity curve.
- **Seen:**
  - `backend/app/data/kalshi_twins.json` (the 33 pairs: questions, deadlines, verification checks; no prices).
  - `research/results/arb/SUMMARY.md` (Polymarket and Kalshi against *options*, not against each other). Its lesson is
    used here: an assumed Polymarket spread around a history point manufactured hundreds of false gaps, and only a
    trade print could confirm them.
  - Live books read while building the recorder, about 23:05–23:11 UTC on 2026-10-03: the Polymarket book of the Fed
    October cut market; the Kalshi books of `KXFEDDECISION-26OCT-C25` (no bid / 0.01 ask), `KXFEDDECISION-26OCT-H25`
    (0.17 / 0.18) and `KXIPO-26-ANTHROPIC` (0.75 / 0.78); one recorded Polymarket row (0.40 / 0.42). No pair's two
    venues were compared.
  - Counts from the recorder's first minute: 128 of 132 Polymarket books and 116 of 132 Kalshi books were two-sided.
- The 8-K holdout, `research/results/oos/` and `research/HYPOTHESIS.md` are not touched.

## 1. Universe and data

- **Universe:** the 33 pairs in `pairs` of `backend/app/data/kalshi_twins.json` as committed (generated
  2026-10-03T09:41:53Z). No pair is added or removed by hand. A pair that cannot be used is listed with the reason.
- **History, Kalshi:** 1-minute candlesticks (`/series/{series}/markets/{ticker}/candlesticks`, `period_interval=1`).
  The executable quote of a minute is the candle's `yes_bid.close` and `yes_ask.close`. These are real quotes. They
  carry no sizes.
- **History, Polymarket:** CLOB `prices-history` for the YES token, `fidelity=1`. This is one price per minute with no
  bid, ask or size.
- **Range per pair:** from `max(T1 − 365 days, Kalshi open_time, Polymarket start date)` to `T1`, the minute the pull
  starts (written to `run_meta.json`). If a venue will not serve 1-minute data for part of the range, that part is
  dropped for that pair, never replaced by coarser bars, and the coverage is reported.
- **Grid and as-of rule:** a 1-minute UTC grid. A venue's quote at minute `t` is its last observation at or before `t`,
  and only if it is at most 15 minutes old; otherwise missing. Nothing is imputed.
- **Valid Kalshi side:** a bid of 0 or an ask of 1 is an empty side. It is never treated as a price.
- **Forward data:** `research/forward/raw/twins/` (real books, 5 levels, sizes, every 15 s; format in
  `research/forward/README.md`).

## 2. Executable prices

| | Kalshi | Polymarket |
|---|---|---|
| History | candle bid / ask close | `m ± h_i`: the history price `m` plus or minus a **modelled** half-spread |
| Forward | recorded book | recorded book |

- **Modelled half-spread `h_i` (history only).** Historical Polymarket books are not published. For pair `i`, `h_i` is
  the median of `(best ask − best bid) / 2` over its recorded books in the **calibration slice**, from the recording
  start (2026-10-03T23:09:48Z) to 2026-10-04T00:00:00Z, with a floor of 0.005. Modelled prices are clipped to
  [0.001, 0.999]. A pair whose Polymarket book is one-sided or empty in more than half of the calibration snapshots has
  no modelled spread and is left out of the historical backtest (it stays in the forward test).
- This is a model fitted on books newer than the history it is applied to. Section 8 adds a trade-print check because
  of that.
- **No short selling on either venue.** Selling YES means buying NO at `1 − (YES bid)`. Polymarket's NO book mirrors
  its YES book; Kalshi's YES asks are its NO bids.

## 3. Costs (1×)

Per contract pair (one YES plus one NO, paying $1):

| cost | rule | source |
|---|---|---|
| Kalshi taker fee | `ceil_to_cent(0.07 × multiplier × C × P × (1 − P))` on the order, at entry and at any exit; nothing at settlement | Kalshi fee schedule (kalshi.com/docs/kalshi-fee-schedule.pdf); `fee_type` and `fee_multiplier` of the series from Kalshi's API |
| Polymarket taker fee | `C × rate × (P × (1 − P))^exponent` with the market's own `feeSchedule`; zero when `feesEnabled` is false | Polymarket gamma market record (`research/arb/arbscan/costs.py`) |
| Both half-spreads | paid by trading at the ask of each leg | Kalshi quote; Polymarket model (history) or book (forward) |
| Carry | `r × τ × capital`: capital is what the two legs cost; `τ` is the time to the pair's deadline (the later of the two venues' end dates) in years; `r` is the latest 3-month Treasury yield at run time | Alpha Vantage `TREASURY_YIELD` (FRED DGS3MO); the value goes in `run_meta.json` |

- **2× costs:** each fee doubled, each half-spread doubled around the venue's mid, carry doubled. The entry and exit
  rules are re-evaluated under the doubled costs.
- **Reported in bp** of the capital committed, per trade and on average: fees, spread and carry separately.
- **Not charged, and said so:** USDC on- and off-ramp and Polygon gas, Kalshi deposit fees, taxes. Kalshi pays
  interest on collateral, which would offset part of the carry; it is ignored.
- An unknown Kalshi `fee_type` is logged as an amendment and the general formula is used.

## 4. Signal

With Polymarket YES bid / ask `pb`, `pa`, Kalshi YES bid / ask `kb`, `ka`, fees per contract `fP(·)`, `fK(·)`:

- **A, buy Polymarket YES and Kalshi NO:** `edge_A = 1 − [pa + fP(pa)] − [(1 − kb) + fK(1 − kb)] − carry`.
- **B, buy Kalshi YES and Polymarket NO:** `edge_B = 1 − [ka + fK(ka)] − [(1 − pb) + fP(1 − pb)] − carry`.

The edge is dollars per contract pair, locked in if both venues resolve the same way.

## 5. Entry, size, exit

- **Entry:** `edge ≥ θ` at two consecutive observations (adjacent grid minutes in history, adjacent snapshots in the
  forward test). The fill is at the prices of the **second**. This is the latency model: a gap that lasts one
  observation is never traded.
- **One open position per pair.** After an exit the pair can be entered again.
- **Size, history:** 100 contract pairs per entry. History has no sizes, so the historical backtest makes **no
  capacity claim**.
- **Size, forward:** walk both recorded books level by level and take every matched increment whose marginal edge is
  still `≥ θ`, from the second snapshot's book. Minimum 5 contracts (Polymarket's minimum order), maximum 500 per
  position. Kalshi's fee rounding is applied to the whole order.
- **Exit:** the position can be sold for `L = (YES leg bid) + (NO leg bid) − exit fees`. Exit when
  `L ≥ 1 − r × τ` (the market pays at least the present value of the guaranteed dollar) at two consecutive
  observations, at the second's prices. Otherwise hold. No pair resolves inside the sample, so a position not exited is
  still open at the end.

## 6. Accounting and segments

- **Capital base:** `K = 33 × $100 = $3,300` in history, the most the rule can deploy; fully funded, no leverage.
  Forward: `K = 33 × $500`.
- **Financing:** each day, `r / 365 ×` the capital locked in open positions is charged. Returns are therefore excess
  returns and no risk-free rate is subtracted again.
- **Marks.** Primary: **mid** (Polymarket history price or book mid; Kalshi `(bid + ask) / 2`, last valid mid carried).
  Also reported: **liquidation** (sell both legs at their bids, net of fees) and **locked** (`$1` at the deadline less
  the remaining financing). A locked arbitrage marked at its locked value has almost no volatility, so a Sharpe ratio
  is computed on the mid mark only.
- **Daily series:** equity at 00:00 UTC each day; `r_d = ΔEquity_d / K`; 365 days a year (both venues trade daily).
- **History window:** `[T0, T1]`, `T0` = the first minute at which any pair has both venues.
- **In-sample / out-of-sample:** OOS is the most recent 20% of `[T0, T1]` by calendar time (the 2-year cap does not
  bind). IS is the rest. The OOS run starts flat at the split; IS positions are closed at their mark at the split.
  Nothing is fitted on either: every parameter is fixed here. If a variant other than the primary is ever preferred,
  it is chosen on IS only and flagged.
- **Forward window:** 2026-10-04T00:00:00Z to 2026-10-04T11:00:00Z (Sun 07:00 ET), starting flat. A later update to
  13:30Z is labelled as such. The window is under a day, so it reports fills, locked edge, marks at the end and
  capacity, and no Sharpe ratio.

## 7. Variants (the complete list)

| id | θ (net edge per contract pair) | exit rule |
|---|---|---|
| **V0, primary** | $0.01 | on |
| V1 | $0.02 | on |
| V2 | $0.03 | on |
| V3 | $0.01 | off (hold only) |

Each is run on IS, OOS and forward, at 1× and 2× costs. The deflated Sharpe ratio
(`research/polybridge_research/stats.py`) uses 4 trials.

## 8. Metrics and checks

- **Per segment and variant:** entries, pairs traded, net P&L under each mark, Sharpe (mid mark), maximum drawdown,
  worst calendar month, turnover (dollars traded / `K`, annualised), mean edge at entry, cost breakdown in bp.
- **Inference:** mean net P&L per trade with a 95% bootstrap interval that resamples **pairs** (trades of one pair are
  not independent).
- **Trade-print check (history).** An entry is *print-verified* if a public Polymarket trade (data-api `trades`)
  within ±10 minutes of the fill shows a price at least as good for our side as the modelled one: for a YES buy, a
  taker bought YES at or below `pa`; for a NO buy, a taker sold YES at or above `pb`. Verified size is the printed
  size, capped at the clip. Results are reported for all entries and for the verified subset.
- **Capacity (forward only):** dollars fillable at `edge ≥ θ` from the recorded depth, per pair and in total, and the
  share of visible depth that takes.
- **Sharpe above 3 means a bug hunt before anything is reported:** fills at the second observation; quote ages;
  Polymarket points that are the middle of an empty or very wide book; fees on every leg; empty Kalshi sides; both
  clocks in UTC; pair direction. The outcome of each check is written to `RUN_LOG.md`.

## 9. Success criterion (primary V0, fixed now)

A pass needs all four:
1. OOS has at least 30 entries across at least 5 pairs.
2. OOS net P&L at 1× costs is positive under both the mid mark and the locked mark, and the pair-bootstrap 95% interval
   of the mean net P&L per trade excludes zero.
3. OOS net P&L is still positive at 2× costs.
4. At least half of the OOS entries are print-verified, and the verified subset has positive net P&L.

The forward test is reported next to it as independent evidence: fills with a positive locked edge support the result;
no fills means the edge was not there this weekend.

Anything else is a null or "too few observations" and goes under "what didn't work", unreframed.

## 10. Caveats known in advance

- **Resolution risk.** The twins were verified from text. If the two venues resolve differently the position can lose
  up to its full cost. No pair has resolved, so this cannot be measured here.
- **Legging risk.** The two legs are assumed to fill together.
- **Polymarket spread in history is a model;** Kalshi sizes in history are unknown.
- **Capital sits on two venues** and cannot be netted between them.

## Outputs

`research/results/s1_twin_spread/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `trades.csv`,
`capacity.md`, `RUN_LOG.md`, `run_meta.json`.

## Amendments

**Amendment 1, 2026-10-03 23:28 UTC, before any backtest was run: a labelled sensitivity for Kalshi quote age.**
The pull showed that Kalshi 1-minute candles are sparse (for example 222 candles in 15 days for one market). A
data-quality check against the recorder, with no strategy quantity computed, shows why: candles are only written when
the top of the book changes. For every recorded snapshot whose last candle was more than 15 minutes old, the candle's
bid and ask equalled the recorded book: 792 of 792 snapshots, 12 markets, gaps up to 5.0 hours. (Over all snapshots:
1,542 of 1,584; the misses are changes inside the current minute.) The 15-minute rule of section 1 therefore discards
valid Kalshi quotes. The registered rule is **not** changed and stays the primary. Added: a sensitivity `kalshi_carry_6h`
in which a Kalshi quote stays valid for up to 6 hours (the longest verified gap is 5.0 h); the Polymarket rule is
unchanged. It is run for every variant and reported next to the primary. The history window and the IS/OOS split are
those of the registered rule. The deflated Sharpe ratio now uses 8 trials (4 variants × 2 quote rules).

**Amendment 2, 2026-10-03 23:28 UTC, before any backtest was run: a signal needs a two-sided Kalshi quote.**
Section 1 says an empty Kalshi side is never a price. The 2× cost rule and the mid mark both need the Kalshi mid, so
a minute with only one Kalshi side gives no signal in either direction, at 1× and at 2×.

**Note on fees, same time.** Kalshi's API reports `fee_type` `quadratic` or `quadratic_with_maker_fees` with
`fee_multiplier` 1 for all 33 series: the general taker formula applies to all. Polymarket's `feeSchedule` rate is
0.04 (27 markets) or 0.05 (the 6 Fed markets), exponent 1; one market (Trump out before 2027) charges no fee.
The 3-month Treasury yield is 4.17% (2026-10-01, the latest value published).

**Amendment 3, 2026-10-03 23:47 UTC, before the forward window opened: the forward test needs two-sided books.**
Amendment 2 (no signal from a one-sided Kalshi quote) applies to the recorded books too, and to Polymarket's book: the
2× cost rule and the mid mark need each venue's mid. A snapshot in which either book has an empty side gives no entry
signal, at 1× and at 2×. At the end of the window the mid mark uses the last snapshot with both books two-sided
("last valid mid carried", section 6); a position that cannot be sold into the final book is counted and shown, not
valued at zero.
