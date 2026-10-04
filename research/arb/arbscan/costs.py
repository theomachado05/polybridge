from __future__ import annotations

import math
from dataclasses import dataclass

OPTION_COMMISSION_PER_CONTRACT = 0.65
SHARES_PER_CONTRACT = 100


def commission_per_share(width: float, per_contract: float = OPTION_COMMISSION_PER_CONTRACT) -> float:
    return per_contract * 2.0 / (SHARES_PER_CONTRACT * width)


@dataclass(frozen=True)
class PolyFee:
    rate: float = 0.04
    exponent: float = 1.0
    enabled: bool = True

    def per_share(self, price: float, qty: float | None = None) -> float:
        if not self.enabled or not (0.0 < price < 1.0):
            return 0.0
        return self.rate * (price * (1.0 - price)) ** self.exponent


@dataclass(frozen=True)
class KalshiFee:
    multiplier: float = 1.0
    coeff: float = 0.07

    def total(self, price: float, qty: float) -> float:
        if not (0.0 < price < 1.0) or qty <= 0:
            return 0.0
        return math.ceil(self.coeff * self.multiplier * qty * price * (1.0 - price) * 100.0 - 1e-9) / 100.0

    def per_share(self, price: float, qty: float | None = None) -> float:
        c = qty if qty and qty > 0 else 100.0
        return self.total(price, c) / c


def fee_from_gamma(market: dict) -> PolyFee:
    sched = market.get("feeSchedule") or {}
    if market.get("feesEnabled") and sched:
        return PolyFee(rate=float(sched.get("rate", 0.04)), exponent=float(sched.get("exponent", 1.0)), enabled=True)
    return PolyFee(enabled=bool(market.get("feesEnabled", False)))
