from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "strategy_backtest"
CACHE_DIR = RESULTS_DIR / ".massive_cache"
EVENTS_PATH = RESEARCH_DIR / "leadlag_closed" / "events.yaml"
MARKETS_PATH = RESEARCH_DIR / "leadlag_replication" / "markets.json"
R1_CSV = RESEARCH_DIR / "results" / "closed_hedge" / "closures_hedged.csv"
TZ = "America/New_York"
TICKER = "SPY"

SPAN_START = "2024-01-02"


@dataclass(frozen=True)
class Params:
    book_usd: float = 1_000_000.0
    pm_stale_min: int = 30
    open_tol_min: int = 5
    pre_tol_min: int = 15
    sig_hm: tuple = (9, 29)
    sig_pre_hm: tuple = (7, 59)
    pre_entry_hm: tuple = (8, 0)
    n_min: int = 20
    t_min: float = 1.96
    target_coverage: float = 0.5
    full_size_gap_bp: float = 50.0
    min_gap_bp: float = 10.0
    cost_rth_bp: float = 1.0
    cost_pre_entry_bp: float = 3.0
    cost_mults: tuple = (1.0, 2.0)
    rf: float = 0.0
    oos_frac: float = 0.2
    oos_max_days: int = 730
    materiality: float = 0.01
    v4_min_closures: int = 40
    cap_share: float = 0.01
    adv_window: int = 20
    pm_pad_before_min: int = 300
    pm_pad_after_min: int = 30
    variants: tuple = field(default=("primary", "V1_premarket", "V2_no_gating", "V3_unwind_close", "V4_expanded"))


PARAMS = Params()
