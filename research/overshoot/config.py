from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "overshoot"
EVENTS_CSV = RESEARCH_DIR / "results" / "open_options" / "events.csv"
DONE = RESULTS_DIR / ".done"

COLUMNS = ("market_id", "question", "underlying", "kind", "outcome", "closure", "status", "pm_close", "pm_open",
           "pm_0945", "pm_eod", "prints_in_closure", "oc_mid", "oo_mid", "oe_mid")


@dataclass(frozen=True)
class Params:
    draws: int = 10_000
    seed: int = 20261003
    min_events: int = 30
    min_clusters: int = 8
    majority: float = 0.5
    log_eps: float = 0.01


PARAMS = Params()
