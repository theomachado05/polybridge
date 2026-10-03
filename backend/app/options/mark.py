"""Mark one listed option contract from Massive quotes, for option P&L in bridges and the portfolio.

    m = await mark("O:AAPL261023P00300000")          # network: snapshot + last NBBO, cached 30 s, bounded
    m = mark_quote(quote, nbbo=None, spot=333.5)     # network-free, from a chain quote you already hold

A mark is the per-share **mid** with its spread and where both came from:

- ``spread_source: "nbbo"``: the last NBBO from ``/v3/quotes`` (15-min delayed on this plan);
- ``spread_source: "estimated"``: no two-sided quote, so the mid is Massive ``fmv`` (else the session close) and the
  half spread is ``est_half_spread`` (documented, conservative); never presented as a quote.
- ``exit_long`` / ``exit_short`` are the per-share prices a holder would realistically close at (bid / ask, or mid
  -/+ the estimated half spread): use them for liquidation value, ``mark`` for the headline P&L.
- ``stale``: during the session the quote is older than 20 min; with the market closed, it predates the last regular
  close by more than 20 min (a Friday-close mark on Saturday is current, and labelled "last close").
- An expired contract is marked at intrinsic from the underlying price (``mark_source: "intrinsic_expired"``).

Never raises: on no key / outage / unknown contract the result has ``available: false`` and a reason.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from ..cache import TTLCache
from ..chain import bounded, make_client
from . import bs
from . import chain as ch
from . import quotes as qt
from .live import greeks_for

MARK_TTL_S = 30.0
EST_MIN_HALF = 0.025        # $ per share: half a nickel tick
EST_PCT_LIQUID = 0.04       # of mid, open interest >= quotes.OI_THIN
EST_PCT_THIN = 0.08         # of mid, otherwise
LABEL = "option mark: mid of the last Massive quote (or fmv when no quote), with spread and staleness"

_MARKS = TTLCache(MARK_TTL_S)


def est_half_spread(mid: float, oi: float) -> float:
    """Estimated half spread ($/share) when there is no two-sided quote: max($0.025, 4% of mid) with open interest
    >= 500, else max($0.025, 8% of mid). Wider than the SimBroker's 2% on purpose: a mark should not flatter."""
    if not math.isfinite(mid) or mid < 0:
        return math.nan
    pct = EST_PCT_LIQUID if math.isfinite(oi) and oi >= qt.OI_THIN else EST_PCT_THIN
    return max(EST_MIN_HALF, pct * mid)


def mark_quote(q: ch.OptionQuote | None, *, nbbo: dict | None = None, spot: float = math.nan,
               now: dt.datetime | None = None, market: dict | None = None) -> dict:
    """Network-free mark of a chain quote (optionally with a fetched NBBO on top)."""
    now = now or qt.now_utc()
    market = market if market is not None else qt.market_state(now)
    if q is None:
        return {"available": False, "reason": "contract not found", "label": LABEL}
    q = qt.apply_nbbo(q, nbbo)
    T = qt.years_to_expiry(q.expiry, now)
    spc = q.shares_per_contract or 100.0
    out: dict[str, Any] = {"contract": q.ticker, "right": q.kind, "strike": q.strike, "expiry": q.expiry,
                           "shares_per_contract": spc, "market_open": market.get("market_open"),
                           "label": LABEL, "underlying_price": spot if math.isfinite(spot) else None}
    if math.isfinite(T) and T <= 0:
        if not math.isfinite(spot):
            return {**out, "available": False, "reason": "expired and no underlying price to settle at"}
        v = bs.intrinsic(spot, q.strike, q.kind == "call")
        return {**out, "available": True, "reason": None, "mark": v, "bid": v, "ask": v, "half_spread": 0.0,
                "spread_source": "settlement", "mark_source": "intrinsic_expired", "exit_long": v, "exit_short": v,
                "mark_per_contract": v * spc, "stale": False, "stale_reason": None, "expired": True,
                "as_of_label": "expired: intrinsic value at the underlying price (settlement estimate)"}
    if not math.isfinite(q.mid):
        return {**out, "available": False, "reason": "no quote, fmv or close for this contract"}
    quoted = math.isfinite(q.bid) and math.isfinite(q.ask)
    half = (q.ask - q.bid) / 2.0 if quoted else est_half_spread(q.mid, q.open_interest)
    stale, why = qt.is_stale(q.updated_ns, market, now)
    g = greeks_for(q, spot, T)
    closed = market.get("market_open") is False
    return {**out, "available": True, "reason": None, "expired": False,
            "mark": q.mid, "bid": q.bid if quoted else None, "ask": q.ask if quoted else None, "half_spread": half,
            "spread_source": "nbbo" if quoted else "estimated", "mark_source": q.mark_source,
            "exit_long": (q.bid if quoted else max(q.mid - half, 0.0)),
            "exit_short": (q.ask if quoted else q.mid + half),
            "mark_per_contract": q.mid * spc, "last": q.last, "last_source": q.last_source,
            "open_interest": q.open_interest, "volume": q.volume, **g,
            "updated_ns": q.updated_ns, "age_s": qt.quote_age(q.updated_ns, now), "stale": stale, "stale_reason": why,
            "as_of_label": ("last close (market closed)" if closed else "session quote (delayed feed)")
            + ("" if quoted else "; no two-sided quote: spread estimated")}


async def _fetch(client, und: str, ticker: str) -> tuple[ch.OptionQuote | None, float, dict | None]:
    q, spot = await bounded(qt.fetch_contract_sync, client, und, ticker)
    nbbo = await qt.get_nbbo(client, ticker) if q is not None else None
    return q, spot, nbbo


_DEFAULT = object()


async def mark(contract: str, *, client: Any = _DEFAULT, now: dt.datetime | None = None) -> dict:
    """Mark an OCC contract ('O:AAPL261023P00300000' or without 'O:') from Massive (``client`` defaults to
    ``make_client()``; pass None for "no key"). Cached 30 s; on a fetch error the last mark is served with
    ``cache_stale: true``. Never raises."""
    occ = qt.parse_occ(contract)
    if occ is None:
        return {"available": False, "contract": contract, "reason": "not an OCC option symbol", "label": LABEL}
    try:
        client = make_client() if client is _DEFAULT else client   # an explicit None means "no key"
        if client is None:
            return {**occ, "contract": occ["ticker"], "available": False, "reason": "MASSIVE_API_KEY not set",
                    "label": LABEL}
        (q, spot, nbbo), cache_stale = await _MARKS.get_or_set(
            ("mark", occ["ticker"]), lambda: _fetch(client, occ["underlying"], occ["ticker"]))
        if q is None and math.isfinite(spot) and qt.years_to_expiry(occ["expiry"], now) <= 0:
            q = ch.OptionQuote(ticker=occ["ticker"], kind=occ["right"], strike=occ["strike"], expiry=occ["expiry"])
        m = mark_quote(q, nbbo=nbbo, spot=spot, now=now)
        if q is None:
            m["contract"] = occ["ticker"]
        return qt.clean({**m, "cache_stale": cache_stale, "underlying": occ["underlying"]})
    except Exception as e:  # noqa: BLE001 - never raise into a bridge loop
        return {**occ, "contract": occ["ticker"], "available": False, "label": LABEL,
                "reason": f"Massive unavailable ({type(e).__name__})"}


def reset_cache() -> None:
    global _MARKS
    _MARKS = TTLCache(MARK_TTL_S)
