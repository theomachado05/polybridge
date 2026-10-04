from __future__ import annotations

from dataclasses import dataclass

SEARCHES = ("hit in", "hit by end of", "hit__", "hit __", "settle at", "Crude Oil", "WTI", "(CL)", "Gold (GC)", "Gold (XAUUSD)",
            "(GC)", "Silver (SI)", "Silver (XAGUSD)", "(SPX)", "S&P 500 hit", "(NVDA) hit", "(TSLA) hit", "hit Week of", "Natural Gas",
            "Crude Oil (CL) hit")
SEARCH_PAGES = 5
KIND_RE = r"hit|settle at"
EXCLUDE_RE = r"all time high"
ASSET_CLASSES = (
    ("crude", r"crude oil|\(WTI\)|\(CL\)"),
    ("gold", r"gold \("),
    ("silver", r"silver \("),
    ("sp500", r"S&P 500"),
    ("stock", r"\((META|TSLA|NVDA|GOOGL|AMZN|MSFT|AAPL|NFLX|PLTR)\)"),
)
MIN_EVENT_VOLUME = 1_000_000.0
MIN_MARKET_VOLUME = 50_000.0

START_ET = "20:00"
ENTRY_SUNDAY_ET = "17:55"
EXIT_AFTER_OPEN_S = 600
EARLY_EXIT_SUNDAY_ET = "19:00"
PM_MAX_AGE_S = 1800
LIVE_BAND = (0.10, 0.90)
ENTRY_BAND = (0.05, 0.95)

HALF_SPREAD = {"crude": 0.005, "gold": 0.0125, "silver": 0.02, "sp500": 0.01, "stock": 0.025}
CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)
MAX_POSITIONS = 10
PRINT_PAGES = 2
PRINT_WINDOW_S = 600

OIL_TICKERS = ("USO", "XLE", "XOP", "XOM", "CVX", "OXY")
TEST_THRESHOLDS = (5.0, 10.0)

OOS_FRACTION = 0.20
WEEKENDS_PER_YEAR = 52


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float
    direction: str
    exit: str
    classes: tuple[str, ...] | None


VARIANTS = (
    Variant("V0", 5.0, "fade", "monday", None),
    Variant("V1", 10.0, "fade", "monday", None),
    Variant("V2", 5.0, "fade", "monday", ("crude",)),
    Variant("V3", 5.0, "fade", "sunday 19:00", ("crude", "gold", "silver", "sp500")),
    Variant("V4", 5.0, "follow", "monday", None),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_WEEKENDS, MIN_VERIFIED_SHARE = 30, 5, 0.5
