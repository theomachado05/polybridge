"""Opportunity-division data routes.

- ``GET /options/implied?market_source=&market_id=`` (optional ``question=`` / ``end_date=`` overrides): the
  options-implied probability of the prediction market's YES, next to the market's own price.
- ``GET /options/chain?ticker=``: the listed chain snapshot (optional expiry / strike window).
- ``GET /options/eightk?ticker=``: the 8-K score and the filing behind it.
- ``GET /options/chain/{underlying}?expiry=&strikes=&window=&quotes=``: one expiry, per contract with bid/ask/mid,
  last, volume, OI, IV and greeks (Massive, else Black–Scholes labelled ``computed``), spot, staleness, market_open.
- ``GET /options/hedge-quote?ticker=&shares=&horizon_days=&protection_pct=&borrow_rate=``: short stock vs protective
  put vs collar vs put spread, side by side at executable prices, with liquidity flags and caveats.
- ``GET /options/mark/{contract}``: one OCC contract's mark (mid, spread, stale flag), as bridges / portfolio use.

Every response says where the numbers come from (``freshness.source``, ``timeframe``, ``data_age_s``,
``staleness``, ``mark_sources``) and is labelled an estimate. No key, an unsupported question or a Massive outage
is a 200 with ``available: false`` and a reason, never a 500.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from ..chain import make_client
from . import chain as ch
from . import hedge as hq
from . import live as lv
from . import mark as mk
from .eightk import OOS_END, eightk_detail, refresh_eightk
from .enrich import refresh, structure_mid
from .implied import implied_for_threshold, jsonable
from .match import match_question, why_no_match

router = APIRouter(prefix="/options", tags=["options"])

DATA = Path(__file__).resolve().parent.parent / "data"
GAMMA_MARKET = "https://gamma-api.polymarket.com/markets/{id}"
KALSHI_MARKET = "https://api.elections.kalshi.com/trade-api/v2/markets/{id}"
TIMEOUT = httpx.Timeout(5.0)
LABEL = "options-implied risk-neutral estimate (not a measured probability)"
_TICKER = re.compile(r"^(I:)?[A-Z][A-Z.]{0,7}$")


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _jlist(x: Any) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def _http(request: Request) -> httpx.AsyncClient:
    if not hasattr(request.app.state, "http"):
        request.app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    return request.app.state.http


def _universe(source: str, mid: str, data_dir: Path = DATA) -> dict:
    try:
        uni = json.loads((data_dir / "market_universe.json").read_text()).get("markets", [])
    except (OSError, ValueError):
        return {}
    return next((m for m in uni if m.get("source") == source and str(m.get("id")) == str(mid)), {})


def kalshi_question(m: dict) -> str | None:
    """Kalshi threshold markets carry the level in the subtitle ("Nvidia price on Dec 31, 2026?" + "$250 or
    above"): join title and yes_sub_title (or subtitle) unless the title already contains it."""
    title = str(m.get("title") or "").strip()
    sub = str(m.get("yes_sub_title") or m.get("subtitle") or "").strip()
    if sub and sub.lower() not in title.lower():
        return f"{title} {sub}".strip()
    return title or None


async def resolve_market(http: httpx.AsyncClient, source: str, mid: str) -> dict:
    """{question, end_date, yes_price, origin}; origin "universe" | "live" | "recording" (a replay sidecar, offline) |
    None when nothing was found."""
    out: dict[str, Any] = {"question": None, "end_date": None, "yes_price": None, "origin": None}
    entry = _universe(source, mid)
    if entry:
        out.update(question=entry.get("question"), end_date=entry.get("end_date"),
                   yes_price=_num(entry.get("yes_price")), origin="universe")
    try:
        if source == "polymarket":
            r = await http.get(GAMMA_MARKET.format(id=mid), timeout=TIMEOUT)
            r.raise_for_status()
            m = r.json() or {}
            prices = _jlist(m.get("outcomePrices"))
            out.update(question=m.get("question") or out["question"], end_date=m.get("endDate") or out["end_date"],
                       yes_price=_num(prices[0]) if prices else out["yes_price"], origin="live")
        elif source == "kalshi":
            r = await http.get(KALSHI_MARKET.format(id=mid), timeout=TIMEOUT)
            r.raise_for_status()
            m = (r.json() or {}).get("market") or {}
            bid, ask = _num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars"))
            px = (bid + ask) / 2 if bid is not None and ask is not None else _num(m.get("last_price_dollars"))
            out.update(question=kalshi_question(m) or out["question"],
                       end_date=m.get("close_time") or m.get("expiration_time") or out["end_date"],
                       yes_price=px if px is not None else out["yes_price"], origin="live")
    except Exception:
        pass  # the universe entry (if any) stands; the response says where it came from
    if out["origin"] is None:  # offline and not in the bundled list: the recording's sidecar names the market
        from ..pipeline.ticks import recording_meta
        meta = recording_meta(source, mid)
        if meta.get("question"):
            out.update(question=meta["question"], end_date=meta.get("end_date"), origin="recording")
    return out


@router.get("/implied")
async def options_implied(request: Request, market_source: str | None = None, market_id: str | None = None,
                          question: str | None = None, end_date: str | None = None) -> dict:
    if not question and not (market_source and market_id):
        raise HTTPException(422, "Give market_source and market_id, or question.")
    if market_source is not None and market_source not in ("polymarket", "kalshi"):
        raise HTTPException(422, "market_source must be polymarket or kalshi.")
    market: dict[str, Any] = {"source": market_source, "id": market_id, "question": question,
                              "end_date": end_date, "yes_price": None, "origin": "request" if question else None}
    if market_source and market_id:
        found = await resolve_market(_http(request), market_source, market_id)
        market.update(question=question or found["question"], end_date=end_date or found["end_date"],
                      yes_price=found["yes_price"], origin="request" if question else found["origin"])
    base = {"label": LABEL, "market": market}
    q = market["question"]
    if not q:
        return {**base, "supported": False, "available": False, "reason": "market not found (no question text)"}
    today = dt.date.today()
    m = match_question(q, market["end_date"], as_of=today)
    if m is None:
        return {**base, "supported": False, "available": False,
                "reason": f"unsupported question: {why_no_match(q, market['end_date'], as_of=today)}"}
    base["match"] = m.to_dict()
    client = make_client()
    if client is None:
        return {**base, "supported": True, "available": False, "reason": "MASSIVE_API_KEY not set"}
    attempts = [(m.underlying, m.strike, m.approx)]
    if m.fallback:
        attempts.append((m.fallback[0], round(m.level * m.fallback[1], 6), True))
    got, used = None, None
    for und, k, approx in attempts:
        got = await refresh(und, k, m.expiry, as_of=today, client=client)
        if got is not None:
            used = (und, k, approx)
            break
    if got is None:
        return {**base, "supported": True, "available": False,
                "reason": "no listed options near the threshold and date, or Massive is unavailable"}
    chain, stale = got
    und, k, approx = used
    res = implied_for_threshold(chain, k, m.expiry, above=m.direction == "above", as_of=today)
    if res.get("expiry"):
        res["structure_mid"] = structure_mid(chain.slice(res["expiry"]), res.get("k_lo"), res.get("k_hi"),
                                             m.direction == "above")
    prob = res.get("prob")
    yes = market.get("yes_price")
    ok = isinstance(prob, float) and math.isfinite(prob) and bool(res.get("expiry_gap_ok"))
    notes = list(m.notes) + ([f"proxy {und} used (approximate scaling)"] if und != m.underlying else [])
    if chain.truncated:
        notes.append("chain truncated at the page limit; expiries or strikes may be missing")
    return {**base, "supported": True, "available": ok,
            "reason": None if ok else "; ".join(res.get("notes") or ["no usable option prices"]),
            "underlying_used": und, "strike_used": k, "approx": approx, "notes": notes,
            "estimate": jsonable(res),
            "pm_yes_price": yes,
            "pm_minus_option": (yes - prob) if ok and yes is not None else None,
            "spot": None if math.isnan(chain.spot) else chain.spot,
            "freshness": ch.staleness(chain, stale)}


def _row(q: ch.OptionQuote | None) -> dict | None:
    if q is None:
        return None
    return ch._clean({"ticker": q.ticker, "bid": q.bid, "ask": q.ask, "mid": q.mid, "mark_source": q.mark_source,
                      "iv": q.iv, "delta": q.delta, "open_interest": q.open_interest, "volume": q.volume,
                      "updated_ns": q.updated_ns})


@router.get("/chain")
async def options_chain(ticker: str, expiry_from: str | None = None, expiry_to: str | None = None,
                        strike_min: float | None = None, strike_max: float | None = None) -> dict:
    tk = ticker.strip().upper()
    if not _TICKER.match(tk):
        raise HTTPException(422, "ticker must look like NVDA, BRK.B or I:SPX.")
    today = dt.date.today()
    try:
        ef = dt.date.fromisoformat(expiry_from) if expiry_from else today
        et = dt.date.fromisoformat(expiry_to) if expiry_to else today + dt.timedelta(days=30)
    except ValueError:
        raise HTTPException(422, "expiry_from / expiry_to must be YYYY-MM-DD.")
    if et < ef:
        raise HTTPException(422, "expiry_to is before expiry_from.")
    base = {"ticker": tk, "label": "Massive option chain snapshot", "window": {
        "expiry_from": ef.isoformat(), "expiry_to": et.isoformat(), "strike_min": strike_min, "strike_max": strike_max}}
    client = make_client()
    if client is None:
        return {**base, "available": False, "reason": "MASSIVE_API_KEY not set", "expiries": []}
    try:
        chain, stale = await ch.get_chain(tk, expiry_from=ef, expiry_to=et, strike_min=strike_min,
                                          strike_max=strike_max, client=client)
    except Exception as e:
        return {**base, "available": False, "reason": f"Massive unavailable ({type(e).__name__})", "expiries": []}
    ch.remember(chain)
    exps = [{"expiry": e, "strikes": [{"strike": k, "call": _row(legs.get("call")), "put": _row(legs.get("put"))}
                                      for k, legs in chain.slice(e).items()]} for e in chain.expiries()]
    return {**base, "available": bool(chain.quotes), "reason": None if chain.quotes else "no listed contracts in window",
            "spot": None if math.isnan(chain.spot) else chain.spot, "n_contracts": len(chain.quotes),
            "expiries": exps, "freshness": ch.staleness(chain, stale)}


@router.get("/eightk")
async def options_eightk(ticker: str, as_of: str | None = None, window_days: int = 30) -> dict:
    tk = ticker.strip().upper()
    if not _TICKER.match(tk) or not 1 <= window_days <= 365:
        raise HTTPException(422, "ticker must look like NVDA; window_days in 1..365.")
    try:
        a = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    except ValueError:
        raise HTTPException(422, "as_of must be YYYY-MM-DD.")
    if a > OOS_END:  # recent dates: load live filings into the shared store (never inside the frozen OOS window)
        client = make_client()
        if client is not None:
            await refresh_eightk(a, window_days, client=client)
    d = eightk_detail(tk, a, window_days)
    source = {"in_sample": "bundled in-sample filings (2024-2025)",
              "live": "live Massive disclosures (from 2026-09-01; the OOS window is never read)"}.get(
        d["coverage"], "no 8-K data covers this date (no key, Massive unavailable, or the frozen OOS window)")
    return {**d, "available": d["coverage"] is not None, "source": source,
            "label": "8-K tag-direction prior (H1 hedge -> negative, H2 opportunity -> positive); not a measured edge"}


@router.get("/chain/{underlying}")
async def options_chain_live(underlying: str, expiry: str | None = None, strikes: int = lv.DEFAULT_STRIKES,
                             window: float = lv.DEFAULT_WINDOW, quotes: bool = True) -> dict:
    """One expiry of the live chain (nearest listed when ``expiry`` is omitted); ``strikes`` nearest the money;
    ``window`` = strike window as a fraction of spot; ``quotes`` = fetch the last NBBO per contract (capped)."""
    tk = underlying.strip().upper()
    if not _TICKER.match(tk):
        raise HTTPException(422, "underlying must look like NVDA, BRK.B or I:SPX.")
    if not 1 <= strikes <= lv.MAX_STRIKES:
        raise HTTPException(422, f"strikes must be 1..{lv.MAX_STRIKES}.")
    if not (math.isfinite(window) and 0.01 <= window <= 0.9):
        raise HTTPException(422, "window must be a fraction of spot in 0.01..0.9 (0.2 = +/-20%).")
    try:
        exp = dt.date.fromisoformat(expiry) if expiry else None
    except ValueError:
        raise HTTPException(422, "expiry must be YYYY-MM-DD.")
    return await lv.live_chain(tk, client=make_client(), expiry=exp, strikes=strikes, window=window, nbbo=quotes)


def _options_at_broker(request: Request) -> bool:
    """The active broker places option orders itself (Webull paper with WEBULL_OPTIONS=1), not its simulator."""
    try:
        from ..broker import SimBroker, get_broker
        b = get_broker(request.app)
    except Exception:
        return False
    return not isinstance(b, SimBroker) and bool(getattr(b, "options_supported", False))


@router.get("/hedge-quote")
async def options_hedge_quote(request: Request, ticker: str, shares: int, horizon_days: int = 30,
                              protection_pct: float = 0.05, borrow_rate: float | None = None) -> dict:
    """Short stock vs protective put vs collar vs put spread for ``shares`` long, over ``horizon_days``, protecting
    below spot x (1 - protection_pct). ``borrow_rate`` (annual, e.g. 0.02) overrides the assumed easy-to-borrow fee."""
    tk = ticker.strip().upper()
    if not _TICKER.match(tk):
        raise HTTPException(422, "ticker must look like NVDA or BRK.B.")
    if not 1 <= shares <= 10_000_000:
        raise HTTPException(422, "shares must be 1..10,000,000 (the long position being hedged).")
    if not 1 <= horizon_days <= 730:
        raise HTTPException(422, "horizon_days must be 1..730.")
    if not (math.isfinite(protection_pct) and 0.0 < protection_pct <= 0.5):
        raise HTTPException(422, "protection_pct must be a fraction in (0, 0.5] (0.05 = protect below spot -5%).")
    if borrow_rate is not None and not (math.isfinite(borrow_rate) and 0.0 <= borrow_rate <= 5.0):
        raise HTTPException(422, "borrow_rate must be an annual fraction in 0..5 (0.003 = 0.3%/yr).")
    return await hq.hedge_quote(tk, shares, horizon_days, protection_pct, client=make_client(),
                                borrow_rate=borrow_rate, options_at_broker=_options_at_broker(request))


@router.get("/mark/{contract}")
async def options_mark(contract: str) -> dict:
    """Mark one OCC option contract (e.g. O:AAPL261023P00300000): mid, spread, exit prices, stale flag."""
    if mk.qt.parse_occ(contract) is None:
        raise HTTPException(422, "contract must be an OCC option symbol like O:AAPL261023P00300000.")
    return await mk.mark(contract, client=make_client())
