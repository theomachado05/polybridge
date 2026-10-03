# In-sample results, 2024-01-01 to 2025-12-31

All numbers come from the CSV files in this folder, produced by `research/export_in_sample.py` (one run, no parameter changes after seeing results). Out-of-sample window not run. Atlas not run (stretch goal), so there is no atlas table here.
Edge = event mean minus placebo mean, P&L per $1 of spot at entry, baseline spec (3-6m expiry, 5% OTM, entry "post"), 97.5% bootstrap CI.

## Sample
| Family | 2024 | 2025 | Total |
|---|---|---|---|
| hedge (H1) | 18 | 18 | 36 |
| opportunity (H2) | 14 | 10 | 24 |

- Total events: 60. Filings excluded as cross-family or fitting neither family: 5.
- Events dropped before pricing (16 event/bucket drops): 1m, ATM pair did not trade near the pre-event session: 8; 2m, ATM pair did not trade: 1; 2m, no expiry 46-80 days out: 5; spot not recoverable from the chain: 2.
- Timing mode: conservative (all 60 filings treated as public after the close; no EDGAR acceptance times).
- Placebo: 120 ordinary days per family. Pricing drops among placebo: 34 (hedge), 39 (opportunity) event/bucket pairs.
- Variants counted for one tag over the sensitivity grid: 810.

## H1 hedge, protective put: NULL
| Horizon | n events / placebo | Edge | 97.5% CI | Ratio diff (events - placebo) | pnl_ok | ratio_ok |
|---|---|---|---|---|---|---|
| 21 | 32 / 106 | +0.0007 | [-0.0270, +0.0291] | +0.019 | False | True |
| 42 | 30 / 104 | +0.0049 | [-0.0451, +0.0577] | +0.209 | False | True |
| exp | 28 / 95 | +0.0333 | [-0.0301, +0.1012] | +0.121 | False | True |

No headline horizon has a CI excluding zero. Verdict as computed: NULL.

## H2 opportunity, cash-secured put: NULL
| Horizon | n events / placebo | Edge | 97.5% CI | Ratio diff (events - placebo) | pnl_ok | ratio_ok |
|---|---|---|---|---|---|---|
| 21 | 24 / 113 | +0.0009 | [-0.0068, +0.0089] | -0.171 | False | True |
| 42 | 24 / 111 | +0.0021 | [-0.0090, +0.0136] | -0.095 | False | True |
| exp | 23 / 99 | +0.0092 | [-0.0036, +0.0234] | +0.185 | False | False |

No headline horizon has a CI excluding zero. Verdict as computed: NULL.

## Parity decay (mean R = realized / priced, entry on pre-event session; full tables in `*_decay_*.csv`)
- Hedge events: R 0.68 at 1 session, 1.15 at 3, 1.04 at 10, 1.11 at 21, 1.36 at 42 (CI 1.03-1.68), 1.19 at 63, 1.18 at expiry. Placebo R stays between 0.92 and 1.15 at all horizons (42-session placebo 1.15, CI 1.00-1.32).
- Opportunity events: R 1.03 at 1 session, 0.87 at 5, 0.77 at 21 (CI 0.45-1.13), 0.91 at 42, 1.11 at 63, 1.06 at expiry. Placebo R between 0.86 and 1.01.
- All event-vs-placebo ratio comparisons rest on 23-34 events; the event CIs overlap the placebo's at every horizon.

## Sensitivity (h=21, edge by bucket x entry x OTM; `*_sensitivity.csv`)
- Hedge: edges range from -0.0091 to +0.0062 across the 18 cells, signs mixed; no CI computed per cell. Baseline cell (3-6m, post, 5%) +0.0007. No spike; no consistent sign.
- Opportunity: edges are positive in all 18 cells, from +0.0008 (3-6m, post, 3%) to +0.0124 (1m, post, 3%). Larger for shorter expiries, smaller for 3-6m. Cell sizes 8-24 events.

## Costs (mean P&L per $1 of spot, events only; `*_costs_h21.csv`, `*_costs_h42.csv`)
| Family, horizon | n | gross | net, 5% haircut 1x | net, haircut 2x | mean half-spread cost | net of spread | median leg volume |
|---|---|---|---|---|---|---|---|
| hedge, 21 | 34 | 0.0210 | 0.0181 | 0.0152 | 0.0029 (34 quoted) | 0.0184 | 33.5 |
| hedge, 42 | 34 | 0.0448 | 0.0419 | 0.0390 | 0.0023 (32 quoted) | 0.0274 | 33.5 |
| opportunity, 21 | 24 | 0.0083 | 0.0054 | 0.0026 | 0.0029 (24 quoted) | 0.0054 | 48.5 |
| opportunity, 42 | 24 | 0.0130 | 0.0102 | 0.0073 | 0.0026 (24 quoted) | 0.0104 | 48.5 |

Quote endpoint worked (no fallback to client=None). Cost-table row counts (34) differ from the pass-check n (32 at h=21, 30 at h=42) for hedge; the cost table does not drop rows with undefined P&L, the pass check does. Means are over the listed rows; spread means cover quoted rows only.

## Caveats stated by the numbers
Samples are 23-36 events per family. Static universe, last-trade marks, inferred spot (see HYPOTHESIS.md section 8). Neither hypothesis passes the pre-registered rule in-sample.
