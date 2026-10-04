from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "gap_model"
PANEL_A_CSV = RESEARCH_DIR / "results" / "leadlag_closed" / "closures_all.csv"
PANEL_A_EVENTS = RESEARCH_DIR / "leadlag_closed" / "events.yaml"
PANEL_B_CSV = RESEARCH_DIR / "results" / "leadlag_replication" / "results.csv"
PANEL_B_MARKETS = RESEARCH_DIR / "leadlag_replication" / "markets.json"
EXPORT_PATH = REPO_DIR / "backend" / "app" / "data" / "gap_rates.json"

MAPPED_ETF = "SPY"
SECONDARY_ETF = "QQQ"


@dataclass(frozen=True)
class Params:
    n_min: int = 20
    z80: float = 1.2816
    theta_pp: float = 1.0
    n_perm: int = 10_000
    seed: int = 20261003
    alpha: float = 0.05
    buckets: tuple = ("<= -10", "(-10, -3]", "(-3, 0)", "= 0", "(0, 3)", "[3, 10)", ">= 10")


PARAMS = Params()
