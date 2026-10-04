# CX1 option insurance: Complete fixed-rule historical diagnostic; underpowered and not confirmed

Selling fully cashsecured ATM SPY puts over market closures returned -0.501% in the recent period at 1x costs and -0.595% at 2x. The 1x OOS daily Sharpe was -1.430. There were only 10 independent OOS entry dates and 51 daily observations, below the frozen 30/60 minimum. Its mean net closure return was -4.99 bp, with a 95% four-closure block interval [-20.77 bp, +11.07 bp]. This cannot pass the preliminary screen or establish an insurance or prediction-market edge.

The only event sizing variant returned -0.338% OOS at 1x, with Sharpe -1.224. Its exposure control returned -0.334% with Sharpe -1.430. The paired gate-minus-static mean was -0.04 bp (95% interval [-4.49 bp, +4.70 bp]). The historical evidence does not establish that the event gate improves returns.

| Book | Costs | Segment | Entries | Daily Sharpe | Total return | Max drawdown | Worst month |
|---|---:|---|---:|---:|---:|---:|---:|
| V0 | 1x | IS | 45 | 2.684 | +5.779% | -1.634% | -0.437% |
| V0 | 1x | OOS | 10 | -1.430 | -0.501% | -1.084% | -0.557% |
| V0 | 1x | ALL | 55 | 2.068 | +5.249% | -1.634% | -0.557% |
| V0 | 2x | IS | 45 | 2.262 | +4.991% | -1.822% | -0.499% |
| V0 | 2x | OOS | 10 | -1.671 | -0.595% | -1.135% | -0.583% |
| V0 | 2x | ALL | 55 | 1.683 | +4.366% | -1.822% | -0.583% |
| V1 | 1x | IS | 45 | 2.815 | +3.846% | -0.818% | -0.130% |
| V1 | 1x | OOS | 10 | -1.224 | -0.338% | -0.875% | -0.375% |
| V1 | 1x | ALL | 55 | 2.114 | +3.495% | -0.875% | -0.375% |
| V1 | 2x | IS | 45 | 2.347 | +3.316% | -0.913% | -0.166% |
| V1 | 2x | OOS | 10 | -1.482 | -0.420% | -0.918% | -0.391% |
| V1 | 2x | ALL | 55 | 1.692 | +2.883% | -0.918% | -0.391% |
| STATIC_IS_MATCH | 1x | IS | 45 | 2.684 | +3.823% | -1.091% | -0.290% |
| STATIC_IS_MATCH | 1x | OOS | 10 | -1.430 | -0.334% | -0.724% | -0.371% |
| STATIC_IS_MATCH | 1x | ALL | 55 | 2.068 | +3.476% | -1.091% | -0.371% |
| STATIC_IS_MATCH | 2x | IS | 45 | 2.262 | +3.306% | -1.217% | -0.332% |
| STATIC_IS_MATCH | 2x | OOS | 10 | -1.672 | -0.397% | -0.758% | -0.389% |
| STATIC_IS_MATCH | 2x | ALL | 55 | 1.683 | +2.896% | -1.217% | -0.389% |

The fixed window is 2025-10-01 to 2026-10-02; OOS starts 2026-07-23. The strategy planned 55 closures and executed 55. DATA_ONLY completion made 21 Massive requests, received 345,096 bytes, and preserved the same rules, chronological split and strike selection. All history is reused exploratory evidence. Untouched observations from 2026-10-05 onward remain reserved.

| Post-run directional-risk diagnostic | IS | OOS | All |
|---|---:|---:|---:|
| Mean full SPY closure return | +22.88 bp | -8.95 bp | +17.10 bp |
| Fixed half-SPY proxy | +11.44 bp | -4.47 bp | +8.55 bp |
| Mean gross put return | +14.21 bp | -4.05 bp | +10.89 bp |
| Gross put minus half-SPY | +2.77 bp | +0.42 bp | +2.34 bp |
| Net put minus half-SPY | +1.10 bp | -0.52 bp | +0.81 bp |
| Descriptive put beta to SPY | 0.512 | 0.473 | 0.510 |

The half-SPY comparison was requested after the first run and uses completed five-minute stock bars at the same frozen entry/exit clocks. It has no stock spread, commissions, interest or rebalance costs and is not an executable hedged strategy. It is a fixed equity-risk proxy, not another pass candidate. The descriptive beta is not used for sizing. A cashsecured put owns stock downside, and these results cannot be described as pure option premium harvesting.

| Net put minus fixed half-SPY proxy | Mean | 95% four-closure block interval |
|---|---:|---:|
| IS | +1.10 bp | [-1.70 bp, +3.87 bp] |
| OOS | -0.52 bp | [-3.21 bp, +2.00 bp] |
| ALL | +0.81 bp | [-1.47 bp, +3.17 bp] |

The net residual intervals include zero. The stock proxy explains most of the positive full-period put mean; a prediction-market gate advantage or separate premium return is not established.

| Event gate state | Planned IS | Planned OOS | Executed IS | Executed OOS |
|---|---:|---:|---:|---:|
| active event | 20 | 1 | 20 | 1 |
| observed quiet event state | 15 | 6 | 15 | 6 |
| unobserved event state | 10 | 3 | 10 | 3 |

Actual NBBO crossing plus the stated $0.65 per contract per side averaged 1.534 bp of strike cash and 2.172% of the entry mid premium per closure at 1x. 2x doubles both half-spreads and both commissions. Short fills are independently computed at bid/ask; they are not the negation of S7 long net returns.

Entry SIP quote age reached 5.548 seconds and exit age 1.797 seconds. NBBO-side execution is a historical fill assumption, not a certified live trade. Both displayed entry bid and exit ask sizes are recorded. Entry cash P&L is marked at the contemporaneous liquidating ask, with fixed contracts through exit. Daily account snapshots leave the last five minutes of the entry session unmarked; the account is cash after exit. The maximum compounded daily/event reconciliation error was 2.41e-16.

Every variant and both cost cases appear in metrics.csv. Subperiods and leave-best-closure-out results follow; no subset changes the trading rule.

| Book | Costs | Period | Entries | Return | Sharpe | Return without best closure |
|---|---:|---|---:|---:|---:|---:|
| V0 | 1x | OOS | 10 | -0.501% | -1.430 | -0.819% |
| V0 | 1x | IS_FIRST_HALF | 24 | +2.257% | 2.198 | +1.601% |
| V0 | 1x | IS_SECOND_HALF | 21 | +3.444% | 3.133 | +2.631% |
| V0 | 1x | OOS_FIRST_HALF | 5 | +0.294% | 2.015 | -0.027% |
| V0 | 1x | OOS_SECOND_HALF | 5 | -0.792% | -4.028 | -1.070% |
| V1 | 1x | OOS | 10 | -0.338% | -1.224 | -0.657% |
| V1 | 1x | IS_FIRST_HALF | 24 | +1.809% | 2.472 | +1.156% |
| V1 | 1x | IS_SECOND_HALF | 21 | +2.001% | 3.226 | +1.598% |
| V1 | 1x | OOS_FIRST_HALF | 5 | +0.274% | 1.889 | -0.046% |
| V1 | 1x | OOS_SECOND_HALF | 5 | -0.611% | -4.871 | -0.750% |
| V0 | 2x | OOS | 10 | -0.595% | -1.671 | -0.897% |
| V0 | 2x | IS_FIRST_HALF | 24 | +1.862% | 1.768 | +1.243% |
| V0 | 2x | IS_SECOND_HALF | 21 | +3.071% | 2.719 | +2.273% |
| V0 | 2x | OOS_FIRST_HALF | 5 | +0.239% | 1.577 | -0.065% |
| V0 | 2x | OOS_SECOND_HALF | 5 | -0.833% | -4.212 | -1.105% |
| V1 | 2x | OOS | 10 | -0.420% | -1.482 | -0.722% |
| V1 | 2x | IS_FIRST_HALF | 24 | +1.487% | 1.951 | +0.871% |
| V1 | 2x | IS_SECOND_HALF | 21 | +1.802% | 2.831 | +1.406% |
| V1 | 2x | OOS_FIRST_HALF | 5 | +0.223% | 1.473 | -0.082% |
| V1 | 2x | OOS_SECOND_HALF | 5 | -0.641% | -5.082 | -0.778% |

The initial archive retains the 48-trade offline result before seven missing dates were completed. The halfday calendar correction changes the two previously omitted holiday query times to 12:55. Output timestamp labels were corrected so scheduled decision clocks and earlier SIP quote clocks remain separate. Calendar/gate comparison to that archive is in RUN_LOG.md.

Capacity and fractional-contract limitations are in capacity.md. ATM cashsecured downside and possible early assignment remain economic risks; early assignment, dividend-related exercise and share-liquidation costs are not modeled. Reused option reference requests omitted an entry-date as_of parameter: actual entry NBBO proves selected-contract existence, but the precise nearest-expiry/nearest-strike chain at historical entry remains unverified. No sealed research/results/oos or 8-K outcome file was opened. Neither variant passes the frozen independent-observation minimum.
