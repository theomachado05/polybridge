# Out-of-sample results, 2026-01-01 to 2026-08-31

The single out-of-sample run of the pre-registered 8-K study (`research/HYPOTHESIS.md` §4), executed after the method freeze (git tag `method-freeze`). Produced by `research/export_oos.py`; every number below is generated from the computed tables, with no edits. Started 2026-10-03 13:00 EDT.

Same `StudyConfig` as in-sample (baseline 3-6m expiry, 5% OTM, entry "post", 97.5% bootstrap CI, 120 placebo days per family), conservative timing, last session used for exits pinned to 2026-10-02. Edge = event mean minus placebo mean, P&L per $1 of spot at entry.

## Verdicts

| hypothesis | oos_verdict | in_sample_verdict |
|---|---|---|
| H1 hedge (protective put) | NULL | NULL |
| H2 opportunity (cash-secured put) | NULL | NULL |

## Sample

- Events: hedge 3, opportunity 8 (by month in `events_summary.csv`). Cross-family filings excluded: 2.
- Event/bucket pricing drops: 1m: ATM pair did not trade on or near the pre-event session: 1; 2m: ATM pair did not trade on or near the pre-event session: 1; 3-6m: ATM pair did not trade on or near the pre-event session: 1.
- Timing: {'conservative': 11}.
- Placebo days sampled: {'hedge': 120, 'opportunity': 120}; placebo pricing drops (event/bucket pairs): hedge 38, opportunity 53.
- Events late in the window have fewer completed exits by 2026-10-02 (42-session, 63-session and expiry horizons), so n falls at longer horizons; the n per horizon is in every table.

## H1 hedge, protective put: NULL

| horizon | n | edge | 97.5% CI | ratio_diff | pnl_ok | ratio_ok |
|---|---|---|---|---|---|---|
| 21 | 3 / 107 | +nan | [+nan, +nan] | +nan | False | False |
| 42 | 3 / 81 | +nan | [+nan, +nan] | +nan | False | False |
| exp | 1 / 65 | +nan | [+nan, +nan] | +nan | False | False |

Rule 1 horizons (CI excludes zero, predicted direction): none. Rule 2 horizons (ratio difference has the predicted sign): none. Passing needs both at 2 or more headline horizons. Verdict as computed: NULL.

In-sample (committed `results/in_sample/`) vs out-of-sample, headline horizons:

| horizon | n_events_in_sample | edge_in_sample | n_events_oos | edge_oos | edge_same_sign | ratio_diff_in_sample | ratio_diff_oos | ratio_same_sign |
|---|---|---|---|---|---|---|---|---|
| 21 | 32 | 0.0007 | 3 |  | False | 0.0187 |  | False |
| 42 | 30 | 0.0049 | 3 |  | False | 0.2087 |  | False |
| exp | 28 | 0.0333 | 1 |  | False | 0.1211 |  | False |

Parity decay (mean R, entry on the pre-event session, events with 95% CI; placebo mean):

| horizon | n | mean_ratio | ci_lo | ci_hi | n_placebo | mean_ratio_placebo |
|---|---|---|---|---|---|---|
| 1 | 3 | 1.859 |  |  | 113 | 0.931 |
| 2 | 3 | 1.894 |  |  | 110 | 0.871 |
| 3 | 3 | 1.448 |  |  | 112 | 0.83 |
| 5 | 3 | 1.75 |  |  | 112 | 0.865 |
| 10 | 3 | 1.52 |  |  | 113 | 0.836 |
| 21 | 3 | 1.324 |  |  | 111 | 0.958 |
| 42 | 3 | 0.613 |  |  | 84 | 0.923 |
| 63 | 1 | 0.601 |  |  | 78 | 1.3 |
| exp | 1 | 1.107 |  |  | 75 | 1.208 |

Costs (mean P&L per $1 spot; net edge = events minus placebo after the 5% haircut, and at 2x):

| horizon | n | n_gross | n_paired | gross | gross_paired | spread_cost_paired | net_spread_paired | net_haircut_1x | net_haircut_2x | net_edge_1x | net_edge_2x |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 21 | 3 | 3 | 3 | 0.0306 | 0.0306 | 0.0057 | 0.025 | 0.0268 | 0.023 | 0.021 | 0.02 |
| 42 | 3 | 3 | 3 | 0.0317 | 0.0317 | 0.0053 | 0.0264 | 0.0279 | 0.0241 | 0.0053 | 0.0042 |
| exp | 1 | 1 | 0 | 0.1044 |  |  |  | 0.1012 | 0.0979 | 0.0622 | 0.0615 |

## H2 opportunity, cash-secured put: NULL

| horizon | n | edge | 97.5% CI | ratio_diff | pnl_ok | ratio_ok |
|---|---|---|---|---|---|---|
| 21 | 7 / 90 | -0.0215 | [-0.0759, +0.0203] | +0.468 | False | False |
| 42 | 7 / 68 | -0.0138 | [-0.0729, +0.0260] | +0.272 | False | False |
| exp | 4 / 51 | +nan | [+nan, +nan] | -0.319 | False | True |

Rule 1 horizons (CI excludes zero, predicted direction): none. Rule 2 horizons (ratio difference has the predicted sign): ['exp']. Passing needs both at 2 or more headline horizons. Verdict as computed: NULL.

In-sample (committed `results/in_sample/`) vs out-of-sample, headline horizons:

| horizon | n_events_in_sample | edge_in_sample | n_events_oos | edge_oos | edge_same_sign | ratio_diff_in_sample | ratio_diff_oos | ratio_same_sign |
|---|---|---|---|---|---|---|---|---|
| 21 | 24 | 0.0009 | 7 | -0.0215 | False | -0.1713 | 0.4675 | False |
| 42 | 24 | 0.0021 | 7 | -0.0138 | False | -0.095 | 0.2725 | False |
| exp | 23 | 0.0092 | 4 |  | False | 0.185 | -0.3194 | False |

Parity decay (mean R, entry on the pre-event session, events with 95% CI; placebo mean):

| horizon | n | mean_ratio | ci_lo | ci_hi | n_placebo | mean_ratio_placebo |
|---|---|---|---|---|---|---|
| 1 | 7 | 2.391 | 0.97 | 3.811 | 95 | 0.914 |
| 2 | 7 | 2.5 | 0.978 | 3.947 | 95 | 0.97 |
| 3 | 7 | 2.327 | 1.066 | 3.722 | 95 | 0.952 |
| 5 | 7 | 2.155 | 1.248 | 3.255 | 93 | 0.964 |
| 10 | 6 | 1.798 | 0.781 | 2.861 | 91 | 0.992 |
| 21 | 6 | 1.569 | 0.85 | 2.301 | 90 | 1.102 |
| 42 | 7 | 1.172 | 0.667 | 1.632 | 67 | 0.9 |
| 63 | 5 | 0.624 | 0.195 | 1.117 | 59 | 0.97 |
| exp | 6 | 0.792 | 0.448 | 1.189 | 54 | 1.111 |

Costs (mean P&L per $1 spot; net edge = events minus placebo after the 5% haircut, and at 2x):

| horizon | n | n_gross | n_paired | gross | gross_paired | spread_cost_paired | net_spread_paired | net_haircut_1x | net_haircut_2x | net_edge_1x | net_edge_2x |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 21 | 7 | 7 | 7 | -0.0209 | -0.0209 | 0.0067 | -0.0276 | -0.0282 | -0.0355 | -0.0242 | -0.0269 |
| 42 | 7 | 7 | 7 | -0.0093 | -0.0093 | 0.0071 | -0.0164 | -0.0166 | -0.0239 | -0.0166 | -0.0193 |
| exp | 6 | 4 | 2 | -0.0106 | -0.0513 | 0.01 | -0.0612 | -0.0152 | -0.0197 | 0.0145 | 0.0139 |

## Notes

- Pass rule as pre-registered (§4, with the 2026-10-02 clarification of rule 2): rule 1 needs the 97.5% CI of the event-minus-placebo edge to exclude zero in the predicted direction at 2 or more of 21, 42 and expiry; rule 2 needs the event-minus-placebo mean R to have the predicted sign (H1 > 0, H2 < 0) at those horizons.

- Figures plot 95% bootstrap bands; the pass-rule CIs are 97.5%.

- This window was run once. `.done` in this folder records the run; `export_oos.py` refuses to run again.

## Reading note (appended after generation; no number changed)

- Blank cells and `nan` mean "not computed", not zero: the pipeline's `difference_board` computes an edge, its CI and the ratio difference only when both sides have at least 5 observations at that horizon (a rule in the code since the in-sample run). H1 has 3, 3 and 1 events at 21, 42 and expiry, so no H1 test is computable; H2 has 7, 7 and 4 (P&L), so its expiry P&L edge is not computable.
- In the in-sample-vs-OOS tables, `edge_same_sign` / `ratio_same_sign` print `False` where the OOS value is missing. Read those cells as "undefined", not as a sign flip. Where both values exist (H2 at 21 and 42, and the H2 ratio at expiry), the sign flipped at every one.
- With 3 (H1) and 8 (H2) out-of-sample events, these results carry very little statistical power; they are reported as computed, per HYPOTHESIS.md §4.
