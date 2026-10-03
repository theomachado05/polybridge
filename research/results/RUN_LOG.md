# Run log

Every run that produces or checks results is recorded here, newest last. Raw logs and metadata live in `logs/` (no keys, no raw API data). Times are US/Eastern.

| # | Started | Run | Commit | Window | Duration | Requests | Exit | Verdict H1 · H2 | Record |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-10-02 23:00 | Pipeline check: Massive starter on `cfo_appointment` (not a hypothesis tag; its OOS cell ran on that tag only — disclosed) | 9b6f82e | starter defaults | — | — | 0 | n/a | `pipeline_check.md` |
| 2 | 2026-10-02 23:28 | First in-sample study + export (`export_in_sample.py`) | 48b4159 | 2024-01-01 → 2025-12-31 | ~2 min | ~8,477 (cold) | 0 | NULL · NULL | `in_sample/` (commit 48b4159) |
| 3 | 2026-10-02 23:53 | Logged re-run of the export after the final review fixes; all previously committed CSVs byte-identical; adds expiry and paired costs, net edge, placebo drops | c0fcfd8 | 2024-01-01 → 2025-12-31 | 87 s | +232 (warm cache) | 0 | NULL · NULL | `logs/20261002-235320-export.*` |
| 4 | 2026-10-02 23:55 | Clean-start reproduction of the judged notebook: fresh copy of the committed `research/`, fresh venv from `requirements.txt`, empty cache, only `MASSIVE_API_KEY`, `jupyter nbconvert --execute` | c0fcfd8 | 2024-01-01 → 2025-12-31 (notebook default) | 331 s | 8,535 (cold) | 0 | NULL · NULL (matches #2, #3) | `logs/20261002-235320-clean-kernel.*` |

| 5 | 2026-10-03 01:08 | Exploratory atlas, attempt 1 (`export_atlas.py`, HYPOTHESIS §5) — failed: KeyError 'tickers' for a tag whose disclosures lack the field | 1ef4a3d | 2024-01-01 → 2025-12-31 | 35 s | +4,182 | 1 | n/a (exploratory) | `results/logs/20261003-010827-atlas.meta` |
| 6 | 2026-10-03 01:15 | Verification after bug fix e26fad1: in-sample export re-run; **0 result files changed** | e26fad1 | 2024-01-01 → 2025-12-31 | 11 s | warm | 0 | NULL · NULL | `results/logs/20261003-011520-export-verify.*` |
| 7 | 2026-10-03 01:15 | Exploratory atlas, attempt 2: 119 tags × 5 strategies × 3 headline horizons, 15 events/tag max, shared 300-day placebo; 96,390 variants counted | e26fad1 | 2024-01-01 → 2025-12-31 | 244 s | +8,783 | 0 | n/a (exploratory) | `results/logs/20261003-011542-atlas.meta`, `atlas/atlas.csv` |
| 8 | 2026-10-03 13:00 | **Single out-of-sample run** (`export_oos.py`, HYPOTHESIS.md §4), after the method freeze (tag `method-freeze` on 344de99, 13:00 ET); LAST_SESSION pinned 2026-10-02, conservative timing, same StudyConfig and pass rule. 11 events (H1 3, H2 8); H1 below the pipeline's n≥5 minimum at every headline horizon, so no H1 edge is computable; H2 edge −0.0215 (21) and −0.0138 (42), both CIs span zero, opposite sign to in-sample. Before the freeze the export code was dry-run on the in-sample window into a scratch folder (in-sample CSVs reproduced byte-identical; output deleted, no OOS data) | 344de99 | 2026-01-01 → 2026-08-31 | 102 s | +6,596 cache files | 0 | NULL · NULL | `oos/SUMMARY.md`, `logs/20261003-130038-oos.*` |

Out-of-sample (2026-01-01 → 2026-08-31): **run once** on 2026-10-03 13:00 ET after the method freeze (run #8). Verdicts as computed: H1 NULL (3 events, not testable), H2 NULL (sign opposite to in-sample). Results in `oos/SUMMARY.md`; `oos/.done` blocks any re-run.
