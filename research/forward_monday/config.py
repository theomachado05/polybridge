from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "forward_monday"
CACHE_DIR = Path(os.environ.get("FORWARD_MONDAY_CACHE", str(RESULTS_DIR / ".cache")))
SNAPSHOT_DATE = "2026-10-03"
TZ = "America/New_York"

GAMMA = "https://gamma-api.polymarket.com"
GAMMA_TAG = 102676
KINDS = ("daily", "weekly")
META_FIELDS = ("id", "conditionId", "clobTokenIds", "outcomes", "question", "startDate", "endDate", "feesEnabled")

REOPEN_MIN, REOPEN_MAX = "2026-10-05", "2026-10-30"
WINDOW_START_HM = (9, 45)
WINDOW_END_HM = (15, 55)
LISTING_LAG_SEC = 300
EXPIRY_CLOSE_HM = (16, 0)
UNRESOLVED_DROP_DAYS = 7

TAU = 0.05
TAUS = (0.03, 0.05, 0.10)
TAU_STOP = 0.10
TICK = 0.01
TICK_SECONDARY = (0.0, 0.02)

BOOT_DRAWS = 10_000
SEED = 20261003
MIN_TRADES = 30
MIN_REOPENINGS = 4
CAPACITY_SHARE = 0.5
