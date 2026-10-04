"""S16 Kalshi quotes: every fixed parameter of METHOD.md. Committed with it, before any give-back or P&L is computed."""
from __future__ import annotations

from dataclasses import dataclass

QUOTE_AGE_PRIMARY_S = 6 * 3600
QUOTE_AGE_STRICT_S = 900
PM_MAX_AGE_S = 1800
SIGNAL_LEAD_S = 60               # the overnight move is read at 09:29
ENTRY_AFTER_OPEN_S = 600         # entry at 09:40
ENTRY_BAND = (0.05, 0.95)
TEST_THRESHOLDS = (5.0, 3.0, 10.0)
CONTRACTS = 100
KALSHI_FEE_COEFF = 0.07
OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float
    quote_age_s: int


VARIANTS = (
    Variant("V0", 5.0, QUOTE_AGE_PRIMARY_S),      # primary
    Variant("V1", 3.0, QUOTE_AGE_PRIMARY_S),
    Variant("V2", 10.0, QUOTE_AGE_PRIMARY_S),
    Variant("V3", 5.0, QUOTE_AGE_STRICT_S),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_DATES = 30, 10
