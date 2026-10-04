# CX1: liquid-index insurance with an event risk gate

Frozen before option price or trade-outcome inspection. Root handles the commit and sends `FREEZE_ACK` before the run.
Only this package and `research/results/cx1_option_insurance/` are writable. No network requests are planned.

The economic question is whether selling weekend downside insurance on liquid SPY options earns a return after actual
crossing costs, and whether one fixed event-risk sizing rule improves that return against equal average exposure.
A fully cashsecured put has a finite worst loss: strike times 100 less net credit. The holder supplies all assignment
cash; no leveraged naked option return or premium-only denominator is permitted. It remains exposed to an equity crash.

## Prior knowledge and scope

- S7's Friday-to-Monday long straddle lost 17.7% net but approximately 1% gross. Most of that loss was costs. A short
  must sell at the bid and buy at the ask; reversing a long trade's net return does not establish short profitability.
- Broad 8-K cashsecured-put conditioning failed. No sealed 8-K outcomes or `research/results/oos/` will be opened.
- SPY contract listings exist locally; SPX listings were absent in the schema inventory. S7's available option quotes
  primarily cover ATM contracts. A put spread requires two actual strikes at both times. Wing coverage has not been
  established. Before looking at prices, the baseline is therefore fixed as a **cashsecured ATM SPY put**, not a spread.
  No other instrument or strike fallback will be added after outcomes are seen.
- All shared historical data have already been used in earlier research. Results are exploratory screening, even with
  a chronological split. Untouched observations from 2026-10-05 onward are reserved for future confirmation and will
  not be downloaded or included tonight.
- The one-year five-minute SPY window has roughly 253 sessions and roughly 55 closures. Its recent 20% cannot meet
  30 independent OOS entries or 60 OOS daily observations. Any computed Sharpe is diagnostic, not a successful screen.

## Fixed trade and data selection

Window: 2025-10-01 through 2026-10-02, the S5 cached SPY intraday window. Derive actual session open and close times
from five-minute timestamp metadata. Every closure exceeding 40 hours is eligible, including holidays. Take at most
one put position per closure and no overlapping positions.

Sell the ATM SPY put five minutes before the preceding session's actual close; buy it back 15 minutes after the next
session's open. Strike is the listed strike nearest the SPY price known 30 minutes before the entry session's close
(tie: lower strike). Select the first listed expiry at least seven calendar days after entry, searching at most
28 further calendar days. Contract multiplier must equal 100; no adjusted contracts. Listing gaps are reported as
missing data, never evidence that a nearer expiry did not exist. The existing Massive reference cache is read only.

Entry and exit use the last NBBO at or before the exact instant. Entry age must be at most ten minutes. Exit age must
be at most fifteen minutes and its timestamp must be at or after that session's open. Both quotes need finite positive
bid, ask at least bid, and positive entry bid size and exit ask size. Missing or invalid data means no executable trade;
every omission is reported. Entry fills are at the bid; exit fills are at the ask. No interpolation, theoretical
option prices, trades-file-derived fills, or fabricated NBBO is allowed. The offline runner must not load an API key.
An NBBO quote is observable market data, not a certified live fill; execution at its displayed side/size is an explicit
historical fill assumption. Capacity is constrained by both displayed entry and future exit size, and does not prove
scalable simultaneous fills.

## Exactly two strategy variants

**V0 (primary):** deploy full strike cash on the fixed put. Each closure's research unit holds one contract and its
return is actual net P&L divided by strike times 100. The portfolio uses that full cash budget on every executable date.
Fractional contracts express proportional portfolio returns; capacity states the cash needed for a real integer lot.
At exactly one-contract cash capital, V1 cannot implement a half contract. An integer implementation needs at least
two contract cash obligations to express the half/full gate. Report that capital floor and available lot capacity.

**V1 (only event-aware variant):** the same contract and times; use half the full-cash exposure when any S5 agreed
SPY-linked question has odds between 10% and 90% at the entry signal cutoff and a mean absolute overnight odds change
of at least four percentage points over the five sessions ending on entry (at least three valid nights). Odds are
as-of values with age at most 30 minutes. The last overnight signal ends before that day's open, and current odds are
sampled 30 minutes before close. Nothing after the entry cutoff enters the decision. If no SPY link is sufficiently
observed, conservatively use half exposure. Otherwise use full exposure. Unallocated cash earns zero.

S5 links were assigned after many linked events had resolved: historical link selection is a known exploratory-data
limitation. We neither refit links nor use realized event resolutions in the risk gate.

Required comparator `STATIC_IS_MATCH`: the V0 trade at the average V1 size over **all eligible IS closures**, determined
from gate values alone, with that one constant applied to OOS. It is an exposure control, not a third optimized strategy.
The IS comparison using the full-IS mean is descriptive. No parameter is selected using performance.

## Cash, marking, costs, and daily returns

Cash collateral is the full strike obligation (strike times 100), with no premium netting, leverage, margin release,
interest, or assumed yield on unused cash. On entry, the liability is marked at the contemporaneous liquidating ask.
The account pays the bid-to-ask crossing loss and entry commission that day. At exit, buy at the actual ask and pay
exit commission, then hold cash. There is no intermediate trading session in a closure. These are observed account
snapshots at entry close-minus-five-minutes and at next-session exit, with cash thereafter; the last five minutes of
entry day are unmarked and disclosed. Weekend nontrading days are not inserted as zero-return sessions.

For a cost multiplier `c`, entry bid equals midpoint minus `c` times half-spread; exit ask equals midpoint plus `c`
times half-spread. The entry liquidation mark is the corresponding widened ask. Commission is `c * $0.65` per contract
per side. Thus 1x uses the real NBBO and $1.30 round-trip commission; 2x doubles every half-spread and commission.
If the widened entry bid is nonpositive, label that cost-case unexecutable and report it. Costs are separately stated
in dollars, basis points of full cash collateral, and percentage of entry option mid premium. Source: contemporaneous
cached Massive NBBO, plus the same stated commission assumption as S7; commission is not claimed as a universal broker rate.

Allocate exposure from the portfolio equity immediately before entry; keep that number of contracts fixed through
exit. Compound daily account returns, including entry-day transaction drag, exit-day P&L, and every inactive session.
The denominator for V1 and the comparator remains the same full cash budget. Verify that compounding the two active
daily returns reproduces the event return and that worsening costs cannot improve the fixed-unit short's P&L.

## Split, inference, reporting, success

Recent 20% of the **complete SPY session calendar**, rounded up, is OOS. Positions whose entry precedes the OOS boundary
and exit falls inside it are assigned to IS for trade inference; their actual dated daily returns remain on the account
calendar and the crossing is disclosed. The boundary is set before quote availability or performance is examined.

Report IS, OOS and full-sample results for V0, V1 and the required static comparator, each at 1x and 2x costs; every
planned closure and omission, quote ages/sizes, daily equity/returns, annualized daily Sharpe (sqrt252), compounded max
drawdown and worst month, option-notional turnover divided by initial collateral cash, and capacity at the weakest
entry bid/exit ask size. Do not annualize an event-only statistic as a daily Sharpe when daily marking is unsupported.

Mean net event return and V1-minus-static difference get a circular moving-block bootstrap over chronological closures,
four closures per block, 5,000 draws, fixed seed 101. A single closure is one bet. Include zero returns for missing
quotes in portfolio/calendar metrics; mean executed-event inference is identified separately. Report each chronological
half of IS and OOS, largest winning/losing closures, and leave-best-closure-out diagnostics. No concentration removal
changes the main strategy. At Sharpe above three, audit time cutoffs, signs, costs, collateral and daily reconciliation.

A preliminary screen requires all of: at least 30 independent executable OOS entry dates; at least 60 OOS daily
observations; V0 net OOS annualized Sharpe at least 1.5; positive OOS total return at 2x costs; OOS block-bootstrap
mean net executed-event return lower95% bound above zero; positive IS and both OOS chronological halves; no single
closure responsible for the entire OOS profit. V1 is assessed identically and must also beat its exposure control with
a positive lower95% bound on the paired block difference. Neither can be called confirmed on reused history.

If executable quotes are too few or unavailable, deliver a not-testable audit and missing-data manifest. Do not infer
a negative or positive strategy result from unavailable data. The maximum network request and download budget is zero;
a proposed future full-quote study is described separately and not run.
Zeros on dates with absent historical quotes describe cash in an incomplete executable-data diagnostic. They are not
evidence that the fully specified historical strategy would have chosen cash or earned zero on those dates.

## Schema inventory before freeze

The shared `research/.massive_cache/` had 31,579 JSON files (559,618,948 logical bytes): 24,646 aggregate-bar files,
2,404 contract-listing files, 2,609 NBBO files, 1,681 empty/other files and 239 other files. Inventory touched schema
keys, timestamps and option symbols only; no option price, size, stock return or trade-outcome value was evaluated.
SPY listing metadata covered 48 expiries from 2025-10-10 to 2026-08-28; SPX listing count was zero. S5 SPY five-minute
NPZ keys are `t,o,c,v,vw` (19,664 rows); its daily NPZ keys are `day,c,o` (337 rows). S4 has another 14,742 SPY intraday
rows and 274 daily rows. S16 JSONL uses `k,v`; quote fields are `bid,ask,bsz,asz,ts` and currently has no SPY quote keys.

## Amendments

None at freeze. Any correction will be dated, additive, and state whether outcomes had been inspected.

**Amendment 1 (2026-10-04 03:57 UTC, after the initial offline run): calendar correction.** The first run found the
cached closing-auction bar at 13:00 on 2025-11-28 and 2025-12-24. Adding five minutes to its timestamp incorrectly
inferred a 13:05 underlying close. The actual NYSE close on both dates was 13:00, as the
[official ICE/NYSE calendar published in 2024](https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx)
states. Clamp those two dates to 13:00; entry becomes 12:55 and strike/signal cutoff 12:30. The original actual-close
rule is unchanged. Both dates were omitted in the first run due to uncached listings, so no executed put price changes.
Recompute the gate with corrected prior-close cutoffs and disclose any exposure changes in the original 48 trades.
The initial metrics/trades/equity/coverage are retained in `initial_offline/` for comparison.

**Amendment 2 (same timestamp, after the initial offline run): DATA_ONLY completion.** Root approved a budget of at
most 60 sequential Massive requests, at most 0.5 requests/second, at most 2,000,000 response bytes, solely to complete
the frozen seven missing closure observations. Expected demand is seven reference-listing queries and 14 NBBO queries
(21 requests). Store responses only under this package's `.cache/`; shared caches stay read only. Root must commit
this amendment and send its acknowledgment before any request. API authentication uses a header loaded through the
existing credential helper; keys never enter URLs, outputs or logs. If budget or API access prevents completion,
report the remaining dates. This neither expands history nor changes the strategy, split, strikes, expiry search,
costs, event thresholds or success conditions. Initial V0 OOS was +0.2936% at 1x costs, Sharpe 1.420, with five entry
dates and 51 daily observations; its event-mean interval included zero. Completing missing dates is not confirmation.

**Amendment 3 (same timestamp, root-requested after the initial offline run): equity-risk diagnostic.** Report SPY's
return from the last completed five-minute underlying bar at the frozen entry instant to the same as-of exit instant,
and a fixed 0.5-times-SPY return alongside the gross and net put returns. No hedge coefficient is fitted or optimized;
it is a post-run diagnostic, not another strategy or pass candidate. ATM short puts own roughly half a share of equity
directional risk per underlying share. Report the gross put minus that fixed stock-risk proxy and a descriptive
event-level beta, with the small sample and bar-versus-NBBO timing differences stated. This diagnostic helps distinguish
ordinary equity exposure from insurance premium; it cannot prove a risk premium or a causal prediction-market edge.

**Amendment 4 (2026-10-04 03:57 UTC, after the initial run): output timestamp labels.** In the initial CSV,
`entry_timestamp` and `exit_timestamp` were accidentally overwritten with SIP quote timestamps when quote fields were
expanded. Quotes had always been requested/validated against the separately computed scheduled instants, so fills,
ages, signals and P&L were unaffected. Preserve scheduled times in `entry_timestamp`, `exit_timestamp` and the explicit
`entry_decision_timestamp`, `exit_decision_timestamp` columns; store SIP times separately as `entry_quote_timestamp`
and `exit_quote_timestamp`. This is an output-label correction, not an execution-rule change.

**Amendment 5 (2026-10-04 04:04 UTC, after initial outcomes, BUG_CORRECTION): same-session cash accounting.** Independent
read-only review found that 2026-01-02 contains the morning exit of the December 31 position and the afternoon entry
of the January 2 position. The initial code added their daily returns instead of compounding them, sized the new
position before the morning exit's P&L, and overwrote that day's turnover. A failing synthetic rollover regression
reproduced this financial invariant violation before the fix. Process the morning exit then afternoon entry at updated
NAV, multiply the within-day return factors, and add both turnover flows. The original event-level fixed-unit P&L,
fills, gate, instrument and split are unchanged. The initial V0 1x full-period return was overstated by 0.001806 bp
and 2x by 0.003384 bp; 1x premium turnover should have been 0.6938116 rather than 0.6902899 per initial cash. Additional
rollover dates November 28 and December 26 become relevant if their quotes are completed. Preserve the initial archive,
require full-book daily/event factor reconciliation, and commit this correction before the final run. This is a cash
accounting repair, not parameter selection or a new variant.

**Amendment 6 (2026-10-04 04:06 UTC, after outcomes): reference-chain limitation.** Independent review noted that the
reused Massive reference requests include expiry and `expired=true` but omit an entry-date `as_of` parameter. The actual
entry NBBO proves that the selected put existed and traded before its decision instant; it does not establish that
the cached listing was the exact historical nearest-expiry/nearest-strike chain. This limitation is disclosed in the
results. The frozen cached-listing request and selection rule are not silently replaced after outcomes. Full-sized
V1 also needs two integer contracts to express the half/full rule, and a historical full-exposure date with only one
displayed contract cannot support that integer book; normalized fractional curves are not an all-date executable
integer-capital simulation.
