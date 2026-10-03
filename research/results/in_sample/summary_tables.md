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
| exp | 34 | 0.0548 | 28 | 0.0518 | 28 | 0.0488 | 28 | 0.0076 | 7 | -0.0994 | 6 | 33.5 |

### hedge: paired cost summary and net-of-haircut edge (events minus placebo)

| horizon | n | n_gross | n_paired | gross_paired | spread_cost_paired | net_spread_paired | gross | median_leg_volume | net_haircut_1x | n_placebo_1x | net_edge_1x | net_haircut_2x | n_placebo_2x | net_edge_2x |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 21 | 34 | 32 | 32 | 0.021 | 0.0026 | 0.0184 | 0.021 | 33.5 | 0.0181 | 106 | 0.0011 | 0.0152 | 106 | 0.0015 |
| 42 | 34 | 30 | 28 | 0.0292 | 0.0019 | 0.0273 | 0.0448 | 33.5 | 0.0419 | 104 | 0.0052 | 0.039 | 104 | 0.0055 |
| exp | 34 | 28 | 6 | -0.0934 | 0.0061 | -0.0994 | 0.0548 | 33.5 | 0.0518 | 95 | 0.0336 | 0.0488 | 95 | 0.0338 |

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
| exp | 24 | 0.0265 | 23 | 0.0236 | 23 | 0.0207 | 23 | 0.0037 | 2 | -0.0015 | 2 | 48.5 |

### opportunity: paired cost summary and net-of-haircut edge (events minus placebo)

| horizon | n | n_gross | n_paired | gross_paired | spread_cost_paired | net_spread_paired | gross | median_leg_volume | net_haircut_1x | n_placebo_1x | net_edge_1x | net_haircut_2x | n_placebo_2x | net_edge_2x |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 21 | 24 | 24 | 24 | 0.0082 | 0.0029 | 0.0054 | 0.0082 | 48.5 | 0.0054 | 113 | 0.0011 | 0.0026 | 113 | 0.0014 |
| 42 | 24 | 24 | 24 | 0.013 | 0.0026 | 0.0104 | 0.013 | 48.5 | 0.0102 | 111 | 0.0024 | 0.0073 | 111 | 0.0027 |
| exp | 24 | 23 | 2 | 0.0023 | 0.0037 | -0.0015 | 0.0265 | 48.5 | 0.0236 | 99 | 0.0095 | 0.0207 | 99 | 0.0097 |
