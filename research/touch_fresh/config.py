from __future__ import annotations

TODAY = "2026-10-04"

GAMMA = "https://gamma-api.polymarket.com"
TAG = "hit-price"
FROZEN_UNIVERSES = ("s9_weekend_price_markets/universe.json", "s15_weekend_scare/universe.json", "s19_crypto_price_markets/universe.json")
FROZEN_CSVS = ("results/s18_price_market_calibration/prints_markets.csv", "results/s18_price_market_calibration/entries.csv",
               "results/s21_options_anchor/anchors.csv")
EXCLUDE_TITLE_RE = r"bitcoin|ethereum|solana|xrp|dogecoin|crude|oil|gold|silver|natural gas|dollar index|nasdaq|dow jones|russell|nyse|nikkei|hang seng|ftse|dax"
NOT_STOCK = ("XAUUSD", "XAGUSD", "WTI", "CL", "GC", "SI", "NG", "DXY", "QQQ", "NDX", "DJIA", "RUT", "NYA", "NIK", "HSI", "UKX", "DAX")
MIN_EVENT_VOLUME = 100_000.0
MIN_MARKET_VOLUME = 10_000.0
RELAXED_MIN_EVENT_VOLUME = 0.0
FIRST_ENTRY_DAY = "2025-10-01"
MIN_MARKETS, MIN_EVENTS = 30, 15
MIN_BOOK_MARKETS, MIN_BOOK_EVENTS = 10, 5
HOLIDAYS = ("2025-11-27", "2025-12-25", "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
            "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25")
HALF_DAYS = ("2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24")

PRINT_WINDOW_S = 48 * 3600
PRINT_PAGES = 2
PRICE_BAND = (0.02, 0.98)
PM_RPS = 3.0

ANCHOR_BEFORE_CLOSE_S = 300
STALE_OPTION_S = 600
MAX_STEP_OUT = 2
RATE = 0.04
MAX_EXPIRY_GAP_DAYS = 45
MAX_EXPIRY_TRIES = 3
MIN_DAYS_TO_EXPIRY = 1
INDEX_ROOT = {"SPX": "O:SPXW"}

THRESHOLD = 5.0
N_BOOT, BOOT_SEED = 2000, 0
FEE_MULTIPLES = (1.0, 2.0)

MAX_RPS = 2.0
PULL_STOP_ET = "2026-10-04 05:00"
