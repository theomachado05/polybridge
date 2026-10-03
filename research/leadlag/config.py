"""Pre-registered parameters (METHOD.md sections 3-7). Change only through an Amendment in METHOD.md."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
EVENTS_PATH = PKG_DIR / "events.yaml"
RESULTS_DIR = RESEARCH_DIR / "results" / "leadlag"
CACHE_DIR = RESULTS_DIR / "cache"
REPO_ENV_DIR = RESEARCH_DIR.parent  # search_from for .env (walks up a few parents)


@dataclass(frozen=True)
class Params:
    warmup_min: int = 180
    # first significant move
    w: int = 3
    k: float = 4.0
    sigma_window: int = 120
    sigma_min_obs: int = 30
    eq_floor_bp: float = 0.5
    pm_floor_pp: float = 0.25
    persist_h: int = 5
    persist_frac: float = 0.5
    sim_tol: int = 1
    # cross-correlation
    xcorr_max_lag: int = 30
    xcorr_min_n: int = 60
    lead_mass_lags: int = 10
    # pooled regression / Granger
    reg_lags: int = 30
    hac_lags: int = 30
    granger_p: int = 10
    granger_p_robust: int = 30
    # usability
    min_pm_points: int = 30
    min_pm_changes: int = 10
    min_eq_cov: float = 0.70
    min_eq_valid: float = 0.80
    min_overlap: int = 60


PARAMS = Params()
SENSITIVITY_K = (3.0, 5.0)
