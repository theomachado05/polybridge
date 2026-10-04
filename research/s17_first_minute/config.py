"""S17 first minute: every fixed parameter of METHOD.md. Committed with it, before any one-minute bar or stock quote is pulled."""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- events (S16 section 1, same rule)
MAIN_THRESHOLD = 10.0        # points of overnight odds move (previous 16:00 to 09:29), mornings.csv x
LOOSE_THRESHOLD = 5.0        # variant
OOS_FROM = "2026-06-22"      # S16's split: the most recent 20% of the 109 main-sample event dates

# ---------------------------------------------------------------- prices
# One-minute regular-session bars from Massive /v2/aggs (adjusted), ticker and SPY. Bar at hh:mm covers hh:mm to hh:mm+1.
OPEN_BAR_MAX_LAG_MIN = 2     # the first bar of the day must start by 09:32, else the ticker-day is dropped
WINDOWS = (                  # (name, start, end): "prev_close" = previous session's close (daily bars), "open" = 09:30 bar open,
    ("gap", "prev_close", "open"),          # hh:mm = close of the bar that ends at hh:mm (i.e. the bar starting one minute earlier)
    ("open_0931", "open", "09:31"),
    ("0931_0935", "09:31", "09:35"),
    ("0935_1000", "09:35", "10:00"),
    ("1000_close", "10:00", "close"),
    ("0931_close", "09:31", "close"),
)
PRIMARY_WINDOW = "0931_close"   # F1's headline: everything after the first minute
BETA_FROM = "S4 engine.betas: daily close-to-close on SPY, sessions strictly before the day"

# ---------------------------------------------------------------- trades at real stock quotes (Massive /v3/quotes NBBO)
ENTRY = "09:31"
EXITS = {"T1": "10:00", "T2": "15:55", "T3": "15:55"}
QUOTE_MAX_AGE_S = 120        # the NBBO at the instant must be this fresh, stamped after 09:30:00 that day
MAX_SPREAD_BP = 100.0        # a quote wider than this is invalid (ticker-day dropped for that trade)
COST_MULTIPLIERS = (1.0, 2.0)  # 2x: every half-spread doubled. No commission (ETFs and stocks, retail brokers charge none).
NOTIONAL = 10000.0           # $ per trade


@dataclass(frozen=True)
class Trade:
    id: str
    direction: str           # "follow" = trade the way the odds moved; "fade" = the other way
    only_unconfirmed: bool   # F2: only ticker-days whose gap went against (or not with) the odds move
    exit: str


TRADES = (
    Trade("T1", "follow", False, "10:00"),   # the first-minute thesis: the open has not finished pricing the night
    Trade("T1f", "fade", False, "10:00"),    # its mirror: the open over-shot (at most one of the two can pass)
    Trade("T2", "follow", False, "15:55"),
    Trade("T3", "follow", True, "15:55"),    # F2 catch-up: the asset opened against the odds and catches up
)
THRESHOLDS = (MAIN_THRESHOLD, LOOSE_THRESHOLD)   # every trade at both; 10+ is primary

# ---------------------------------------------------------------- inference
N_BOOT, BOOT_SEED = 2000, 0
MIN_OOS_TRADES = 30
DAYS_PER_YEAR = 252

# ---------------------------------------------------------------- pull
MASSIVE_RATE = 1.5           # requests a second; S16 pulls at 2 in parallel; the brief's ceiling is 5
STOP_PULL_ET = "04:30"       # Sunday; whatever is pulled by then is what is reported, labelled
