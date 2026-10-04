"""Frozen reward accounting choices; no historical reward is assumed."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    cost_multipliers: tuple[float, ...] = (1.0, 2.0)
    minimum_sharpe: float = 1.5
    minimum_independent_oos_entry_dates: int = 30
    minimum_oos_daily_observations: int = 60
    per_market_capital_fraction: float = 0.01
    chronological_holdout_fraction: float = 0.20
    unknown_reward_policy: str = "not_testable"
    network_requests: int = 0


CONFIG = Config()
