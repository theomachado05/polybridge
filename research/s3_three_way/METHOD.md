# S3: three-way consistency on "S&P 500 closes above K" (pre-registered)

**Question.** The same event, "the S&P 500 closes above K today", is priced in three places: Kalshi (the index level
at 4pm), Polymarket (the SPY ETF close) and listed options (a call spread around the strike). When one of the two
prediction venues disagrees with the options and the other does not, does trading the outlier against the other
prediction venue make money after every cost? And over a weekend, when options are closed, do the two prediction
venues stay consistent with each other on Monday's close?

This file and `config.py` are committed **before any data is pulled for S3 and before the recorded threshold books are
read**. Every rule is fixed. Changes go under "Amendments", dated. Each part is reported whatever it shows.

## 0. What was known before this commit

- `research/results/arb/SUMMARY.md` and its CSV (each venue against options, never against each other): of 500
  resolved Kalshi rows, 0 gaps survive costs (mean absolute gap 2.3 points); of 2,761 resolved Polymarket rows, 224
  pass a cost screen on an assumed spread and 5 have a supporting trade print (1 of them is SPY). Live rows read on
  Saturday morning: 0 executable.
- Rows of `arb_gaps.csv` looked at while scoping this study: the first SPY rows of 2026-08-17, a handful of Kalshi SPX
  rows of 2026-10-01 and 10-02, and one mid-window date's SPY and SPX rows (SPY 745 to 775, SPX 7565 to 7620). No
  cross-venue match was computed.
- The recorder's universe file (names, strikes, dates; no prices): 11 Polymarket SPY strikes ($740 to $790) and 60
  Kalshi SPX strikes (7500 to 7795) for Monday 2026-10-05.
- S1's result so far: a modelled Polymarket spread manufactures false gaps, and a trade-print check removes most of
  them. The same check is built in here.
- **Not seen:** any Kalshi quote matched to a Polymarket strike; any price in `research/forward/raw/thresholds/`.

## 1. Universe and the strike map

- **Polymarket:** "S&P 500 (SPY) closes above $K on <date>" daily markets.
- **Kalshi:** series `KXINXU`, the 16:00 ET event of the same date, "above K′" markets (5-point steps).
- **Options referee:** the call-spread bounds `[p_lo, p_hi]` on SPY options for the Polymarket strike, as computed by
  the arb scan (`research/arb/METHOD.md`).
- Nasdaq-100 and single stocks are out: only the S&P 500 is listed as a threshold on all three.
- **Strike map.** `R` = official S&P 500 close ÷ official SPY close on the last session before the snapshot (Massive
  daily bars). The Kalshi strike for Polymarket strike `K` is the listed `K′` nearest `R × K`. The set is kept only if
  `|K′ − R × K| ≤ 2.5` index points and the Kalshi market exists.
- **Dropped:** a resolution date that is an SPY ex-dividend date (the ratio from the previous close is then wrong by
  the dividend).
- The two contracts are **near-twins, not twins:** SPY against the index, a strike rounded by up to 2.5 points, and two
  different closing prints. They can resolve differently when the close lands next to the strike. In history this is
  measured: each leg is paid by its own venue's actual result.

## 2. Part H: history (34 resolution dates, 2026-08-17 to 2026-10-02)

- **Snapshot:** 12:00 ET on the resolution date (`S2` of the arb scan), the only fixed instant at which both venues
  have a book (Kalshi's 16:00 markets open the evening before).
- **Polymarket:** the resolved, scored, clean-expiry SPY rows of the committed `research/results/arb/arb_gaps.csv`:
  price, the assumed bid and ask the scan used, the options bounds, the outcome.
- **Kalshi (new pull):** for each mapped strike, the 1-minute candle bid and ask as of the snapshot, at most 6 hours
  old (Kalshi writes a candle only when the top of the book changes: S1 amendment 1), both sides present; and the
  market's settled result.
- One snapshot a day, so there is no two-observations rule here. That is a stated weakness of Part H.

## 3. Part F: forward (this weekend's recorded books)

- `research/forward/raw/thresholds/`, real books every 30 s, for the Monday 2026-10-05 markets. `R` from Friday's
  closes.
- **Window:** 2026-10-04T00:00:00Z to 11:00:00Z (Sun 07:00 ET); a later update to 13:30Z is labelled.
- Options are closed all weekend. Their Friday-close bounds (the live SPY rows of `arb_gaps.csv`) are stale, so in
  Part F the referee is **reported, not used to gate trades**.
- Entry needs the edge at two consecutive snapshots and fills from the second one's recorded levels: at least 5
  contracts, at most 500, one position per strike.
- The markets resolve Monday 16:00 ET, after the submission deadline. Part F therefore reports fills, the edge locked
  if both legs resolve alike, marks at the end of the window and capacity. No Sharpe ratio.

## 4. Signal

With Polymarket YES bid / ask `pb`, `pa`, Kalshi `kb`, `ka`, and the referee band `[lo, hi]`:

- A venue **disagrees with the options** when its whole quote is outside the band: rich if `bid > hi`, cheap if
  `ask < lo`. Otherwise it agrees.
- **Outlier:** exactly one of the two prediction venues disagrees.
- **Cross-venue lock** (the trade): buy YES where it is cheap and NO where it is rich.
  `edge = 1 − (YES ask + fee) − (NO ask + fee) − carry`, as in S1 section 4.
- **Unhedged fade** (variant): buy only the outlier's cheap side; edge is the distance beyond the band less that
  venue's fee.

## 5. Costs

As S1 section 3: Kalshi `ceil_to_cent(0.07 × multiplier × C × P × (1 − P))` with the series' own `fee_multiplier`
from Kalshi's API; Polymarket's `feeSchedule` (0.04 × P × (1 − P) on these markets); both half-spreads by trading at
the ask; carry at the 3-month Treasury yield to resolution (hours to two days, so near zero). 2× costs doubles fees,
half-spreads and carry. Costs are reported in bp of capital.

## 6. Variants (the complete list)

| id | trade | θ | outlier filter (Part H) |
|---|---|---|---|
| **V0, primary** | cross-venue lock | $0.02 | on |
| V1 | cross-venue lock | $0.01 | on |
| V2 | cross-venue lock | $0.02 | off |
| V3 | unhedged fade of the outlier | $0.02 beyond the band | on |

Part F has no live referee, so there V0 and V2 coincide and V3 is not run. θ is 2¢ in the primary, twice S1's, to pay
for the near-twin risk. Each variant is run at 1× and 2× costs.

## 7. Accounting and segments

- 100 contract pairs per entry in Part H (no sizes in history, no capacity claim). Each leg is paid by its own
  venue's result: `P&L = payoff(Polymarket leg) + payoff(Kalshi leg) − cost`. A split resolution is counted and shown.
- Capital base: `$100 ×` the largest number of sets open on one day. Positions resolve the same day.
- Daily P&L ÷ capital gives daily returns; Sharpe on 252 days; maximum drawdown; worst month; turnover.
- **In-sample / out-of-sample:** by resolution date, OOS is the most recent 20% of the dates (7 of 34). Nothing is
  fitted on either.
- **Trade-print check:** a Part H entry is print-verified if a public Polymarket trade within ±10 minutes of the
  snapshot shows a price at least as good as the one assumed (S1 section 8). Results are given for all entries and for
  the verified ones.
- Mean P&L per trade with a 95% bootstrap interval resampling **dates**.

## 8. Success criterion (primary V0, fixed now)

A pass needs all of: at least 20 print-verified entries on at least 10 dates in the whole history, at least 5 of them
out-of-sample; positive net P&L at 1× and at 2× costs on the verified entries, in-sample and out-of-sample; a
date-bootstrap interval above zero. With 34 dates this is unlikely to be reachable; **"too few observations" is the
expected answer and will be reported as that.** n is reported for every cell.

## 9. Caveats known in advance

- Near-twin risk (section 1). Legging risk. One snapshot a day in history. Polymarket's historical spread is assumed.
- Part F's edge is "locked" only if the two venues resolve alike on Monday; the outcome is not known by the deadline.
- Kalshi's weekend books on these markets are wide (median spread 23 points on Saturday morning per the arb scan), so
  few fills are expected.

## Outputs

`research/results/s3_three_way/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `trades.csv`,
`capacity.md`, `RUN_LOG.md`.

## Amendments

**Amendment 1, 2026-10-03 23:42 UTC, before any S3 result existed: source of the S&P 500 close.** Section 1 takes the
index close from Massive daily bars. Massive refused the index (`403` on `I:SPX`; the plan covers options and stocks,
not index aggregates). The index close is taken instead from Kalshi's own settlement value (`expiration_value`) of the
previous session's 16:00 `KXINXU` event, which is the S&P 500 level Kalshi settled on. SPY's close still comes from
Massive. The ratio rule is otherwise unchanged. The first run stopped at the refused request; no set had been built.
