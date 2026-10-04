from __future__ import annotations

from dataclasses import dataclass

PM_MAX_AGE_S = 1800
SIGNAL_LEAD_S = 60
VOTE_BAR_S = 300
ENTRY_AFTER_OPEN_S = 600
ENTRY_BAND = (0.05, 0.95)
HALF_SPREAD = 0.005
MAX_POSITIONS = 10
WEEKEND_GAP_S = 40 * 3600
OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252
TEST_THRESHOLDS = (5.0, 10.0)
PRINT_PAGES = 2


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float
    vote: str
    exit: str
    weekends_only: bool


VARIANTS = (
    Variant("V0", 5.0, "not confirmed", "close", False),
    Variant("V1", 10.0, "not confirmed", "close", False),
    Variant("V2", 5.0, "not confirmed", "next 09:40", False),
    Variant("V3", 5.0, "any", "close", False),
    Variant("V4", 5.0, "not confirmed", "close", True),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_DATES, MIN_VERIFIED_SHARE = 30, 10, 0.5
