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


# ==== Part 2, the mechanism (METHOD.md amendment 1, added before any price of these pairs is read) ====
# Pairs: type B, two event questions linked to the same ticker (all hours, full history); type A, an event question
# and a Polymarket price market on the asset its link names (weekend windows only, the S9 cache).
TICKER_CLASS = {**{t: "crude" for t in OIL_TICKERS}, "GLD": "gold",
                **{t: "stock:" + t for t in ("MSFT", "AMZN", "GOOGL", "NVDA", "TSLA", "META")}}
ACTIVITY_WINDOW_S = 3600        # activity of a market = minutes in the last hour in which its one-minute price changed
STALE_WINDOW_S = 900            # a market is stale at t if its price did not change in the 15 minutes before t
PAIR_BAND = (0.05, 0.95)        # both prices inside this band at t - 5 minutes for a pair-bin to count
MECH_HORIZONS_S = (300, 900, 1800)
N_BOOT_MECH = 1000
# the pick-off trade (type B primary, type A variant)
EVENT_HALF_SPREAD = 0.005       # S8: half of the 1.0-point median spread of event markets (S5 cost snapshot)
EVENT_FEE_RATE = 0.04           # taker fee 0.04 x P x (1 - P), as S8
PICKOFF_EXIT_S = 1800
PICKOFF_MAX_PER_DATE = 10


# ==== Part 3, a mechanical link: 15-minute Bitcoin Up/Down markets against spot (METHOD.md amendment 2) ====
BTC_SLUG = "btc-updown-15m-{start}"      # start = window start, epoch seconds (multiple of 900)
BTC_FIRST_ET = "2026-08-04 00:00"        # windows starting from here ...
BTC_LAST_ET = "2026-10-03 00:00"         # ... to here (60 days, 5,760 windows)
BTC_WINDOW_S = 900
BTC_SPOT = "coinbase BTC-USD 1-minute candles"
BTC_VOL_LOOKBACK_MIN = 60                # volatility: std of the last 60 one-minute log returns
BTC_SIGNAL_MINUTES = tuple(range(1, 14)) # minutes into the window at which a signal is read (entry one minute later)
BTC_HALF_SPREAD = 0.005                  # half of the 1.0-point spread on the live books, Sat 2026-10-03 23:50 New York time
BTC_PM_MAX_AGE_S = 120
BTC_PRINT_WINDOW_S = 120                 # a print within two minutes after the signal
BTC_GAMMA_BATCH = 20
BTC_RATE = 1.8                           # 2.5 in amendment 2; lowered for the print check so a live recorder (amendment 5) fits under 3 a second


@dataclass(frozen=True)
class BtcVariant:
    id: str
    theta: float             # minimum |fair - Polymarket| in points to trade
    min_minute: int          # earliest signal minute


BTC_VARIANTS = (
    BtcVariant("B0", 5.0, 1),             # primary
    BtcVariant("B1", 3.0, 1),
    BtcVariant("B2", 10.0, 1),
    BtcVariant("B3", 5.0, 10),
)
BTC_PRIMARY = "B0"
BTC_MIN_OOS_TRADES, BTC_MIN_OOS_DATES = 30, 10


# ==== Part 4, hold the stale side to the result (METHOD.md amendment 3) ====
HOLD_SOURCE = "results/s10_weekend_lag/mechanism/trades.csv"   # Part 2's type-B pick-off entries at 1x
HOLD_MIN_OOS_TRADES, HOLD_MIN_OOS_QUESTIONS = 30, 10
