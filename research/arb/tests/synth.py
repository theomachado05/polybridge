from __future__ import annotations

import math

from arbscan.implied import Quote


def _N(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(s: float, k: float, sigma: float, t: float, r: float = 0.0) -> float:
    if t <= 0:
        return max(s - k, 0.0)
    d1 = (math.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return s * _N(d1) - k * math.exp(-r * t) * _N(d2)


def true_prob(s: float, k: float, sigma: float, t: float, r: float = 0.0) -> float:
    d2 = (math.log(s / k) + (r - 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    return _N(d2)


def make_chain(s=100.0, sigma=0.30, t=1 / 252, strikes=None, half=0.01, size=50, ts=1_000.0, r=0.04):
    strikes = strikes or [float(k) for k in range(80, 121)]
    chain = {k: f"O:TEST{int(k * 1000):08d}" for k in strikes}
    quotes = {}
    for k, tk in chain.items():
        mid = bs_call(s, k, sigma, t, r)
        h = max(half, 0.0)
        quotes[tk] = Quote(bid=max(mid - h, 0.01), ask=max(mid + h, 0.02), bid_size=size, ask_size=size, ts=ts)
    return chain, quotes
