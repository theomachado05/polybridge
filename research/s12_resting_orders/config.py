from __future__ import annotations

from dataclasses import dataclass

S9_VARIANT = "V0"
S8_MIN_MOVE_PP = 10.0
S8_ENTRY_BAND = (0.05, 0.95)
SAMPLES = ("S9", "S8")
PRIMARY_SAMPLE = "S9"

TICK = 0.01
CONTRACTS = 100
QUEUE_ALLOWANCE = 500.0
TAKER_ONLY = True
PRINT_PAGES = 2
PRINT_RATE = 3.0
MAX_WINDOW_S = 120 * 60
PM_MAX_AGE_S = 1800

S8_HALF_SPREAD = 0.005
S9_HALF_SPREAD = {"crude": 0.005, "gold": 0.0125, "silver": 0.02, "sp500": 0.01, "stock": 0.025}
S8_FEE_RATE, S8_FEE_EXPONENT = 0.04, 1.0
COST_MULTIPLIERS = (1.0, 2.0)


@dataclass(frozen=True)
class Variant:
    id: str
    window_min: int
    offset_ticks: int


VARIANTS = (
    Variant("R0", 30, 0),
    Variant("R1", 120, 0),
    Variant("R2", 30, 1),
    Variant("R3", 120, 1),
)
PRIMARY = "R0"

N_BOOT, BOOT_SEED = 10000, 12
S9_WEEKENDS_PER_YEAR, S8_DAYS_PER_YEAR = 52, 252
CAPACITY_SIZES = (100, 500, 2000, 10000)

MIN_OOS_FILLED, MIN_OOS_GROUPS = 15, 5
