"""S16 overnight options: every fixed parameter of METHOD.md. Committed with it, before any option quote is pulled."""
from __future__ import annotations

from dataclasses import dataclass

TODAY = "2026-10-03"

# ---- events (from research/results/s8_open_referee/mornings.csv; odds only)
MAIN_THRESHOLD = 10.0            # points of overnight odds move, main sample
LOOSE_THRESHOLD = 5.0            # variant V3 and the case files
OOS_FRACTION = 0.20
OOS_FROM = "2026-06-22"          # the most recent 22 of the 109 main-sample event dates; counted from odds before any quote
SINCE_DAY = "2026-07-01"         # the "12 largest recent moves" table
TOP_N = 12

# ---- controls
CONTROL_MAX_TRADING_DAYS = 30
QUIET_BELOW = 2.0                # no linked question moved this many points overnight
PM_MAX_AGE_S = 1800              # as S8: an odds reading older than 30 minutes is missing

# ---- contracts
EXPIRY_MIN_DAYS, EXPIRY_MAX_DAYS = 7, 45
STRIKE_BAND = 0.08               # the listing request asks for strikes within 8% of the first price
OPEN_BAR_MAX_LATE_S = 600        # the first bar must start within 10 minutes of 09:30

# ---- instants, New York time
PREV_CLOSE, T0931, T0935, T0945, T1000, T1030, CLOSE = "prev 15:55", "09:31", "09:35", "09:45", "10:00", "10:30", "15:55"
MORNING = (T0931, T0935, T0945, T1000, T1030)
PRIMARY_ENTRY, PRIMARY_EXIT = T0935, CLOSE
MORNING_QUOTE_MAX_AGE_S = 900    # S7's Monday rule; and the quote must be stamped at or after 09:30 that day
CLOSE_QUOTE_MAX_AGE_S = 600      # S7's Friday 15:55 rule

# ---- costs
COMMISSION = 0.65                # dollars per contract per leg, each way (S7)
COST_MULTIPLIERS = (1.0, 2.0)    # 2x doubles every half-spread and every commission

# ---- inference
N_BOOT, BOOT_SEED = 2000, 0
MIN_OOS_TRADES = 30
DAYS_PER_YEAR = 252

HYPOTHESES = ("H-dir", "H-slow", "H-rich")


@dataclass(frozen=True)
class Variant:
    id: str
    entry: str
    exit: str
    threshold: float
    weekends_only: bool
    note: str


VARIANTS = (
    Variant("V0", T0935, CLOSE, 10.0, False, "primary"),
    Variant("V1", T0931, CLOSE, 10.0, False, "entry at 09:31"),
    Variant("V2", T0935, T1030, 10.0, False, "exit at 10:30"),
    Variant("V3", T0935, CLOSE, 5.0, False, "moves of 5+ points"),
    Variant("V4", T0935, CLOSE, 10.0, True, "weekends and holidays only"),
)
PRIMARY = "V0"

# ---- case files (exploratory)
BRAZIL_MARKETS = {"polymarket:4037599": -1, "polymarket:4037600": +1, "polymarket:1365861": +1}   # EWZ sign, S4's proposer links
BRAZIL_TICKER = "EWZ"
OIL_TICKERS = ("USO", "XLE", "XOP")
FED_TICKERS = ("TLT", "KRE", "XLF")
FED_REGEX = r"\bfed\b|interest rates"      # question text of a link in s8_open_referee.run.links(), case-insensitive

# ---- the pull (Massive only)
MAX_RPS = 2.0                    # one worker
SLOW_RPS = 1.0                   # if the recorder's `fetch failed` count grows by more than RECORDER_TOLERANCE during the pull
RECORDER_TOLERANCE = 5
RECORDER_CHECK_EVERY = 50        # requests between two counts of the recorder log
PULL_HARD_STOP_ET = "2026-10-04 01:50"     # the pull stops here whatever is done
TIER_SEED = 16                   # seeded shuffle of tiers 4 and 5, so a tier cut by the stop is a random subsample
