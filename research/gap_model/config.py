"""Pre-registered parameters of the expected-gap OOS study (METHOD.md). Change only through an Amendment."""
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
    n_min: int = 20                 # min training closures with x != 0 for a per-market rate (and for any prediction)
    z80: float = 1.2816             # two-sided 80% normal quantile for the band
    theta_pp: float = 1.0           # secondary G1 restriction |x| >= theta
    n_perm: int = 10_000
    seed: int = 20261003
    alpha: float = 0.05
    # calibration buckets on predicted gap (bp); "zero" is its own bucket
    buckets: tuple = ("<= -10", "(-10, -3]", "(-3, 0)", "= 0", "(0, 3)", "[3, 10)", ">= 10")


PARAMS = Params()
