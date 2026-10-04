"""Build the evidence decision and a paper figure from audited source tables.

Run from research/: .venv/bin/python -m cx5_strategy_selection.build_report
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .compare import OUT


def main() -> None:
    source = OUT / "OPTION_MICRO_METRICS.csv"
    rows = list(csv.DictReader(source.open()))

    def row(cut: str, seg: str = "ALL", fee: str = "1", study: str = "S18") -> dict:
        matches = [r for r in rows if r["study"] == study and r["cut"] == cut
                   and r["segment"] == seg and r["fee_multiplier"] == fee]
        if len(matches) != 1:
            raise ValueError((study, cut, seg, fee, len(matches)))
        return matches[0]

    def n(r: dict, k: str, decimals: int = 2) -> str:
        return f"{float(r[k]):.{decimals}f}" if r.get(k) else "unavailable"

    cut = "ACTUAL_VWAP_50_TO_75"
    all1, all2, ins, oos = row(cut), row(cut, fee="2"), row(cut, "IS"), row(cut, "OOS")
    index = row("SP500_MIXED_ROOT_HORIZON")
    spy = row("SPY_MONTHLY_TOUCH_PRIMARY_CANDIDATE")
    spx = row("SPX_MONTHLY_TOUCH_COMPARATOR")
    broad_oos = row("ALL_TRADED_SELLERS", "OOS")
    snapshot = json.loads((OUT / "comparison_snapshot.json").read_text())

    def headline(study: str, segment: str = "OOS", cost: str = "1.0",
                 field: str = "sharpe") -> str:
        found = [r["source_row"] for r in snapshot["headline_rows"]
                 if r["study"] == study and r["source_row"]["segment"] == segment
                 and r["source_row"].get("cost_mult", cost) == cost]
        if len(found) != 1:
            raise ValueError((study, segment, cost, len(found)))
        return f"{float(found[0][field]):.2f}"

    question_share = 100 * snapshot["s17_concentration"][0]["largest_question_share"]
    s11_current = next(r["source_row"] for r in snapshot["headline_rows"]
                       if r["study"] == "S11 logical violations"
                       and r["source_row"]["cost_mult"] == "1.0")
    s11_supported = {r["segment"]: r for r in snapshot["s11_print_supported_rows"]}

    text = f"""# Decision: focus the paper on S18's medium-priced barrier tickets

**Choose the first-weekend, 50–75% traded-YES-price cohort as the strongest
current positive evidence.** It supports a focused empirical paper about a
barrier-ticket premium. It does not yet prove an executable daily Sharpe or a
hedged alpha strategy. Selection was made after inspecting existing results.

The cohort contains {all1['markets']} markets in {all1['events']} events, with
actual taker-sale prices. Its mean fee-net seller return is
**{n(all1,'mean_pnl_points')} cents per $1 contract**, with the original
event-bootstrap 95% interval [{n(all1,'event_cluster_ci_low')},
{n(all1,'event_cluster_ci_high')}]. Reconstructed annualized settlement-month
Sharpe is **{n(all1,'settlement_month_sharpe')}**; with fees doubled it is
{n(all2,'settlement_month_sharpe')}. This is the most useful paper evidence in
the compared results because the return calculation uses actual transactions,
not an assumed spread around a historical midpoint.

## What this evidence establishes

The market-weighted average YES sale price was
{100*float(all1['mean_traded_price']):.2f}%, while
{100*float(all1['resolved_yes_share']):.2f}% resolved YES. Buying NO at the
corresponding observed price and holding through the result has P&L per contract
`p_YES - outcome_YES - fee`. This is an observational cohort of other traders'
transactions. Its 48-hour VWAP is known after the weekend, not at entry.

| Reused chronological segment | Markets / events | Fee-net return, cents per contract | Event-bootstrap 95% interval | Settlement-month Sharpe |
|---|---:|---:|---:|---:|
| Earlier events | {ins['markets']} / {ins['events']} | {n(ins,'mean_pnl_points')} | [{n(ins,'event_cluster_ci_low')}, {n(ins,'event_cluster_ci_high')}] | {n(ins,'settlement_month_sharpe')} |
| Recent events | {oos['markets']} / {oos['events']} | {n(oos,'mean_pnl_points')} | [{n(oos,'event_cluster_ci_low')}, {n(oos,'event_cluster_ci_high')}] | {n(oos,'settlement_month_sharpe')} |
| Whole cohort | {all1['markets']} / {all1['events']} | {n(all1,'mean_pnl_points')} | [{n(all1,'event_cluster_ci_low')}, {n(all1,'event_cluster_ci_high')}] | {n(all1,'settlement_month_sharpe')} |
| Whole cohort, doubled fees | {all2['markets']} / {all2['events']} | {n(all2,'mean_pnl_points')} | [{n(all2,'event_cluster_ci_low')}, {n(all2,'event_cluster_ci_high')}] | {n(all2,'settlement_month_sharpe')} |

The capped-size reconstruction earns ${n(all1,'capped_book_pnl')} with up to 100
contracts per market, bounded by observed printed size. Peak locked principal is
${n(all1,'peak_locked_cash')}; the fee-and-payoff cash diagnostic requires
${n(all1,'minimum_initial_cash_with_recycling')} initial cash under its assumed
release clocks. Maximum settlement-month loss from peak is
{100*float(all1['drawdown_in_units_of_fixed_peak_cash']):.2f}% of the fixed
principal base, not a complete daily drawdown. Removing the largest winning
event leaves ${n(all1,'net_pnl_ex_best_event')} net P&L. A disclosed hypothetical
4% annual carry charge on principal-days leaves
${n(all1,'net_cash_after_assumed_4pct_opportunity_cost')}.

**Limits:** the recent interval includes zero; the new selected cohort has only
{oos['events']} recent events; fees doubled is not doubled total execution cost;
the selected price bucket was inspected among other cuts; and no adjustments for
multiple selection or shared month/asset risk justify a new significance claim.
Results are unhedged. Positive insurance premium is not sufficient evidence of
mispricing relative to risk or options. The original S18 primary and broad
seller criterion still fail. Broad recent sellers earn
{n(broad_oos,'mean_pnl_points')} cents per contract. S19's crypto replication
does not establish a broad seller premium.

![Observed seller returns with uncertainty](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/barrier_premium.png)

## Why a reported Sharpe of seven is not the selection rule

| Candidate | Attractive reported number | Evidence that controls the decision |
|---|---:|---|
| S1 cross-venue twins | OOS {headline('S1 cross-venue twins',field='sharpe_mid')}; supported-subset modeled {headline('S1 cross-venue twins',field='sharpe_mid_verified')} | Only 15/99 entries have nearby PM print support; no simultaneous depth; current Anthropic IPO rules have different predicates |
| S6 Monday fade | OOS {headline('S6 Monday options anchor')} | Only one recent entry has print support; full supported-cohort interval includes zero |
| S11 bundles | Updated OOS {headline('S11 logical violations')}; print-supported {float(s11_supported['OOS']['sharpe']):.2f} | {s11_current['verified']}/{s11_current['trades']} entries have print support in the updated row; later-same-day entry ranking and entry-date P&L attribution remain |
| S17 continuation variant | OOS {headline('S17 continuation variant',cost='1')} at real stock NBBO | Earlier events lose; {question_share:.0f}% of recent P&L is one crypto-legislation question |
| S19 crypto sellers | OOS {headline('S19 crypto sellers')} | Only five result months; full-period seller Sharpe {headline('S19 crypto sellers',segment='ALL')} and interval includes zero |
| S18 selected traded-price cohort | ALL {n(all1,'settlement_month_sharpe')} | Strongest positive print-based cohort; selection and causal execution remain to be confirmed |

These numbers use daily, closure-level and monthly conventions. They are not an
apples-to-apples ranking of funded daily portfolios. See the three audits and
the immutable source rows/hashes in comparison_snapshot.json.
The S11 audit separates an earlier independently reconstructed 4.07 OOS Sharpe
from the updated {headline('S11 logical violations')} source generation; their counts must not be combined.
The updated print-supported cohort is positive: {s11_supported['ALL']['trades']}
entries overall, modeled Sharpe {float(s11_supported['ALL']['sharpe']):.2f};
{s11_supported['OOS']['trades']} recent entries, modeled Sharpe
{float(s11_supported['OOS']['sharpe']):.2f}. This is promising repair-and-confirm
research, particularly cumulative deadline ladders. Nearby prints do not prove
simultaneous multi-leg fills, and the causal selection/accounting issues still apply.

## Micro-market scope

Primary evidence is the **newly observed first-weekend barrier-ticket segment**
with traded YES VWAP in [0.50, 0.75), across the existing non-crypto S18 universe.
It includes commodity, stock and S&P markets. The price range is a cohort
definition in existing evidence; a future entry must use a causal executable
price instead of future VWAP. Do not describe this broad segment as SPY alone.

Use **monthly SPY high/low barrier ladders** as the first prospective engineering
pilot: a named liquid hedge instrument, explicit numeric levels, a defined
regular-session window and closely related strikes. Keep SPX index tickets and
commodity tickets in separately identified sleeves. This choice is motivated
by verifiable mechanics and hedge measurement; it is not the highest historical
family Sharpe or an independently successful pilot.

The mixed S&P result is {n(index,'settlement_month_sharpe')} on
{index['markets']} markets/{index['events']} events, combining SPY monthly,
SPY weekly and SPX monthly tickets. SPY monthly alone is
{n(spy,'settlement_month_sharpe')} on {spy['markets']} markets/{spy['events']}
events, interval [{n(spy,'event_cluster_ci_low')},
{n(spy,'event_cluster_ci_high')}]. SPX monthly is
{n(spx,'settlement_month_sharpe')} on {spx['markets']} markets/{spx['events']}
events with no recent observations. Neither is a confirmed Sharpe-three strategy.

Current representative SPY rules use Pyth final one-minute HIGH/LOW candles,
regular hours, exact source prices, corporate-action adjustment and an outage
fallback. The sampled SPX contract uses Yahoo Finance one-minute index candles
over a different starting window. They need separate oracle, instrument and
payoff identities. [Rule examples](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/sp500_contract_examples.json)
are current metadata, not historical version proof.

## The paper and the C++ contribution

Suggested title: **A barrier-ticket premium at traded prices: evidence and
execution limits in prediction micro markets**.

Defensible present claim: a disclosed historical cohort of first-weekend taker
sales in the 50–75% YES-price bucket earned a positive fee-net settlement
premium. Its capped transaction-cohort monthly Sharpe is approximately 2.17.
The selected recent subgroup's uncertainty includes zero. This is evidence for
a systematic trading hypothesis, not proof of executable returns or hedged alpha.

AI extracts source, payoff, threshold, horizon, session and exceptional clauses
into a versioned contract manifest and proposes models. C++ consumes direct
token books and source ticks, evaluates frozen rules, maintains barrier state,
enforces event-level loss/cash limits and records order/fill/unwind timings.
Option hedges need a path-dependent barrier model plus source/basis-risk
measurement. A European closing-price digital or generic vertical spread does
not replicate a first-passage payoff. Local computation speed and net execution
returns must be measured separately.

The [prospective protocol](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/PROTOCOL.md)
specifies the confirmation evidence. No new collector, live trading, protected
forward analysis or modifications to the original studies were performed.

## Reproduce and inspect

- [S6/S18/S19 audit](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/S6_S18_S19_AUDIT.md)
- [S1 audit](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/S1_AUDIT.md)
- [S11/S10/S16 audit](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/S11_S10_S16_AUDIT.md)
- OPTION_MICRO_METRICS.csv reports all disclosed cuts, fee levels and segments.
- OPTION_MICRO_SOURCE_HASHES.csv identifies the calculations and input tables.

From research/:

```sh
.venv/bin/python -m cx5_strategy_selection.compare
.venv/bin/python -m cx5_strategy_selection.option_micro_audit
.venv/bin/python -m cx5_strategy_selection.build_report
```

Reproduction requires source tables matching their recorded hashes. Other study
owners may be updating their outputs concurrently. This report is a share-with-
caveats research decision, not a validated executable-performance claim.
"""

    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "cx5_mpl"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["50–75% cohort\nearlier events", "50–75% cohort\nrecent events", "50–75% cohort\nwhole period", "All S18 sellers\nrecent events", "Crypto control\nfirst 48h of listing\nwhole period"]
    plotted = [ins, oos, all1, broad_oos, row("ALL_TRADED_SELLERS", study="S19")]
    means = [float(r["mean_pnl_points"]) for r in plotted]
    low = [means[i] - float(r["event_cluster_ci_low"]) for i, r in enumerate(plotted)]
    high = [float(r["event_cluster_ci_high"]) - means[i] for i, r in enumerate(plotted)]
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    ax.errorbar(range(5), means, yerr=[low, high], fmt="o", capsize=6,
                color="#234e70", markersize=7, linewidth=1.5)
    ax.axhline(0, color="#666666", linewidth=1)
    ax.set_xticks(range(5), labels)
    ax.set_ylabel("Fee-net settlement P&L, cents per $1 contract")
    ax.set_title("Observed seller returns: first-weekend cohort and crypto control", loc="left")
    ax.grid(axis="y", alpha=0.2)
    for i, r in enumerate(plotted):
        ax.annotate(f"{r['markets']} markets / {r['events']} events", (i, means[i]),
                    xytext=(0, 10), textcoords="offset points", ha="center", fontsize=8)
    fig.text(0.06, 0.04, "95% event-bootstrap intervals; historical transaction cohorts. Bucket selection is exploratory; no causal fills or hedges assumed.", fontsize=8)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(OUT / "barrier_premium.png", dpi=170)
    plt.close(fig)
    (OUT / "SUMMARY.md").write_text(text)
    (OUT / "decision_meta.json").write_text(json.dumps({
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_selection": cut, "engineering_pilot": "SPY monthly barriers",
        "fresh_validation": False, "assessment": "Share with caveats",
        "micro_metrics_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "actual_funded_daily_sharpe_verified": False,
        "market_metadata_requests": 11,
    }, indent=2) + "\n")
    print(json.dumps({"selected": cut, "monthly_cohort_sharpe": float(all1['settlement_month_sharpe']),
                      "fresh_validation": False}))


if __name__ == "__main__":
    main()
