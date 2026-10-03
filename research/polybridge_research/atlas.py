"""Exploratory atlas (HYPOTHESIS.md §5): every tag, baseline spec, BH q-values. Never a headline."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .analysis import difference_board
from .config import StudyConfig
from .evaluate import evaluate
from .events import build_tag_events
from .pricing import price_events
from .stats import benjamini_hochberg
from .strategies import STRATEGIES


def count_variants(cfg: StudyConfig, n_tags: int = 1, strategies=STRATEGIES) -> int:
    return len(cfg.buckets) * 2 * len(cfg.otm_grid) * (len(cfg.horizons) + 1) * (len(strategies) - 1) * n_tags


def run_atlas(client, cal, cfg: StudyConfig, tags, start, end, last_session, placebo_results,
              max_events_per_tag: int = 30, seed: int = 0, max_workers: int = 8) -> pd.DataFrame:
    base = {cfg.baseline_bucket: cfg.buckets[cfg.baseline_bucket]}
    strategies = [s for s in STRATEGIES if s != "stock"]
    heads = list(cfg.headline_horizons)
    rows = []
    for tag in tags:
        ev = build_tag_events(client, tag, start, end, cfg.universe, cal)
        if len(ev) > max_events_per_tag:
            ev = ev.sample(max_events_per_tag, random_state=seed).sort_values("filing_date")
        priced, _ = price_events(client, ev, cal, cfg, buckets=base, max_workers=max_workers, label=tag)
        res = evaluate(priced, cal, cfg, last_session)
        n_events = len({(p.ticker, p.event_date) for p in priced})
        diff = (difference_board(res, placebo_results, cfg, strategies=strategies)
                if not res.empty else pd.DataFrame(columns=["strategy", "horizon"]))
        for s in strategies:
            for h in heads:
                hit = diff[(diff.strategy == s) & (diff.horizon == h)] if not diff.empty else diff
                rec = hit.iloc[0].to_dict() if len(hit) else {}
                rows.append({"tag": tag, "n_events": n_events, "strategy": s, "horizon": h,
                             "difference": rec.get("difference", np.nan), "ci_lo": rec.get("ci_lo", np.nan),
                             "ci_hi": rec.get("ci_hi", np.nan), "p_value": rec.get("p_value", np.nan)})
    out = pd.DataFrame(rows)
    out["q_value"] = benjamini_hochberg(out["p_value"].to_numpy(float)) if len(out) else []
    out["exploratory"] = True
    return out
