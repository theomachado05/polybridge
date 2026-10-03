### hedge: pass check (97.5% CI)

| horizon | n_events | n_placebo | pnl_difference | ci_lo | ci_hi | ratio_difference | pnl_ok | ratio_ok |
|---|---|---|---|---|---|---|---|---|
| 21 | 32 | 106 | 0.0007 | -0.027 | 0.0291 | 0.0187 | False | True |
| 42 | 30 | 104 | 0.0049 | -0.0451 | 0.0577 | 0.2087 | False | True |
| exp | 28 | 95 | 0.0333 | -0.0301 | 0.1012 | 0.1211 | False | True |

### hedge: sensitivity at h=21 (edge, events minus placebo)

min -0.0091 (2m, pre, 5% OTM); max +0.0068 (3-6m, post, 10% OTM); positive cells 10 of 18

### hedge: costs (mean P&L per $1 spot; n_* = non-missing rows behind each mean)

| horizon | n_rows | gross | n_gross | net_haircut_1x | n_net_haircut_1x | net_haircut_2x | n_net_haircut_2x | spread_cost | n_spread_cost | net_spread | n_net_spread | median_leg_volume |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 21 | 34 | 0.021 | 32 | 0.0181 | 32 | 0.0152 | 32 | 0.0029 | 34 | 0.0184 | 32 | 33.5 |
| 42 | 34 | 0.0448 | 30 | 0.0419 | 30 | 0.039 | 30 | 0.0023 | 32 | 0.0273 | 28 | 33.5 |

### opportunity: pass check (97.5% CI)

| horizon | n_events | n_placebo | pnl_difference | ci_lo | ci_hi | ratio_difference | pnl_ok | ratio_ok |
|---|---|---|---|---|---|---|---|---|
| 21 | 24 | 113 | 0.0009 | -0.0068 | 0.0089 | -0.1713 | False | True |
| 42 | 24 | 111 | 0.0021 | -0.009 | 0.0136 | -0.095 | False | True |
| exp | 23 | 99 | 0.0092 | -0.0036 | 0.0234 | 0.185 | False | False |

### opportunity: sensitivity at h=21 (edge, events minus placebo)

min +0.0008 (3-6m, post, 3% OTM); max +0.0124 (1m, post, 3% OTM); positive cells 18 of 18

### opportunity: costs (mean P&L per $1 spot; n_* = non-missing rows behind each mean)

| horizon | n_rows | gross | n_gross | net_haircut_1x | n_net_haircut_1x | net_haircut_2x | n_net_haircut_2x | spread_cost | n_spread_cost | net_spread | n_net_spread | median_leg_volume |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 21 | 24 | 0.0082 | 24 | 0.0054 | 24 | 0.0026 | 24 | 0.0029 | 24 | 0.0054 | 24 | 48.5 |
| 42 | 24 | 0.013 | 24 | 0.0102 | 24 | 0.0073 | 24 | 0.0026 | 24 | 0.0104 | 24 | 48.5 |
