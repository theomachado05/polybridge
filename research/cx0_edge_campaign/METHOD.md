# Independent edge campaign

Written 2026-10-04, before this campaign reads candidate test prices.

The user authorized parallel researchers to investigate merger hedges, contractual
baskets, option insurance, resolution carry, and rewarded liquidity provision.
The goal is a defensible systematic thesis. A positive result is not guaranteed.

## Prior information and data reuse

Existing studies S1 through S16 have exposed much of 2025-2026 history. S1 reports
15 print-supported out-of-sample entries with $47.50 modeled entry edge, but fails
its fill-verification criterion. S7's long-straddle losses mostly reflect costs.
S12's passive fills exhibit adverse selection. Related signal trades have failed
after costs. Every reused historical window is exploratory for this campaign;
chronological holdout is a diagnostic, not independent confirmation.

## Frozen acceptance rule

- Net annualized portfolio Sharpe at least 1.5 on the chronological holdout.
- Positive net holdout return at both 1x and 2x transaction costs.
- At least 30 independent holdout entry dates and 60 holdout return observations
  at the declared daily frequency. A smaller sample is insufficient, even if
  its point estimate is attractive.
- A 95% block/date bootstrap interval for net returns excludes zero.
- Use a funded portfolio, daily marked inventory, cash and collateral; include
  idle days, funding, commissions, bid/ask execution and open positions.
- Exact payout and deadline agreement for claims of contractual arbitrage.
- Demonstrated price/size support, causal timestamps, partial-fill risk and
  sustainable capacity. Mid-only fills or unknown reward allocations cannot
  support a confirmed execution claim.
- Report max drawdown, worst month, turnover, capital, data exclusions, all
  variants, concentration, tails and the source of each cost assumption.
- Investigate any Sharpe above 3 for accounting or timestamp errors.
- A candidate on previously inspected history remains exploratory after passing
  the numerical gates. Confirmed status also requires independently reserved
  observations under frozen rules.

Thresholds are research screening choices, not universal standards. No candidate
may be selected by dropping losing variants or changing rules after outcomes.

## Ownership and preservation

Researchers own only cx1_option_insurance, cx2_merger_bridge,
cx3_payoff_carry, and corresponding results directories. Root owns this campaign
and cx4_reward_quotes. Existing Claude studies, sealed 8-K results and the live
recorder are preserved. Git freezes are coordinated by root with exact pathspecs.
No live trading, credential changes or messages to external people are authorized.

## Deliverables

Per-study method, configuration, reproducible evaluator, meaningful tests, data
inventory, results and an explicit verdict: confirmed, exploratory-pass, fail,
insufficient, or not-testable. A consolidated table reports each hypothesis and
identifies the binding limitation. The research code is validated before a
successful thesis is handed to the C++ execution layer.
