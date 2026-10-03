# Atlas (EXPLORATORY)

EXPLORATORY — HYPOTHESIS.md §5. Not confirmatory, not a headline.

119 tags × 5 strategies × 3 headline horizons; total variants = 96,390 (`variants.txt`: the full grid counted over all 119 tags); BH q-values across all rows.

- Window: in-sample only (cfg.study_start to cfg.study_end); the out-of-sample window is never used.
- Baseline spec, at most 15 randomly sampled events per tag, one shared 300-day placebo over TOP_100 (seed 11).
- Produced by `research/export_atlas.py`; columns: `tag, n_events, strategy, horizon, difference, ci_lo, ci_hi, p_value, q_value, exploratory`.

## How to read it

Every tag here has at most 15 events and is compared against one placebo shared across all 100 stocks, not against the same companies. Many bootstrap p-values sit at the resolution floor (1 / 4000), which pushes q-values down. A low q-value in this table is a lead for a future pre-registered test, not evidence. The one row that agrees with a confirmatory hypothesis is `restructuring_plan` × cash-secured put at expiry, which has the sign H2 predicts.
