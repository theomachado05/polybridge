"""Fill a MarketTick dict's option fields (and optionally the 8-K score) for the bridge loop and the tick builder.

    tick = enrich(tick, "NVDA", 150.0, "2026-12-31")            # network-free; uses the last cached snapshot
    await refresh("NVDA", 150.0, "2026-12-31")                    # fetch/refresh that snapshot (bounded, cached)

Field meanings (MarketTick, engine/hedgecore/include/hedgecore/market.hpp), all for the YES side of the question:
- ``opt_implied_prob``: options-implied P(YES) (see implied.py: call spread, parity fallback, delta approximation);
- ``opt_mid``: per-share mid of one unit of the YES-equivalent structure: the call spread C(k_lo) - C(k_hi) for
  "above", the put spread P(k_hi) - P(k_lo) for "below" (the C++ option families trade one unit at opt_mid, x100);
- ``opt_delta``: delta interpolated at K (call delta for "above", put delta for "below");
- ``opt_iv``: implied volatility interpolated at K;
- ``eightk_score``: [-1, 1], 0 = none (eightk.py), only when ``eightk_ticker`` is given.

NaN-safe: a missing chain, a missing strike or a broken quote leaves the field NaN (or its existing finite value);
enrich never raises on bad input.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from . import chain as ch
from .eightk import eightk_score
from .implied import RISK_FREE, _date, _g, implied_for_threshold

NAN = math.nan
OPT_FIELDS = ("opt_mid", "opt_delta", "opt_iv", "opt_implied_prob")
EXPIRY_STEPS = (3, 10, 30, 60)
STRIKE_PAD = 0.10


def _fin(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _tick_date(tick: dict) -> dt.date | None:
    try:
        ts = int(tick.get("ts_ns"))
        return dt.datetime.fromtimestamp(ts / 1e9, tz=dt.timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def structure_mid(sl: dict, k_lo: float | None, k_hi: float | None, above: bool) -> float:
    if k_lo is None or k_hi is None:
        return NAN
    lo, hi = sl.get(k_lo, {}), sl.get(k_hi, {})
    if above:
        a, b = _g(lo.get("call"), "mid"), _g(hi.get("call"), "mid")
    else:
        a, b = _g(hi.get("put"), "mid"), _g(lo.get("put"), "mid")
    v = a - b
    return v if _fin(v) and v >= 0 else NAN


def enrich_detail(tick: dict | None, underlying: str, K: float, expiry: Any, *, above: bool = True,
                  chain: Any = None, as_of: Any = None, r: float = RISK_FREE,
                  eightk_ticker: str | None = None) -> tuple[dict, dict]:
    """(enriched tick copy, estimate detail). See module docstring."""
    out = dict(tick or {})
    for f in OPT_FIELDS:
        v = out.get(f, NAN)
        out[f] = float(v) if _fin(v) else NAN
    detail: dict = {"available": False, "notes": []}
    try:
        a = _date(as_of) or _tick_date(out) or dt.date.today()
        if eightk_ticker:
            out["eightk_score"] = eightk_score(eightk_ticker, as_of=a)
        c = chain if chain is not None else (ch.last_chain(underlying) if underlying else None)
        if c is None:
            detail["notes"].append("no option chain cached for this underlying")
            return out, detail
        try:
            k = float(K)
        except (TypeError, ValueError):
            k = NAN
        if not _fin(k) or _date(expiry) is None:
            detail["notes"].append("missing threshold or expiry")
            return out, detail
        res = implied_for_threshold(c, k, expiry, above=above, r=r, as_of=a)
        detail = res
        detail["available"] = _fin(res.get("prob"))
        if res.get("expiry"):
            mid = structure_mid(c.slice(res["expiry"]), res.get("k_lo"), res.get("k_hi"), above)
            res["structure_mid"] = mid
            vals = {"opt_implied_prob": res.get("prob"), "opt_delta": res.get("delta"), "opt_iv": res.get("iv"),
                    "opt_mid": mid}
            for f, v in vals.items():
                if _fin(v):
                    out[f] = float(v)
    except Exception as e:  # NaN-safety contract: never break the tick loop
        detail = {"available": False, "notes": [f"enrich failed: {type(e).__name__}"]}
    return out, detail


def enrich(tick: dict | None, underlying: str, K: float, expiry: Any, **kw) -> dict:
    """Returns a copy of ``tick`` with opt_mid / opt_delta / opt_iv / opt_implied_prob filled where possible."""
    return enrich_detail(tick, underlying, K, expiry, **kw)[0]


async def refresh(underlying: str, K: float, expiry: Any, *, as_of: Any = None, client=None,
                  cache=None) -> tuple[Any, bool] | None:
    """Fetch (TTL-cached) the snapshot around K and the resolution date so ``enrich`` can use it.

    Index chains list an expiry almost every day, so the expiry window widens step by step (``EXPIRY_STEPS`` days
    either side of the resolution date) and stops at the first window with contracts: that window holds the
    nearest listed expiry. Strikes within ``STRIKE_PAD`` of K. Returns (chain, cache_stale), or None when there is
    no key, no listed contracts, or Massive is unavailable and nothing is cached."""
    e = _date(expiry)
    a = _date(as_of) or dt.date.today()
    try:
        k = float(K)
    except (TypeError, ValueError):
        return None
    if e is None or not _fin(k) or k <= 0:
        return None
    for w in EXPIRY_STEPS:
        lo = max(a, e - dt.timedelta(days=w))
        hi = max(e, a) + dt.timedelta(days=w)
        try:
            c, stale = await ch.get_chain(underlying, expiry_from=lo, expiry_to=hi, strike_min=k * (1 - STRIKE_PAD),
                                          strike_max=k * (1 + STRIKE_PAD), client=client, cache=cache)
        except Exception:
            return None
        if c.quotes:
            ch.remember(c)
            return c, stale
    return None
