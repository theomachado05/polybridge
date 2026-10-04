"""S9 weekend price markets: every fixed parameter of METHOD.md. Committed with it, before any price of these markets is pulled."""
from __future__ import annotations

from dataclasses import dataclass

# ---- universe (catalogue metadata only)
SEARCHES = ("hit in", "hit by end of", "hit__", "hit __", "settle at", "Crude Oil", "WTI", "(CL)", "Gold (GC)", "Gold (XAUUSD)",
            "(GC)", "Silver (SI)", "Silver (XAGUSD)", "(SPX)", "S&P 500 hit", "(NVDA) hit", "(TSLA) hit", "hit Week of", "Natural Gas",
            "Crude Oil (CL) hit")
SEARCH_PAGES = 5
KIND_RE = r"hit|settle at"
EXCLUDE_RE = r"all time high"
ASSET_CLASSES = (                       # first match wins; the asset must be shut from Friday evening to Sunday 18:00 New York time
    ("crude", r"crude oil|\(WTI\)|\(CL\)"),
    ("gold", r"gold \("),
    ("silver", r"silver \("),
    ("sp500", r"S&P 500"),
    ("stock", r"\((META|TSLA|NVDA|GOOGL|AMZN|MSFT|AAPL|NFLX|PLTR)\)"),
)
MIN_EVENT_VOLUME = 1_000_000.0
MIN_MARKET_VOLUME = 50_000.0

# ---- the weekend clock, New York time
START_ET = "20:00"                      # the last session day before the weekend: after-hours trading has ended
ENTRY_SUNDAY_ET = "17:55"               # five minutes before futures reopen
EXIT_AFTER_OPEN_S = 600                 # 09:40 on the next stock-market session
EARLY_EXIT_SUNDAY_ET = "19:00"          # one hour after futures reopen (variant)
PM_MAX_AGE_S = 1800
LIVE_BAND = (0.10, 0.90)                # the Friday price of a market that counts as live
ENTRY_BAND = (0.05, 0.95)

# ---- costs: half-spread per fill, in price units, by asset class. Measured on this weekend's live books of the open
# markets of each class priced between 10% and 90% (Sat 2026-10-03 22:13 New York time; METHOD.md section 0).
HALF_SPREAD = {"crude": 0.005, "gold": 0.0125, "silver": 0.02, "sp500": 0.01, "stock": 0.025}
CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)
MAX_POSITIONS = 10
PRINT_PAGES = 2
PRINT_WINDOW_S = 600

# ---- the link test (crude only)
OIL_TICKERS = ("USO", "XLE", "XOP", "XOM", "CVX", "OXY")
TEST_THRESHOLDS = (5.0, 10.0)

OOS_FRACTION = 0.20
WEEKENDS_PER_YEAR = 52


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float         # weekend move, points
    direction: str           # "fade" or "follow"
    exit: str                # "monday" or "sunday 19:00"
    classes: tuple[str, ...] | None


VARIANTS = (
    Variant("V0", 5.0, "fade", "monday", None),                # primary
    Variant("V1", 10.0, "fade", "monday", None),
    Variant("V2", 5.0, "fade", "monday", ("crude",)),
    Variant("V3", 5.0, "fade", "sunday 19:00", ("crude", "gold", "silver", "sp500")),
    Variant("V4", 5.0, "follow", "monday", None),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_WEEKENDS, MIN_VERIFIED_SHARE = 30, 5, 0.5
