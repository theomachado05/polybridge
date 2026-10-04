"""S20 closed against open: every fixed parameter of METHOD.md. Committed with it, before any print outside W1 is pulled."""
from __future__ import annotations

# ---- windows (METHOD.md section 1)
WINDOW_S = 48 * 3600                    # W1 and W2 are 48 hours long, as S18's first weekend
WEEKEND_START_ET = "20:00"              # 20:00 New York on the last session day before a weekend (S9's and S18's clock)
SESSION_S = int(6.5 * 3600)             # a regular session: 09:30 to 16:00 New York
EARLY_SESSION_S = int(3.5 * 3600)       # an early close: 09:30 to 13:00 New York
EARLY_IF_SHORTER_THAN_S = 6 * 3600      # a calendar session shorter than this is an early close
WINDOWS = ("W1", "D1", "W2")

# ---- which markets count in a window (METHOD.md section 3)
RULES = ("A", "B")                      # A: the result came after the window's end (as briefed). B: after the window's start, prints before the result only.
PRIMARY_RULE = "A"

# ---- one observation per market, window and taker side (S18's formulas)
FEE_MULTIPLIERS = (1.0, 2.0)
BUCKETS = ((0.02, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 0.98))     # S18's
CLASS_GROUPS = {"stocks and S&P 500": ("stock", "sp500"), "commodities": ("crude", "gold", "silver", "natgas")}

# ---- the book (S18's book function)
CONTRACTS = 100
MONTHS_PER_YEAR = 12

# ---- inference (S18's and S7's: events are resampled, an event is one bet)
N_BOOT, BOOT_SEED = 2000, 0

# ---- the pull (METHOD.md section 7)
PAGE, PAGES = 10000, 2                  # the data API serves the latest 20,000 prints of a market
REQUESTS_PER_S = 1.0                    # one worker, at most one request a second
SLOW_REQUESTS_PER_S = 0.5               # after the recorder guard trips: one request every two seconds
GUARD_GROWTH = 5                        # more than this many new `fetch failed` lines in the recorder's log trips the guard
GUARD_PAUSE_S = 120
GUARD_EVERY_REQUESTS = 10               # the recorder's log is counted this often
