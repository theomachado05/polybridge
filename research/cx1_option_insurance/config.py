"""CX1 fixed insurance-selling rules; freeze before reading option outcomes."""
from dataclasses import dataclass

PACKAGE = "cx1_option_insurance"
UNDERLYING = "SPY"
INSTRUMENT = "cashsecured_atm_put"
WINDOW_START, WINDOW_END = "2025-10-01", "2026-10-02"
FUTURE_RESERVE_FROM = "2026-10-05"
MIN_CLOSURE_HOURS = 40
ENTRY_BEFORE_CLOSE_MINUTES = 5
STRIKE_BEFORE_CLOSE_MINUTES = 30
SIGNAL_BEFORE_CLOSE_MINUTES = 30
EXIT_AFTER_OPEN_MINUTES = 15
EXPIRY_MIN_DAYS, EXPIRY_SEARCH_DAYS = 7, 28
ENTRY_QUOTE_MAX_AGE_SECONDS = 600
EXIT_QUOTE_MAX_AGE_SECONDS = 900
CONTRACT_MULTIPLIER = 100
COMMISSION_PER_CONTRACT_SIDE = 0.65
COST_MULTIPLIERS = (1.0, 2.0)
FULL_COLLATERAL_FRACTION = 1.0
GATED_COLLATERAL_FRACTION = 0.5
ODDS_LOW, ODDS_HIGH = 0.10, 0.90
ACTIVITY_NIGHTS, ACTIVITY_MIN_NIGHTS = 5, 3
ACTIVITY_THRESHOLD_POINTS = 4.0
PM_MAX_AGE_SECONDS = 1800
MISSING_GATE_IS_HIGH_RISK = True
OOS_FRACTION = 0.20
DAYS_PER_YEAR = 252
BOOTSTRAP_DRAWS, BOOTSTRAP_SEED = 5000, 101
BOOTSTRAP_BLOCK_CLOSURES = 4
MIN_OOS_ENTRY_DATES = 30
MIN_OOS_DAILY_OBSERVATIONS = 60
TARGET_OOS_SHARPE = 1.5
MAX_RPS = 0.5
NETWORK_REQUEST_BUDGET = 0
MAX_DOWNLOAD_BYTES = 0

@dataclass(frozen=True)
class Variant:
    id: str
    event_aware: bool
    description: str

VARIANTS = (
    Variant("V0", False, "Full-cashsecured SPY ATM put insurance over market closures"),
    Variant("V1", True, "The same put with half collateral exposure during active or unobserved event risk"),
)
PRIMARY = "V0"
STATIC_COMPARATOR = "STATIC_IS_MATCH"

PRIORS = (
    "S7 long weekend straddles lost 17.7% net and about 1% gross; negating long net returns is invalid for shorts.",
    "Broad 8-K cashsecured-put event conditioning failed in previous work.",
    "These reused historical data are exploratory; the recent 20% is chronology, not pristine confirmation.",
    "A short cashsecured put sells crash insurance and owns equity downside; a cash collateral denominator is mandatory.",
    "A one-year history cannot satisfy 30 OOS closure entries and 60 OOS sessions under the fixed split.",
)
