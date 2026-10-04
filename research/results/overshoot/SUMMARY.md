# T4: overshoot or slow options at the Monday open?

Run 2026-10-03T21:47Z. Pre-registered method: [`research/overshoot/METHOD.md`](../../overshoot/METHOD.md) (committed in `88b2541` before any statistic was computed). Numbers: [`stats.json`](stats.json). Chart: [`decomposition.png`](decomposition.png). Log: [`RUN_LOG.md`](RUN_LOG.md).

**This is a pre-registered re-analysis of R3's already-seen rows (`research/results/open_options/events.csv`). It is not confirmatory.** No new data was fetched.

## Answer

Sample: 1535 R3 events from 44 closures; decomposition sample (PM at 16:00 and options at 15:55 both present) 1123 events from 43 closures. Intervals are 95% closure-cluster bootstrap (10,000 draws).

**(a) Decomposition verdict: OVERSHOOT-PARTIAL / NO-LAG-SHOWN** (GAP-PERSISTS).

- Closure gap G (PM move minus option move, signed by the PM move): +7.84 pt [+5.61, +9.96].
- PM gives back after the open (by 16:00): +3.84 pt [+1.84, +6.22]; share of G 0.49 [0.26, 0.80].
- Options catch up after 09:45 (by 15:55): -0.59 pt [-2.43, +0.88]; share of G -0.08 [-0.32, 0.12].
- Left at the end of the reopening day: +4.59 pt [+2.87, +6.26]; share of G 0.59 [0.45, 0.70].
- Catch-up slope at 09:45 on the PM closure move: 0.33 [0.22, 0.48]; on the PM move that survives to 16:00: 0.31 [0.21, 0.40]; options' full-day move on the PM's full-day move: 0.73 [0.62, 0.83].

**(b) Forecast verdict at the open: OPTIONS-BETTER**; at the prior close: OPTIONS-BETTER.

- Open pair (PM 09:30 vs options 09:45, n=1535, 44 closures), PM vs options, diff = PM minus options (positive = options better): Brier 0.1464 vs 0.1196, diff +0.0267 [+0.0189, +0.0349]; log score 0.4548 vs 0.3798, diff +0.0749 [+0.0532, +0.0980].
- Close pair (PM at the close vs options 15:55, n=1535): Brier 0.1639 vs 0.1511, diff +0.0129 [+0.0046, +0.0218]; log score 0.5019 vs 0.4720, diff +0.0300 [+0.0084, +0.0515].

## Secondary (reported, not used for the verdicts)

Decomposition variants:

| sample | events | closures | G | PM gives back | options catch up | left | share given back |
|---|---|---|---|---|---|---|---|
| primary | 1123 | 43 | +7.84 pt [+5.61, +9.96] | +3.84 pt [+1.84, +6.22] | -0.59 pt [-2.43, +0.88] | +4.59 pt [+2.87, +6.26] | 0.49 [0.26, 0.80] |
| same instant (PM at 09:45) | 1123 | 43 | +5.53 pt [+3.58, +7.49] | +1.53 pt [-0.03, +3.43] | -0.59 pt [-2.43, +0.88] | +4.59 pt [+2.87, +6.26] | 0.28 [-0.01, 0.68] |
| Polymarket trade print inside the closure | 838 | 43 | +7.29 pt [+5.00, +9.58] | +3.24 pt [+1.09, +5.82] | -0.11 pt [-2.46, +1.74] | +4.17 pt [+2.31, +6.00] | 0.44 [0.17, 0.83] |
| kind = daily | 374 | 33 | +7.02 pt [+3.55, +11.28] | +5.73 pt [+0.81, +10.91] | -2.54 pt [-6.79, +1.22] | +3.83 pt [+0.93, +7.29] | 0.82 [0.15, 1.70] |
| kind = weekly | 135 | 4 | +9.24 pt [+4.75, +12.33] | +2.18 pt [+0.85, +5.31] | +1.91 pt [-3.27, +3.28] | +5.14 pt [+0.47, +9.27] | 0.24 [0.07, 0.80] |
| kind = monthly | 614 | 19 | +8.03 pt [+5.23, +10.73] | +3.05 pt [+1.15, +4.82] | +0.04 pt [-0.82, +1.10] | +4.94 pt [+2.84, +7.10] | 0.38 [0.18, 0.56] |

Equal weight per closure (primary decomposition): G +7.39 pt [+5.24, +9.67]; R +5.60 pt [+2.09, +9.37]; F -1.80 pt [-4.94, +0.94]; L +3.60 pt [+1.82, +5.55].

Forecast variants (diff = PM minus options, positive = options better):

| pair | events | closures | Brier PM vs options, diff [CI] | log score PM vs options, diff [CI] |
|---|---|---|---|---|
| open pair (primary) | 1535 | 44 | 0.1464 vs 0.1196, diff +0.0267 [+0.0189, +0.0349] | 0.4548 vs 0.3798, diff +0.0749 [+0.0532, +0.0980] |
| close pair | 1535 | 44 | 0.1639 vs 0.1511, diff +0.0129 [+0.0046, +0.0218] | 0.5019 vs 0.4720, diff +0.0300 [+0.0084, +0.0515] |
| same instant (PM 09:45 vs options 09:45) | 1535 | 44 | 0.1317 vs 0.1196, diff +0.0121 [+0.0051, +0.0195] | 0.4105 vs 0.3798, diff +0.0307 [+0.0114, +0.0500] |
| end of day (PM 16:00 vs options 15:55) | 1123 | 43 | 0.1050 vs 0.0985, diff +0.0065 [-0.0007, +0.0139] | 0.3302 vs 0.3148, diff +0.0154 [-0.0052, +0.0367] |
| Polymarket trade print inside the closure, open pair | 1175 | 44 | 0.1430 vs 0.1141, diff +0.0289 [+0.0201, +0.0377] | 0.4474 vs 0.3654, diff +0.0819 [+0.0569, +0.1078] |
| kind = daily, open pair | 730 | 33 | 0.1284 vs 0.0966, diff +0.0317 [+0.0196, +0.0443] | 0.4057 vs 0.3152, diff +0.0905 [+0.0573, +0.1251] |
| kind = weekly, open pair | 173 | 5 | 0.1471 vs 0.1175, diff +0.0296 [+0.0067, +0.0502] | 0.4520 vs 0.3740, diff +0.0780 [+0.0293, +0.1270] |
| kind = monthly, open pair | 632 | 20 | 0.1670 vs 0.1468, diff +0.0201 [+0.0074, +0.0331] | 0.5121 vs 0.4561, diff +0.0561 [+0.0254, +0.0895] |

Equal weight per closure, open pair: Brier diff +0.0295 [+0.0210, +0.0384]; log diff +0.0825 [+0.0584, +0.1076].

Change in the options' forecasting edge over the closure (open-pair diff minus close-pair diff, n=1535): Brier +0.0139 [+0.0032, +0.0260]; log +0.0449 [+0.0171, +0.0777].

Does the PM add anything beyond the options? Linear probability of YES on both prices (n=1535): PM at 09:30 coefficient +0.02 [-0.15, +0.17], options at 09:45 +1.04 [+0.88, +1.20]. The PM is not shown to add information beyond the options.

## Caveats

- Re-analysis of rows whose R3 summary was read before this method was written; the signs of the PM give-back and the option follow-through were known. Not confirmatory.
- Overshoot and noise are not separated: Polymarket per-minute prices can be thin-book midpoints, and R3 kept only PM moves of 3 points or more, so part of any give-back is mechanical regression to the mean. 'Gives back' means only that the PM moved back toward its Friday price. The trade-print subset is the partial check.
- The only later horizon is the end of the reopening day; weekly and month-end contracts resolve later.
- Options are measured at 09:45, the PM at 09:30; the same-instant rows handle that.
- Outcomes are shared within a closure and underlying, so the effective sample is nearer the number of closures; the bootstrap resamples closures.
- The call spread approximates the digital and settles on a slightly different print than the PM.
