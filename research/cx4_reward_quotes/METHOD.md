# Rewarded, externally hedged liquidity provision

Written 2026-10-04 before reading this campaign's test data. Existing S12's
reported adverse selection is known. This study will not tune its quoting rule
on those outcomes, consume the protected recorder window, or claim that a
synthetic replay received exchange rewards.

## Hypothesis

Earned rewards and rebates can exceed losses from adverse selection, hedging,
financing and execution. Counterparty compensation is the venue's incentive
budget and the spread paid by takers; both are finite and competitive.

## Frozen economic rule

Net P&L = trading P&L + earned liquidity rewards + earned maker rebates
          - external hedge costs - financing.

Rewards are recorded only when historical eligibility settings, relative share
of competing liquidity, and actual allocated/paid rewards are available. Missing
rewards do not become assumed profit. Maker rebates require actual maker fills;
posting an order does not imply a rebate. Ended incentive programs are excluded.

Two-sided inventory has a funded capital budget. Cross-venue hedges require exact
contract terms, observed quotes/depth/timestamps and modeled unhedged fill losses.
Public taker prints alone do not identify queue priority or our maker fills.

## Data feasibility and diagnostic

After the method freeze, inspect local schemas and existing S12 trades to
calculate the break-even dollars of incentives needed to offset observed losses.
This is a sensitivity calculation using known research, not a new strategy
backtest. Inspect available local reward/quote/payment records without fetching
credentials or consuming sealed/protected studies.

If the full causal dataset exists, use one fixed qualifying two-sided quote rule,
market minimum order sizes and a 1% per-market funded capital limit, with exact
event-contract hedging. Reserve the latest 20% of complete calendar days.
Evaluate at 1x and 2x execution/hedge costs, using daily marked returns and the
campaign acceptance gates. If reward settings, competing scores, fills or hedge
quotes are absent, report not-testable; do not fabricate a Sharpe.

No API calls or historical reward reconstruction from today's settings. No live
orders. Diagnostic thresholds and exclusions are fixed before examining inputs.

## Outputs

Dataset audit, break-even sensitivity, reusable reward-P&L accounting and tests,
summary, metrics and run log. Empty trade/equity files identify absence of a
valid historical experiment. Every fixture is labeled synthetic.
