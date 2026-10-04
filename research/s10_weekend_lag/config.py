from __future__ import annotations

from dataclasses import dataclass

START_ET = "20:00"
END_SUNDAY_ET = "17:55"
LOOKBACK_S = 900
LAST_SIGNAL_BEFORE_END_S = 1800

BIN_S = 300
PM_MAX_AGE_S = 300
LIVE_BAND = (0.10, 0.90)
JUMP_REF_BAND = (0.05, 0.95)
ENTRY_BAND = (0.05, 0.95)

JUMP_RULES = ((300, 3.0), (900, 5.0))
HORIZONS_S = (300, 900, 1800, 3600)

OIL_TICKERS = ("USO", "XLE", "XOP", "XOM", "CVX", "OXY")

ENTRY_DELAY_S = 60
REFRACTORY_S = 1800
MAX_SIGNALS_PER_WEEKEND = 3
MAX_MARKETS_PER_SIGNAL = 5
HALF_SPREAD = {"crude": 0.005, "gold": 0.0125}
CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)

PRINT_WINDOW_S = 300
PRINT_PAGES = 2
PRINT_RATE = 2.5

OOS_FRACTION = 0.20
WEEKENDS_PER_YEAR = 52
N_BOOT, BOOT_SEED = 2000, 0


@dataclass(frozen=True)
class Variant:
    id: str
    asset_class: str
    exit: str


VARIANTS = (
    Variant("V0", "crude", "30m"),
    Variant("V1", "crude", "60m"),
    Variant("V2", "crude", "sunday 17:55"),
    Variant("V3", "gold", "30m"),
    Variant("V4", "gold", "60m"),
    Variant("V5", "gold", "sunday 17:55"),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_OOS_TRADES, MIN_OOS_WEEKENDS, MIN_VERIFIED_SHARE = 30, 5, 0.5
LEAD_T = 2.0


TICKER_CLASS = {**{t: "crude" for t in OIL_TICKERS}, "GLD": "gold",
                **{t: "stock:" + t for t in ("MSFT", "AMZN", "GOOGL", "NVDA", "TSLA", "META")}}
ACTIVITY_WINDOW_S = 3600
STALE_WINDOW_S = 900
PAIR_BAND = (0.05, 0.95)
MECH_HORIZONS_S = (300, 900, 1800)
N_BOOT_MECH = 1000
EVENT_HALF_SPREAD = 0.005
EVENT_FEE_RATE = 0.04
PICKOFF_EXIT_S = 1800
PICKOFF_MAX_PER_DATE = 10


BTC_SLUG = "btc-updown-15m-{start}"
BTC_FIRST_ET = "2026-08-04 00:00"
BTC_LAST_ET = "2026-10-03 00:00"
BTC_WINDOW_S = 900
BTC_SPOT = "coinbase BTC-USD 1-minute candles"
BTC_VOL_LOOKBACK_MIN = 60
BTC_SIGNAL_MINUTES = tuple(range(1, 14))
BTC_HALF_SPREAD = 0.005
BTC_PM_MAX_AGE_S = 120
BTC_PRINT_WINDOW_S = 120
BTC_GAMMA_BATCH = 20
BTC_RATE = 1.8


@dataclass(frozen=True)
class BtcVariant:
    id: str
    theta: float
    min_minute: int


BTC_VARIANTS = (
    BtcVariant("B0", 5.0, 1),
    BtcVariant("B1", 3.0, 1),
    BtcVariant("B2", 10.0, 1),
    BtcVariant("B3", 5.0, 10),
)
BTC_PRIMARY = "B0"
BTC_MIN_OOS_TRADES, BTC_MIN_OOS_DATES = 30, 10


HOLD_SOURCE = "results/s10_weekend_lag/mechanism/trades.csv"
HOLD_MIN_OOS_TRADES, HOLD_MIN_OOS_QUESTIONS = 30, 10
