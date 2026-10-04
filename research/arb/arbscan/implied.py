from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .costs import commission_per_share, SHARES_PER_CONTRACT

RATE = 0.04
STALE_OPTION_SEC = 600
MIN_EDGE = 0.01
GAP_MID = 0.05
INFORMATIVE = (0.02, 0.98)
COARSE_WIDTH_SENS = 0.05
MAX_STEP_OUT = 2


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_size: float = float("nan")
    ask_size: float = float("nan")
    ts: float = float("nan")

    def valid(self, snapshot_ts: float | None = None, max_age: float | None = STALE_OPTION_SEC) -> bool:
        if not (self.bid > 0 and self.ask >= self.bid):
            return False
        if snapshot_ts is not None and max_age is not None and not math.isnan(self.ts):
            return snapshot_ts - self.ts <= max_age
        return True


@dataclass
class Spread:
    k1: float
    k2: float
    q1: Quote
    q2: Quote
    t_years: float
    rate: float = RATE
    stepped: int = 0
    p_mid: float = field(init=False)
    p_lo: float = field(init=False)
    p_hi: float = field(init=False)
    raw_mid: float = field(init=False)

    def __post_init__(self):
        disc = math.exp(self.rate * max(self.t_years, 0.0)) / self.width
        self.raw_mid = ((self.q1.bid + self.q1.ask) / 2 - (self.q2.bid + self.q2.ask) / 2) * disc
        self.p_mid = _clamp(self.raw_mid)
        self.p_lo = _clamp((self.q1.bid - self.q2.ask) * disc)
        self.p_hi = _clamp((self.q1.ask - self.q2.bid) * disc)

    @property
    def width(self) -> float:
        return self.k2 - self.k1

    @property
    def noarb_violation(self) -> bool:
        return not (-1e-9 <= self.raw_mid <= 1 + 1e-9)

    @property
    def min_leg_size(self) -> float:
        s = [x for x in (self.q1.bid_size, self.q1.ask_size, self.q2.bid_size, self.q2.ask_size) if not math.isnan(x)]
        return min(s) if len(s) == 4 else float("nan")

    def strip_loss(self, k: float) -> tuple[float, float]:
        return (max(self.k2 - k, 0.0) / self.width, max(k - self.k1, 0.0) / self.width)


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def bracket_indices(strikes: Sequence[float], k: float, extra: int = 0) -> tuple[int, int] | None:
    s = list(strikes)
    j = bisect.bisect_left(s, k - 1e-9)
    if j < len(s) and abs(s[j] - k) < 1e-6:
        lo, hi = j - 1, j + 1
    else:
        lo, hi = j - 1, j
    lo, hi = lo - extra, hi + extra
    if lo < 0 or hi >= len(s):
        return None
    return lo, hi


def pick_spread(strikes: Sequence[float], k: float, get_quote: Callable[[float], Quote | None], t_years: float,
                extra: int = 0, snapshot_ts: float | None = None, max_age: float | None = STALE_OPTION_SEC,
                rate: float = RATE) -> Spread | None:
    s = list(strikes)
    ij = bracket_indices(s, k, extra)
    if ij is None:
        return None
    lo, hi = ij
    stepped = 0
    q1 = q2 = None
    for n in range(MAX_STEP_OUT + 1):
        if q1 is None and lo - n >= 0:
            q = get_quote(s[lo - n])
            if q is not None and q.valid(snapshot_ts, max_age):
                q1, lo, stepped = q, lo - n, stepped + n
        if q2 is None and hi + n < len(s):
            q = get_quote(s[hi + n])
            if q is not None and q.valid(snapshot_ts, max_age):
                q2, hi, stepped = q, hi + n, stepped + n
        if q1 is not None and q2 is not None:
            break
    if q1 is None or q2 is None:
        return None
    return Spread(s[lo], s[hi], q1, q2, t_years, rate=rate, stepped=stepped)


def edges(sp: Spread, k: float, pm_bid: float, pm_ask: float, fee, size: float | None = None) -> dict:
    comm = commission_per_share(sp.width)
    edge_a = pm_bid - fee.per_share(pm_bid, size) - sp.p_hi - comm
    edge_b = sp.p_lo - pm_ask - fee.per_share(pm_ask, size) - comm
    loss_a, loss_b = sp.strip_loss(k)
    if edge_a >= edge_b:
        return {"trade": "A_sell_yes_buy_spread", "edge": edge_a, "strip_loss": loss_a, "edge_A": edge_a, "edge_B": edge_b}
    return {"trade": "B_buy_yes_sell_spread", "edge": edge_b, "strip_loss": loss_b, "edge_A": edge_a, "edge_B": edge_b}


def edge_for_trade(sp: Spread, trade: str, pm_bid: float, pm_ask: float, fee, size: float | None = None) -> float:
    comm = commission_per_share(sp.width)
    if trade.startswith("A"):
        return pm_bid - fee.per_share(pm_bid, size) - sp.p_hi - comm
    return sp.p_lo - pm_ask - fee.per_share(pm_ask, size) - comm


def classify(*, clean: bool, informative: bool, fresh: bool, p_mid_narrow: float | None, p_lo: float | None,
             p_hi: float | None, pm_mid: float | None, edge: float | None, edge_wide_same_trade: float | None,
             live: bool = False, options_open: bool = False, pm_size_at_touch: float | None = None,
             width: float | None = None, legs_have_size: bool = False) -> str:
    if not (clean and informative and fresh) or p_mid_narrow is None or pm_mid is None:
        return "not_scored"
    label = "none"
    if abs(pm_mid - p_mid_narrow) >= GAP_MID:
        label = "gap_mid"
    if p_lo is not None and p_hi is not None and (pm_mid < p_lo - 1e-12 or pm_mid > p_hi + 1e-12):
        label = "gap_beyond_bounds"
    if edge is not None and edge >= MIN_EDGE:
        label = "gap_net"
        if edge_wide_same_trade is not None and edge_wide_same_trade > 0:
            label = "gap_robust"
            if (live and options_open and legs_have_size and pm_size_at_touch is not None and width
                    and pm_size_at_touch >= SHARES_PER_CONTRACT * width):
                label = "gap_executable"
    return label
