"""S25 ticket sold, option spread bought: every fixed parameter of METHOD.md. Committed with it, before any Monday
option quote or any underlying close is pulled."""
from __future__ import annotations

from dataclasses import dataclass

TODAY = "2026-10-04"

# ---- the markets and the rule subset (S21's B0, unchanged)
RULE_THRESHOLD_POINTS = 5.0          # ticket's traded bid 5+ points above S21's central anchor
CONTRACTS = 100                      # S18's book: up to 100 ticket contracts per market, never more than the printed size
MONTHS_PER_YEAR = 12

# ---- the hedge leg
HEDGE_TIME_ET = "09:35"              # primary: the first session after the ticket's weekend, New York time
SESSION_OPEN_ET = "09:30"            # a usable Monday quote is timestamped at or after the open of that session
HEDGE_STALE_S = 300                  # ... so it is at most 5 minutes older than the hedge instant
HEDGE_RATIO_PRIMARY = 2.0            # spreads per ticket: the reflection rule S21 used for its central anchor
HEDGE_RATIO_LOWER = 1.0              # variant A: the lower-bound replication
OPTION_COMMISSION_PER_CONTRACT = 0.65    # dollars per contract per leg (the existing cost model's figure, arbscan.costs)
SHARES_PER_CONTRACT = 100
EXPIRY_CLOSE_ET = "16:00"            # the hedge leg's P&L is booked at the close of the expiry date
INDEX_AGG_TICKER = {"SPX": "I:SPX"}  # the index's own close for the index questions; every other ticker is itself

# ---- the underlying's close and splits
CLOSE_FROM, CLOSE_TO = "2025-10-27", "2026-10-02"
SPLIT_RECONCILE_TOL = 0.005          # adjusted/unadjusted close must match the later splits to 0.5%
LEVEL_RATIO_BOUNDS = (0.2, 5.0)      # unadjusted close on the anchor Friday divided by the question's level must lie inside


@dataclass(frozen=True)
class Variant:
    id: str
    quotes: str          # "monday" (09:35 on the first session after the weekend) or "friday" (S21's 15:55 quotes)
    h: float             # spreads per ticket
    cost_mult: float     # 1.0: long leg at the ask, short leg at the bid; 2.0: each leg a further half-spread against us, fees doubled
    note: str


VARIANTS = (
    Variant("P", "monday", HEDGE_RATIO_PRIMARY, 1.0, "primary: 2 spreads per ticket, bought Monday 09:35"),
    Variant("A", "monday", HEDGE_RATIO_LOWER, 1.0, "variant A: 1 spread per ticket, bought Monday 09:35"),
    Variant("B", "friday", HEDGE_RATIO_PRIMARY, 1.0, "variant B: 2 spreads per ticket at Friday 15:55 quotes (not executable in that order)"),
    Variant("P2x", "monday", HEDGE_RATIO_PRIMARY, 2.0, "primary at 2x costs"),
    Variant("A2x", "monday", HEDGE_RATIO_LOWER, 2.0, "variant A at 2x costs"),
    Variant("B2x", "friday", HEDGE_RATIO_PRIMARY, 2.0, "variant B at 2x costs"),
)
PRIMARY = "P"

# ---- intervals
N_BOOT, BOOT_SEED = 2000, 0          # the event bootstrap of S7/S18/S21, same draws and seed
MIN_EVENTS_FOR_INTERVAL = 5

# ---- the pull (Massive only)
MAX_RPS = 2.0
SLOW_RPS = 1.0
RECORDER_TOLERANCE = 5               # more new `fetch failed` lines than this while pulling: drop to SLOW_RPS
RECORDER_CHECK_EVERY = 20            # requests between two reads of the recorder's log
PULL_ORDER_SEED = 25                 # events are pulled in a seeded random order, so a pull cut short leaves a random sample
PULL_STOP_ET = "2026-10-04 02:50"    # hard stop of the pull, New York time; what is not pulled by then is reported as not pulled
