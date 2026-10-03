"""Pre-registered parameters (METHOD.md sections 3-5). Change only through an Amendment in METHOD.md."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
EVENTS_PATH = PKG_DIR / "events.yaml"
RESULTS_DIR = RESEARCH_DIR / "results" / "leadlag_closed"
CACHE_DIR = RESULTS_DIR / "cache"
REPO_ENV_DIR = RESEARCH_DIR.parent
TZ = "America/New_York"

PRIMARY = "SPY"
SECONDARY = "QQQ"


@dataclass(frozen=True)
class Params:
    pm_stale_min: int = 30          # PM quote must be within this many minutes before the instant
    open_tol_min: int = 5           # first RTH bar must start within this many minutes of 09:30
    resid_cut_hour: int = 8         # residual-gap cutoff 08:00 ET
    resid_tol_min: int = 15         # equity bar for the cutoff must end within this many minutes before 08:00
    theta_pp: float = 1.0           # min |oriented PM change| for sign tests
    theta_sens: tuple = (0.5, 2.0)
    n_perm: int = 10_000
    seed: int = 20261003
    alpha: float = 0.05
    pm_pad_before_min: int = 120
    pm_pad_after_min: int = 30


PARAMS = Params()

# placebo panels: closures whose START date lies in [start, end]
PANELS = {
    "election": {"start": "2024-04-01", "end": "2024-11-04", "sign": +1},
    "recession": {"start": "2025-01-10", "end": "2025-12-30", "sign": -1},
}
