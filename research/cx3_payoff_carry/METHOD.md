# Exact payoff baskets and resolution carry — frozen method

Frozen before inspecting any new price or outcome values. Owner: `cx3_payoff_carry`.
Only this package and `research/results/cx3_payoff_carry/` may be changed. No Kalshi API,
no forward/raw, no sealed research/results/oos or original 8-K OOS. The root session
commits this method and config before authorizing evaluation. All reused history is
exploratory, including a recent-20% split; it cannot become a fresh holdout.

## Question and prior knowledge

Can contract certainty, rather than a forecast, produce a repeatable return after all
execution costs and collateral lockup? A mathematical payoff floor is insufficient:
the contracts, quotes, depth and cash must coexist at the entry time.

Known before this method: S1 reported $47.50 of modeled hold-to-resolution edge on
15 print-supported OOS entries, on about $1,177. Its registered strict print check
failed. Its source uses Kalshi minute candle closes, Polymarket minute price history,
a later live half-spread calibration and public print evidence on only the PM leg.
This is a baseline validity audit, not a rerun or variant search. S11 owns strike,
date and negative-risk bundle studies; this package does not rerun or tune S11.
Its source strips full contract descriptions and official sources from stored
market metadata. These observations are known priors, not discoveries from our test.

## Inventory observed before freeze

Header-only inspection; numeric price arrays and outcome values were not read.
S1: 33 pair records, 66 NPZ files, 17,221,186 total cache bytes. PM arrays are `t,p`;
Kalshi arrays are `t,bid,ask,vol`. No historical PM depth or size exists here.
S4: 299 cache files, 41,447,697 bytes; PM schema `t,p`.
S5: 227 cache files, 54,921,233 bytes; PM schema `t,p`.
S9: 566 cache files, 20,942,576 bytes; PM schema `t,p,served`, prints JSON.
S11: 879 cache files, 149,596,433 bytes; PM schema `t,p`; counts may change while
another session works, and will be remeasured without reading prices.
S9 has 391 metadata records; S11 historical has 2,564 markets and 233 bundles;
S11 live has 888 markets and 90 bundles. These four principal metadata sets
(S1, S9, S11 historical and S11 live) contain zero nonempty complete descriptions,
resolution sources, observed source publication times or redemption times.
The twin manifest stores heuristic verification checks and titles, not full rules.
A static arb snapshot contains Kalshi rules and a PM book snapshot; a single
snapshot cannot supply a historical split or matched PM contractual rules.
`research/forward/README.md` describes timestamped depth recording since Oct 3,
but its protected raw window is outside this study. No forward/raw files were read.

## The two frozen rules (no parameter search)

### A. Exact-payoff basket

A manually signed, versioned metadata manifest must identify a finite set of
permitted terminal states and full contractual rules captured before entry. For an
implication A => B, buy YES(B) + NO(A), which pays at least $1 in each permitted
state. For identical event contracts on two venues, buy complementary legs only
if deadline, observation window, source, boundary convention, revisions,
exceptional outcomes and payout units coincide. For an exhaustive one-of-many
set, buy all YES only if the complete fixed set and exactly-one condition are
proved; a `negRisk` flag or similar titles alone is insufficient. Require a minimum
payoff >= $1 per basket unit. Do not assume boundary states away or certify
completeness from resolved outcomes.

At the first snapshot with the conditions below, and the next valid snapshot at
least 2 seconds later, execute the basket if net conservative edge is at least
$0.02 per basket unit after fees, adverse tick and projected funding. Use 100 units
as target, capped by 10% of each observed ask level and portfolio cash. One open
position per contract family. All eligible opportunities execute in deterministic
(contract-family, basket-id) lexical order; no best-edge sorting or variant selection.
There is no early profit-taking: hold to each leg's observed collateral release.

Book requirements: direct bid and ask for the actual token/contract bought, venue
and local receive timestamps, bid/ask depth, tick/minimum size, contemporaneous
fee terms. At decision time all receive timestamps must be no later than decision,
not older than 2 seconds; cross-leg receive-time skew <= 1 second; venue timestamp
lag <= 2 seconds. Reject empty, crossed, malformed, one-sided or stale books.
Walk ask levels with 10% participation. A trade print is not an ask or reservation.
Require records covering the decision and subsequent submission/fill times.

Multi-leg orders are sequential fill-or-kill (FOK), not atomically cross-venue. A conservative historical quote replay is a valid explicitly simulated backtest,
provided it uses causal observations and includes sequential fills and legging
losses. Submit legs in manifest order with 1 second latency per leg; fill at the
earliest book received at least 1 second after submission and no more than
2 seconds later, using only that book's displayed ask depth. Each later leg is
submitted after the previous simulated fill. Recheck its net economics, cash and
book validity at that time. A FOK leg must have all required quantity, otherwise
it fails. If one leg fails, stop adding exposure and submit an unwind of filled
legs, applying the same latency and next-book rule to observed executable bids.
Charge fees, adverse tick and funding on every fill. An unwind without sufficient
depth fills available quantity only; remaining exposure stays in the portfolio
until the next valid bid or observed release. Retain failed/partial attempts and
residual exposures in P&L and turnover. Missing causal book windows or marks
block a historical performance claim, rather than assuming a free or certain fill.
Historical book replay does not require actual order acknowledgments, and its
Sharpe must be labeled simulated and exploratory. Actual acknowledgments are
required only to call execution verified live execution.

### B. Official-source resolution carry

A complete contract rule must specify a named official source. A preserved source
release, release timestamp and first locally observed timestamp must determine
the bought side at that instant. Enter 60 seconds after the later of release and
first-observed time, while the contract still accepts orders. Never derive entry
from an eventual market outcome, `closedTime`, scheduled deadline, file mtime or a
near-$1 price. Revisions, ambiguous source text and disputes are identified from
information available at entry; those cases remain in the denominator and all
actual losses/delays count. A source interpretation that cannot be mechanically
resolved from the pre-entry contract is a failed eligibility attempt, not silently
dropped after the outcome.

Buy 100 shares of the source-determined winner, under the same book, cost and
participation gates. Require expected net edge >= $0.02 per $1 payoff after
projected 30-day funding. One open position per contract family. Hold to observed
release of redeemable collateral. The final venue resolution and release times
are evaluation facts only; disputes, losses and delays beyond 30 days remain.

## Costs, collateral and portfolio

Exactly 1x and 2x cost scenarios; neither is selected after evaluation. At 1x, fill at
actual ask VWAP, add the contemporaneous taker fee and one observed adverse tick
per leg. Spread cost = ask VWAP minus simultaneous bid/ask midpoint. At 2x, add one
extra copy of that spread cost and double fees, tick/slippage and funding. Report
costs as dollars, payoff points and basis points of entry collateral. No fixed PM
half-spread is calibrated from later books. Fee schedules must be timestamped;
missing fees block a performance claim. Fee formulas are checked against official
primary documentation after the freeze; no live venue pull is required.

Fixed funding assumption: 10% annual simple opportunity cost, stressed to 20% at
2x, applied daily to actually locked entry collateral including fees. This is an
explicit conservative hurdle, not a claim about the current risk-free yield.
Projected entry funding uses 30 days after the later contractual deadline (A), or
30 days after entry (B); actual costs use actual release dates including longer
resolution/dispute delays. A requires its contractual deadline <= 7 days from entry.
Capital = $10,000, initially $5,000 per venue where applicable. No automatic cross-
venue cash transfer. Maximum portfolio entry collateral = 50% of capital; maximum
per family = 5%. Reject insufficient funds or venue/minimum-order violations.
No unsecured leverage, reinvestment of unredeemed winners, or assumed instant
settlement. Normal conversion/transfer/gas costs require observed records; missing
material cash flows block historical net performance.

Daily portfolio equity at 00:00 UTC includes free cash, open positions valued at
contemporaneous executable liquidation bids net of exit fees/tick, and daily funding.
Final payout enters cash only on observed collateral release. All calendar days,
including idle days, are included. Missing required marks block a Sharpe claim;
no locked-payoff mark or last known mid manufactures a smooth curve.

## Split, uncertainty and success

IS = first 80% and OOS = most recent 20% of observed calendar span, split without
looking at prices/outcomes, globally shared across contracts. A position crossing
the boundary is marked at the split; incremental OOS P&L and opening collateral
are retained. OOS statistics are not computed from only new or completed trades.
Use full portfolio daily returns and sqrt(365) annualization. Report total/net P&L,
Sharpe, max drawdown, worst month, turnover, locked capital and failed orders.
Use date-cluster bootstrap (2,000 draws, seed 7301) for mean net daily return and
Sharpe; entries on one date are one independent cluster. Also report event-family
concentration, and leave-one-family-out sensitivity without selecting a survivor.

Success requires both cost scenarios to have OOS Sharpe >= 1.5, positive net OOS
P&L, a positive 95% date-cluster interval for mean daily return, >= 30 independent
OOS entry dates and >= 60 OOS daily observations with valid marks, complete audit
trails and no unresolved material omissions. A Sharpe > 3 triggers a bug audit;
it does not relax the sample gate. Missing data is not a zero-return strategy.
No threshold, timing, universe or marking variant may be tuned after evaluation.

## Feasibility and future observations

Current primary caches fail the historical data gates. If no already-cached,
contemporaneous full rules, official source observations, synchronized depth,
sequential execution-time books and redemption records can be located without opening
protected data, deliver `not_testable`, zero evidence-qualified historical trades,
NA Sharpe/P&L/capacity, explicit blockers and deterministic contract/execution tests.
Do not claim a historical zero trade result or zero profit from missing evidence.
No network prices, outcomes, fresh books or historical bulk pulls are planned.

A prospective start is fixed at **2026-10-05T00:00:00Z**, strictly after the current
protected recorder window. No collection or evaluation begins without root
coordination. At least 300 full daily observations would be needed for a recent20%
OOS span of 60 days; that future effort is not represented as today's backtest.

## Amendments

None at freeze. Any changes here must be appended and dated after freeze.
