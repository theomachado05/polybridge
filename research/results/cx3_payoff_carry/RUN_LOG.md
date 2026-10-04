# Run log

- First phase: inspected source, schema/header-only cache inventory and contractual
  metadata. No new price/outcome values or forward/raw were read.
- Freeze accepted by root in `6e33ff0`. Git log for owned paths:
  `6e33ff0bcd51780b4718da6fe67c72fbbc428737 2026-10-03T23:46:48-04:00 research: freeze option insurance and payoff carry tests before evaluation`. Root owns final commit and push; this agent made no
  Git mutations and changed only its two assigned directories.
- Audit ran 2026-10-04T03:59:29Z to 2026-10-04T03:59:33Z, 4.55 seconds.
  Command: `.venv/bin/python -m cx3_payoff_carry.run` from research/. Exit code 0.
  Financial outcome: not_testable; all IS/OOS 1×/2× financial metrics NA.
- Final synthetic validation: `.venv/bin/python -m pytest cx3_payoff_carry/tests -q`.
  Exit code 0, **35 passed in 0.08 seconds**. These cases verify payoff orientation,
  refund state risk, causal clocks, displayed depth, fees, sequential/partial failure,
  price drift, venue cash, collateral delay, source publication and portfolio marks.
- Sources: S1/S4/S5/S9/S11 cached NPZ timestamp arrays only; full filenames/schemas,
  row/date coverage and metadata hashes are in inventory.csv and metadata_inventory.csv.
  No numerical PM price or Kalshi bid/ask array was opened. Reused S1 CSV result values
  were audited as an already-known exploratory baseline, never relabelled a fresh trial.
- Read-only C++ inspection: market.hpp lines 25–27 and 33–44; algos/opportunity.hpp
  lines 40–42 and 87–98. No engine edits.
- Official documentation checked via web after freeze on 2026-10-04: Polymarket
  resolution, negative-risk, prices/order-book and fee pages; Kalshi fee-schedule PDF.
  Links are saved in run_meta.json. No venue market-data pulls or Kalshi API calls.
- Failures: initial header inspection called a private NumPy helper unavailable in
  the bundled version; replaced by documented array-header readers, without reading
  array prices. Initial chart import warned that default font/cache paths were not
  writable, used a temporary cache and succeeded. The runner now places chart/font
  caches in the owned ignored .cache folder. inventory_read_log.json records zero
  cache-read failures for the completed snapshot.
- Missing input is the substantive result: full as-of rules; direct historical PM
  books/depth; publication/first-observed archive; fee cash-flow archive; dispute and
  collateral-release records; executable daily marks. No candidate strategy price
  scan was attempted and no unavailable mark was imputed.
- Protected forward and sealed OOS windows untouched. Network market-data volume:
  0 bytes. No recorder changes, restarts or collection. Prospective start remains
  2026-10-05T00:00:00Z, requiring root coordination.
- Summary values were read back from saved inventory, metrics and audit CSVs before
  writing SUMMARY.md. Synthetic examples are confined to tests; trades/equity CSVs
  have headers only. Figures contain an explicit unavailable-data message.
