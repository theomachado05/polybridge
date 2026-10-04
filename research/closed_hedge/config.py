from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
PANEL_CSV = RESEARCH_DIR / "results" / "leadlag_closed" / "closures_all.csv"
REPLICATION_CSV = RESEARCH_DIR / "results" / "leadlag_replication" / "results.csv"
ARB_META = RESEARCH_DIR / "results" / "arb" / "run_meta.json"
RESULTS_DIR = RESEARCH_DIR / "results" / "closed_hedge"

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


@dataclass(frozen=True)
class Params:
    min_prior: int = 20
    min_prior_nonzero: int = 10
    k_bp: float = 100.0
    k_sens: tuple = (50.0, 200.0)
    eq_cost_bp: float = 2.0
    eq_cost_pre_bp: float = 10.0
    hs_fallback_pp: float = 0.5
    hs_tick_pp: float = 0.1
    hs_thin_pp: float = 5.0
    n_books: int = 100
    min_books: int = 10
    mid_lo: float = 0.02
    mid_hi: float = 0.98
    bad_open_bp: float = -50.0
    n_boot: int = 10_000
    block_len: int = 10
    seed: int = 20261003


PARAMS = Params()
