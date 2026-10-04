from __future__ import annotations

from dataclasses import dataclass

ASSET_CLASSES = (
    ("crude", r"crude oil|\(WTI\)|\(CL\)"),
    ("gold", r"gold \("),
    ("silver", r"silver \("),
    ("sp500", r"S&P 500"),
    ("natgas", r"natural gas"),
    ("stock", r"\((META|TSLA|NVDA|GOOGL|AMZN|MSFT|AAPL|NFLX|PLTR|OPEN|RKLB|HOOD|MU|EWY)\)"),
)
MIN_EVENT_VOLUME = 100_000.0
MIN_MARKET_VOLUME = 10_000.0

RISE, QUIET = 5.0, 2.0
TEST_THRESHOLDS = (5.0, 10.0)
LIVE_BAND = (0.10, 0.90)
ENTRY_BAND = (0.05, 0.95)
PM_MAX_AGE_S = 1800

HALF_SPREAD = {"crude": 0.005, "gold": 0.0125, "silver": 0.02, "sp500": 0.01, "stock": 0.025, "natgas": 0.02}
HALF_SPREAD_WEEKLY = 0.03
CONTRACTS = 100
MAX_POSITIONS = 10
PRINT_PAGES = 2
PRINT_WINDOW_S = 600
OOS_FRACTION = 0.20
WEEKENDS_PER_YEAR = 52


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float
    classes: tuple[str, ...] | None


VARIANTS = (
    Variant("V0", 5.0, None),
    Variant("V1", 10.0, None),
    Variant("V2", 5.0, ("crude",)),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_WEEKENDS, MIN_VERIFIED_SHARE = 30, 5, 0.5
