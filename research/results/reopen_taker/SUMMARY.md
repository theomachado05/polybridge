# Study A: options-anchored taker on reopening days: NULL

Verdict: **NULL**. Primary (tau 0.05, one tick, net of fee): mean net P&L per $1 contract -0.40 pt [-4.68, +3.74], n = 402 trades, 44 closures (closure-cluster bootstrap 95% CI).

These closures and their PM and option prices were already seen in R3 and the overshoot study; this is a pre-registered re-analysis at printed trade prices, not a confirmation (METHOD.md section 0).

## Secondary (labelled secondary, never change the verdict)

- tick_0.02_tau_0.05: -1.40 pt [-5.68, +2.74], n = 402 trades, 44 closures
- tau_0.03: +0.24 pt [-3.66, +3.79], n = 461 trades, 44 closures
- tau_0.1: +0.96 pt [-4.39, +6.26], n = 291 trades, 43 closures
- side_BUY: -0.01 pt [-6.66, +6.96], n = 184 trades, 43 closures
- side_SELL: -0.72 pt [-7.43, +6.48], n = 218 trades, 42 closures
- kind_daily: -0.93 pt [-5.61, +3.65], n = 275 trades, 33 closures
- kind_monthly: -1.82 pt [-11.62, +8.36], n = 102 trades, 16 closures
- kind_weekly: +11.29 pt [+0.88, +24.67], n = 25 trades, 5 closures

## Capacity

- Sum of print notional at entry: $16,084; profit at half the print size: $-2,507; median print size 20 shares.

## Scope

```
{
 "events": 1535,
 "closures": 44,
 "markets_evaluated": 969,
 "markets_offset_cap": 0,
 "prints_raw": 16319,
 "prints_kept": 11780,
 "drop_option_unusable": 566,
 "drop_no_outcome": 0
}
```

Caveats: seen closures; copy-the-taker; the 09:45 option probability is stale for later prints; trades within a closure share the market move; monthly markets tie up capital for weeks.
