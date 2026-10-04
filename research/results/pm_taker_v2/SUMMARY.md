# P2 study B options-anchored Polymarket taker: INSUFFICIENT

Verdict: **INSUFFICIENT**. Primary rule (tau = 0.05, entry = taker print + 1c, Polymarket fee, hold to settlement): mean net P&L +29.79 pt [+13.01, +44.58] per $1 contract, 95% day-cluster bootstrap CI (10,000 draws), 40 trades on 21 resolution days. Pass rule: lower bound > 0 with >= 100 trades on >= 30 days.

Precision: approximate SE +8.05 pt, so the MDE at 80% power is about +22.55 pt. The estimate is 1.3x that MDE. It lands near the MDE, so a significant estimate here is likely to overstate the true edge (type-M); if the true edge were 2 pt, a significant estimate would overstate it about 2x.

## Results

| variant | n trades | days | mean net, pt per $1 | 95% CI (day clusters) |
|---|---|---|---|---|
| **primary** (tau 0.05, +1c, fee) | 40 | 21 | +29.79 | [+13.01, +44.58] |
| secondary: +2c slippage | 40 | 21 | +28.79 | [+12.01, +43.58] |
| secondary: no tick | 40 | 21 | +30.79 | [+14.01, +45.58] |
| secondary: tau 0.03 | 110 | 35 | +15.18 | [+5.33, +25.29] |
| secondary: tau 0.10 | 5 | 3 | +39.88 | [+22.27, +55.58] |
| secondary: gross (no fee, no tick) | 40 | 21 | +31.28 | [+14.50, +46.04] |
| secondary: ticker-day clusters | 40 | 33 | +29.79 | [+14.53, +44.12] |
| secondary: mid variant (prices-history mid +/- 2.5c) | 112 | 38 | +21.86 | [+13.64, +29.46] |
| secondary: equal weight per day | | 21 | +27.05 | [+10.01, +42.57] |

Secondary rows are pre-registered (METHOD.md section 5) and never change the verdict.

## Splits (primary rule)

| split | group | n | days | mean, pt | 95% CI |
|---|---|---|---|---|---|
| tk | AAPL | 5 | 4 | +57.26 | [+40.33, +82.66] |
| tk | AMZN | 3 | 3 | +1.78 | [-50.00, +78.00] |
| tk | GOOGL | 4 | 3 | +35.35 | [-35.00, +64.00] |
| tk | META | 1 | 1 | +44.01 | [+44.01, +44.01] |
| tk | MSFT | 2 | 2 | +67.14 | [+67.14, +67.14] |
| tk | NVDA | 6 | 5 | +63.15 | [+15.79, +86.39] |
| tk | SPY | 15 | 11 | +22.21 | [+3.25, +39.92] |
| tk | TSLA | 4 | 4 | -32.99 | [-56.99, +4.75] |
| side | BUY | 31 | 17 | +28.38 | [+10.24, +43.84] |
| side | SELL | 9 | 7 | +34.62 | [-19.49, +69.42] |
| fee_enabled | False | 11 | 4 | +29.64 | [-8.64, +60.50] |
| fee_enabled | True | 29 | 17 | +29.84 | [+11.50, +45.58] |

## Signal check

Over 970 evaluated prints with a usable spread (324 markets), the Brier score of the option p_mid is 0.2145 against 0.2257 for the PM print price.

## Capacity

Taking half of each qualifying print: 2881 shares, $747 deployed and $1,535 net P&L over the whole window (median print size 19.493669 shares).

## Settlement

Unresolved trades dropped: 0. Primary trades where the Polymarket resolution disagrees with the Massive close vs K: 0 (kept as resolved by Polymarket).

## Scope

```
{
 "drop_outside_window": 1640,
 "drop_reopening_day": 852,
 "drop_no_clean_expiry": 1200,
 "universe_markets": 2012,
 "universe_days": 68,
 "universe_ticker_days": 328,
 "universe_empty_window": 25,
 "markets_processed": 2012,
 "prints_raw": 2293,
 "markets_offset_cap": 0,
 "prints_kept": 1962,
 "markets_with_prints": 726,
 "eval_ok": 970,
 "eval_unusable": 177,
 "eval_no_spread": 8,
 "markets_empty_window": 25
}
```

## Caveats

- Copy-the-taker: being first to the stale quote is assumed; if faster bots already take these quotes, the sign can survive while our share does not. Capacity is bounded by print sizes.
- Option-mid noise and winner's curse: selecting on the gap shrinks the realised edge out of sample.
- Outcomes on one day share the market move, so the effective sample is closer to the number of days than to the number of trades.
- The fresh window (Apr 1 to Aug 14 2026) differs in regime from the seen lead (Aug to Oct 2026).

Commit ea4d7a0. Requests: {'data-api.polymarket.com': 1987, 'gamma-api.polymarket.com': 399, 'clob.polymarket.com': 324, 'massive': 2296}. Files: stats.json, trades.csv, trades_frozen.csv, prints_evaluated.csv, universe.csv, kill_test.json, chart.png, RUN_LOG.md.
