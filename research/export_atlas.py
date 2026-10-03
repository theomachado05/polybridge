"""Export the EXPLORATORY atlas (HYPOTHESIS.md §5) over every 8-K filing type, in-sample only.

Mirrors the notebook's atlas cell: baseline spec, max_events_per_tag=15, one shared 300-day placebo over
TOP_100 at the baseline bucket (seed 11). Window is cfg.study_start -> cfg.study_end; the out-of-sample
window is never referenced. Run from research/:
    .venv/bin/python export_atlas.py
Writes results/atlas/atlas.csv and results/atlas/variants.txt (derived aggregates only).
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from polybridge_research.analysis import sample_placebo
from polybridge_research.atlas import count_variants, run_atlas
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.evaluate import evaluate
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pricing import price_events

OUT = Path("results/atlas")
OUT.mkdir(parents=True, exist_ok=True)
MAX_EVENTS = 15
MAX_WORKERS = 8
t_start = time.time()


def log(msg):
    print(f"[{time.time() - t_start:7.0f}s] {msg}", flush=True)


cfg = StudyConfig()
cfg.validate()
client = MassiveClient(load_api_key(search_from=Path.cwd()))
cal = TradingCalendar()
last = cal.last_completed()
start, end = cfg.study_start, cfg.study_end
log(f"window {start} -> {end}; last completed session {last.date()}")

rows = client.get_all("/stocks/taxonomies/vX/disclosures", {"limit": 1000})
tags = sorted({t["tertiary_category"] for t in rows})
log(f"{len(tags)} tags")

base = {cfg.baseline_bucket: cfg.buckets[cfg.baseline_bucket]}
pl_events = sample_placebo(pd.DataFrame({"ticker": list(cfg.universe),
                                         "filing_date": [pd.Timestamp("1900-01-01")] * len(cfg.universe)}),
                           300, start, end, cal, gap_days=0, seed=11)
pl_priced, _ = price_events(client, pl_events, cal, cfg, buckets=base, max_workers=MAX_WORKERS, label="atlas placebo")
pl_res = evaluate(pl_priced, cal, cfg, last)
log("placebo done")

# run_atlas loops tags internally; call per tag for progress, then re-adjust q-values over all rows.
from polybridge_research.stats import benjamini_hochberg  # noqa: E402

parts = []
for i, tag in enumerate(tags, 1):
    part = run_atlas(client, cal, cfg, [tag], start, end, last, pl_res,
                     max_events_per_tag=MAX_EVENTS, max_workers=MAX_WORKERS)
    parts.append(part)
    log(f"[{i}/{len(tags)}] {tag}: n_events={int(part['n_events'].iloc[0]) if len(part) else 0}")
atlas = pd.concat(parts, ignore_index=True)
atlas["q_value"] = benjamini_hochberg(atlas["p_value"].to_numpy(float)) if len(atlas) else []
atlas["exploratory"] = True

cols = ["tag", "n_events", "strategy", "horizon", "difference", "ci_lo", "ci_hi", "p_value", "q_value", "exploratory"]
atlas[cols].to_csv(OUT / "atlas.csv", index=False)
(OUT / "variants.txt").write_text(f"{count_variants(cfg, n_tags=len(tags))}\n")
log(f"done: {len(atlas)} rows, {len(tags)} tags")
