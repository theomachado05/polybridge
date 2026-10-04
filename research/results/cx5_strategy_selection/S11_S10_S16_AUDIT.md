# S11 / S10 / S16 independent strategy-selection audit

Audit date: 2026-10-04. Read-only review of existing code, metadata and published results; no network, new prices, raw forward data, protected OOS files, parameter search, original-study edits or Git mutations. **This is selection discovered on reused history, not a fresh out-of-sample confirmation.**

## Recommendation

**Prioritize S11's same-event nested threshold ladders for the paper. Use Gold first-passage price markets as the main historical micro-market family, with WTI as the comparison.** The exact historical cases are Polymarket `gc-hit-jan-2026` and `gc-hit-jun-2026`; the smaller later cases are Gold/XAUUSD August 2026 event `746375` and WTI August 2026 event `746379`. Keep GC futures and XAUUSD spot as separate instruments, and keep each observation window and resolution source separate. The recommended mechanism is logical consistency across thresholds of the *same* underlying, source and window, not forecasting the direction of Gold or buying every “Gold” market.

For two increasing thresholds L < H, the event “hit H during this window” implies “hit L during this window.” Consequently NO(H) + YES(L) pays at least $1. For decreasing thresholds the implication reverses. A cost below that floor can be a real edge **if the full resolution rules establish the implication and both legs can be bought at the displayed prices**. This is a stronger mechanism than a correlation or a lag regression. The archived results justify this research focus; they do not yet establish an executable, funded Sharpe of 2–7.

The one existing live threshold example is Bitcoin `what-price-will-bitcoin-hit-before-2027`, pair `1343228>1343220`. It provides a useful execution comparison, not evidence that Gold's large historical modeled profits were fillable. Its maximum quoted profit is only $0.11.

## Evidence ranking

Points below mean cents of P&L per $1 contract. Sharpe labels describe the actual calculation, rather than calling all of them funded daily returns.

| Rank / candidate | Existing 1x result | Chronological held-out slice | Interpretation |
|---|---|---|---|
| 1. S11 violation, gap-close exit | 448 entries, 199 dates; +5.385 points, date-bootstrap CI [4.139, 6.755]; $2,412.52 modeled P&L; reported Sharpe **6.7368** | 21 entries, 14 dates; +7.806 points [2.499, 13.693]; Sharpe **4.0678** | Positive modeled candidate. Sharpe assigns eventual P&L to entry dates; no entry was print-checked. Entry selection also uses later same-day signals. |
| S11 violation H | Same 448 entries; +8.610 points [6.448, 10.894]; reported Sharpe 6.1043 | 21 entries; +15.053 points [3.520, 26.876]; Sharpe 4.1721 | Alternative terminal marks, not verified settlement proceeds. It reuses the gap-close entry cap even though holdings last longer. |
| 2. S10 oil weekend information transmission | Primary V0: 421 entries; +0.137 gross points, −2.558 net points [−2.749, −2.332]; annualized **weekend** P&L Sharpe −13.3948 | 42 entries on only four traded weekends; −2.142 points; Sharpe −5.3592 | Useful information-arrival mechanism; no positive primary trading edge after costs. All six primary variants lose at 1x. |
| S10 stale-question hold extension | 2,154 resolved entries; −2.122 net points; question-cluster CI [−4.282, 0.129] | 332 entries / 19 questions; +0.372 points [−2.823, 4.590]; reported Sharpe 0.3021 | A weak positive slice, not a 2–7 Sharpe candidate. OOS turns negative at 2x; unresolved entries were omitted. |
| 3. S16 Kalshi own-quote overnight fade | 98 entries, 64 dates; +0.796 gross points, −10.427 net points [−12.910, −8.089]; session P&L Sharpe −5.1373 | 66 entries, 35 dates / 50 sessions; −12.284 points [−15.434, −9.364]; Sharpe −10.7171 | Executable-side price diagnostic decisively rejects the fade. Candle quotes have no sizes and can be six hours old. All four variants lose at 1x. |

S11 propagation is also negative: P0 ALL −1.051 points [−2.994, 1.271], Sharpe −0.8982; OOS four entries lose. Its positive sibling-response event study is not a trading result. S10's oil lead/lag slopes and S16's selected quoted-mid reversal tests are likewise statistical response measurements, not funded strategy Sharpes.

## Independent numerical checks

Using only published trade/equity CSVs, I independently reproduced:

- S11 ALL 1x: aggregate `100*pnl_close` by entry date, insert zeros between the first and last entry, and calculate mean / sample standard deviation × √365: **6.7368214123**, $2,412.5150195, 371 calendar days. OOS gives **4.0678469858**. This is calendar-day aggregation, not an annualized trade-level Sharpe, but the profit is assigned before it is earned.
- S10 V0 ALL 1x: aggregate by the 36 weekend keys, insert nontraded weekends, and annualize with √52: **−13.3948494324**, P&L −$1,077.0497704. The CSV's `daily_sharpe=−1.8575314` is the **unannualized weekend mean/SD**, not a separate funded daily curve.
- S16 V0 ALL 1x: aggregate over all 249 session keys and annualize with √252: **−5.1373097488**, P&L −$1,021.8499900. Its `daily_sharpe=−0.3236201` is an unannualized session ratio.
- All **35 existing pure-fixture tests passed**: `.venv/bin/python -B -m pytest s11_bundles/tests s10_weekend_lag/tests s16_kalshi_quotes/tests -q -p no:cacheprovider`, from `research/`. This checks the existing formulas and fixtures; it does not validate historical execution or the omitted accounting properties below.

No reviewed artifact supplies a validated daily mark-to-market NAV, including outstanding positions, entry fees, idle capital and cash constraints. Therefore there is **no independently established funded daily Sharpe of 2–7 in this three-study review**.

## S11 findings and limits

**High: entry decisions use later same-day information.** [run.py:218](/Users/theomachado/gatorquant/research/s11_bundles/run.py:218) sorts *all* of a day's episodes by edge before enforcing the cap and one-open-position rule. I executed that exact function extracted from the source on a two-row fixture: bundle A fires at 09:00, closes at 10:00, and fires more strongly at 13:00, closing at 14:00. The prefix through 09:00 selects the 09:00 trade; the full day selects only 13:00 and erases the earlier decision. A causal policy cannot do this. The existing cap test checks the count/overlap properties but misses this prefix invariant. This finding does not depend on prices or alternative strategy parameters.

**High: positive modeled fills lack execution evidence.** All 884 archived trade rows say `prints=not checked`; verified/not-verified/uncheckable counts of zero mean the check was skipped, not that every entry was verified. [run.py:419](/Users/theomachado/gatorquant/research/s11_bundles/run.py:419) and [config.py:58](/Users/theomachado/gatorquant/research/s11_bundles/config.py:58) specify the check and success criterion. The primary has 21 OOS entries against the required 30, and zero print-verified entries. It fails its stated historical success criteria. A trade print at a compatible price would still not prove simultaneous quantity on every leg.

**High: metadata matching does not prove the settlement implication.** [universe.py:31](/Users/theomachado/gatorquant/research/s11_bundles/universe.py:31) retains titles but drops full descriptions/resolution rules; none of the 2,564 archived market records has a description. [universe.py:73](/Users/theomachado/gatorquant/research/s11_bundles/universe.py:73) also replaces the actual date phrase when building strike templates, despite the docstring saying it keeps dates. That can incorrectly combine different windows if such questions share an event; I did not establish such a mismatch among the inspected commodity examples. `negRisk` and an event title alone also do not establish exhaustive, exactly-one coverage, particularly for augmented sets or a live universe that has filtered out closed members ([universe.py:133](/Users/theomachado/gatorquant/research/s11_bundles/universe.py:133), [universe.py:242](/Users/theomachado/gatorquant/research/s11_bundles/universe.py:242)).

**Medium: the reported Sharpe and drawdown are not funded daily NAV statistics.** [run.py:293](/Users/theomachado/gatorquant/research/s11_bundles/run.py:293) attributes all realized/terminal P&L to entry dates, uses a fixed maximum one-day opening cost as K, and constructs K + cumulative dollar P&L. It does not mark open holdings daily or reserve lifecycle cash. Changing a fixed denominator alone would not change this mean/SD Sharpe; timing, fees and executable sizing matter. H uses the same gap-close-selected entries without rechecking outstanding holdings through terminal marks ([run.py:399](/Users/theomachado/gatorquant/research/s11_bundles/run.py:399), [report.py:74](/Users/theomachado/gatorquant/research/s11_bundles/report.py:74)).

All 448 archived primary rows have `settled_by=marked`. The primary can still close at the gap; that field describes the H terminal alternative. Consequently the H label “hold to result” is misleading for this snapshot: none of those terminal alternatives uses a verified result. Entry token costs also exclude entry fees, and future terminal times are absent from the trade export.

**Medium: current artifacts are mixed generations.** `trades.csv` and `metrics.csv` have mtime 03:17:32 UTC, whereas `episodes.csv` has mtime 04:14:22 UTC and 4,202 episodes. `tables.md` describes 1,116 episodes across costs. Current `cap` applied to current 1x episodes gives 1,425 entries, not the archived 448. The published primary trade/metric headline is reproducible, but the current episode file is not its original run manifest.

I could uniquely match all 448 archived trades to rows in the newer episode file. On that **provisional mixed-generation reconstruction**, all have finite gap exits: median holding time 0.558 hours, 28 exceed 24 hours, maximum 219.77 hours. Assigning profits to those exit dates reduces the fixed-K ALL Sharpe to **6.10065** (2x: 5.37024). Peak simultaneous token cost is $658.20, below the published $1,093.45 base; thus **underfunding is not proved for these primary entries**. These checks are not corrected funded returns: the source generation differs, entry/exit path marks are unavailable, and entry fees/MTM remain omitted. They should be repeated against one consistent archived run before citation.

**Concentration and dependence:** strike ladders produce $1,843.73 / **76.4%** of primary modeled profit; date ladders $548.33; negrisk $20.45. Gold GC January/June contribute **$835.74 / 34.6%** across 112 entries, with only 54 distinct entry dates between them. The top five events contribute 57.0%. OOS has only five events; Gold/XAUUSD August and WTI August produce **68.4%** of OOS P&L on three distinct entry dates. Date resampling does not remove repeated exposure to one event's prices and terminal outcome. These are reasons to focus the paper's mechanism and cluster inference by event as well as date, not evidence of broad diversification.

**Cost robustness is not cohort-matched:** 2x recomputes violation episodes and selects a smaller, stronger-edge entry set (244 versus 448). Its +7.420 points and Sharpe 6.0054 are useful modeled screening diagnostics, but not proof that the same 448 trades survive doubled execution costs. The current newer episode generation must not be used to reconstruct a supposedly identical cost cohort.

**Historical spread assumption:** all three kinds use 0.005 half-spreads calibrated from the first live hour on October 3, applied to earlier history ([run.py:38](/Users/theomachado/gatorquant/research/s11_bundles/run.py:38), `calibration.json`). This is a transparent model assumption, not an observed historical spread. The runner also does not trim cached series to configured history boundaries ([run.py:69](/Users/theomachado/gatorquant/research/s11_bundles/run.py:69)); three archived entries precede the stated October 1 start, and the Sharpe span is the first-to-last entry rather than the fixed research window.

**Live capacity:** 23 snapshots / 5,543 checks find two distinct quoted opportunities, both meeting the minimum order: BTC $0.11 maximum profit on 481.79 contracts and USA–Mexico negrisk $0.03 on 69 contracts. Sum of per-opportunity maxima is $0.14, not repeated profit on every snapshot. BTC's best edge is 0.023 cents/token; USA–Mexico 0.04 cents/token. [live.py:58](/Users/theomachado/gatorquant/research/s11_bundles/live.py:58) correctly walks the displayed YES books, subject to its implied NO/mint execution model. Sequential book batches discard exchange timestamps and are treated as one snapshot ([live.py:91](/Users/theomachado/gatorquant/research/s11_bundles/live.py:91)); neither observed persistence nor depth proves atomic fills or capital recycling. Fees, rounding, legging and quote disappearance are material at these tiny edges.

## Why S10 and S16 belong in the paper as controls

S10 supports *information transmission*, not profitable stale-price trading. The primary oil event-index slopes are positive, but the typical signed follower change is much smaller than the round trip. 68% of primary entries have a flat 15-minute history; only 17/421 have compatible prints, and verified net performance is also negative. In the mechanism extension, active-to-thin response is positive, while thin-to-active also predicts response; this weakens a simple claim that passive stale quotes are easy pickoffs. Its 2,340 question-pair trades average +0.069 gross versus −2.229 net points. No existing BTC subdirectory result was found, so the presence of BTC evaluator source is not a positive BTC backtest.

S10's hold extension drops 186 unresolved entries ([hold.py:59](/Users/theomachado/gatorquant/research/s10_weekend_lag/hold.py:59)), assigns settlement P&L to entry dates through its generic book evaluator, and shares outcome risk across repeated questions. Its positive OOS mean has wide question-cluster uncertainty and reverses at 2x. The primary capital-base curve loses more than 100% of its nominal base, so its negative Sharpe is a diagnostic, not a feasible unrestricted funded path.

S16 is especially useful as an **execution/adverse-selection control**. [run.py:47](/Users/theomachado/gatorquant/research/s16_kalshi_quotes/run.py:47) uses the correct sides: sell at bid / buy back at ask for a rise, and the mirror for a fall, plus both fees. Selected primary entry spreads have median **5.0 points** and mean **10.49**, versus a 1-point median over ordinary market-sessions. The mean round-trip spread cost is 8.684 points and fees 2.539, swallowing the 0.796-point gross reversal. This conditional spread widening is direct evidence against treating a large midpoint move as free insurance premium. The six-hour quote-age allowance, absent depth and five dropped primary entries with no exit quote limit execution inference; strict 15-minute V3 still loses −6.433 points. Existing cross-venue same-night tests compare mid responses, not simultaneously funded arbitrage, and title/twin matching does not independently establish exact settlement identity.

S16's 327.5% nominal-base drawdown and S10's >100% losses also reveal that generic `closure_metrics` ([run.py:136](/Users/theomachado/gatorquant/research/s6_monday_fade/run.py:136)) reports additive losses over an initial fixed base, not a solvent, compounded NAV. These negative results remain valid rejection evidence for the modeled trade; their numerical ratios should not be relabeled live strategy performance.

## Defensible claim and evidence still needed

The paper can state: **nested commodity thresholds exhibit large positive modeled consistency trades in reused historical prices, while related information-lag/fade trades lose after costs and observed contemporaneous bundle opportunities are tiny.** It cannot currently state that an executable funded strategy has a confirmed Sharpe of 2–7.

A decisive follow-up needs a consistent immutable run, full point-in-time rule identity, sequential causal entry replay, both outcome-token books with timestamps/depth and fee/rounding treatment, all-leg execution evidence, and a daily cash/mark ledger through actual close or resolution. A genuinely new confirmation period must follow the micro-market selection made here; existing labeled OOS should remain a reused historical diagnostic. These are measurement and accounting requirements, not a recommendation to tune thresholds until a desired Sharpe appears.

## Source fingerprints

SHA-256 at review time (full values allow the parent to distinguish subsequent concurrent study updates):

```text
S11 run.py        bdbff592e31225717a4c308d10baccc36d57804b8b14de3f15d03afae887e06a
S11 trades.csv    0d5d458efd35951b00da6b9b3ec88263d9da55b6ee3becaba165fa18f135d681
S11 metrics.csv   97edc8ddeeee7721de1a6b15bdec04b4573172bef5e91e99fd0f6d569b727f35
S11 episodes.csv  6b055a948a71a39ac08a8a558812368f0cab5488c93082b1a8c119c9b3658307
S10 metrics.csv   b02ac777977ffc3d6db4a745c78f47e22e2e5e521abcdd4209ad416665fe9949
S10 trades.csv    99d1c467914b25ce97c046ebe9ff7a05b51b379e8f097c3bd9394aa4b5b7a577
S16 metrics.csv   c2e6c1ce7cac3a9f01487860c9af4d0b292933f070bb6bbc52a4d1b879d3bc23
S16 trades.csv    ef3ea98ea5a0551a0d2cf0247a32aa9d9946ad09e1a8fef964025a831026f050
```

## Current-generation appendix — 2026-10-04 04:56 UTC

This bounded follow-up **supersedes the earlier snapshot's counts, print-status and concentration claims for the current S11 generation**. The preceding analysis and fingerprints remain a record of the archived 03:17 generation. S10/S16 were not rerun or re-audited here. There were no network calls or original-study edits.

The newer S11 output now has 1,425 primary 1x entries and does check prints. Its current cap output reconciles to the 1x episode CSV, resolving the earlier generation mismatch for this count. The current source still ranks each full day's episodes by edge before processing them ([run.py:223](/Users/theomachado/gatorquant/research/s11_bundles/run.py:223)). Re-executing the *current* function on the same causal-prefix fixture still selects only the 13:00 trade from the full day, versus the 09:00 trade from the prefix. The causal defect therefore persists. `perf` also continues to assign eventual P&L to entry dates with a fixed opening-cost denominator; the drawdown convention changed, but it remains an additive diagnostic without daily position marks.

### Positive current results, independently reproduced

I recomputed means, P&L, entry-date Sharpe and the exact date-bootstrap intervals (2,000 draws, seed 11) directly from current `trades.csv`. All figures below match current `metrics.csv`.

| Primary gap-close trade, 1x | Entries / dates | Mean net points, 95% date CI | Modeled P&L | Entry-date diagnostic Sharpe |
|---|---:|---:|---:|---:|
| ALL, all entries | 1,425 / 326 | +8.538751 [5.985285, 11.605870] | $12,167.72 | **5.383332** |
| OOS, all entries | 94 / 46 | +6.152748 [3.351197, 8.723628] | $578.36 | **7.381785** |
| ALL, print-supported | 99 / 71 | +3.889872 [2.493363, 5.430447] | $385.10 | **4.640474** |
| IS, print-supported | 88 / 62 | +3.970667 [2.492565, 5.517820] | $349.42 | **4.944413** |
| OOS, print-supported | 11 / 9 | +3.243512 [0.617036, 7.086581] | $35.68 | **4.291301** |

Current ALL print classifications are **99 supported / 965 not verified / 361 uncheckable**; OOS is **11 / 70 / 13**. Thus the newer generation has positive print-supported modeled results, including an OOS date-bootstrap lower bound above zero. It must not be dismissed as “no checked prints.” It still has only 11 supported OOS entries, below the fixed success requirement of 30. At 2x the supported ALL subset is 79 entries, +4.337569 points [2.619875, 6.196986], Sharpe 4.362370; supported OOS is six entries, +2.386105 points **[−2.051120, 6.981856]**, Sharpe 2.933652. The 2x cohort is selected again rather than being an identical entry cohort.

### What print support proves

The checker uses **±600 seconds around entry**, not a strictly after-entry window: S11 calls `s6_monday_fade.run.verify`, whose [timestamp test](/Users/theomachado/gatorquant/research/s6_monday_fade/run.py:107) uses `abs(timestamp-at)`. It accepts compatible prices and directions, including NO prints converted into YES terms. [run.py:425](/Users/theomachado/gatorquant/research/s11_bundles/run.py:425) checks **both legs** of a monotone pair; baskets require the compatible classification on every member; `combine` returns supported only when all are supported. Each leg needs at least one compatible print. The code discards returned size in [verify_leg](/Users/theomachado/gatorquant/research/s11_bundles/run.py:340), so it does not establish the assumed 100 contracts on every leg.

The prints can precede the signal, and different legs' qualifying prints can be up to 20 minutes apart. The export does not identify a synchronous, depth-supported all-leg fill, nor does this entry check verify the unwind prices. Prices and round-trip P&L still come from the historical midpoint/half-spread model. **Print-supported is meaningful stronger evidence than an unchecked midpoint, but is not a historical executable return series.**

### Updated concentration and market recommendation

The larger all-entry sample is less concentrated: 123 events; top event 10.6%, top two 16.3%, top five 29.7% of total net profit. The **supported** subset has 45 events, with top two contributing 23.9% and top five 48.2%. Its family contributions differ materially from the old snapshot:

| Family, supported 1x ALL | Entries | Modeled profit | Share of supported net profit |
|---|---:|---:|---:|
| Cumulative deadline ladders | 65 | $276.73 | **71.9%** |
| Threshold ladders | 33 | $91.68 | 23.8% |
| Negrisk | 1 | $16.69 | 4.3% |

The largest supported ALL events are `us-strikes-iran-by` (10 entries, $49.05), `si-hit-jun-2026` (four, $42.99), `trump-announces-us-blockade-of-hormuz-lifted-by` (four, $37.95), and `next-round-of-us-iran-peace-talks-byptptpt-20260623022722982` (seven, $30.95). Supported OOS contains seven events. One July Fed basket earns **46.8%** of its net profit; the top two events earn 69.2%. OOS date ladders earn $21.47 across eight entries, the one basket $16.69, and two threshold trades **lose $2.49**. The three supported OOS US–Iran peace-talk entries all occur on September 22 and sum to $4.45; they are not three independent confirmation dates.

**Material update to the evidence-first paper focus:** prioritize **same-event cumulative “by deadline” ladders for timestamped geopolitical milestones**, especially the US–Iran military/diplomatic event families named above. Keep the same-event commodity threshold ladders as the clean payoff-logic comparison, rather than calling Gold the strongest currently print-supported subgroup. This is an exploratory selection on reused history, not a new tested strategy rule or proof of a geopolitical premium.

The cumulative payoff argument requires the *same underlying milestone* and resolution convention, with early YES implying late YES. Current identity evidence is still title/template matching within an event, parsed deadlines and inferred years ([universe.py:90](/Users/theomachado/gatorquant/research/s11_bundles/universe.py:90)); `bundles.json` is unchanged and still omits full rule descriptions. The current all-entry sample includes **four flagged broken date implications**, with −$194.60 aggregate primary P&L. None is in the supported subset. They demonstrate that the title rule does not guarantee a valid payoff floor for every included pair; the cause cannot be established from this retained metadata alone. Full point-in-time rules remain necessary before calling any candidate an arbitrage.

Overall recommendation: S11 remains the strongest positive modeled candidate among S11/S10/S16, and its positive supported ALL/OOS statistics deserve reporting. The causal entry defect, entry-date accounting, modeled spreads, nonsynchronous prints and small supported OOS cohort still prevent a confirmed funded daily Sharpe claim. The date-ladder focus follows the newer evidence; the original Gold recommendation belongs to the archived snapshot.

Current fingerprints, sampled at 04:56 UTC:

```text
run.py        923436888ba160b51c105d33c65d3e4ad8c9566b624949285fe136772c9d08b1
report.py     c007066102c8131d15f2dca998537f3f21f90bf4ed1547a407841a53112f6302
config.py     cd7bcee677182e6fa6246eb776eb3276e0b04772fca869298dddf2903d831ea8
bundles.json  b3452fc63971cb227b5601ea48e5a9f4ad965dedd6ea15fc64a9668bad776d0a
trades.csv    dd4f1a9e9dd267607718dcf299704638b024f754d5c4a124b9ccd886458419da
metrics.csv   849d8867fa41bf2f248daeffc63ab0c15a740d1e05b7bc91dfc72e905363f1df
episodes.csv  6b055a948a71a39ac08a8a558812368f0cab5488c93082b1a8c119c9b3658307
tables.md     ffa906ea1e72d095a76734a6bbd7bd46173077872ef4f36e1f6472d35f3304f6
```
