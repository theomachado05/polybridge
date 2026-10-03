"""Pre-registered parameters (METHOD.md). Change only through an Amendment in METHOD.md."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "leadlag_replication"
CACHE_DIR = RESULTS_DIR / ".massive_cache"   # gitignored by the repo-wide `.massive_cache/` rule (PM and Massive caches)
MARKETS_PATH = PKG_DIR / "markets.json"      # frozen selection (written by `python -m leadlag_replication.select`)
REPO_ENV_DIR = RESEARCH_DIR.parent
TZ = "America/New_York"

PRIMARY = "SPY"
SECONDARY = ("QQQ", "IWM")

# Study window (METHOD.md section 2): closures whose START day is in [WINDOW_START, WINDOW_END] and whose open day is
# not after OPEN_DAY_MAX. Nothing dated 2026 is requested (the 2026-01-01..2026-08-31 window is sealed for the 8-K study).
WINDOW_START = "2024-01-01"
WINDOW_END = "2025-12-30"
OPEN_DAY_MAX = "2025-12-31"

# Candidate pool: gamma events carrying any of these tags (Economy, Geopolitics, Economic Policy, Politics).
POOL_TAGS = {"economy": 100328, "geopolitics": 100265, "economic-policy": 101800, "politics": 2}
POOL_EVENTS_PER_QUERY = 1000         # top events by volume per (tag, closed/open) query
EXCLUDED_SLUGS = ("will-donald-trump-win-the-2024-us-presidential-election", "us-recession-in-2025")

# The two original placebo panels (start-day ranges); closures outside both form the "fresh-date" subset.
ORIGINAL_PANELS = (("2024-04-01", "2024-11-04"), ("2025-01-10", "2025-12-30"))


@dataclass(frozen=True)
class Params:
    n_markets: int = 10             # N, fixed ex ante
    min_window_days: int = 92        # >= 3 months of market life inside the study window
    min_pm_closures: int = 40        # coverage rule: closures with a PM quote at both ends
    pm_stale_min: int = 30           # PM quote must be within this many minutes before the instant
    open_tol_min: int = 5            # first RTH bar must start within this many minutes of 09:30
    theta_pp: float = 1.0            # primary sign-test threshold
    theta_sens: tuple = (0.5, 2.0)
    n_perm: int = 10_000
    seed: int = 20261003
    alpha: float = 0.05
    t_min: float = 2.0               # success criterion: HC3 t > 2
    pm_pad_before_min: int = 300
    pm_pad_after_min: int = 30


PARAMS = Params()
