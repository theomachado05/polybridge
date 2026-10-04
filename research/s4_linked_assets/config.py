from __future__ import annotations

from dataclasses import dataclass

WINDOW_START, WINDOW_END = "2026-01-02", "2026-10-02"
PM_MAX_AGE_S = 1800
BETA_LOOKBACK, BETA_MIN = 60, 20

GATE_BIN_MIN = 30
GATE_MIN_BINS = 60
GATE_MIN_SESSIONS = 5
GATE_MIN_T = 2.0

X_MIN_PP = 2.0
NOTIONAL = 10_000.0
MAX_POSITIONS = 10
CAPITAL = 100_000.0
EXIT_VARIANT_TIME = "10:00"
CAPACITY_SHARE = 0.05

COST_SPY = 1.0
COST_LIQUID = 2.0
COST_OTHER = 5.0
LIQUID = frozenset("""
AAPL AMZN GOOGL META MSFT NVDA TSLA ORCL LLY TSM XOM RTX LMT ETN CEG AEP
SPY TLT IWM GLD XLE XOP SMH KRE XHB ITA EWZ FXI VGK KWEB USO IBIT ETHA ICLN JETS
""".split())

MOTIVATING = ("polymarket:4037600", "polymarket:4037599", "polymarket:1365861", "polymarket:1365854",
              "polymarket:601922", "polymarket:601920")
MOTIVATING_WORDS = ("brazil", "bolsonaro", "lula")

OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252
N_BOOT = 2000
BOOT_SEED = 0


@dataclass(frozen=True)
class Variant:
    id: str
    links: str
    spot_proxy: bool
    exit: str


VARIANTS = (
    Variant("V0", "trusted", False, "close"),
    Variant("V1", "trusted", False, "10:00"),
    Variant("V2", "agreed", False, "close"),
    Variant("V3", "trusted", True, "close"),
    Variant("V4", "proposed", True, "close"),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)

MIN_OOS_TRADES, MIN_OOS_DATES, MIN_OOS_TICKERS = 30, 10, 5
