from __future__ import annotations

import math

IV_LO, IV_HI = 0.001, 5.0
IV_ITERS = 80
NAN = math.nan


def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _ok(*xs: float) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


def _d1d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    v = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / v
    return d1, d1 - v


def intrinsic(S: float, K: float, call: bool) -> float:
    return max(S - K, 0.0) if call else max(K - S, 0.0)


def price(S: float, K: float, T: float, r: float, sigma: float, call: bool, q: float = 0.0) -> float:
    if not _ok(S, K, T, r, sigma, q) or S <= 0 or K <= 0:
        return NAN
    if T <= 0:
        return intrinsic(S, K, call)
    if sigma <= 0:
        fwd_intr = S * math.exp(-q * T) - K * math.exp(-r * T)
        return max(fwd_intr, 0.0) if call else max(-fwd_intr, 0.0)
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    dq, dr = math.exp(-q * T), math.exp(-r * T)
    if call:
        return S * dq * ncdf(d1) - K * dr * ncdf(d2)
    return K * dr * ncdf(-d2) - S * dq * ncdf(-d1)


def greeks(S: float, K: float, T: float, r: float, sigma: float, call: bool, q: float = 0.0) -> dict:
    out = {"delta": NAN, "gamma": NAN, "theta": NAN, "vega": NAN}
    if not _ok(S, K, T, r, sigma, q) or S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return out
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    dq, dr, sq = math.exp(-q * T), math.exp(-r * T), math.sqrt(T)
    pdf = npdf(d1)
    gamma = dq * pdf / (S * sigma * sq)
    vega = S * dq * pdf * sq
    common = -S * dq * pdf * sigma / (2.0 * sq)
    if call:
        delta = dq * ncdf(d1)
        theta = common - r * K * dr * ncdf(d2) + q * S * dq * ncdf(d1)
    else:
        delta = dq * (ncdf(d1) - 1.0)
        theta = common + r * K * dr * ncdf(-d2) - q * S * dq * ncdf(-d1)
    return {"delta": delta, "gamma": gamma, "theta": theta / 365.0, "vega": vega / 100.0}


def implied_vol(px: float, S: float, K: float, T: float, r: float, call: bool, q: float = 0.0) -> float:
    if not _ok(px, S, K, T, r, q) or S <= 0 or K <= 0 or T <= 0 or px <= 0:
        return NAN
    lo_px, hi_px = price(S, K, T, r, IV_LO, call, q), price(S, K, T, r, IV_HI, call, q)
    if not (lo_px <= px <= hi_px):
        return NAN
    lo, hi = IV_LO, IV_HI
    for _ in range(IV_ITERS):
        mid = 0.5 * (lo + hi)
        if price(S, K, T, r, mid, call, q) < px:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
