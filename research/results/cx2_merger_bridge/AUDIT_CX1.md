# Independent CX1 read-only audit

Audit completed 2026-10-04 UTC. No CX1 source/result files, shared caches, credentials, recorder, git state or strategy parameters were edited by this auditor. Commands read frozen source, cached data and the 48-trade output snapshot; pure synthetic fixtures ran in memory. No additional data was pulled. The option agent is separately completing the seven missing closures. Numbers below describe the audited 48-trade snapshot, not an anticipated completed sample.

## Financial finding: same-session rollover, P2, corrected

The pre-correction `run.py:82-90` added a prior closure's morning exit return to a new closure's afternoon entry return. It excluded the morning exit from `entry_portfolio_equity`, and assigned turnover to the same day twice, overwriting the morning flow. This occurs on 2026-01-02 in the existing executed sample. Planned rolls also occur 2025-11-28 and 2025-12-26 if their missing quotes are completed.

Daily factors must multiply in chronological order. The portfolio value before a new afternoon order must include that morning's closeout, and turnover must add both trades. Independent multiplication of all executed event factors quantifies the original error:

| Portfolio | Original total return | Correct sequential total return | Original overstatement (bp) |
|---|---:|---:|---:|
| V0, 1x | 6.2872717050% | 6.2872536497% | 0.001805526 |
| V0, 2x | 5.4654912500% | 5.4654574058% | 0.003384423 |
| V1, 1x | 4.3246280618% | 4.3246192013% | 0.000886050 |
| Static exposure control, 1x | 4.1549577977% | 4.1549499300% | 0.000786768 |

The NAV error is tiny here and does not change OOS returns, because January 2 is in IS. The bug matters to the accounting invariant and would recur on completed holiday rolls. V0 1x original premium turnover was 0.6902899443 times initial cash; independently summed sequential turnover is 0.6938116090. January 2 alone loses 0.0035163346 times cash in the old turnover ledger.

Root recorded correction commit **e0b7bb1**. Corrected [engine.py](/Users/theomachado/gatorquant/research/cx1_option_insurance/engine.py:47) incorporates the current session's morning return in entry NAV, multiplies session return factors, and adds both flows. [run.py](/Users/theomachado/gatorquant/research/cx1_option_insurance/run.py:91) now checks whole-book daily factors against executed-event factors. Leave-best-closure-out removes only that closure's factors instead of erasing unrelated returns on a shared day.

Independent post-fix checks used four cash-ledger fixtures: 1x/2x costs, shared/nonshared sessions, varying strikes and exposures 0.5, 2/3 and 1. Each agreed on NAV, pre-entry equity and turnover within 1e-12. The package's regression reproduces a synthetic pre-fix NAV discrepancy; its financial tests now pass.

## Accounting and timing checks that passed

- Short credit at entry bid, closeout debit at exit ask and two commissions reconcile against an independent explicit cash ledger in 2,000 random valid quote cases. Maximum dollar error: 8.21e-13. Return denominator is strike times 100, with no premium netting. 2x doubles measured half-spreads and commissions; a nonpositive stressed entry bid is rejected.
- Full collateral and idle cash remain in account returns. Entry is marked at liquidation ask and its transaction drag is recorded on entry day. For each isolated closure, entry and exit factors reconcile to the fixed-contract event return. Whole-book reconciliation required the rollover correction above.
- Calendar has exactly 253 sessions matching the [published NYSE holiday calendar](https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx). Opens are 09:30 New York; 251 closes are 16:00 and two are 13:00. Corrected half-day entries are 12:55 and strike/signal cutoffs 12:30. Eligible options may trade later than the equity close; the frozen rule deliberately uses the equity session clock.
- Recent 20% is ceil(253*0.20)=51 complete calendar sessions, beginning 2026-07-23, set before quote availability. Entry-based trade segmentation and calendar-based daily returns are separate; the method discloses split-crossing trades.
- All 55 selected underlying strike/signal, entry and exit bars end at or before their decision instants. In the sampled data the completed bar ends exactly at each instant. No unfinished future bar close enters ATM selection.
- Separate scheduled decision and SIP quote timestamps are preserved. Maximum ages in the executed 48-trade snapshot: entry 5.5481 seconds, exit 1.7967 seconds. Quote validation excludes future, stale, crossed and pre-open exits.
- Event gate code uses current odds at close-minus-30 minutes and activity ending at the current morning, using previous session closes. A prefix-only replay after deleting every observation later than the decision cutoff on five fixed calendar dates (October 3, December 31, January 2, July 24 and August 21) reproduces each original gate. The fixed static comparator uses IS planned gate exposure only. Retrospectively selected S5 links remain a disclosed exploratory selection limitation, rather than a newly found timestamp leak.

## Source-validity caveat: point-in-time listings, P2 limitation

[data.py:38](/Users/theomachado/gatorquant/research/cx1_option_insurance/data.py:38) queries expired contract listings without `as_of=entry_day`. [Massive's official All Contracts documentation](https://massive.com/docs/rest/options/contracts/all-contracts) says the default point in time is today. Therefore the cached chain does not independently prove that the chosen expiry and nearest strike were the available chain at historical entry. A later-added or corrected contract could affect the selection rule.

A valid entry NBBO does prove that the selected put existed by entry. The audit has **not** established that any actual selected expiry/strike is wrong, and it does not allege fabricated option prices. This is an unresolved selection-proof gap to disclose; silently changing historical queries or selection after returns are seen would require a dated data-validity amendment and fresh accounting comparisons. No such requery was initiated by this auditor.

Observed listing rows had standard 100-share units and no additional-underlying field (9,797 rows across the selected requests). The general source filter should still explicitly reject additional deliverables when applied beyond SPY, because a 100-share field alone does not guarantee a standard contract.

## Capacity and sample limitations

The current study is a proportional fractional-contract diagnostic, as its method states. V1 cannot be advertised as an exactly executable half/full integer portfolio across every observed quote. On 2025-10-31 its full gate has only one contract of limiting displayed capacity; exact two-contract full/one-contract half operation needs two contracts at full exposure. Minimum observed half-gate capacity is two contracts, while minimum full-gate capacity is one. Maximum observed two-contract cash obligation is $155,200. A larger portfolio does not repair a one-contract quote-depth constraint. Future exit depth is retrospective capacity evidence, not information available for entry sizing.

The audited 48-trade sample has 43 IS and five OOS entries. OOS covers 51 daily sessions and only five of ten planned closure entries have quotes. Missing recent quotes are concentrated from late August through September. Cash zeros on those days describe incomplete executable-data accounting; they are not evidence that the complete strategy would earn zero. Even completion gives at most ten OOS entries and 51 daily observations, below the frozen 30-entry/60-session minimum. No valid success claim can follow this one-year split.

## Economic interpretation: much of the positive P&L is equity exposure

The fixed 0.5-times-SPY diagnostic was requested after the run, is not an optimized hedge, and uses completed underlying bars rather than simultaneous equity NBBO. It cannot establish causal insurance compensation. In the 48 executed trades:

| Segment | Trades | Mean gross put (bp) | Mean net put (bp) | Half-SPY proxy (bp) | Mean net residual (bp) | Net residual 95% interval (bp) |
|---|---:|---:|---:|---:|---:|---:|
| IS | 43 | 15.23931 | 13.55859 | 12.33127 | 1.22731 | -1.66449 to 4.04498 |
| OOS | 5 | 6.96650 | 5.88144 | 4.82324 | 1.05820 | -0.65841 to 2.77481 |
| ALL | 48 | 14.37756 | 12.75888 | 11.54918 | 1.20970 | -1.37492 to 3.81634 |

Intervals were independently reproduced with the frozen circular four-closure blocks, 5,000 draws and seed 101. The fixed stock proxy accounts for roughly 90% of mean net ALL return; descriptive gross put beta is 0.50812. Existing diagnostic output has an interval for **gross** residual, whose ALL lower bound is positive; the independently calculated **net** residual interval crosses zero. Neither positive gross residual nor raw short-put P&L establishes an economically verified net insurance premium.

V1's OOS paired gate-minus-static interval also crosses zero at both cost levels. Its return cannot be attributed to a useful prediction-market gate from this sample. The primary result is a reused-data cashsecured equity-risk diagnostic with explicit downside exposure and incomplete recent quote coverage.

## Reproducible verification

Commands ran from research/ using the bundled .venv/bin/python. Read-only checks independently reconstructed event-factor products and chronological turnover, replayed prefix-only gates, verified bar completion and the complete exchange calendar, inspected cached listing schema, and recomputed net residual block intervals. The final test invocation disabled bytecode and pytest cache writes: `.venv/bin/python -B -m pytest cx1_option_insurance/tests -q -p no:cacheprovider`. No parameter search, live order or additional data pull was performed.
