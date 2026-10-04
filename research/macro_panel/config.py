from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "macro_panel"
CACHE_DIR = RESULTS_DIR / ".massive_cache"
MARKETS_PATH = PKG_DIR / "markets.json"
DONE_PATH = RESULTS_DIR / ".done"
REPLICATION_ROWS = RESEARCH_DIR / "results" / "leadlag_replication" / "results.csv"
REPO_ENV_DIR = RESEARCH_DIR.parent
TZ = "America/New_York"

PRIMARY = "SPY"

WINDOW_START = "2023-01-01"
WINDOW_END = "2025-12-30"
OPEN_DAY_MAX = "2025-12-31"

POOL_TAG_IDS = {"economy": 100328, "economic-policy": 101800}
POOL_TAG_SLUGS = ("fed-rates", "fed", "inflation", "economy")
POOL_EVENTS_PER_QUERY = 1000

LEADLAG_CLOSED_SLUGS = ("will-donald-trump-win-the-2024-us-presidential-election", "us-recession-in-2025")
REPLICATION_SLUGS = (
    "russia-x-ukraine-ceasefire-in-2025",
    "us-government-shutdown-before-2025",
    "us-x-venezuela-military-engagement-by-december-31-391-819-722-945-174-285-817-971-353-859-836-598-255-382-192-983",
    "will-china-invade-taiwan-before-2027",
    "will-israel-invade-syria-in-2024",
    "israel-x-hamas-ceasefire-before-july-2025",
    "will-china-invade-taiwan-in-2024",
    "will-the-supreme-court-rule-in-favor-of-trumps-tariffs",
    "will-a-nuclear-weapon-detonate-in-2024",
    "israel-x-hamas-ceasefire-in-2024",
)
EXCLUDED_SLUGS = LEADLAG_CLOSED_SLUGS + REPLICATION_SLUGS

CLASSES = ("recession", "fed", "inflation", "unemployment", "gdp")

EARLIER_PANELS = (("2024-01-01", "2025-12-30"),)


@dataclass(frozen=True)
class Params:
    max_per_class: int = 10
    max_markets: int = 50
    min_volume_usd: float = 50_000.0
    min_window_days: int = 28
    min_pm_closures: int = 15
    pm_stale_min: int = 30
    open_tol_min: int = 5
    theta_pp: float = 1.0
    n_perm: int = 10_000
    seed: int = 20261003
    alpha: float = 0.05
    t_min: float = 2.0
    z_ci: float = 1.959964
    pm_pad_before_min: int = 300
    pm_pad_after_min: int = 30


PARAMS = Params()
