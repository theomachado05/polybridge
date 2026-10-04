# Fresh-market accuracy, options repriced at the Polymarket timestamp (exploratory)

Alignment sensitivity check chosen after the original test was seen (see `research/fresh_accuracy_synced/METHOD.md`, Amendment 1). It measures how the comparison changes when the option and Polymarket timestamps match. It does not identify trader bias or true quote-update delays, and it does not change the pre-registered verdict.

Each option leg is the last NBBO at or before the Polymarket history timestamp. The original strikes k1, k2 are held fixed; 5 valid rows needed a step outward (steps: {0.0: 7102, 1.0: 5}). All comparisons use the same surviving rows.

Scored rows in the primary study: 7111. Synced option probability valid on 7107; dropped 4 (no_chain 4).

Differences are row-weighted means over resolution-date clusters, 95% bootstrap intervals (10,000 draws, seed 20261004). Positive means the second forecast was more accurate.

## All valid rows (n = 7107, dates = 89)

| | PM | options at snapshot | options at PM timestamp |
|---|---|---|---|
| mean Brier | 0.09388 | 0.08310 | 0.08358 |
| mean log score | 0.30454 | 0.27274 | 0.27569 |

| difference | Brier | log score |
|---|---|---|
| PM minus synced options | +0.01029 [+0.00592, +0.01532] | +0.02885 [+0.01283, +0.04442] |
| snapshot options minus synced options | -0.00049 [-0.00070, -0.00029] | -0.00295 [-0.00514, -0.00130] |
| PM minus snapshot options (same rows) | +0.01078 [+0.00641, +0.01582] | +0.03180 [+0.01699, +0.04709] |

## Rows with pm_age_s <= 30 (n = 669, dates = 15)

| | PM | options at snapshot | options at PM timestamp |
|---|---|---|---|
| mean Brier | 0.08769 | 0.08653 | 0.08662 |
| mean log score | 0.28268 | 0.27581 | 0.27658 |

| difference | Brier | log score |
|---|---|---|
| PM minus synced options | +0.00107 [-0.00123, +0.00447] | +0.00610 [+0.00002, +0.01525] |
| snapshot options minus synced options | -0.00009 [-0.00088, +0.00046] | -0.00077 [-0.00336, +0.00099] |
| PM minus snapshot options (same rows) | +0.00116 [-0.00149, +0.00516] | +0.00687 [-0.00044, +0.01812] |

