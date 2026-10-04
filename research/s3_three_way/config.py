from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc

KALSHI_SERIES = "KXINXU"
PM_UNDERLYING = "SPY"
STRIKE_TOLERANCE = 2.5
SNAPSHOT = "S2"
KALSHI_MAX_AGE_S = 6 * 3600
PRINT_WINDOW_S = 600

CLIP_HISTORY = 100
FORWARD_MIN_SIZE = 5
FORWARD_MAX_SIZE = 500
FORWARD_START = datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC)
FORWARD_END = datetime(2026, 10, 4, 11, 0, 0, tzinfo=UTC)
FORWARD_END_FINAL = datetime(2026, 10, 4, 13, 30, 0, tzinfo=UTC)
FORWARD_RESOLUTION = datetime(2026, 10, 5, 20, 0, 0, tzinfo=UTC)
FORWARD_RATIO_DATE = "2026-10-02"

OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252
N_BOOT = 2000
BOOT_SEED = 0


@dataclass(frozen=True)
class Variant:
    id: str
    trade: str
    theta: float
    outlier_filter: bool


VARIANTS = (
    Variant("V0", "lock", 0.02, True),
    Variant("V1", "lock", 0.01, True),
    Variant("V2", "lock", 0.02, False),
    Variant("V3", "fade", 0.02, True),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)

MIN_VERIFIED_ENTRIES = 20
MIN_VERIFIED_DATES = 10
MIN_VERIFIED_OOS = 5
