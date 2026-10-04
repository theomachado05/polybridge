# Exact payoff baskets and source-publication carry

**Neither rule can be backtested honestly from the available historical cache.**
Historical Polymarket prices lack executable order-book depth. The main contract
metadata lacks complete rules, observed official publication times and collateral
release times. At both 1× and 2× costs, P&L, Sharpe, drawdown, worst month, turnover,
confidence intervals and capacity are **NA**. This is a data limitation, not evidence
of zero opportunities or zero returns. There are zero evidence-qualified entries
and daily portfolio marks; no price-based candidate scan was run.

The method and the two rules were frozen in commit `6e33ff0` before
evaluation. The local audit covers **1,840 Polymarket price files and
161,911,274 timestamp rows**. Numeric price arrays were never opened; the reused S1
numeric result files were read solely for the independent baseline audit below.
No Kalshi API or market-data network request occurred. The protected forward
window and sealed OOS files were never opened. **35 deterministic synthetic
contract/execution checks pass**; they are not historical trades or performance.

## Why contract certainty did not produce a backtest

| Required input | Evidence available | Effect |
|---|---|---|
| Full rules captured before entry, including source, deadline, boundaries, revisions and refunds | 33 S1 pair records, 391 S9 markets and 2,564 S11 historical markets have zero complete rule/source records in these stored schemas | Similar titles and heuristic verification cannot establish an identical or nested payout |
| Synchronized direct bid/ask and size/depth for every actual purchased token | PM files are `t,p` (S9 also has `served`); S1 Kalshi has candle-close bid/ask plus traded volume, not quote depth | Neither basket capacity nor sequential fills/failed-leg loss can be reconstructed |
| Official release and first locally observed timestamps plus preserved release content | Zero such records in the audited metadata | An eventual winner or `closedTime` cannot create a causal carry entry |
| Actual collateral release and dispute/exceptional payout records | Zero release records | Holding cost, available cash and eventual redemption P&L cannot be reconstructed |
| Daily executable liquidation bids and depth | Zero qualified historical marks | A locked-payoff or last-mid curve would fabricate portfolio Sharpe |

A static arb snapshot contains some Kalshi rule text and PM books. It lacks matched
full PM rules and a continuous book history; it cannot supply a recent-20% test.
The live forward recorder can supply books for its own frozen studies, but that
protected window remains untouched here. S11 bundles were not rerun or tuned.
Metadata labelled live was used only to inspect stored field presence.

For A => B, the correct pair is YES(B) + NO(A): allowed binary states pay $1, $2 and
$1. The inverse pair can pay $0. The contract proof also needs exceptional states:
one venue refunding $0.50 while the other leg pays $0 breaks an apparent $1 floor.
The official [resolution documentation](https://docs.polymarket.com/concepts/resolution)
explains that rules govern the outcome, disputes can produce a 50/50 payout, and
trading stops on final resolution. Carry must enter after source publication and
before venue finality; it is not simply buying an already finalized winner.

The official [negative-risk documentation](https://docs.polymarket.com/concepts/negative-risk)
describes conversion across a complete set and augmented events with placeholders
and a changing Other definition. A list of named members plus a flag is insufficient
to prove that every possible winner is included. These mechanics checks establish
requirements; they do not identify a historical profit.

## Independent audit of the already published S1 baseline

This is **reused exploratory evidence**, not a fresh OOS trial. We audited the
registered primary V0 only, at its already reported 1× and 2× costs. No new threshold,
variant or profitable subset was selected.

| Reused S1 OOS quantity | 1× | 2× |
|---|---:|---:|
| Modeled entries | 99 | 38 |
| PM print-supported entries | 15 | 9 |
| Independent UTC entry dates of that subset | 12 | 7 |
| Modeled hold-to-deadline edge, independently recomputed | $47.50 | $32.28 |
| Modeled entry collateral scaled to printed size | $1,176.95 | $381.12 |
| Share of modeled edge from two largest entries | 55.07% | 78.24% |
| Modeled mid P&L of supported subset | $65.67 | $40.62 |
| Modeled mid Sharpe, independently reproduced | 4.531 | 2.905 |
| Simultaneous two-leg depth proven | 0 | 0 |

The $47.50 accounting is arithmetically correct given S1's assumed prices, fees and
carry. It is an assumed entry edge, not realized net profit or a contractual floor
proved from complete rules. Public PM prints within **±600 seconds** do not show
that both legs were available together; Kalshi candle volume is not displayed size.
The later live PM spread calibration is not the spread of those historical entries.
The supported subset has only 12 entry dates at 1× and 7 at 2×, below this study's
30-date minimum. There is no valid confidence interval for execution profitability.

The primary S1 OOS account starts flat: at 1×, **5
IS positions with $472.07 collateral are still
open at the split, and 4 of those pairs
receive 20 new OOS entries. At 2×, the corresponding
figures are 3 positions,
$284.34, 3
pairs and 8 entries. These results describe
separately restarted IS/OOS sleeves, not one continuous collateral account.
The reported max-locked field is end-of-window open cost; event-time reconstruction
finds a higher OOS peak: $1412.04 versus
$1317.17 at 1×, and
$1175.39 versus
$1078.94 at 2×. Both remain below S1's
$3,300 aggregate capital base. This is an accounting-label correction, not evidence
of an aggregate capital breach.

## C++ latency benchmark and execution alignment

[MarketTick](../../../engine/hedgecore/include/hedgecore/market.hpp) lines 25–27 holds
current-venue prices/depth and only the other venue's midpoint. `Intent` at lines
33–44 holds one instrument, side, quantity and venue. The
[opportunity family](../../../engine/hedgecore/include/hedgecore/algos/opportunity.hpp)
lines 40–42 describes convergence on one venue; lines 87–98 choose one side, charge
that venue's spread/fee and emit one order. There is no second-leg typed book, clock,
contract proof or basket cash-flow state. A fast evaluation benchmark demonstrates
signal-processing speed; it cannot establish executable basket profitability.
No C++ engine files were modified.

## What is ready, and what remains

The Python primitives test the implication orientation and refund states, complete
contract evidence, book clock/depth validation, FOK fills, fixed latency, adverse
costs, changing later-leg economics, failed/partial unwinds, venue cash, actual
release funding, source-observation causality and daily liquidation marks. They
are an audited starting point, not a complete trading system or a fabricated
historical dataset adapter.

A future test needs versioned full rules, an as-of source-observation archive,
direct token books at decision/submission/unwind times, contemporaneous fee/tick/
minimum-size terms, dispute and release cash flows, and daily liquidation depth.
The prospective start is frozen at **2026-10-05T00:00:00Z**, after the protected
window, and requires root coordination. No collector was started. A most-recent20%
split needs at least 300 calendar observations to contain 60 OOS daily marks.
All reused caches remain exploratory. The fixed success bar is OOS Sharpe ≥1.5
at both costs, positive OOS P&L and a positive date-cluster confidence interval,
30 OOS entry dates and 60 valid OOS daily observations.

Files: `metrics.csv`, header-only `trades.csv` and `equity.csv`, `inventory.csv`,
`metadata_inventory.csv`, `s1_baseline_audit.csv`, `s1_concentration.csv`,
`capacity.md`, `RUN_LOG.md`, `run_meta.json`. The two PNGs explicitly display why
financial curves are unavailable; neither plots a fake zero return.

Reproduce from `research/`:

```sh
.venv/bin/python -m pytest cx3_payoff_carry/tests -q
.venv/bin/python -m cx3_payoff_carry.run
```

The runner verifies that METHOD.md, config.py and .gitignore still exactly match
the freeze commit. Source cache counts may grow while other sessions work; the
saved inventory is the audit snapshot, not a claim that the live directory is fixed.
