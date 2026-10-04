# Decision: focus the paper on S18's medium-priced barrier tickets

**Choose the first-weekend, 50–75% traded-YES-price cohort as the strongest
current positive evidence.** It supports a focused empirical paper about a
barrier-ticket premium. It does not yet prove an executable daily Sharpe or a
hedged alpha strategy. Selection was made after inspecting existing results.

The cohort contains 88 markets in 51 events, with
actual taker-sale prices. Its mean fee-net seller return is
**13.30 cents per $1 contract**, with the original
event-bootstrap 95% interval [5.16,
21.33]. Reconstructed annualized settlement-month
Sharpe is **2.17**; with fees doubled it is
2.11. This is the most useful paper evidence in
the compared results because the return calculation uses actual transactions,
not an assumed spread around a historical midpoint.

## What this evidence establishes

The market-weighted average YES sale price was
61.64%, while
47.73% resolved YES. Buying NO at the
corresponding observed price and holding through the result has P&L per contract
`p_YES - outcome_YES - fee`. This is an observational cohort of other traders'
transactions. Its 48-hour VWAP is known after the weekend, not at entry.

| Reused chronological segment | Markets / events | Fee-net return, cents per contract | Event-bootstrap 95% interval | Settlement-month Sharpe |
|---|---:|---:|---:|---:|
| Earlier events | 72 / 40 | 11.35 | [2.58, 20.54] | 1.89 |
| Recent events | 16 / 11 | 22.10 | [-1.10, 39.05] | 2.51 |
| Whole cohort | 88 / 51 | 13.30 | [5.16, 21.33] | 2.17 |
| Whole cohort, doubled fees | 88 / 51 | 12.69 | [4.56, 20.72] | 2.11 |

The capped-size reconstruction earns $1134.43 with up to 100
contracts per market, bounded by observed printed size. Peak locked principal is
$741.63; the fee-and-payoff cash diagnostic requires
$675.26 initial cash under its assumed
release clocks. Maximum settlement-month loss from peak is
19.01% of the fixed
principal base, not a complete daily drawdown. Removing the largest winning
event leaves $991.59 net P&L. A disclosed hypothetical
4% annual carry charge on principal-days leaves
$1127.19.

**Limits:** the recent interval includes zero; the new selected cohort has only
11 recent events; fees doubled is not doubled total execution cost;
the selected price bucket was inspected among other cuts; and no adjustments for
multiple selection or shared month/asset risk justify a new significance claim.
Results are unhedged. Positive insurance premium is not sufficient evidence of
mispricing relative to risk or options. The original S18 primary and broad
seller criterion still fail. Broad recent sellers earn
-0.99 cents per contract. S19's crypto replication
does not establish a broad seller premium.

![Observed seller returns with uncertainty](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/barrier_premium.png)

## Why a reported Sharpe of seven is not the selection rule

| Candidate | Attractive reported number | Evidence that controls the decision |
|---|---:|---|
| S1 cross-venue twins | OOS 7.16; supported-subset modeled 4.53 | Only 15/99 entries have nearby PM print support; no simultaneous depth; current Anthropic IPO rules have different predicates |
| S6 Monday fade | OOS 7.70 | Only one recent entry has print support; full supported-cohort interval includes zero |
| S11 bundles | Updated OOS 7.38; print-supported 4.29 | 11/94 entries have print support in the updated row; later-same-day entry ranking and entry-date P&L attribution remain |
| S17 continuation variant | OOS 3.88 at real stock NBBO | Earlier events lose; 77% of recent P&L is one crypto-legislation question |
| S19 crypto sellers | OOS 2.21 | Only five result months; full-period seller Sharpe -0.09 and interval includes zero |
| S18 selected traded-price cohort | ALL 2.17 | Strongest positive print-based cohort; selection and causal execution remain to be confirmed |

These numbers use daily, closure-level and monthly conventions. They are not an
apples-to-apples ranking of funded daily portfolios. See the three audits and
the immutable source rows/hashes in comparison_snapshot.json.
The S11 audit separates an earlier independently reconstructed 4.07 OOS Sharpe
from the updated 7.38 source generation; their counts must not be combined.
The updated print-supported cohort is positive: 99
entries overall, modeled Sharpe 4.64;
11 recent entries, modeled Sharpe
4.29. This is promising repair-and-confirm
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

The mixed S&P result is 3.21 on
56 markets/10 events, combining SPY monthly,
SPY weekly and SPX monthly tickets. SPY monthly alone is
1.66 on 31 markets/5
events, interval [-1.52,
22.57]. SPX monthly is
3.98 on 21 markets/4
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
