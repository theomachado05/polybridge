"""touch_fresh forward test: every fixed parameter of FORWARD.md. Committed before any market it covers is listed."""
from __future__ import annotations

FIRST_LISTING_ET = "2026-10-05 00:00"     # markets whose startDate is at or after this instant, New York time
TAG = "hit-price"
SNAPSHOT_ET = "15:55"                     # Friday (12:55 on a half session): catalogue snapshot and option anchor
PRINTS_FROM_ET = "20:00"                  # Friday 20:00 to Sunday 20:00: the first weekend's taker prints
PRINT_WINDOW_S = 48 * 3600
MIN_MARKET_VOLUME = 10_000.0              # read at the Sunday 20:00 snapshot, before any result
PRICE_BAND = (0.02, 0.98)
THRESHOLD = 5.0                           # sell YES at the traded bid when it is 5+ points above the matched central anchor
FEE_MULTIPLES = (1.0, 2.0)
N_BOOT, BOOT_SEED = 2000, 0
MIN_MARKETS, MIN_EVENTS = 30, 15          # resolved B0 markets and events needed for a verdict
EVALUATE_BY = "2027-06-30"                # if the minimum is not reached by this date: INSUFFICIENT
LOG_DIR = "forward_log"                   # one JSON line per market per stage, append only
