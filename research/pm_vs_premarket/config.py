"""Pre-registered parameters (METHOD.md). Change only through an Amendment in METHOD.md."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_ENV_DIR = RESEARCH_DIR
RESULTS_DIR = RESEARCH_DIR / "results" / "pm_vs_premarket"
ARM_K_DIR = RESULTS_DIR / "arm_k"
CACHE_DIR = RESULTS_DIR / ".massive_cache"
PRIMARY_CSV = RESEARCH_DIR / "results" / "leadlag_closed" / "closures_all.csv"
PRIMARY_EVENTS = RESEARCH_DIR / "leadlag_closed" / "events.yaml"
SECONDARY_CSV = RESEARCH_DIR / "results" / "leadlag_replication" / "results.csv"
SECONDARY_MARKETS = RESEARCH_DIR / "leadlag_replication" / "markets.json"
TZ = "America/New_York"

OUTCOME = "SPY"
OUTCOME_2 = "QQQ"

PROBE_WINDOW_ET = ("2024-06-03 08:00", "2024-06-03 09:30")
PROBE_TICKERS = ("ESM4", "ESM24")
PROBE_MIN_BARS = 30
FUTURES_PATH = "/futures/vX/aggs/{ticker}"
FUTURES_ROOTS = {"SPY": "ES", "QQQ": "NQ"}
QUARTER_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}
ROLL_DAYS = 8


@dataclass(frozen=True)
class Params:
    t_primary: tuple = (9, 25)
    t_sens: tuple = (8, 0)
    bar_tol_min: int = 15
    pm_stale_min: int = 30
    pm_pad_before_min: int = 300
    pm_pad_after_min: int = 30
    t_crit: float = 1.96
    alpha: float = 0.05
    n_perm: int = 10_000
    n_boot: int = 2_000
    seed: int = 20261003


PARAMS = Params()
