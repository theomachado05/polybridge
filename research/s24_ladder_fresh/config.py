"""S24 fresh ladders: every fixed parameter of METHOD.md. Committed with it, before any print of these markets is pulled."""
from __future__ import annotations

# ---- the two fresh sets (catalogue text and metadata only; universe.py applies S11's ladder rules)
SET_A_LISTED = ("2024-01-01", "2025-09-30")     # a rung's listing date (catalogue startDate, else createdAt), UTC, inclusive
SET_A_MIN_VOLUME = 50_000.0                     # S11's floor
SET_B_LISTED = ("2025-10-01", "2026-10-03")     # S11's year
SET_B_VOLUME = (10_000.0, 50_000.0)             # at least $10,000 and under $50,000: below S11's floor
YES_NO = ["Yes", "No"]                          # a rung must be a Yes/No market: the trade is written in YES terms

# ---- catalogue reading (gamma /events, by event volume, largest first, 100 a page)
CAT_PAGE = 100
CAT_MAX_PAGES = {"a": 60, "b": 380}             # per query; a query also stops when a page's last event is under the floor below.
                                                # Set (a) fills its print budget from far fewer events than set (b), so (b) is read deeper.
CAT_OFFSET_CAP = 2000                           # the catalogue serves no offset above about 2,000: the query restarts below the last volume
CAT_STOP_EVENT_VOLUME = {"a": 100_000.0, "b": 20_000.0}   # two rungs at the set's volume floor

# ---- request budget: one worker, at most one request a second, 3,000 requests in all
RATE = 1.0                                      # requests a second
SLOW_RATE = 0.5                                 # after the recorder check trips: one request every two seconds
MAX_REQUESTS = 3000                             # catalogue + prints + results, probes included
MAX_PRINT_REQUESTS = 2400                       # prints: 1,200 per set first; what one set leaves goes to the other
PRINT_REQUESTS_PER_SET = 1200
RESULT_BATCH = 60                               # market ids per results request (gamma /markets?id=...&closed=true)
PULL_DEADLINE_ET = "2026-10-04 03:40"           # no new ladder is started after this (the ladder in progress is finished)
PRINT_PAGE, PRINT_PAGES = 10_000, 2             # data-api /trades: market=<conditionId>, limit=10000, offset=0 and 10000 (as S11)
RECORDER_LOG = "forward/recorder.log"           # read only
RECORDER_CHECK_EVERY = 20                       # requests between counts of "fetch failed"
RECORDER_MAX_NEW_FAILS = 5                      # more new lines than this: pause, then go on at SLOW_RATE
RECORDER_PAUSE_S = 120

# ---- detection, from prints only
WINDOW_S = 600                                  # the two prints are within 10 minutes of each other (primary)
WINDOW_VARIANT_S = 120                          # variant: within 2 minutes
# A qualifying match: a taker SELL of YES on the rich rung at price a, a taker BUY of YES on the cheap rung at price b,
# |t_a - t_b| <= window, both before either rung closed, and a - b > fee_rich(a) + fee_cheap(b).
# One trade per pair per New York day: the first match to complete (the later print's time). Ties in engine.first_matches.

# ---- the trade
HAIRCUT = 0.01                                  # sell one cent below the sale print, buy one cent above the purchase print
SIZE_CAP = 100.0                                # contracts; size = min(the two printed sizes), capped (primary); uncapped (capacity)
PRICE_CLIP = (0.001, 0.999)                     # a fill price outside this range is not a trade
COSTS = {1.0: {"fee_mult": 1.0, "haircut": 0.01},      # 1x: each market's own taker fee, one cent worse than the print
         2.0: {"fee_mult": 2.0, "haircut": 0.02}}      # 2x: fees doubled, each price one further cent worse. Same trades.

# ---- out-of-sample: within each set, the most recent 20% of the New York dates that have a primary trade (rounded up).
# The cut dates are computed from the dates alone and written to results/oos_cut.json before any P&L is computed.
OOS_SHARE = 0.20
# A second split fixed here, before the pull, from the calendar alone (reported next to the first, never the pass test):
CALENDAR_OOS_START = {"a": "2025-05-26",        # the last 20% of set (a)'s listing window (639 days), and every later date
                      "b": "2026-07-22"}        # the last 20% of S11's year; S11's own cut

N_BOOT, BOOT_SEED = 2000, 24

# ---- pass (all must hold, on the pooled primary trades at 1x; each set is also reported against the same lines)
MIN_OOS_TRADES, MIN_OOS_DATES = 30, 10
# 1. in-sample: net points per trade > 0 and the date-bootstrap 95% interval excludes zero
# 2. out-of-sample: net points per trade > 0 and the interval excludes zero
# 3. the same trades at 2x costs: net points per trade > 0, whole sample
# 4. at least 30 out-of-sample trades on 10 or more dates
