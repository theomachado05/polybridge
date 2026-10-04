# Fresh-market accuracy, options repriced at the Polymarket timestamp (exploratory)

**Status: exploratory alignment sensitivity check, not pre-registered.** This check was chosen after the original fresh-accuracy test (`research/results/fresh_accuracy/`, verdict PASS) was seen. It measures how the comparison changes when the two forecasts are timestamped at the same instant. It does not identify trader bias, and it does not identify true quote-update delays on either venue. It is reported whatever it shows and does not change or replace the pre-registered verdict.

**Question.** In the fresh-accuracy test the option-implied probability is measured at the snapshot `snap_utc`, while the Polymarket price is the last per-minute `prices-history` point at or before the snapshot, which is `pm_age_s` seconds older (median 52 s, max 60 s on scored rows). Does the accuracy comparison change when the option probability is measured at the same instant as the Polymarket point?

**Rows.** Exactly the 7,111 rows of `research/results/fresh_accuracy/rows.csv` with `status == "scored"`. No row is added. The Polymarket price `pm_mid`, the outcome and the original option probability `p_mid` are taken from that file unchanged.

**Synced option probability.** For each row, the new instant is `t_pm = snap_utc - pm_age_s`. The option probability is recomputed at `t_pm` with the fresh_accuracy / arbscan code unchanged (`fresh_accuracy.rows.option_row`, which calls `arbscan.score.score_row`): same clean-expiry chain (Massive contract listing for the ticker and resolution date), same strike selection (neighbours k1, k2 of K, or the strikes just below and above), same stepping rule (a leg without a valid quote steps one listed strike outward, at most twice), each leg the last NBBO at or before `t_pm` (`timestamp.lte` at `t_pm`, newest first), valid only if bid > 0, ask >= bid and the quote is no more than 10 minutes (600 s) older than `t_pm`, `p = e^{rT}(C1 - C2)/w` with r = 4% and T from `t_pm` to 16:00 ET on the expiry, clipped to [0, 1]. Strikes may differ from the snapshot computation when quote validity differs at `t_pm`. A row whose synced computation does not return `scored` is dropped from every comparison and counted by reason.

**Comparisons** (on rows with a valid synced probability, and separately on the subset `pm_age_s <= 30`):

- mean Brier of PM, of options at the snapshot, and of options at `t_pm`;
- Brier differences PM minus synced options, and snapshot options minus synced options; PM minus snapshot options is also reported on the same rows;
- the same differences in log score (`LS(p) = -[y ln p + (1 - y) ln(1 - p)]`, p clipped to [0.01, 0.99]);
- inference: `fresh_accuracy.stats.cluster_boot`, bootstrap over resolution dates, 10,000 draws, seed 20261004, 95% percentile intervals, same weights for every series.

**Validation.** Before the synced run, the same code is run at `snap_utc` from the cached quotes and must reproduce the stored `p_mid` on every row.

Outputs: `research/results/fresh_accuracy_synced/{rows.csv, summary.json, SUMMARY.md}`. Code: `research/fresh_accuracy_synced/run.py`.

## Amendment 1 (2026-10-04, after the first synced run, before any further fetching)

The first synced run (commit `76dcf5b` method, run started 2026-10-04T08:37:49Z) re-ran the strike selection at `t_pm`. Its outputs are kept as `research/results/fresh_accuracy_synced/{rows_reselect.csv, summary_reselect.json, SUMMARY_reselect.md}`. The primary synced method is changed as follows, at the coordinator's request:

1. Each option leg is the last NBBO at or before `t_pm` (`timestamp.lte`), never the nearest quote in either direction. This was already the rule and is unchanged.
2. The original row's strikes k1 and k2 are held fixed. Only if a leg has no valid quote at `t_pm` does the original stepping rule apply, stepping that leg one listed strike outward from the original k1 (down) or k2 (up), at most twice. Implementation: `score_row` is called unchanged with the clean-expiry chain restricted to listed strikes at or below k1 and at or above k2, so the narrow bracket of K is exactly (k1, k2) and `pick_spread` steps outward from there. The number of rows that needed a step is reported.
3. Rows whose synced probability is not valid are dropped and counted by reason. Every comparison (PM vs snapshot options, PM vs synced options, snapshot vs synced options) is computed on the same surviving rows.
4. The check is labelled in METHOD and SUMMARY as an alignment sensitivity check chosen after the original test, which measures how the comparison changes when timestamps match and does not identify trader bias or true quote-update delays.
