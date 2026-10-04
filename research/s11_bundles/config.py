"""S11 bundles: every fixed parameter of METHOD.md. Committed with it, before any price of these markets is read."""
from __future__ import annotations

# ---- bundle rules (catalogue text only; universe.py applies them)
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
# a date phrase: "April 30", "April 30, 2026", "end of June", "June 2026", "December 31st"
DATE_RE = (r"(?:end of\s+)?(?:" + "|".join(m.capitalize() for m in MONTHS) + r"|" + "|".join(m.capitalize()[:3] for m in MONTHS)
           + r")\.?(?:\s+\d{1,2}(?:st|nd|rd|th)?)?(?:,?\s+20\d\d)?")
CUMULATIVE_DATE_RE = r"\b(?:by|before)\s+(?:the\s+)?@D@"      # "by <date>" or "before <date>": YES on an earlier date implies YES later
NUM_RE = r"[$€£]?\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:[kKmMbBtT]\b|%))?"
UP_WORDS = r"\(HIGH\)|↑|\babove\b|\bover\b|\bmore than\b|\bat least\b|>|\breach(?:es)?\b|\bexceeds?\b|\bhigher than\b|\+"
DOWN_WORDS = r"\(LOW\)|↓|\bbelow\b|\bunder\b|\bless than\b|<|\bdips? to\b|\bfalls? to\b|\blower than\b"
MIN_MARKET_VOLUME = 50_000.0            # a rung must have traded at least this much (catalogue volume, as S9)
NEGRISK_MAX_MEMBERS = 30                # one-of-many sets larger than this are left out (too many legs to buy at once)

# ---- history window (the same as S5's cache)
WINDOW_START, WINDOW_END = "2025-10-01", "2026-10-03"
OOS_START = "2026-07-22"                # the most recent 20% of the 367-day window, by date (New York)
MAX_NEW_PULLS = 1400                    # one-minute histories pulled for this study, beyond S5's and S9's caches. Order: every
                                        # date and strike ladder leg first, then one-of-many sets whole, largest event first,
                                        # stopping before a set that would pass the cap (a set is pulled whole or not at all).
                                        # Amendment 2: 2500 -> 1400, the server serves about 1.3 requests a second
PULL_RATE = 2.5                         # requests a second (the brief allows 3; the live logger takes the rest)
PRICE_MAX_AGE_S = 1800                  # a mid older than this does not count

# ---- costs. Half-spread per fill in price units, by bundle kind: the median over markets of the median half-spread
# seen in the first live snapshot hour of this study's own logger, markets with a mid between 10% and 90%, floored at
# half a tick (0.005). Fees: each market's own feeSchedule (rate * (p(1-p))**exponent), taker only.
HALF_SPREAD_FLOOR = 0.005
HALF_SPREAD_CALIBRATION_BAND = (0.10, 0.90)
PRICE_CLIP = (0.001, 0.999)

# ---- part (a): violations
# A monotone pair (rich leg A, cheap leg B) must have P(A) <= P(B). A violation at 1x costs is
#   (mid_A - h - fee_A) - (mid_B + h + fee_B) > 0, i.e. selling A and buying B at the assumed fills locks in money.
# One-of-many sets: buy every YES when sum(mid + h + fee) < 1; buy every NO when sum(mid - h - fee) > 1 (n NOs pay n-1).
EPISODE_GAP_S = 3600                    # a violation that reappears within an hour is the same episode
MIN_VIOLATION = 0.0                     # beyond costs, in price units
CONTRACTS = 100                         # per leg (one-of-many: per member)
MAX_NEW_TRADES_PER_DAY = 10             # cap: the largest violations first
PRINT_WINDOW_S = 600                    # a print within 10 minutes at a price at least as good proves a fill
PRINT_PAGES = 2

# ---- part (b): propagation (monotone pairs only)
JUMP_POINTS = 3.0                       # a rung moves 3+ points
JUMP_WINDOW_S = 300                     # within 5 minutes
JUMP_COOLDOWN_S = 3600                  # one jump per rung per hour
HORIZONS_S = (300, 900, 1800, 3600)     # the sibling's move over the next 5, 15, 30, 60 minutes
TRADE_ENTRY_DELAY_S = 60                # trade the sibling one minute after the jump is seen
TRADE_HOLD_S = 3600                     # exit 60 minutes after entry
ENTRY_BAND = (0.03, 0.97)               # the sibling's mid at entry

COST_MULTIPLIERS = (1.0, 2.0)
N_BOOT, BOOT_SEED = 2000, 11

# ---- live books (part a, live)
LIVE_INTERVAL_S = 180                   # one snapshot of every open bundle every three minutes
LIVE_UNTIL_ET = "2026-10-04 07:00"
BOOKS_PER_CALL = 100
LIVE_SEARCH_PAGES = 4                   # open events, by 24-hour volume, 100 a page
LIVE_MIN_EVENT_VOLUME = 100_000.0

# ---- success (all must hold)
# Violations, history: print-verified violation trades at 1x costs net positive per trade with the date-bootstrap 95%
# interval above 0 in-sample, positive out-of-sample, at least 30 out-of-sample trades on 5+ dates.
# Propagation: the primary trade (follow the jump in the sibling, 1x costs) has a date-bootstrap interval above 0
# in-sample, a positive mean out-of-sample on 30+ trades and 5+ dates, and is positive at 2x costs over the whole sample.
# Live: an arbitrage is a bundle whose books, at the best bid and ask and after both fees, lock in money for at least
# 1 contract. Reported as counts, dollars locked in at the size shown, and size; no pass/fail threshold.
MIN_OOS_TRADES, MIN_OOS_DATES = 30, 5
