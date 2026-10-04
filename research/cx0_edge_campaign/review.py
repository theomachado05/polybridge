"""Screen observed evidence without selecting a winning backtest variant."""
from dataclasses import dataclass
import math

import numpy as np


def nav_metrics(nav, initial_nav: float, periods_per_year: int = 252) -> dict:
    """Whole funded account metrics, including first-day costs and initial peak."""
    values = np.asarray(nav, dtype=float)
    if values.ndim != 1 or not len(values):
        raise ValueError("Need an ordered, nonempty one-dimensional daily NAV series")
    if not math.isfinite(initial_nav) or initial_nav <= 0:
        raise ValueError("Initial NAV must be positive and finite")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Missing, nonfinite or bankrupt NAV is not a valid Sharpe series")
    full = np.r_[initial_nav, values]
    returns = full[1:] / full[:-1] - 1.0
    sd = float(np.std(returns, ddof=1)) if len(returns) >= 2 else math.nan
    sharpe = float(np.mean(returns) / sd * math.sqrt(periods_per_year)) if sd > 0 else math.nan
    peaks = np.maximum.accumulate(full)
    return {"observations": len(values), "total_return": float(values[-1] / initial_nav - 1),
            "sharpe": sharpe, "max_drawdown": float(np.max(1 - full / peaks))}


@dataclass(frozen=True)
class Evidence:
    oos_sharpe: float | None
    oos_return_1x: float | None
    oos_return_2x: float | None
    oos_mean_ci_low: float | None
    independent_oos_entry_dates: int
    oos_daily_observations: int
    execution_inputs_supported: bool
    accounting_supported: bool
    independent_confirmation: bool


def screen(e: Evidence) -> tuple[str, list[str]]:
    missing = []
    if not e.execution_inputs_supported:
        missing.append("execution data do not support the tested fills")
    if not e.accounting_supported:
        missing.append("funded daily marking, costs or income are unidentified")
    if missing:
        return "NOT_TESTABLE", missing
    metrics = (e.oos_sharpe, e.oos_return_1x, e.oos_return_2x, e.oos_mean_ci_low)
    if any(x is None or not math.isfinite(x) for x in metrics):
        return "INSUFFICIENT", ["required holdout metrics cannot be estimated"]
    reasons = []
    if e.independent_oos_entry_dates < 30:
        reasons.append("fewer than 30 independent holdout entry dates")
    if e.oos_daily_observations < 60:
        reasons.append("fewer than 60 holdout daily return observations")
    if reasons:
        return "INSUFFICIENT", reasons
    if e.oos_sharpe < 1.5:
        reasons.append("net holdout Sharpe below 1.5")
    if e.oos_return_1x <= 0 or e.oos_return_2x <= 0:
        reasons.append("holdout return is nonpositive at 1x or 2x costs")
    if e.oos_mean_ci_low <= 0:
        reasons.append("net return confidence interval includes zero")
    if reasons:
        return "FAIL", reasons
    if not e.independent_confirmation:
        return "EXPLORATORY_PASS", ["reused history still needs independent confirmation"]
    return "CONFIRMED", []
