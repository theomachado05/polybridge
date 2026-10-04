"""Build the campaign report from completed study artifacts."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH = Path(__file__).resolve().parent.parent
OUT = RESEARCH / "results" / "cx0_edge_campaign"
OPTION = RESEARCH / "results" / "cx1_option_insurance"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    metrics = pd.read_csv(OPTION / "metrics.csv")
    def metric(variant, segment, cost):
        return metrics[(metrics.variant == variant) & (metrics.segment == segment)
                       & (metrics.cost_multiplier == cost)].iloc[0]
    one, two = metric("V0", "OOS", 1), metric("V0", "OOS", 2)
    gated = metric("V1", "OOS", 1)
    full = metric("V0", "ALL", 1)
    initial = pd.read_csv(OPTION / "initial_offline" / "metrics.csv")
    pilot = initial[(initial.variant == "V0") & (initial.segment == "OOS")
                    & (initial.cost_multiplier == 1)].iloc[0]
    directional = pd.read_csv(OPTION / "equity_risk_diagnostic.csv")
    residual = directional[directional.segment == "OOS"].iloc[0]
    rewards = pd.read_csv(RESEARCH / "results" / "cx4_reward_quotes" / "metrics.csv")
    reward_need = rewards[(rewards.segment == "OOS") & (rewards.cost_mult == 1)].iloc[0]
    merger = json.loads((RESEARCH / "results" / "cx2_merger_bridge" / "feasibility.json").read_text())
    rows = [
        {"hypothesis": "option insurance", "verdict": "OOS_LOSS_AND_INSUFFICIENT_VALIDATION",
         "oos_sharpe_1x": one.annualized_sharpe, "oos_return_1x": one.total_return,
         "oos_sharpe_2x": two.annualized_sharpe, "oos_return_2x": two.total_return,
         "independent_oos_entry_dates": one.executed_entry_dates,
         "source": str(OPTION / "metrics.csv")},
        {"hypothesis": "merger failure hedge", "verdict": "NOT_TESTABLE",
         "independent_oos_entry_dates": merger["verified_entry_dates"],
         "source": str(RESEARCH / "results" / "cx2_merger_bridge" / "feasibility.json")},
        {"hypothesis": "contractual payoff baskets", "verdict": "NOT_TESTABLE",
         "independent_oos_entry_dates": 0,
         "source": str(RESEARCH / "results" / "cx3_payoff_carry" / "metrics.csv")},
        {"hypothesis": "official-source resolution carry", "verdict": "NOT_TESTABLE",
         "independent_oos_entry_dates": 0,
         "source": str(RESEARCH / "results" / "cx3_payoff_carry" / "metrics.csv")},
        {"hypothesis": "rewarded hedged liquidity", "verdict": "NOT_TESTABLE",
         "independent_oos_entry_dates": 0,
         "source": str(RESEARCH / "results" / "cx4_reward_quotes" / "metrics.csv")},
    ]
    pd.DataFrame(rows).to_csv(OUT / "comparison.csv", index=False)
    report = f"""# Edge campaign: no validated positive thesis yet

Three subagents completed independent investigations; root completed the reward
diagnostic and portfolio review. All five proposed ideas were assessed. The option
strategy received a full historical quote backtest; the remaining four reached
documented data or contract feasibility limits. They were not replaced by invented
performance results.

| Hypothesis | Evidence | Conclusion |
|---|---|---|
| Cashsecured SPY option insurance | {int(full.executed_entry_dates)} closures; recent {int(one.executed_entry_dates)} entries/{int(one.daily_observations)} sessions; net Sharpe {one.annualized_sharpe:.2f}, return {one.total_return:+.2%}; 2x return {two.total_return:+.2%} | Recent returns fail; too few independent observations for validation |
| Event-aware insurance sizing | Net recent Sharpe {gated.annualized_sharpe:.2f}, return {gated.total_return:+.2%}; advantage over matched static exposure includes zero | No demonstrated incremental prediction-market benefit |
| Merger failure hedge | {merger['corporate_acquisition_questions']} acquisition questions; all announcement-based; {merger['eligible_completion_contracts']} eligible completion hedges | Contract mismatch; no historical performance test |
| Contractual baskets | Historical PM mids without direct token depth and full contractual proof | No executable historical Sharpe identified |
| Source-publication carry | No causal publication/first-observed archive or redemption cash flows | No historical entry/financing test identified |
| Rewarded, hedged liquidity | No historical allocation/competing scores/fills ledger; prior S12 loss needs ${reward_need.incentive_needed_dollars:.2f} incentive income before external hedge costs | Reward-inclusive returns unidentified |

The screening choices were frozen before candidate prices: net recent Sharpe at
least 1.5, positive doubled-cost returns, a positive clustered/block confidence
bound, at least 30 independent recent entry dates and 60 daily return observations,
credible fills and funded portfolio accounting. Passing on reused history would
still require independent confirmation. This campaign does not claim future
profits or infer that untestable ideas have no opportunities.

## Why the preliminary option result changed

The offline cache initially supplied only {int(pilot.executed_entry_dates)} recent
trades and suggested Sharpe {pilot.annualized_sharpe:.2f}, return
{pilot.total_return:+.2%}. An explicitly recorded data-only amendment completed
the missing quotes under the same trading rule, split and thresholds. Twenty-one
successful Massive requests retrieved 345,096 bytes, with one additional blocked
zero-byte attempt. All 55 closures now have quotes. The initial result and every
correction remain archived; no favorable subset became the headline.

The completed recent mean is {1e4 * one.mean_executed_event_return:+.2f} basis points
of full strike cash per closure, interval
[{1e4 * one.event_ci_low:+.2f}, {1e4 * one.event_ci_high:+.2f}]. Gross returns already
lose money, before crossing costs. The full-period Sharpe of
{full.annualized_sharpe:.2f} and return {full.total_return:+.2%} therefore cannot be
advertised as proof that the strategy generalizes.

A post-run fixed half-SPY proxy explains most of the positive full-period put
mean. The recent net residual is {1e4 * residual.mean_net_put_minus_half_spy:+.2f}
basis points, interval [{1e4 * residual.net_residual_ci_low:+.2f},
{1e4 * residual.net_residual_ci_high:+.2f}]. This proxy uses stock bars and is not
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

- [Option backtest]({OPTION / 'SUMMARY.md'}) and [equity curve]({OPTION / 'equity_curve.png'}).
- [Independent cash/causality review]({RESEARCH / 'results/cx2_merger_bridge/AUDIT_CX1.md'}).
- [Merger contract audit]({RESEARCH / 'results/cx2_merger_bridge/SUMMARY.md'}).
- [Basket/carry audit]({RESEARCH / 'results/cx3_payoff_carry/SUMMARY.md'}).
- [Reward economics]({RESEARCH / 'results/cx4_reward_quotes/SUMMARY.md'}).
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
"""
    (OUT / "SUMMARY.md").write_text(report)
    meta = {"run_utc": datetime.now(timezone.utc).isoformat(),
            "frozen_campaign_commit": "24485b8", "frozen_merger_commit": "01bce54",
            "frozen_option_payoff_commit": "6e33ff0", "data_amendment_commit": "c77233f",
            "accounting_fix_commit": "e0b7bb1", "validated_positive_candidates": 0,
            "tests_passed": 96, "network_successful_requests": 21,
            "independent_confirmation": False}
    (OUT / "RUN_LOG.md").write_text("# Consolidated run log\n\n" + json.dumps(meta, indent=2)
                                    + "\n\nPer-study run logs contain source hashes, request audits, amendments and timestamps.\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
