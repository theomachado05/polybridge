from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "leadlag_replication"
CACHE_DIR = RESULTS_DIR / ".massive_cache"
MARKETS_PATH = PKG_DIR / "markets.json"
REPO_ENV_DIR = RESEARCH_DIR.parent
TZ = "America/New_York"

PRIMARY = "SPY"
SECONDARY = ("QQQ", "IWM")

WINDOW_START = "2024-01-01"
WINDOW_END = "2025-12-30"
OPEN_DAY_MAX = "2025-12-31"

POOL_TAGS = {"economy": 100328, "geopolitics": 100265, "economic-policy": 101800, "politics": 2}
POOL_EVENTS_PER_QUERY = 1000
EXCLUDED_SLUGS = ("will-donald-trump-win-the-2024-us-presidential-election", "us-recession-in-2025")

ORIGINAL_PANELS = (("2024-04-01", "2024-11-04"), ("2025-01-10", "2025-12-30"))


@dataclass(frozen=True)
class Params:
    n_markets: int = 10
    min_window_days: int = 92
    min_pm_closures: int = 40
    pm_stale_min: int = 30
    open_tol_min: int = 5
    theta_pp: float = 1.0
    theta_sens: tuple = (0.5, 2.0)
    n_perm: int = 10_000
    seed: int = 20261003
    alpha: float = 0.05
    t_min: float = 2.0
    pm_pad_before_min: int = 300
    pm_pad_after_min: int = 30


PARAMS = Params()
