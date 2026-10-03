"""Cost model (METHOD.md section 5). All functions are pure."""
from __future__ import annotations

import math
from dataclasses import dataclass

OPTION_COMMISSION_PER_CONTRACT = 0.65   # assumption: flat retail figure, per contract per leg
SHARES_PER_CONTRACT = 100


def commission_per_share(width: float, per_contract: float = OPTION_COMMISSION_PER_CONTRACT) -> float:
    """Two legs; one spread contract hedges 100 * width PM shares."""
    return per_contract * 2.0 / (SHARES_PER_CONTRACT * width)


@dataclass(frozen=True)
class PolyFee:
    """Polymarket taker fee: shares * rate * (p * (1 - p)) ** exponent (the market's own feeSchedule)."""
    rate: float = 0.04
    exponent: float = 1.0
    enabled: bool = True

    def per_share(self, price: float, qty: float | None = None) -> float:
        if not self.enabled or not (0.0 < price < 1.0):
            return 0.0
        return self.rate * (price * (1.0 - price)) ** self.exponent


@dataclass(frozen=True)
class KalshiFee:
    """Kalshi taker fee: ceil_to_cent(0.07 * mult * C * p * (1 - p)). Per share = total / C (C = 100 if unknown)."""
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
