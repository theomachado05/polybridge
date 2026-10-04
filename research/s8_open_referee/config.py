"""S8 open referee: every fixed parameter of METHOD.md. Committed with it, before the give-back is split by the asset's vote."""
from __future__ import annotations

from dataclasses import dataclass

PM_MAX_AGE_S = 1800
SIGNAL_LEAD_S = 60           # the overnight move is read at 09:29
VOTE_BAR_S = 300             # the asset's vote uses the first five-minute bar (09:30 to 09:35)
ENTRY_AFTER_OPEN_S = 600     # entry at 09:40
ENTRY_BAND = (0.05, 0.95)
HALF_SPREAD = 0.005          # 0.5 point: half of the 1.0-point median spread in results/s5_big_moves/pm_cost_snapshot.json
MAX_POSITIONS = 10
WEEKEND_GAP_S = 40 * 3600    # more than one night between sessions
OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252
TEST_THRESHOLDS = (5.0, 10.0)
PRINT_PAGES = 2              # the data API serves at most the latest 20,000 prints of a market


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float         # overnight move, points
    vote: str                # "not confirmed" or "any"
    exit: str                # "close" or "next 09:40"
    weekends_only: bool


VARIANTS = (
    Variant("V0", 5.0, "not confirmed", "close", False),      # primary
    Variant("V1", 10.0, "not confirmed", "close", False),
    Variant("V2", 5.0, "not confirmed", "next 09:40", False),
    Variant("V3", 5.0, "any", "close", False),
    Variant("V4", 5.0, "not confirmed", "close", True),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_DATES, MIN_VERIFIED_SHARE = 30, 10, 0.5
