from __future__ import annotations

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
DATE_RE = (r"(?:end of\s+)?(?:" + "|".join(m.capitalize() for m in MONTHS) + r"|" + "|".join(m.capitalize()[:3] for m in MONTHS)
           + r")\.?(?:\s+\d{1,2}(?:st|nd|rd|th)?)?(?:,?\s+20\d\d)?")
CUMULATIVE_DATE_RE = r"\b(?:by|before)\s+(?:the\s+)?@D@"
NUM_RE = r"[$€£]?\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:[kKmMbBtT]\b|%))?"
UP_WORDS = r"\(HIGH\)|↑|\babove\b|\bover\b|\bmore than\b|\bat least\b|>|\breach(?:es)?\b|\bexceeds?\b|\bhigher than\b|\+"
DOWN_WORDS = r"\(LOW\)|↓|\bbelow\b|\bunder\b|\bless than\b|<|\bdips? to\b|\bfalls? to\b|\blower than\b"
MIN_MARKET_VOLUME = 50_000.0
NEGRISK_MAX_MEMBERS = 30

WINDOW_START, WINDOW_END = "2025-10-01", "2026-10-03"
OOS_START = "2026-07-22"
MAX_NEW_PULLS = 1400
PULL_RATE = 2.5
PRICE_MAX_AGE_S = 1800

HALF_SPREAD_FLOOR = 0.005
HALF_SPREAD_CALIBRATION_BAND = (0.10, 0.90)
PRICE_CLIP = (0.001, 0.999)

EPISODE_GAP_S = 3600
MIN_VIOLATION = 0.0
CONTRACTS = 100
MAX_NEW_TRADES_PER_DAY = 10
PRINT_WINDOW_S = 600
PRINT_PAGES = 2

JUMP_POINTS = 3.0
JUMP_WINDOW_S = 300
JUMP_COOLDOWN_S = 3600
HORIZONS_S = (300, 900, 1800, 3600)
TRADE_ENTRY_DELAY_S = 60
TRADE_HOLD_S = 3600
ENTRY_BAND = (0.03, 0.97)

COST_MULTIPLIERS = (1.0, 2.0)
N_BOOT, BOOT_SEED = 2000, 11

LIVE_INTERVAL_S = 180
LIVE_UNTIL_ET = "2026-10-04 07:00"
BOOKS_PER_CALL = 100
LIVE_SEARCH_PAGES = 4
LIVE_MIN_EVENT_VOLUME = 100_000.0

MIN_OOS_TRADES, MIN_OOS_DATES = 30, 5
