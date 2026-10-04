"""S6 Monday fade: every fixed parameter of METHOD.md. Committed with it, before any P&L of the trade is computed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
FEE_RATE = 0.04
CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)

# Half-spread calibration: this weekend's recorded Polymarket threshold books
CALIBRATION_START = datetime(2026, 10, 3, 23, 9, 48, tzinfo=UTC)
CALIBRATION_END = datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC)
CALIBRATION_MID_RANGE = (0.05, 0.95)

OOS_FRACTION = 0.20
PRINT_WINDOW_S = 600
ENTRY_TIME_ET = "09:45"
N_BOOT, BOOT_SEED = 2000, 0


@dataclass(frozen=True)
class Variant:
    id: str
    theta: float
    rows: str      # "events" or "all valid"
    exit: str      # "resolution" or "end of day"


VARIANTS = (
    Variant("V0", 0.02, "events", "resolution"),     # primary
    Variant("V1", 0.05, "events", "resolution"),
    Variant("V2", 0.02, "all valid", "resolution"),
    Variant("V3", 0.02, "events", "end of day"),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_CLOSURES, MIN_VERIFIED_SHARE = 30, 5, 0.5
