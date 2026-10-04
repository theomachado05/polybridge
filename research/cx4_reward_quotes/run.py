"""Run frozen reward feasibility and cash break-even diagnostic on prior S12."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from .accounting import minimum_pool, required_incentive

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
OUT = RESEARCH / "results" / HERE.name
SOURCE = RESEARCH / "results" / "s12_resting_orders" / "trades.csv"


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    trades = pd.read_csv(SOURCE)
    primary = trades[(trades["sample"] == "S9") & (trades["variant"] == "R0")]
    primary = pd.concat([primary, primary.assign(segment="ALL")], ignore_index=True)
    rows, pools = [], []
    for (cost, segment), g in primary.groupby(["cost_mult", "segment"]):
        filled = g[g["filled"].astype(str).str.lower().isin(["true", "1"])]
        pnl = float(filled["pnl"].sum())
        quantity = float((100 * filled["fill_frac"]).sum())
        need = required_incentive(pnl)
        rows.append({"sample": "known_S12_diagnostic", "variant": "R0",
                     "cost_mult": cost, "segment": segment,
                     "orders": len(g), "fills": len(filled),
                     "independent_filled_groups": filled["group"].nunique(),
                     "filled_contracts": quantity, "prior_trading_pnl_dollars": pnl,
                     "incentive_needed_dollars": need,
                     "needed_cents_per_filled_contract": 100 * need / quantity if quantity else None,
                     "actual_reward_income": None, "actual_rebate_income": None,
                     "net_rewarded_pnl": None, "sharpe": None,
                     "verdict": "NOT_TESTABLE", "fresh_backtest": False})
        for share in (0.01, 0.05, 0.10):
            pools.append({"cost_mult": cost, "segment": segment,
                          "hypothetical_share": share,
                          "minimum_total_pool_dollars": minimum_pool(need, share),
                          "observed_pool": False})
    pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
    pd.DataFrame(pools).to_csv(OUT / "break_even_sensitivity.csv", index=False)
    pd.DataFrame(columns=["entry", "exit", "quantity", "net_pnl", "earned_reward"]).to_csv(OUT / "trades.csv", index=False)
    pd.DataFrame(columns=["date", "marked_nav", "daily_return"]).to_csv(OUT / "equity.csv", index=False)
    audit = pd.DataFrame([
        {"input": "two-sided historical causal quotes and queue", "available": False,
         "reason": "S12 uses taker prints and a queue allowance, not actual maker fills"},
        {"input": "historical market reward eligibility and allocations", "available": False,
         "reason": "No local reward-setting time series identified"},
        {"input": "competing qualifying liquidity scores", "available": False,
         "reason": "Relative share cannot be reconstructed from midpoint or print history"},
        {"input": "historical earned reward and rebate records", "available": False,
         "reason": "No historical allocation/payment ledger identified"},
        {"input": "synchronized exact-contract external hedge fills", "available": False,
         "reason": "Existing studies do not establish simultaneous hedged maker execution"},
        {"input": "previous S12 model trades", "available": True,
         "reason": "Usable only for a known-result break-even diagnostic"},
    ])
    audit.to_csv(OUT / "data_audit.csv", index=False)
    oos = next(r for r in rows if r["cost_mult"] == 1 and r["segment"] == "OOS")
    stress = next(r for r in rows if r["cost_mult"] == 2 and r["segment"] == "OOS")
    summary = f"""# Rewarded liquidity: NOT TESTABLE with current historical inputs

No earned-income history supports an incentive-inclusive Sharpe or equity curve.
This is a diagnostic using S12's already known primary orders, not a new strategy.

At 1x costs, S12's recent segment loses ${-oos['prior_trading_pnl_dollars']:.2f}
on {oos['fills']} modeled fills across {oos['independent_filled_groups']} independent
weekend groups. Offsetting that loss alone requires ${oos['incentive_needed_dollars']:.2f}
in earned income, or {oos['needed_cents_per_filled_contract']:.2f} cents per filled contract.
External hedging and financing would raise the requirement. At 2x costs the
same frozen source model requires ${stress['incentive_needed_dollars']:.2f}, with
{stress['fills']} modeled fills. The stress model changes which orders fill;
it is not simply twice the cost on an identical set of fills.

A hypothetical 1% share would require a total pool of
${minimum_pool(oos['incentive_needed_dollars'], .01):,.2f} over the tested interval.
No such pool or share has been measured. Reward eligibility, competitors' scores,
maker fills, actual allocations, and exact-contract hedge execution remain missing.
Today's settings cannot be applied retrospectively to fabricate income.

Numbers: metrics.csv and break_even_sensitivity.csv. Empty trades/equity files
mean no valid new trading experiment was conducted. No performance chart is
created from fabricated cash flows. Financial accounting tests use synthetic
fixtures; they validate arithmetic, not market profitability.

Mechanics: [liquidity rewards](https://docs.polymarket.com/programs/liquidity-rewards)
are allocated by qualifying relative quote score;
[maker rebates](https://docs.polymarket.com/programs/maker-rebates) require fills.
The special August crypto reward allocation is explicitly ended.

Next evidence needed: timestamped historical eligibility, qualifying two-sided
depth and competing scores, actual maker fill/payment records, and synchronized
hedge quotes. Start with a frozen prospective paper policy; no live orders are
part of this research.
"""
    (OUT / "SUMMARY.md").write_text(summary)
    (OUT / "capacity.md").write_text("# Capacity\n\nUnknown. Public taker prints do not establish our maker queue position, reward share, or simultaneous external hedge depth. No dollar capacity is claimed.\n")
    meta = {"run_utc": datetime.now(timezone.utc).isoformat(),
            "freeze_commit": "24485b8", "source": str(SOURCE),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "network_requests": 0, "outcome": "NOT_TESTABLE",
            "synthetic_fixtures_are_evidence": False}
    (OUT / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (OUT / "RUN_LOG.md").write_text("# Run log\n\n" + json.dumps(meta, indent=2) + "\n\nRun from research/: `.venv/bin/python -m cx4_reward_quotes.run`.\nTests: `.venv/bin/python -m pytest cx4_reward_quotes/tests -q`.\n")
    print(json.dumps({"verdict": "NOT_TESTABLE", "oos_incentive_required": oos["incentive_needed_dollars"],
                      "oos_2x_incentive_required": stress["incentive_needed_dollars"]}))


if __name__ == "__main__":
    run()
