"""S18 price-market calibration: every fixed parameter of METHOD.md. Committed with it, before any entry price is matched to a result."""
from __future__ import annotations

from dataclasses import dataclass

PM_MAX_AGE_S = 1800
PRICE_RANGE = (0.02, 0.98)
BUCKETS = ((0.02, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 0.98))
C1_RANGE, C2_RANGE = (0.02, 0.25), (0.75, 0.98)
CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)
OOS_FRACTION = 0.20
MONTHS_PER_YEAR = 12
N_BOOT, BOOT_SEED = 2000, 0


@dataclass(frozen=True)
class Variant:
    id: str
    side: str                 # "sell YES" or "buy YES"
    lo: float
    hi: float
    universe: str | None      # None, or "S9"
    classes: tuple[str, ...] | None


VARIANTS = (
    Variant("V0", "sell YES", 0.05, 0.25, None, None),          # primary
    Variant("V1", "buy YES", 0.75, 0.95, None, None),
    Variant("V2", "sell YES", 0.05, 0.25, "S9", None),
    Variant("V3", "sell YES", 0.05, 0.25, None, ("crude",)),
    Variant("V4", "sell YES", 0.05, 0.95, None, None),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_EVENTS = 30, 10
