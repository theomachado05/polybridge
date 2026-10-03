"""S1 twin spread: every fixed parameter of METHOD.md. Committed with it, before any S1 data is pulled."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc

LOOKBACK_DAYS = 365
GRID_SECONDS = 60
MAX_QUOTE_AGE_S = 900

# Polymarket modelled half-spread (history only): median of the recorded books in the calibration slice.
CALIBRATION_START = datetime(2026, 10, 3, 23, 9, 48, tzinfo=UTC)
CALIBRATION_END = datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC)
HALF_SPREAD_FLOOR = 0.005
PRICE_CLIP = (0.001, 0.999)
CALIBRATION_MIN_TWO_SIDED = 0.5

# Forward paper test window (starts where the calibration slice ends).
FORWARD_START = CALIBRATION_END
FORWARD_END = datetime(2026, 10, 4, 11, 0, 0, tzinfo=UTC)          # Sun 07:00 ET
FORWARD_END_FINAL = datetime(2026, 10, 4, 13, 30, 0, tzinfo=UTC)   # Sun 09:30 ET, labelled update

KALSHI_FEE_COEFF = 0.07
CLIP_HISTORY = 100          # contract pairs per entry; history has no sizes
FORWARD_MIN_SIZE = 5
FORWARD_MAX_SIZE = 500
N_PAIRS = 33
CAPITAL_HISTORY = N_PAIRS * CLIP_HISTORY * 1.0
CAPITAL_FORWARD = N_PAIRS * FORWARD_MAX_SIZE * 1.0

OOS_FRACTION = 0.20
DAYS_PER_YEAR = 365
PRINT_WINDOW_S = 600
N_BOOT = 2000
BOOT_SEED = 0


@dataclass(frozen=True)
class Variant:
    id: str
    theta: float
    exit_on: bool


VARIANTS = (
    Variant("V0", 0.01, True),     # primary
    Variant("V1", 0.02, True),
    Variant("V2", 0.03, True),
    Variant("V3", 0.01, False),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)

# Success criterion (METHOD.md section 9)
MIN_OOS_ENTRIES = 30
MIN_OOS_PAIRS = 5
MIN_VERIFIED_SHARE = 0.5
SHARPE_BUG_HUNT = 3.0
