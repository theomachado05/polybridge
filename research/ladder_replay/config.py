"""Ladder replay: every fixed parameter of METHOD.md. Committed with it, before any new data pull or computation."""
from __future__ import annotations

# ---- settlement-rule check (step 1)
MANUAL_SAMPLE_N, MANUAL_SAMPLE_SEED = 20, 2026
# A pair (rich A, cheap B) is nested when, after normalisation, A's and B's market descriptions are identical once each
# rung's own key (its date for a date ladder, its level for a strike ladder) is replaced by a placeholder, and the
# resolution sources (market resolutionSource, else the event's) are identical. Normalisation: lower case, whitespace
# collapsed, the rung's own key replaced wherever it appears in any of its spellings ("June 30", "June 30, 2026",
# "Jun 30", "June 30th", "30 June"; "$100", "100", "100.00", "100,000"). Every other date, time, timezone and number is
# kept verbatim, so a different window start, cutoff hour, timezone or source makes the pair not nested.

# ---- causal replay (steps 2 and 3)
PAIR_WINDOW_S = 60                      # both legs' qualifying taker prints within 60 seconds; entry at the later print
TICKS_AGAINST = 1                       # fill = printed price moved one tick against us (tick = market's orderPriceMinTickSize)
DEFAULT_TICK = 0.01
MAX_CONTRACTS = 100                     # size = min(print size A, print size B, 100)
PAIR_COOLDOWN_S = 3600                  # a pair can be entered again only an hour after its last entry (S11 episode gap)
MAX_NEW_TRADES_PER_DAY = 10             # first come first served (New York date); causal, unlike "largest first"
PRINT_PAGES, PRINT_PAGE = 2, 10000      # data-api trades, taker prints only: the latest 20,000 prints of a market
REQ_RATE = 3.0                          # requests a second, all endpoints together
WINDOW_START, WINDOW_END = "2025-10-01", "2026-10-04"   # entries between these New York dates (end exclusive)
S11_OOS_START = "2026-07-22"
N_BOOT, BOOT_SEED = 2000, 41

# ---- pass rule (step 3, fresh universe, confirmatory)
PASS_MIN_TRADES, PASS_MIN_DATES = 30, 15
# PASS: date-clustered 95% bootstrap interval of net P&L per trade (points per contract, trade-weighted) entirely above 0,
#       with >= 30 trades on >= 15 New York entry dates.
# NULL: >= 30 trades on >= 15 dates and the interval includes or lies below 0.
# INSUFFICIENT: fewer than 30 trades or fewer than 15 dates.

# ---- fresh catalogue (step 3): S11's date-ladder rule (s11_bundles.universe.date_ladders, $50k rung volume, "by/before")
FRESH_END_DATE_MIN = "2025-10-01"       # gamma events whose end date is on or after this and that hold >= 1 closed market
GAMMA_PAGE = 100

# ---- live (step 4)
LIVE_BOOKS_PER_CALL = 100
