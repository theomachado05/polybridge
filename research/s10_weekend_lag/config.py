"""S10 weekend lag: every fixed parameter of METHOD.md. Committed with it, before any price is read for this test."""
from __future__ import annotations

from dataclasses import dataclass

# ---- the weekend window, New York time (S9's clock: s9_weekend_price_markets.run.calendar())
START_ET = "20:00"                      # the last session day before the weekend
END_SUNDAY_ET = "17:55"                 # five minutes before futures reopen
LOOKBACK_S = 900                        # signals start 15 minutes after the start (the 15-minute rule needs it)
LAST_SIGNAL_BEFORE_END_S = 1800         # the last signal is at Sunday 17:25, so a 30-minute exit is at or before 17:55

# ---- the grid
BIN_S = 300                             # five-minute bins
PM_MAX_AGE_S = 300                      # a one-minute reading is valid for five minutes
LIVE_BAND = (0.10, 0.90)                # price at the start of a market that counts as live that weekend (S9)
JUMP_REF_BAND = (0.05, 0.95)            # an event question's price before a jump must be inside this band
ENTRY_BAND = (0.05, 0.95)               # a price market's mid at the entry minute must be inside this band

# ---- what counts as a jump (either rule), in points
JUMP_RULES = ((300, 3.0), (900, 5.0))   # (window seconds, minimum absolute change): 3 points in 5 minutes, 5 points in 15
HORIZONS_S = (300, 900, 1800, 3600)     # 5, 15, 30, 60 minutes

# ---- the event questions (S9 T2): S5 and S4 agreed links naming one of these tickers, signed by link direction
OIL_TICKERS = ("USO", "XLE", "XOP", "XOM", "CVX", "OXY")

# ---- the trade
ENTRY_DELAY_S = 60                      # the next minute's price after the signal
REFRACTORY_S = 1800                     # after a signal, no new signal on the same weekend for 30 minutes
MAX_SIGNALS_PER_WEEKEND = 3             # the first three signals of a weekend
MAX_MARKETS_PER_SIGNAL = 5              # the live signed markets of the class whose entry mid is closest to 50%
HALF_SPREAD = {"crude": 0.005, "gold": 0.0125}   # S9's half-spreads (live books of Sat 2026-10-03 22:13 New York time)
CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)

# ---- the print check (step 4)
PRINT_WINDOW_S = 300                    # a public print within five minutes after the signal
PRINT_PAGES = 2                         # the data API serves the latest 20,000 prints of a market
PRINT_RATE = 2.5                        # requests a second (the brief caps Polymarket at 3)

OOS_FRACTION = 0.20
WEEKENDS_PER_YEAR = 52
N_BOOT, BOOT_SEED = 2000, 0


@dataclass(frozen=True)
class Variant:
    id: str
    asset_class: str
    exit: str                # "30m", "60m" or "sunday 17:55"


VARIANTS = (
    Variant("V0", "crude", "30m"),            # primary
    Variant("V1", "crude", "60m"),
    Variant("V2", "crude", "sunday 17:55"),
    Variant("V3", "gold", "30m"),
    Variant("V4", "gold", "60m"),
    Variant("V5", "gold", "sunday 17:55"),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_WEEKENDS, MIN_VERIFIED_SHARE = 30, 5, 0.5
LEAD_T = 2.0                             # |t| at or above which a lead or lag slope is called significant
