"""S21 options anchor: every fixed parameter of METHOD.md. Committed with it, before any option quote is pulled."""
from __future__ import annotations

from dataclasses import dataclass

TODAY = "2026-10-04"
ASSET_CLASSES = ("stock", "sp500")

# ---- the anchor
ANCHOR_BEFORE_CLOSE_S = 300          # 15:55 New York on a full session; five minutes before the close on a half day
STALE_OPTION_S = 600                 # a leg quote may be at most 10 minutes older than the anchor instant
MAX_STEP_OUT = 2                     # a leg with no usable quote moves outward by at most two listed strikes
RATE = 0.04                          # the existing code's rate, to undo the discount on the spread
MAX_EXPIRY_GAP_DAYS = 45             # the expiry is at most this many calendar days after the window's last session day
MAX_EXPIRY_TRIES = 3                 # listed expiries tried, in order, until one gives two usable legs
CENTRAL_MULTIPLE = 2.0               # reflection rule: touch probability = twice the finish-beyond probability, capped at 1
INDEX_ROOT = {"SPX": "O:SPXW"}       # S&P 500 index questions use the PM-settled index options at the index level named

# ---- the tests
GAP_BUCKETS = ((None, -5.0), (-5.0, 0.0), (0.0, 5.0), (5.0, 10.0), (10.0, None))   # points, traded price minus central anchor
N_BOOT, BOOT_SEED = 2000, 0          # the event bootstrap of S7/S18 (imported), same seed
CONTRACTS = 100                      # S18's book: up to 100 contracts per market, never more than the printed size
MONTHS_PER_YEAR = 12
MIN_OOS_MARKETS = 30


@dataclass(frozen=True)
class Book:
    id: str
    side: str            # "sell" (sell YES at the traded bid) or "buy" (buy YES at the traded ask)
    anchor: str          # "central" or "lower"
    threshold: float     # points; sell: traded price - anchor >= threshold; buy: anchor - traded price >= threshold
    note: str


BOOKS = (
    Book("B0", "sell", "central", 5.0, "primary: sell YES at the traded bid when it is 5+ points above the central anchor"),
    Book("B1", "sell", "central", 10.0, "variant: the same at 10+ points"),
    Book("B2", "buy", "lower", 5.0, "variant: buy YES at the traded ask when it is 5+ points below the lower-bound anchor"),
)
PRIMARY = "B0"
FEE_MULTIPLES = (1.0, 2.0)

# ---- the pull (Massive only)
MAX_RPS = 2.0
SLOW_RPS = 1.0
RECORDER_TOLERANCE = 5               # more new `fetch failed` lines than this while pulling: drop to SLOW_RPS
RECORDER_CHECK_EVERY = 20            # requests between two reads of the recorder's log
PULL_ORDER_SEED = 21                 # events are pulled in a seeded random order, so a pull cut short leaves a random sample
PULL_STOP_ET = "2026-10-04 02:05"    # hard stop of the pull, New York time; what is not anchored by then is reported as not pulled
