"""Cash accounting which refuses to turn unknown incentives into income."""
from dataclasses import dataclass
import math


class UnidentifiedIncome(ValueError):
    """Historical rewards or rebates have not been identified."""


@dataclass(frozen=True)
class Ledger:
    trading_pnl: float
    liquidity_reward: float | None
    maker_rebate: float | None
    external_hedge_cost: float
    financing_cost: float

    def net_pnl(self) -> float:
        if self.liquidity_reward is None or self.maker_rebate is None:
            raise UnidentifiedIncome("Unknown incentive allocation cannot be backtested as earned income")
        amounts = (self.trading_pnl, self.liquidity_reward, self.maker_rebate,
                   self.external_hedge_cost, self.financing_cost)
        if not all(math.isfinite(x) for x in amounts):
            raise ValueError("All cash amounts must be finite")
        if any(x < 0 for x in amounts[1:]):
            raise ValueError("Incentive income and explicit costs must be nonnegative")
        return (self.trading_pnl + self.liquidity_reward + self.maker_rebate
                - self.external_hedge_cost - self.financing_cost)


def required_incentive(trading_pnl: float, hedge_cost: float = 0.0,
                       financing_cost: float = 0.0) -> float:
    if not all(math.isfinite(x) for x in (trading_pnl, hedge_cost, financing_cost)):
        raise ValueError("Cash amounts must be finite")
    if hedge_cost < 0 or financing_cost < 0:
        raise ValueError("Costs must be nonnegative")
    return max(0.0, hedge_cost + financing_cost - trading_pnl)


def minimum_pool(required_income: float, reward_share: float) -> float:
    """Hypothetical pool required at a specified share; not an estimate of income."""
    if not math.isfinite(required_income) or required_income < 0:
        raise ValueError("Required income must be finite and nonnegative")
    if not math.isfinite(reward_share) or not 0 < reward_share <= 1:
        raise ValueError("Share must be in (0, 1]")
    return required_income / reward_share
