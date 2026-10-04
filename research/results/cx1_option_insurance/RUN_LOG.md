# Run log

Generated 2026-10-04T04:10:02.596158+00:00.

Pre-outcome freeze: 6e33ff0 (2026-10-03 23:46:48 New York). Root sent FREEZE_ACK before prices were read.
Data-only/calendar amendment commit: c77233f, root acknowledged before any Massive request.
Same-session cash-ledger correction commit: e0b7bb1, acknowledged before final data completion and accounting run.
Latest method/config commit recorded by runner: e0b7bb1 2026-10-04T00:06:45-04:00 research: fix same-session cash rollover accounting and add regression tests.

Initial offline run started 2026-10-04T03:52:09.658372+00:00 and finished 03:52:11.001579+00:00, before report plotting. It used 48/55 closures and five OOS entries. Its CSVs are preserved under initial_offline/.
Final computation started 2026-10-04T04:10:00.744293+00:00 and finished 2026-10-04T04:10:02.028969+00:00 (before report plotting).
Completion requests started 2026-10-04T04:07:16.627034+00:00 and finished 2026-10-04T04:07:56.845449+00:00. HTTP requests 21; response bytes 345,096; cap 60 requests/2,000,000 bytes; max rate0.5/s. Completion error: none.

One sandboxed network attempt failed immediately with zero bytes. Its sanitized log is archived; the successful data completion used the approved network sandbox escalation. Total network call attempts including that failed attempt: 22.

Read-only source paths: research/s5_big_moves/.cache/eq_SPY.npz; S5 labels/universe metadata via merge_links; the 18 agreed SPY-link pm_<id>.npz odds histories; research/.massive_cache/ cached contract/NBBO responses. New responses are only in this package's ignored .cache/massive/. No Kalshi or Polymarket requests were made. No shared study, environment, recorder, sealed OOS array or API key output was used. Input file hashes are in input_manifest.json.

The public ICE/NYSE 2025 calendar was read to verify 13:00 halfday closes. The two local 13:00 auction-stamped bars made the generic timestamp helper infer 13:05; the corrected 12:55 entry and12:30 strike/signal cutoff follow the existing actual-close rule.
All 48 original executable V0 trades retain identical P&L (maximum absolute change $0.000000000000). Correcting prior-close timestamps changed the gate exposure on 0 of those original dates.

The same-session rollover repair compounds morning-exit and afternoon-entry factors, uses updated cash NAV for the new lot, and adds both turnover flows. A synthetic regression first failed then passed, and independent review checked four cash-ledger fixtures. The original initial archive's V0 1x ALL return was overstated by0.001806bp and2x by0.003384bp; corrected costs/signals are unchanged.

Initial CSV timestamp field expansion accidentally replaced scheduled clocks with earlier SIP timestamps. It never changed quote requests, age validation or computed fills. Final tables preserve both quote and decision clocks separately.

Accounting audit: all short-side signs correct=True; maximum event/daily compound reconciliation error=2.412e-16. Costs stress is applied to both half-spreads and both commissions.
A V1 IS daily Sharpe above3 triggered a sign, quote-time, strike-cutoff, gate-cutoff, size, funded-cash denominator and daily-reconciliation audit. No remaining accounting or lookahead error was found. A high historical Sharpe remains exploratory and does not overcome sparse OOS.

Validation command: cd research && .venv/bin/python -m pytest cx1_option_insurance/tests -q (14 tests passed before completion; final rerun exit status recorded by parent). Runnable commands: python -m cx1_option_insurance.run (offline); python -m cx1_option_insurance.report. pull_missing is budgeted data completion and needs the previously granted root acknowledgment.

Matplotlib initially warned that the user font-cache directories are read only and created a temporary cache. Final plotting uses a writable temporary MPLCONFIGDIR. This did not affect prices or accounting.

Full cache-response status counts:
- ok: 55
