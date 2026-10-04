"""Pre-registered parameters of Study A, the options-anchored Polymarket taker on reopening days (METHOD.md). Change only through an Amendment."""
from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "reopen_taker"
CACHE_DIR = PKG_DIR / ".cache"
EVENTS_CSV = RESEARCH_DIR / "results" / "open_options" / "events.csv"
EVENT_STATUS = "event"
TZ = "America/New_York"

WINDOW_START_HMS = (9, 45, 0)
WINDOW_END_HMS = (15, 55, 0)

TAU = 0.05
TAUS_SECONDARY = (0.03, 0.10)
TICK = 0.01
TICK_SECONDARY = (0.02,)
X_RANGE = (0.02, 0.98)
BUY_EVAL_MAX = 0.94
SELL_EVAL_MIN = 0.06
BAND_MAX = 0.20
P_RANGE = (0.03, 0.97)

FEE_RATE_DEFAULT = 0.04
FEE_EXP_DEFAULT = 1.0

TRADES_PAGE = 500
TRADES_MAX_OFFSET = 10_000

BOOT_DRAWS = 10_000
SEED = 20261003
MIN_TRADES = 30
MIN_CLUSTERS = 8
CAPACITY_SHARE = 0.5
