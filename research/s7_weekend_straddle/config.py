"""S7 weekend straddle: every fixed parameter of METHOD.md. Committed with it, before any option price is pulled."""
from __future__ import annotations

from dataclasses import dataclass

ACTIVITY_NIGHTS, ACTIVITY_MIN_NIGHTS = 5, 3
PM_MAX_AGE_S = 1800
ENTRY_ET, EXIT_ET, STRIKE_ET = "15:55", "09:45", "15:30"
EXPIRY_MIN_DAYS = 7
EXPIRY_SEARCH_DAYS = 28
FRIDAY_QUOTE_MAX_AGE_S = 600
MONDAY_QUOTE_MAX_AGE_S = 900
COMMISSION = 0.65            # per contract per leg, each way
OOS_FRACTION = 0.20
N_BOOT, BOOT_SEED = 2000, 0


@dataclass(frozen=True)
class Variant:
    id: str
    activity: float          # mean absolute overnight odds move, points
    lo: float
    hi: float


VARIANTS = (
    Variant("V0", 4.0, 0.10, 0.90),      # primary
    Variant("V1", 2.0, 0.10, 0.90),      # the loosest: defines which weekends are controls
    Variant("V2", 4.0, 0.25, 0.75),
)
PRIMARY, LOOSEST = "V0", "V1"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_WEEKENDS = 30, 5
