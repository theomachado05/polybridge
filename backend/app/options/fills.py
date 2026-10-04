from __future__ import annotations

import math
from typing import Any

from .chain import Chain, OptionQuote

STRUCTURES = ("call", "put", "call_spread", "put_spread", "straddle", "cash_secured_put")


def _leg(sl: dict, k: float | None, kind: str) -> OptionQuote | None:
    return None if k is None else (sl.get(float(k)) or {}).get(kind)


def structure_legs(chain: Chain, structure: str, expiry: str, k_lo: float | None = None,
                   k_hi: float | None = None) -> list[tuple[int, OptionQuote | None]] | None:
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
