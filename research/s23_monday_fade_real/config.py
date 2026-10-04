"""S23, the Monday fade at prices that traded: every fixed parameter of METHOD.md.
Committed with METHOD.md before any P&L of this study is computed. Change only through a dated Amendment."""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
REPO = RESEARCH.parent
RESULTS = RESEARCH / "results" / "s23_monday_fade_real"

TZ = "America/New_York"
SNAPSHOT_HM = "09:45"                       # the options snapshot both studies measured against

# ---- inputs (all on disk or in git; no network)
S6_TRADES = RESEARCH / "results" / "s6_monday_fade" / "trades.csv"
S6_PRINTS = RESEARCH / "s6_monday_fade" / ".cache"            # prints_<market_id>.json, read only
S6_PRIMARY, S6_COST_MULT = "V0", 1.0
EVENTS = RESEARCH / "results" / "open_options" / "events.csv"  # read for the closure calendar only (open_day)
PARTNER_COMMIT = "fb66dc7a07ff32e47293bc1d4f9c265ed9080d4c"    # origin/r/thesis-pass-2 when this file was written
PARTNER_TRADES = "research/results/reopen_taker/trades.csv"    # read with `git show`, never checked out
PARTNER_TRADES_BLOB = "78a25dad9eed6d67dbc28f5edbfab2f6d0c22159"
PRINT_PAGE_CAP = 10_000                     # S6 pulled one page of 10,000: a file at the cap would be incomplete

# ---- shared
OOS_FROM = "2026-08-03"                     # S6's split: the most recent 20% of the 45 reopening days (9 of them)
CLOSURES_PER_YEAR = 52.0
N_BOOT, BOOT_SEED = 10_000, 20261004
MIN_CLUSTERS_FOR_INTERVAL = 5
SHARPE_BUG_HUNT = 3.0

# ---- T1: the decay curve at real prices
T1_TAU = 0.05
T1_PNL = "pnl_t1"                           # the partner's primary: one tick of slippage, net of the market's fee
T1_TICK = 0.01
T1_WINDOWS = (("0-15", 0.0, 15.0), ("15-60", 15.0, 60.0), ("60-180", 60.0, 180.0), ("180+", 180.0, float("inf")))
T1_EARLY = "0-15"                           # minutes since 09:45:00, exact seconds, lower bound in, upper bound out
T1_VARIANT_TAUS = (0.03, 0.10)
T1_VARIANT_FIRST_MIN = 30.0
T1_VARIANT_KIND = "daily"
T1_MIN_RECENT_TRADES = 30

# ---- T2: S6 replayed at prices that printed
T2_WINDOW_S = 1800                          # prints with 09:45:00 <= time <= 10:15:00 on the reopening day
T2_SLIP = 0.01                              # one cent worse than the print
T2_THETA = 0.02                             # S6's own threshold beyond the options band, after the fee
T2_FEE_RATE = 0.04                          # S6's fee, charged on every trade (some markets had fees off: conservative)
T2_MAX_CONTRACTS = 100
PRICE_CLIP = (0.001, 0.999)
COST_MULTIPLIERS = (1.0, 2.0)
