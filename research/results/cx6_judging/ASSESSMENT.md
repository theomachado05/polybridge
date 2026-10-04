# Submission readiness against the GQH judging rubric

Assessment: 2026-10-04. Read-only evaluation of published
rules and saved project artifacts. Original studies, the locked 8-K results,
forward observations and other researchers' note files were not changed.

**Decision: enough evidence for a substantial, honest research note; insufficient
evidence for a confirmed executable Sharpe-two barrier strategy.** These are
different claims. S18 remains the strongest positive transaction-cohort exhibit
from our prior audit, but that does not make it the strongest *validated trading
strategy* or a submission that can rely on a high-Sharpe headline.

## What is officially scored

The [main track page](https://www.gqhacks.com/tracks/systematic-trading) has no
profit leaderboard. Each of five criteria has ten points:

| Official criterion | Weight |
|---|---:|
| Economic Foundation | 10 |
| Innovation | 10 |
| Risk Management Plan | 10 |
| Liquidity & Capital | 10 |
| Performance & Analytical Evidence | 10 |

The evidence criterion breaks ties, then economics. It is capped at four for
unreproducible results, lookahead or holdout tuning. Code supports that criterion;
paper/live trading and language choice earn no separate score. The latest
20% of history or two years, whichever is shorter, is the required untouched
holdout. Submit a public GitHub repo and a PDF of at most five pages, including
figures/tables, with 11pt-or-larger text and standard margins. References and
optional appendices are outside that limit. Deadline: **October 4, 11:00 ET**.

The rendered page and its public assets were inspected. An organizer announcement
or participant brief overrides the site's summary. Source URLs and asset/input
hashes are in [sources.json](sources.json). This is an assessment, not an official
score prediction.

## How our evidence performs against each criterion

| Criterion | Our assessment | Evidence and remaining work |
|---|---|---|
| Economics | Plausible, incompletely established | S18 provides a positive selected seller premium. Insurance demand, lottery preferences, liquidity and ordinary compensation for tail risk are competing explanations. We have not identified the buyer's motive or demonstrated risk-adjusted mispricing. State a falsifiable demand/risk-premium hypothesis and compare with unfiltered sellers and options-based references. |
| Innovation | A credible strength | Prediction-contract rules, source-specific barriers, options references and evidence gates form a distinctive research/implementation combination. Explain the incremental contribution with an ablation: what the options reference adds beyond price alone. AI and C++ are implementation choices, not evidence that a signal works. |
| Risk | A usable plan, incomplete measurement | We have cash fixtures, event-level exposure budgets and product gates. They do not establish portfolio tail behavior for the selected cohort. Show correlated barrier-hit losses, maximum committed loss, funding/settlement delays and market/volatility exposure. The prospective budget is a proposed rule, not a tested portfolio. |
| Liquidity/capital | A material weakness | Real prints show that transactions occurred. Aggregate weekend printed size does not establish simultaneous available depth or an additional trader's queue position. Peak principal is not deployable AUM. Separate historical printed-size opportunity from executable capacity; show order-size sensitivity and conservative fill assumptions. |
| Evidence | Substantial empirical work, incomplete strategy proof | Independent S18 reconstruction, clustering, fee stress, concentration checks and negative controls are useful. The selected bucket reuses exposed outcomes; its average weekend price is unavailable at entry; monthly settlement returns are not daily NAV. These limits must be on the main pages. A causal executable replay and proper portfolio accounting would improve the evidence, but reused history would remain exploratory. |

The main cap risk is a *claim*: presenting retrospective VWAP-conditioned or
later-same-day-selected results as the performance of a causal strategy. A paper
can instead disclose those artifacts, reject those implementations and report
the original nulls. That is useful research; disclosure does not transform the
newly selected candidate's historical results into an untouched test.

## Evidence worth putting in the note

### S18: the strongest independently reconstructed positive exhibit

From the [selection audit](../cx5_strategy_selection/SUMMARY.md), the 50–75% actual
YES-sale-price cohort has **88 markets in 51 events**; mean seller P&L after fees
is **13.3021 cents per $1 contract**, event-bootstrap interval **[5.1650, 21.3257]**.
Annualized settlement-month Sharpe is **2.1703**, or **2.1085 with doubled fees**.
Removing the largest winning event leaves **+$991.59** in the illustrative
capped-print-size book.

The price buckets existed in the original method, but choosing this bucket as
the new trading headline occurred after results were inspected. It was not the
original primary trade. The recent subgroup contains 16 markets/11 events,
interval **[-1.0966, 39.0518]**. Broad recent sellers lose **0.9881 cents** per
contract. The crypto replication does not establish a full-period seller premium.
Those counterexamples belong next to the positive exhibit. Doubled fees is not
doubled total execution costs, and unhedged premium is not hedged alpha.

### Newer studies: a stronger mechanism discussion, not fresh validation

These are **saved-source findings**, reviewed after the prior selection report;
their runners and quotes were not independently re-audited here.

- **S20** compares the same tickets across first weekend, open week and second
  weekend. Buyers' additional weekend loss accompanies a wider buy/sell price
  gap; sellers do not receive a significant first-weekend premium over the open
  week. This challenges a timing explanation. Its exclusion rule changes the
  inference, and its three entry windows share outcome risk. Show both rules.
- **S21** adds a Friday NBBO options reference. Its B0 filtered seller cohort
  earns **22.27 cents**, interval **[10.35, 33.14]**, on **60 markets/33 events**;
  the selected-versus-left difference is **19.19 cents [5.82, 31.45]**. Only
  **two** selected markets/events are recent, so it fails its confirmation rule.
  This is a promising secondary empirical exhibit, not an OOS success.
  Its central touch reference is approximately twice the option-implied terminal
  probability. Drift, jumps, the contract's price source/session and an option
  expiry later than the ticket window prevent treating it as exact fair value.
  In particular, finishing beyond a level *after* the ticket window does not
  establish that the level was touched *within* that window; the advertised
  lower-bound interpretation needs matching horizons and payoff conditions.
- **S22** reports a **2.82** modeled resolution-date Sharpe, but assumes resting
  fills from prints that crossed a hypothetical quote. Its primary sample is
  74 fills/27 dates and fails its sample criterion. The stressed cash book loses
  **$37.15**, despite a positive equal-weight mean: weighting matters. It has no
  demonstrated queue position, finite-inventory portfolio or complete daily NAV.
- **S23** reduces S6's modeled closure Sharpe from about **4.31** to **1.75** at
  the best prices printed within a subsequent 30-minute window. Taking the first
  eligible print gives **1.25**, with the P&L interval including zero; only one
  trade is recent. The attractive 1.75 uses retrospective best-price selection.
  Use this as an execution-fragility exhibit, not a causal profitable strategy.

Updated S11 also remains a positive research lead: the prior independent audit
reproduces print-supported modeled Sharpe **4.64 overall / 4.29 recent**. The
full-day ranking defect persists, prints may precede the signal, and every leg's
separate compatible print does not establish simultaneous size or exit fills.
It is unsuitable as the submission's validated performance headline.

## Recommended five-page main-track narrative

Suggested title: **Prediction-market barrier insurance: pricing evidence and
execution limits**.

The present contribution is to separate an apparent pricing premium from the
execution, payoff and risk conditions required to earn it systematically.
We should not claim an already proven cross-venue arbitrage or daily Sharpe two.

1. **Question and economics.** Define one barrier-ticket strategy, the presumed
   counterparty and competing tail-risk explanation. State what was written
   before results and what is new exploratory selection. Define an exact
   underlying/source/window; monthly SPY is an operational pilot, not the
   population that produced S18's 2.17.
2. **Data and causal trade specification.** Explain token sides, eligibility,
   timing, actual prints versus modeled quotes, fees, missing markets and contract
   rules. Show the original primary and recent-period failure. An executable
   replay must use information available at each decision and retain rejected
   orders/idle cash.
3. **Evidence.** One calibration/uncertainty figure and one compact IS/recent/ALL
   table. Include S18's selected cohort and its limits, S20's timing control and
   S21's added reference. Record the entire search across studies/variants;
   do not substitute a handful of selected trials for the project's full search.
4. **Risk, costs and capacity.** Same-position cost stress, daily liquidation
   marks and funded cash if available, joint barrier-loss scenarios, exposure
   and funding limits, and executable-size sensitivity. If a requested metric
   is unavailable, say so; do not relabel settlement-month drawdown as daily NAV.
5. **Implementation and conclusion.** Explain the reproducible research pipeline,
   contract manifests and deterministic execution gates briefly. Keep synthetic
   local C++ timing separate from end-to-end fills and P&L. State the current
   rejection/selection decision and frozen future protocol. Put detailed study
   failures and benchmarks in the appendix, but retain material caveats here.

The existing engine benchmark is useful engineering evidence, explicitly on a
synthetic tape and excluding network/Python/JSON costs. It is not a market edge
or a reason to spend a page on speed. Current project instructions keep scored
research independent of hedgecore and LLM calls; preserve that separation.

## Submission blockers and next work in priority order

1. **Finish the actual note.** The saved `note/WRITEUP.md` still contains `[OOS]`
   placeholders. Its inference that an undetected edge means protection is
   fairly priced or can be bought without waiting is unsupported: a wide null
   interval permits economically meaningful effects. The existing
   `note/RECONCILE.md` already records needed corrections. Those files belong to
   another writer and were not edited here.
2. **Choose and freeze the submitted claims.** Retain the original failures;
   label S18/S21 selection as exploratory. Do not turn the existing recent
   subgroup into fresh OOS by renaming it. A newly corrected replay validates
   mechanics, not independent generalization. Do not rerun the locked 8-K study.
3. **Close the portfolio/execution gap where data permits.** First-eligible
   entries, contemporaneous executable price/depth, cash plus fees, correct
   collateral release, all days and executable liquidation marks. A quote/fill
   path that is absent cannot be invented. Report the resulting sample loss.
4. **Make clean-checkout reproduction concrete.** Existing saved-data modules
   reproduce S18 audit results locally, but that is not a demonstrated
   clean-environment rebuild. Freeze the input version, provide one entry point,
   dependencies and data instructions, and reconcile its headline to the PDF.
   Keep licensed responses/API keys out of the public repository. No new
   submission command or PDF was created in this assessment.
5. **Use the remaining time on risk and capacity rather than more selection.**
   They are explicit weaknesses in the current evidence. Adding more high-Sharpe
   candidates expands selection exposure without answering those questions.

The selected monthly SPY pilot cannot produce 30 independent monthly clusters
before the hackathon deadline. A Monday test occurs after submission and adds
one closure, not confirmation. Present the future protocol as future work.

## The Massive bonus requires a separate evidentiary focus

The [bonus brief](https://www.gqhacks.com/tracks/systematic-trading/massive) weights
novel hypothesis and rigor at 30 points each, sealed replication 20, trade
realism 10 and communication 10. It requires an 8-K-to-options rule from its
strategy menu; S18's prediction tickets cannot replace that experiment.

Our original 8-K study has committed hypotheses, placebo controls, fixed
horizons and a sealed-window forecast. Its H1 recent sample is insufficient;
H2 is null with a sign reversal. That supports a rigorous null note, not a
profitable 8-K strategy. The forecast missed H1 event counts and H2's sign;
report those misses. Hypothesis wording, saved verdict tables and the note use
different gross/net and insufficiency labels: reconcile them explicitly without
changing the frozen test or inventing sealed results.

## Validation status

**Share with caveats.** Track rules were verified on the rendered public pages.
S18/S11 numbers inherit the prior independent audit; S20–S23 are attributed
saved results, not newly certified performance. No official judge score,
clean-environment success, protected-window result or executable live Sharpe is
claimed. The absence of an existing reliable edge does not prevent an honest
research paper; it prevents marketing that paper as proof of profitable trading.
