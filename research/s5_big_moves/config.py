"""S5 big moves: every fixed parameter of METHOD.md. Committed with it, before any S5 price is pulled."""
from __future__ import annotations

from dataclasses import dataclass

WINDOW_START, WINDOW_END = "2025-10-01", "2026-10-02"
EVENT_END_MIN, EVENT_END_MAX = "2025-11-01T00:00:00Z", "2027-12-31T23:59:59Z"
N_MARKETS = 240
MAX_PER_EVENT = 6
MIN_VOLUME = 1_000_000.0
MIN_SESSIONS = 20
# An event carrying any of these tags is dropped (lower case, substring match on the tag label)
DROP_TAGS = ("sports", "esports", "e-sports", "soccer", "nfl", "nba", "mlb", "nhl", "tennis", "golf", "ufc", "boxing",
             "cricket", "formula 1", "f1", "crypto prices", "up or down", "hit price", "recurring", "mentions",
             "tweet markets", "weather", "pop culture", "movies", "music", "awards", "games", "chess")
DROP_WORDS = ("up or down", "brazil", "bolsonaro", "lula")       # in the question text

# The ticker menu shown to both labellers
MENU = """
SPY QQQ IWM DIA
TLT IEF SHY HYG LQD UUP FXE FXY
USO UNG GLD SLV CPER URA DBA CORN WEAT
XLE XOP XLF KRE XLK SMH XLV XBI XLI ITA XLU XLY XLP XHB XRT JETS ICLN TAN
EWZ EWW EWC EWJ FXI KWEB MCHI EWT EWY INDA EWG EWU EWQ VGK EIS TUR ARGT EWA EPOL GREK EZA
AAPL MSFT GOOGL AMZN META NVDA TSLA AMD INTC TSM ORCL NFLX DIS BA LMT RTX NOC GD
XOM CVX OXY JPM GS BAC WFC UNH PFE MRNA LLY NVO WMT COST TGT NKE F GM UBER DAL UAL CCL
COIN MSTR MARA IBIT ETHA HOOD
DJT PLTR GEO CXW SMR OKLO CEG VST CCJ FSLR ENPH MSOS NUE CLF DE CAT ZIM FRO STNG BABA PDD VRT DLR EQIX CRWV RKLB
""".split()

# Costs per side, bp (S4 section 3). Liquid = ETFs with deep books and stocks above $50 billion market value.
COST_SPY, COST_LIQUID, COST_OTHER = 1.0, 2.0, 5.0
LIQUID = frozenset("""
SPY QQQ IWM DIA TLT IEF SHY HYG LQD GLD SLV USO XLE XOP XLF KRE XLK SMH XLV XBI XLI ITA XLU XLY XLP XHB XRT
EWZ EWW EWC EWJ FXI KWEB MCHI EWT EWY INDA EWG EWU VGK IBIT ETHA
AAPL MSFT GOOGL AMZN META NVDA TSLA AMD INTC TSM ORCL NFLX DIS BA LMT RTX NOC GD XOM CVX JPM GS BAC WFC UNH PFE LLY NVO
WMT COST TGT NKE GM UBER COIN MSTR PLTR CEG CAT DE BABA PDD
""".split())
CRYPTO_EQUITIES = frozenset("COIN MSTR MARA IBIT ETHA HOOD".split())

NOTIONAL, MAX_POSITIONS, CAPITAL = 10_000.0, 10, 100_000.0
CAPACITY_SHARE = 0.05
OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252
N_BOOT, BOOT_SEED = 2000, 0
P1_MIN_T = 2.0


@dataclass(frozen=True)
class Variant:
    id: str
    threshold: float
    exit: str            # "close" or "10:00"
    weekends_only: bool


VARIANTS = (
    Variant("V0", 10.0, "close", False),     # primary
    Variant("V1", 10.0, "10:00", False),
    Variant("V2", 5.0, "close", False),
    Variant("V3", 10.0, "close", True),
)
PRIMARY = "V0"
COST_MULTIPLIERS = (1.0, 2.0)
MIN_TRADES, MIN_DATES, MIN_TICKERS = 30, 15, 8
