# Run log

Every run that produces or checks results is recorded here, newest last. Raw logs and metadata live in `logs/` (no keys, no raw API data). Times are US/Eastern.

| # | Started | Run | Commit | Window | Duration | Requests | Exit | Verdict H1 · H2 | Record |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-10-02 23:00 | Pipeline check: Massive starter on `cfo_appointment` (not a hypothesis tag; its OOS cell ran on that tag only — disclosed) | 9b6f82e | starter defaults | — | — | 0 | n/a | `pipeline_check.md` |
| 2 | 2026-10-02 23:28 | First in-sample study + export (`export_in_sample.py`) | 48b4159 | 2024-01-01 → 2025-12-31 | ~2 min | ~8,477 (cold) | 0 | NULL · NULL | `in_sample/` (commit 48b4159) |
| 3 | 2026-10-02 23:53 | Logged re-run of the export after the final review fixes; all previously committed CSVs byte-identical; adds expiry and paired costs, net edge, placebo drops | c0fcfd8 | 2024-01-01 → 2025-12-31 | 87 s | +232 (warm cache) | 0 | NULL · NULL | `logs/20261002-235320-export.*` |
| 4 | 2026-10-02 23:55 | Clean-start reproduction of the judged notebook: fresh copy of the committed `research/`, fresh venv from `requirements.txt`, empty cache, only `MASSIVE_API_KEY`, `jupyter nbconvert --execute` | c0fcfd8 | 2024-01-01 → 2025-12-31 (notebook default) | 331 s | 8,535 (cold) | 0 | NULL · NULL (matches #2, #3) | `logs/20261002-235320-clean-kernel.*` |

Out-of-sample (2026-01-01 → 2026-08-31): **not run**. It runs once after the method freeze, scheduled for Saturday 2026-10-03 13:00 ET.
