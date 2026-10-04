"""touch_fresh: every fixed parameter of METHOD.md. Committed with it, before any new price or result is pulled."""
from __future__ import annotations

TODAY = "2026-10-04"

# ---- the fresh universe (catalogue metadata only)
GAMMA = "https://gamma-api.polymarket.com"
TAG = "hit-price"                                   # every closed event under Polymarket's "hit-price" tag, paged to the end
FROZEN_UNIVERSES = ("s9_weekend_price_markets/universe.json", "s15_weekend_scare/universe.json", "s19_crypto_price_markets/universe.json")
FROZEN_CSVS = ("results/s18_price_market_calibration/prints_markets.csv", "results/s18_price_market_calibration/entries.csv",
               "results/s21_options_anchor/anchors.csv")
EXCLUDE_TITLE_RE = r"bitcoin|ethereum|solana|xrp|dogecoin|crude|oil|gold|silver|natural gas|dollar index|nasdaq|dow jones|russell|nyse|nikkei|hang seng|ftse|dax"
NOT_STOCK = ("XAUUSD", "XAGUSD", "WTI", "CL", "GC", "SI", "NG", "DXY", "QQQ", "NDX", "DJIA", "RUT", "NYA", "NIK", "HSI", "UKX", "DAX")
MIN_EVENT_VOLUME = 100_000.0                        # S15's floors, inherited by S18 and S21 (the primary sample)
MIN_MARKET_VOLUME = 10_000.0                       # applied to both samples
RELAXED_MIN_EVENT_VOLUME = 0.0                      # secondary sample: S21's rules without the event floor (section 2)
FIRST_ENTRY_DAY = "2025-10-01"
MIN_MARKETS, MIN_EVENTS = 30, 15                    # fewer eligible fresh markets than this (metadata count): INSUFFICIENT
MIN_BOOK_MARKETS, MIN_BOOK_EVENTS = 10, 5           # fewer markets in the primary book than this: INSUFFICIENT (no interval read)
HOLIDAYS = ("2025-11-27", "2025-12-25", "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
            "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25")
HALF_DAYS = ("2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24")

# ---- prints (S18's rule)
PRINT_WINDOW_S = 48 * 3600                          # Friday 20:00 to Sunday 20:00 New York
PRINT_PAGES = 2
PRICE_BAND = (0.02, 0.98)                           # S18's entry band, applied to the size-weighted first-weekend print price
PM_RPS = 3.0

# ---- the anchor (S21's, with the horizon matched)
ANCHOR_BEFORE_CLOSE_S = 300                         # 15:55 New York; 12:55 on a half session
STALE_OPTION_S = 600
MAX_STEP_OUT = 2
RATE = 0.04
MAX_EXPIRY_GAP_DAYS = 45                            # the expiry is within this many calendar days of the window's last session, either side
MAX_EXPIRY_TRIES = 3
MIN_DAYS_TO_EXPIRY = 1                              # the expiry is after the anchor day
INDEX_ROOT = {"SPX": "O:SPXW"}

# ---- tests
THRESHOLD = 5.0                                     # B0: sell YES at the traded bid when it is 5+ points above the central anchor
N_BOOT, BOOT_SEED = 2000, 0
FEE_MULTIPLES = (1.0, 2.0)

# ---- Massive pull
MAX_RPS = 2.0
PULL_STOP_ET = "2026-10-04 05:00"
