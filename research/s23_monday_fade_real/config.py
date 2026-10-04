from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
REPO = RESEARCH.parent
RESULTS = RESEARCH / "results" / "s23_monday_fade_real"

TZ = "America/New_York"
SNAPSHOT_HM = "09:45"

S6_TRADES = RESEARCH / "results" / "s6_monday_fade" / "trades.csv"
S6_PRINTS = RESEARCH / "s6_monday_fade" / ".cache"
S6_PRIMARY, S6_COST_MULT = "V0", 1.0
EVENTS = RESEARCH / "results" / "open_options" / "events.csv"
PARTNER_COMMIT = "fb66dc7a07ff32e47293bc1d4f9c265ed9080d4c"
PARTNER_TRADES = "research/results/reopen_taker/trades.csv"
PARTNER_TRADES_BLOB = "78a25dad9eed6d67dbc28f5edbfab2f6d0c22159"
PRINT_PAGE_CAP = 10_000

OOS_FROM = "2026-08-03"
CLOSURES_PER_YEAR = 52.0
N_BOOT, BOOT_SEED = 10_000, 20261004
MIN_CLUSTERS_FOR_INTERVAL = 5
SHARPE_BUG_HUNT = 3.0

T1_TAU = 0.05
T1_PNL = "pnl_t1"
T1_TICK = 0.01
T1_WINDOWS = (("0-15", 0.0, 15.0), ("15-60", 15.0, 60.0), ("60-180", 60.0, 180.0), ("180+", 180.0, float("inf")))
T1_EARLY = "0-15"
T1_VARIANT_TAUS = (0.03, 0.10)
T1_VARIANT_FIRST_MIN = 30.0
T1_VARIANT_KIND = "daily"
T1_MIN_RECENT_TRADES = 30

T2_WINDOW_S = 1800
T2_SLIP = 0.01
T2_THETA = 0.02
T2_FEE_RATE = 0.04
T2_MAX_CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)
COST_MULTIPLIERS = (1.0, 2.0)
