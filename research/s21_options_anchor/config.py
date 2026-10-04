from __future__ import annotations

from dataclasses import dataclass

TODAY = "2026-10-04"
ASSET_CLASSES = ("stock", "sp500")

ANCHOR_BEFORE_CLOSE_S = 300
STALE_OPTION_S = 600
MAX_STEP_OUT = 2
RATE = 0.04
MAX_EXPIRY_GAP_DAYS = 45
MAX_EXPIRY_TRIES = 3
CENTRAL_MULTIPLE = 2.0
INDEX_ROOT = {"SPX": "O:SPXW"}

GAP_BUCKETS = ((None, -5.0), (-5.0, 0.0), (0.0, 5.0), (5.0, 10.0), (10.0, None))
N_BOOT, BOOT_SEED = 2000, 0
CONTRACTS = 100
MONTHS_PER_YEAR = 12
MIN_OOS_MARKETS = 30


@dataclass(frozen=True)
class Book:
    id: str
    side: str
    anchor: str
    threshold: float
    note: str


BOOKS = (
    Book("B0", "sell", "central", 5.0, "primary: sell YES at the traded bid when it is 5+ points above the central anchor"),
    Book("B1", "sell", "central", 10.0, "variant: the same at 10+ points"),
    Book("B2", "buy", "lower", 5.0, "variant: buy YES at the traded ask when it is 5+ points below the lower-bound anchor"),
)
PRIMARY = "B0"
FEE_MULTIPLES = (1.0, 2.0)

MAX_RPS = 2.0
SLOW_RPS = 1.0
RECORDER_TOLERANCE = 5
RECORDER_CHECK_EVERY = 20
PULL_ORDER_SEED = 21
PULL_STOP_ET = "2026-10-04 02:05"
