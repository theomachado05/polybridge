from __future__ import annotations

from dataclasses import dataclass

TODAY = "2026-10-04"

RULE_THRESHOLD_POINTS = 5.0
CONTRACTS = 100
MONTHS_PER_YEAR = 12

HEDGE_TIME_ET = "09:35"
SESSION_OPEN_ET = "09:30"
HEDGE_STALE_S = 300
HEDGE_RATIO_PRIMARY = 2.0
HEDGE_RATIO_LOWER = 1.0
OPTION_COMMISSION_PER_CONTRACT = 0.65
SHARES_PER_CONTRACT = 100
EXPIRY_CLOSE_ET = "16:00"
INDEX_AGG_TICKER = {"SPX": "I:SPX"}

CLOSE_FROM, CLOSE_TO = "2025-10-27", "2026-10-02"
SPLIT_RECONCILE_TOL = 0.005
LEVEL_RATIO_BOUNDS = (0.2, 5.0)


@dataclass(frozen=True)
class Variant:
    id: str
    quotes: str
    h: float
    cost_mult: float
    note: str


VARIANTS = (
    Variant("P", "monday", HEDGE_RATIO_PRIMARY, 1.0, "primary: 2 spreads per ticket, bought Monday 09:35"),
    Variant("A", "monday", HEDGE_RATIO_LOWER, 1.0, "variant A: 1 spread per ticket, bought Monday 09:35"),
    Variant("B", "friday", HEDGE_RATIO_PRIMARY, 1.0, "variant B: 2 spreads per ticket at Friday 15:55 quotes (not executable in that order)"),
    Variant("P2x", "monday", HEDGE_RATIO_PRIMARY, 2.0, "primary at 2x costs"),
    Variant("A2x", "monday", HEDGE_RATIO_LOWER, 2.0, "variant A at 2x costs"),
    Variant("B2x", "friday", HEDGE_RATIO_PRIMARY, 2.0, "variant B at 2x costs"),
)
PRIMARY = "P"

N_BOOT, BOOT_SEED = 2000, 0
MIN_EVENTS_FOR_INTERVAL = 5

MAX_RPS = 2.0
SLOW_RPS = 1.0
RECORDER_TOLERANCE = 5
RECORDER_CHECK_EVERY = 20
PULL_ORDER_SEED = 25
PULL_STOP_ET = "2026-10-04 02:50"
