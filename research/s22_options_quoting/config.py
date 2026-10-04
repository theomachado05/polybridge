from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "s22_options_quoting"

INPUT_COMMIT = "fb66dc7a07ff32e47293bc1d4f9c265ed9080d4c"
INPUT_PATH = "research/results/pm_taker_v2/prints_evaluated.csv"
INPUT_BLOB = "7597b31fedf18fde85e6aab1c04775dae7bbb1dc"
INPUT_ROWS = 1155
INPUT_OK_ROWS = 970
STATUS_OK = "ok"

M_PRIMARY = 0.05
M_VARIANTS = (0.02, 0.10)
POST_RANGE = (0.02, 0.98)
QUOTE_SIZE = 100.0
EPS = 1e-9

STRESS_WIDEN = 0.02
STRESS_THROUGH = 0.01

TICK = 0.01

BOOT_DRAWS = 10_000
SEED = 20261004
OOS_SHARE = 0.20
P_MID_EDGES = (0.10, 0.25, 0.75, 0.90)
P_MID_LABELS = ("below 10%", "10 to 25%", "25 to 75%", "75 to 90%", "above 90%")
DOSE_MULTS = (2.0, 4.0)
DOSE_LABELS = ("m to 2m", "2m to 4m", "beyond 4m")

MIN_FILLS = 100
MIN_DAYS = 30
SHARPE_BUG_HUNT = 3.0
