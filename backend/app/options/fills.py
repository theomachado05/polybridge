"""Fill prices for the option structures the C++ Opportunity families trade (spec §5: option fills at the Massive
quote mid +/- half the spread, per-contract fee charged by the broker).

An Intent on ``Instrument::Option`` trades one unit of the family's structure; ``structure_quote`` prices that
unit from a chain snapshot as signed legs, so the SimBroker (or the bridge) can fill it as one order:

    legs = structure_legs(chain, "call_spread", expiry, k_lo=145, k_hi=155)
    q = structure_quote(legs)   # {"mid", "half_spread", "bid", "ask", "source", "legs": [...]}
    px = q["mid"] + side * q["half_spread"]    # buy at mid + half, sell at mid - half

``half_spread`` is the sum of the legs' quoted half spreads when every leg has a quote; otherwise it is None and
``source`` says the mid came from fmv / close, so the broker applies its own documented fallback spread.
"""
from __future__ import annotations

import math
from typing import Any

from .chain import Chain, OptionQuote

STRUCTURES = ("call", "put", "call_spread", "put_spread", "straddle", "cash_secured_put")


def _leg(sl: dict, k: float | None, kind: str) -> OptionQuote | None:
    return None if k is None else (sl.get(float(k)) or {}).get(kind)


def structure_legs(chain: Chain, structure: str, expiry: str, k_lo: float | None = None,
                   k_hi: float | None = None) -> list[tuple[int, OptionQuote | None]] | None:
    """Signed legs [(+1 long / -1 short, quote)] for one unit; None for an unknown structure.

    call_spread: +C(k_lo) -C(k_hi)   put_spread: +P(k_hi) -P(k_lo)   straddle: +C(k_lo) +P(k_lo)
    call / put: +leg at k_lo         cash_secured_put: -P(k_lo) (the family sells it)"""
    if structure not in STRUCTURES:
        return None
    sl = chain.slice(expiry)
    return {
        "call": lambda: [(1, _leg(sl, k_lo, "call"))],
        "put": lambda: [(1, _leg(sl, k_lo, "put"))],
        "call_spread": lambda: [(1, _leg(sl, k_lo, "call")), (-1, _leg(sl, k_hi, "call"))],
        "put_spread": lambda: [(1, _leg(sl, k_hi, "put")), (-1, _leg(sl, k_lo, "put"))],
        "straddle": lambda: [(1, _leg(sl, k_lo, "call")), (1, _leg(sl, k_lo, "put"))],
        "cash_secured_put": lambda: [(-1, _leg(sl, k_lo, "put"))],
    }[structure]()


def structure_quote(legs: list[tuple[int, Any]] | None) -> dict:
    """Net per-share mid and half spread of signed legs. ``mid`` is None if any leg has no price."""
    out: dict[str, Any] = {"mid": None, "half_spread": None, "bid": None, "ask": None, "source": None, "legs": []}
    if not legs:
        return out
    mid, half, srcs, quoted = 0.0, 0.0, set(), True
    for sign, q in legs:
        m = getattr(q, "mid", math.nan) if q is not None else math.nan
        out["legs"].append({"side": sign, "ticker": getattr(q, "ticker", None), "mid": m if math.isfinite(m) else None})
        if not math.isfinite(m):
            return {**out, "source": "missing_leg"}
        mid += sign * m
        srcs.add(q.mark_source)
        b, a = q.bid, q.ask
        if math.isfinite(b) and math.isfinite(a):
            half += (a - b) / 2.0
        else:
            quoted = False
    out["mid"] = mid
    out["source"] = "quote" if srcs == {"quote"} else "+".join(sorted(s for s in srcs if s))
    if quoted:
        out["half_spread"] = half
        out["bid"], out["ask"] = mid - half, mid + half
    return out
