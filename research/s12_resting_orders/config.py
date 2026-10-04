"""S12 resting orders: every fixed parameter of METHOD.md. Committed with it, before any trade print is pulled."""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- the two samples (inputs already on disk)
# S9: every primary (V0, 1x) trade of S9: weekend move of 5+ points, entry Sunday 17:55 New York, exit next session 09:40.
# S8: every market-morning of S8 with an overnight move of 10+ points and a 09:40 price inside ENTRY_BAND (the 2.63-point
#     give-back), whatever the asset's vote; entry 09:40, exit at the session close.
S9_VARIANT = "V0"
S8_MIN_MOVE_PP = 10.0
S8_ENTRY_BAND = (0.05, 0.95)
SAMPLES = ("S9", "S8")
PRIMARY_SAMPLE = "S9"

# ---------------------------------------------------------------- the fill rule
TICK = 0.01                  # price grid; the mid is rounded to it on the passive side (sell up, buy down)
CONTRACTS = 100              # order size, contracts (S8 and S9 use 100)
QUEUE_ALLOWANCE = 500.0      # contracts that trade AT our price before any of it counts toward our fill
TAKER_ONLY = True            # data API prints are the taker's side (takerOnly=true, passed explicitly)
PRINT_PAGES = 2              # the data API serves at most the latest 20,000 prints of a market
PRINT_RATE = 3.0             # requests per second, shared limit (brief section 5)
MAX_WINDOW_S = 120 * 60      # longest window of any variant: only prints inside [t, t + this] of an entry or exit are kept
PM_MAX_AGE_S = 1800          # a one-minute mid older than this at a deadline is missing

# ---------------------------------------------------------------- costs
S8_HALF_SPREAD = 0.005                    # S8 config: half of the 1.0-point median spread
S9_HALF_SPREAD = {"crude": 0.005, "gold": 0.0125, "silver": 0.02, "sp500": 0.01, "stock": 0.025}   # S9 config
S8_FEE_RATE, S8_FEE_EXPONENT = 0.04, 1.0  # S8/S6: 0.04 x P x (1 - P), takers only
# S9: each market's own fee_rate / fee_exponent from weekends.csv, takers only.
COST_MULTIPLIERS = (1.0, 2.0)
# 1x: no fee and no spread on a resting fill; an exit that is not filled by its deadline crosses: mid at the deadline
#     -/+ half-spread and the taker fee.
# 2x: fills are judged one tick further (prints must reach our price + 1 tick: through it, or at it beyond the queue
#     allowance); there is no resting exit: every exit crosses at the exit instant with 2x half-spread and 2x fee.


@dataclass(frozen=True)
class Variant:
    id: str
    window_min: int          # how long the entry order rests; the exit order rests the same time
    offset_ticks: int        # 0 = post at the mid (rounded to the passive tick); 1 = one tick better for the taker


VARIANTS = (
    Variant("R0", 30, 0),    # primary
    Variant("R1", 120, 0),
    Variant("R2", 30, 1),
    Variant("R3", 120, 1),
)
PRIMARY = "R0"

# ---------------------------------------------------------------- statistics
N_BOOT, BOOT_SEED = 10000, 12
S9_WEEKENDS_PER_YEAR, S8_DAYS_PER_YEAR = 52, 252
CAPACITY_SIZES = (100, 500, 2000, 10000)   # contracts: share of reachable orders that would fill fully at this size

# ---------------------------------------------------------------- success criterion (primary sample, primary variant)
MIN_OOS_FILLED, MIN_OOS_GROUPS = 15, 5
# pass needs ALL of:
#   1. at least MIN_OOS_FILLED filled orders out-of-sample on at least MIN_OOS_GROUPS weekends;
#   2. in-sample net P&L per filled order above zero at 1x, weekend-bootstrap 95% interval excluding zero;
#   3. out-of-sample net P&L per filled order above zero at 1x;
#   4. whole-sample net P&L per filled order above zero at 2x.
