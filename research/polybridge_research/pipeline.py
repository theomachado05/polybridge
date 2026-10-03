"""The whole confirmatory study for one window: a pure function of (client, config, start, end)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import pass_check, sample_placebo
from .evaluate import evaluate
from .events import build_confirmatory_events
from .pricing import price_events
from .timing import apply_filing_session, fetch_acceptance_time


def run_family_study(client, cal, cfg, start: str, end: str, last_session: pd.Timestamp, user_agent: str | None = None,
                     cache_dir: Path = Path(".massive_cache"), max_workers: int = 8, placebo_seed: int = 7) -> dict:
    events, excluded = build_confirmatory_events(client, start, end, cfg.universe, cal)
    accepted = None
    if user_agent and not events.empty:
        acc = []
        for url in events["filing_url"]:
            try:
                acc.append(fetch_acceptance_time(url, user_agent, cache_dir))
            except Exception:
                acc.append(None)
        accepted = pd.Series(acc, index=events.index)
    if not events.empty:
        events = apply_filing_session(events, cal, accepted)
    timing_counts = events["timing"].value_counts().to_dict() if "timing" in events else {}
    priced, dropped = price_events(client, events, cal, cfg, max_workers=max_workers, label="events")
    results = evaluate(priced, cal, cfg, last_session)
    pl_events, pl_priced, pl_frames, checks = [], [], [], {}
    for fam in sorted(set(events["family"])) if not events.empty else []:
        fam_ev = events[events.family == fam]
        pl = sample_placebo(fam_ev, cfg.n_placebo, start, end, cal, cfg.placebo_gap_days, seed=placebo_seed,
                           last_session=last_session)
        p_priced, _ = price_events(client, pl, cal, cfg, max_workers=max_workers, label=f"placebo {fam}")
        p_res = evaluate(p_priced, cal, cfg, last_session)
        pl_events.append(pl)
        pl_priced += p_priced
        pl_frames.append(p_res)
        checks[fam] = pass_check(results[results.family == fam], p_res, fam, cfg)
    placebo_results = pd.concat(pl_frames, ignore_index=True) if pl_frames else results.iloc[0:0]
    return {"events": events, "excluded": excluded, "priced": priced, "dropped": dropped, "results": results,
            "placebo_events": pd.concat(pl_events, ignore_index=True) if pl_events else pd.DataFrame(),
            "placebo_priced": pl_priced, "placebo_results": placebo_results, "checks": checks,
            "timing_counts": timing_counts}
