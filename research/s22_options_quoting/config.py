"""S22 pre-registered parameters (METHOD.md). Fixed before any row of the input file is read. Change only through a
dated Amendment in METHOD.md."""
from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "s22_options_quoting"

# ---- input: one file, already committed in git on the partner's branch; no network -------------------------------
INPUT_COMMIT = "fb66dc7a07ff32e47293bc1d4f9c265ed9080d4c"      # origin/r/thesis-pass-2 when S22 was registered
INPUT_PATH = "research/results/pm_taker_v2/prints_evaluated.csv"
INPUT_BLOB = "7597b31fedf18fde85e6aab1c04775dae7bbb1dc"        # git blob id of that file at that commit
INPUT_ROWS = 1155
INPUT_OK_ROWS = 970
STATUS_OK = "ok"

# ---- our quotes ---------------------------------------------------------------------------------------------------
M_PRIMARY = 0.05                 # offer = p_hi + m, bid = p_lo - m
M_VARIANTS = (0.02, 0.10)
POST_RANGE = (0.02, 0.98)        # a quote outside this range is not posted
QUOTE_SIZE = 100.0               # contracts resting on each side; refilled after every fill
EPS = 1e-9                       # float tolerance in price comparisons

# ---- stress (the 2x case) -----------------------------------------------------------------------------------------
STRESS_WIDEN = 0.02              # quote moved a further 2 points away from the band
STRESS_THROUGH = 0.01            # the print must be at least one cent beyond our quote

# ---- secondary (reported, never changes the verdict) --------------------------------------------------------------
TICK = 0.01                      # tick-grid row: offer rounded up to the cent, bid rounded down

# ---- statistics ---------------------------------------------------------------------------------------------------
BOOT_DRAWS = 10_000
SEED = 20261004
OOS_SHARE = 0.20                 # the most recent 20% of resolution dates (of the 970 rows, not of the fills)
P_MID_EDGES = (0.10, 0.25, 0.75, 0.90)
P_MID_LABELS = ("below 10%", "10 to 25%", "25 to 75%", "75 to 90%", "above 90%")
DOSE_MULTS = (2.0, 4.0)          # distance beyond the band: [m, 2m), [2m, 4m), [4m, ...)
DOSE_LABELS = ("m to 2m", "2m to 4m", "beyond 4m")

# ---- pass rule ----------------------------------------------------------------------------------------------------
MIN_FILLS = 100
MIN_DAYS = 30
SHARPE_BUG_HUNT = 3.0
