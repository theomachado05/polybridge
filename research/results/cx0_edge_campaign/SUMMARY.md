# Edge campaign: no validated positive thesis yet

Three subagents completed independent investigations; root completed the reward
diagnostic and portfolio review. All five proposed ideas were assessed. The option
strategy received a full historical quote backtest; the remaining four reached
documented data or contract feasibility limits. They were not replaced by invented
performance results.

| Hypothesis | Evidence | Conclusion |
|---|---|---|
| Cashsecured SPY option insurance | 55 closures; recent 10 entries/51 sessions; net Sharpe -1.43, return -0.50%; 2x return -0.60% | Recent returns fail; too few independent observations for validation |
| Event-aware insurance sizing | Net recent Sharpe -1.22, return -0.34%; advantage over matched static exposure includes zero | No demonstrated incremental prediction-market benefit |
| Merger failure hedge | 6 acquisition questions; all announcement-based; 0 eligible completion hedges | Contract mismatch; no historical performance test |
| Contractual baskets | Historical PM mids without direct token depth and full contractual proof | No executable historical Sharpe identified |
| Source-publication carry | No causal publication/first-observed archive or redemption cash flows | No historical entry/financing test identified |
| Rewarded, hedged liquidity | No historical allocation/competing scores/fills ledger; prior S12 loss needs $141.26 incentive income before external hedge costs | Reward-inclusive returns unidentified |

The screening choices were frozen before candidate prices: net recent Sharpe at
least 1.5, positive doubled-cost returns, a positive clustered/block confidence
bound, at least 30 independent recent entry dates and 60 daily return observations,
credible fills and funded portfolio accounting. Passing on reused history would
still require independent confirmation. This campaign does not claim future
profits or infer that untestable ideas have no opportunities.

## Why the preliminary option result changed

The offline cache initially supplied only 5 recent
trades and suggested Sharpe 1.42, return
+0.29%. An explicitly recorded data-only amendment completed
the missing quotes under the same trading rule, split and thresholds. Twenty-one
successful Massive requests retrieved 345,096 bytes, with one additional blocked
zero-byte attempt. All 55 closures now have quotes. The initial result and every
correction remain archived; no favorable subset became the headline.

The completed recent mean is -4.99 basis points
of full strike cash per closure, interval
[-20.77, +11.07]. Gross returns already
lose money, before crossing costs. The full-period Sharpe of
2.07 and return +5.25% therefore cannot be
advertised as proof that the strategy generalizes.

A post-run fixed half-SPY proxy explains most of the positive full-period put
mean. The recent net residual is -0.52
basis points, interval [-3.21,
+2.00]. This proxy uses stock bars and is not
an executable delta hedge or a newly optimized candidate. It does not establish
separate insurance alpha.

The independent reviewer identified and repaired same-session morning-exit and
afternoon-entry cash compounding and additive turnover. The financial P&L effect
was tiny; it did not cause the recent loss. Two holiday close clocks and CSV
quote/decision timestamp labels were corrected with dated amendments. Historical
point-in-time contract-chain selection, early assignment and exact fractional-lot
implementation remain disclosed limitations.

## What the C++ engine can claim

The existing cross-venue family emits one order and sees only the other venue's
midpoint. It does not yet implement a funded, synchronized two-leg basket.
Its latency benchmark measures local computation, rather than execution profit.
The appropriate next infrastructure is full rule versions, direct multi-leg books,
fee versions, source-observation clocks, fill/unwind records and collateral release.
AI can propose/check relationships; deterministic execution must enforce their
payoff and risk constraints. Fast code is useful after executable economics are
established.

## Artifacts and reproduction

- [Option backtest](/Users/theomachado/gatorquant/research/results/cx1_option_insurance/SUMMARY.md) and [equity curve](/Users/theomachado/gatorquant/research/results/cx1_option_insurance/equity_curve.png).
- [Independent cash/causality review](/Users/theomachado/gatorquant/research/results/cx2_merger_bridge/AUDIT_CX1.md).
- [Merger contract audit](/Users/theomachado/gatorquant/research/results/cx2_merger_bridge/SUMMARY.md).
- [Basket/carry audit](/Users/theomachado/gatorquant/research/results/cx3_payoff_carry/SUMMARY.md).
- [Reward economics](/Users/theomachado/gatorquant/research/results/cx4_reward_quotes/SUMMARY.md).
- comparison.csv, independent_nav_audit.csv and validation.json accompany this report.

From research/:

```sh
.venv/bin/python -m cx1_option_insurance.run
.venv/bin/python -m cx1_option_insurance.report
.venv/bin/python -m cx2_merger_bridge.run
.venv/bin/python -m cx3_payoff_carry.run
.venv/bin/python -m cx4_reward_quotes.run
.venv/bin/python -m cx0_edge_campaign.validate_option
.venv/bin/python -m cx0_edge_campaign.build_report
.venv/bin/python -m pytest cx0_edge_campaign/tests cx1_option_insurance/tests cx2_merger_bridge/tests cx3_payoff_carry/tests cx4_reward_quotes/tests -q
```

The latest combined check passes 96 tests; the independent NAV check reproduces
18 curves. Synthetic fixtures validate payoff/execution/accounting behavior,
not market returns. No live trades, sealed 8-K data, protected recorder window or
other agents' files were changed. Required market-data caches remain local and
ignored by Git; reproduction requires those source caches.
