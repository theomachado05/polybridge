"""Pre-registered parameters (METHOD.md). Change only through an Amendment in METHOD.md."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = PKG_DIR.parent
REPO_DIR = RESEARCH_DIR.parent
RESULTS_DIR = RESEARCH_DIR / "results" / "fresh_accuracy"
R3_EVENTS = RESEARCH_DIR / "results" / "open_options" / "events.csv"
ARB_GAPS = RESEARCH_DIR / "results" / "arb" / "arb_gaps.csv"
FROZEN_IDS = PKG_DIR / "frozen_ids.csv"
FROZEN_SHA = PKG_DIR / "frozen_ids.sha256"
CACHE_DIR = Path(os.environ.get("FRESH_ACC_CACHE", PKG_DIR / ".cache"))
MASSIVE_CACHE = Path(os.environ.get("SHARED_MASSIVE_CACHE", CACHE_DIR / "massive"))

GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class Params:
    tag_id: int = 102676
    end_min: str = "2025-10-14"
    end_max: str = "2026-08-14"
    kinds: tuple = ("daily", "weekly", "monthly")
    s1_hhmm: tuple = (15, 45)
    s2_hhmm: tuple = (12, 0)
    hist_pad_before: int = 3600
    hist_pad_after: int = 600
    pm_max_age: int = 900
    opt_max_age: int = 600
    placeholder: float = 0.5
    log_clip: tuple = (0.01, 0.99)
    seed: int = 20261004
    draws: int = 10_000
    min_rows: int = 2000
    min_dates: int = 40
    slice_n: int = 50
    slice_min_valid: float = 0.30
    trade_window: int = 600
    kalshi_series: tuple = (("KXINXU", "SPX"), ("KXNASDAQ100U", "NDX"))
    kalshi_start: str = "2025-10-01"
    kalshi_end: str = "2026-08-14"
    kalshi_top: int = 8
    kalshi_candle_pad: int = 1800
    tost_margin: float = 0.003
    h3_deadline_et: str = "2026-10-04T01:30:00"


PARAMS = Params()
