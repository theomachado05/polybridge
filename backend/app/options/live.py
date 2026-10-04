from __future__ import annotations

import datetime as dt
import math
from typing import Any

from . import bs
from . import chain as ch
from . import quotes as qt
from .implied import RISK_FREE

DEFAULT_STRIKES = 12
MAX_STRIKES = 60
DEFAULT_WINDOW = 0.20
DEFAULT_EXPIRY_DAYS = 45


def greeks_for(q: ch.OptionQuote, spot: float, T: float, r: float = RISK_FREE) -> dict:
    out = {"iv": q.iv, "delta": q.delta, "gamma": q.gamma, "theta": q.theta, "vega": q.vega,
           "iv_source": "massive" if math.isfinite(q.iv) else None, "greeks_source": None}
    names = ("delta", "gamma", "theta", "vega")
    if all(math.isfinite(out[n]) for n in names):
        out["greeks_source"] = "massive"
        return out
    call = q.kind == "call"
    if not (math.isfinite(spot) and spot > 0 and math.isfinite(T) and T > 0):
        out["greeks_source"] = "massive_partial" if any(math.isfinite(out[n]) for n in names) else None
        return out
    iv = q.iv
    if not math.isfinite(iv) and math.isfinite(q.mid) and q.mid > 0:
        iv = bs.implied_vol(q.mid, spot, q.strike, T, r, call)
        if math.isfinite(iv):
            out["iv"], out["iv_source"] = iv, "computed"
    if not math.isfinite(iv):
        return out
    g = bs.greeks(spot, q.strike, T, r, iv, call)
    filled = False
    for n in names:
        if not math.isfinite(out[n]):
            out[n], filled = g[n], True
    had_massive = any(math.isfinite(getattr(q, n)) for n in names)
    out["greeks_source"] = "massive+computed" if had_massive and filled else "computed"
    return out


def contract_row(q: ch.OptionQuote, *, spot: float, now: dt.datetime, market: dict, nbbo_tried: bool) -> dict:
    T = qt.years_to_expiry(q.expiry, now)
    g = greeks_for(q, spot, T)
    stale, why = qt.is_stale(q.updated_ns, market, now)
    quoted = q.mark_source == "quote"
    flags, grade = qt.liquidity_flags(bid=q.bid, ask=q.ask, mid=q.mid, oi=q.open_interest, volume=q.volume,
                                      quoted=quoted, stale=stale)
    return {"ticker": q.ticker, "strike": q.strike, "right": q.kind, "expiry": q.expiry,
            "bid": q.bid, "ask": q.ask, "mid": q.mid, "mark_source": q.mark_source,
            "quote_source": "massive_last_nbbo" if quoted else ("nbbo_unavailable" if nbbo_tried else "not_fetched"),
            "last": q.last, "last_source": q.last_source, "volume": q.volume, "open_interest": q.open_interest,
            **g, "updated_ns": q.updated_ns, "age_s": qt.quote_age(q.updated_ns, now), "stale": stale,
            "stale_reason": why, "liquidity": grade, "liquidity_flags": flags,
            "exercise_style": q.exercise_style}


def _pick_expiry(expiries: list[str], now: dt.datetime) -> str | None:
    live = [e for e in expiries if qt.years_to_expiry(e, now) > 0]
    return live[0] if live else None


def snapshot_label(market: dict, timeframe: str | None) -> str:
    if market.get("market_open") is False:
        return "last close snapshot (market closed): prices are the last session's, not tradable now"
    tf = (timeframe or "").upper()
    if tf.startswith("REAL"):
        return "live session snapshot (real-time)"
    return "live session snapshot (Massive delayed feed, about 15 minutes)"


async def live_chain(underlying: str, *, client, expiry: dt.date | None = None, strikes: int = DEFAULT_STRIKES,
                     window: float = DEFAULT_WINDOW, nbbo: bool = True, now: dt.datetime | None = None) -> dict:
    now = now or qt.now_utc()
    und = underlying.strip().upper()
    market = qt.market_state(now)
    pub_market = {k: v for k, v in market.items() if k != "last_close_s"}
    base: dict[str, Any] = {"underlying": und, "label": "Massive option chain (per contract)", "market": pub_market,
                            "market_open": market.get("market_open"),
                            "request": {"expiry": expiry.isoformat() if expiry else None, "strikes": strikes,
                                        "window": window}}
    if client is None:
        return {**base, "available": False, "reason": "MASSIVE_API_KEY not set", "contracts": []}
    try:
        spot_info, _ = await qt.get_spot(client, und, market.get("market_open"))
        spot = qt.fnum(spot_info.get("price"))
        today = now.astimezone(qt.ET).date()
        ef, et = (expiry, expiry) if expiry else (today, today + dt.timedelta(days=DEFAULT_EXPIRY_DAYS))
        kmin = spot * (1 - window) if math.isfinite(spot) else None
        kmax = spot * (1 + window) if math.isfinite(spot) else None
        try:
            chain, cache_stale = await ch.get_chain(und, expiry_from=ef, expiry_to=et, strike_min=kmin,
                                                    strike_max=kmax, client=client)
        except Exception as e:  # noqa: BLE001
            return {**base, "available": False, "reason": f"Massive unavailable ({type(e).__name__})", "contracts": [],
                    "underlying_price": qt.clean(spot_info)}
        ch.remember(chain)
        exp = expiry.isoformat() if expiry else _pick_expiry(chain.expiries(), now)
        notes: list[str] = []
        if chain.truncated:
            notes.append("chain truncated at the page limit; some strikes may be missing")
        if math.isfinite(chain.spot):
            spot, spot_src = chain.spot, "massive_option_snapshot"
        else:
            spot_src = spot_info.get("source")
        underlying_price = {"price": spot if math.isfinite(spot) else None, "source": spot_src,
                            "stock_snapshot": qt.clean(spot_info)}
        if exp is None or not chain.slice(exp):
            return {**base, "available": False, "contracts": [], "underlying_price": qt.clean(underlying_price),
                    "expiries_listed": chain.expiries(),
                    "reason": "no listed contracts for that expiry in the strike window" if expiry else
                    f"no listed expiry in the next {DEFAULT_EXPIRY_DAYS} days in the strike window",
                    "freshness": ch.staleness(chain, cache_stale)}
        sl = chain.slice(exp)
        ks = list(sl)
        if math.isfinite(spot):
            ks = sorted(sorted(ks, key=lambda k: (abs(k - spot), k))[:strikes])
        else:
            ks = ks[:strikes]
            notes.append("underlying price unknown: strikes are the lowest listed, not the nearest the money")
        picked = [sl[k][kind] for k in ks for kind in ("call", "put") if kind in sl[k]]
        tried: set[str] = set()
        if nbbo and not any(q.mark_source == "quote" for q in picked):
            by_dist = sorted(picked, key=lambda q: abs(q.strike - spot) if math.isfinite(spot) else q.strike)
            want = [q.ticker for q in by_dist][:qt.MAX_NBBO]
            got = await qt.get_nbbos(client, want)
            tried = set(want)
            picked = [qt.apply_nbbo(q, got.get(q.ticker)) for q in picked]
            n_ok = sum(1 for v in got.values() if v)
            notes.append(f"bid/ask: last NBBO fetched for {n_ok} of {len(picked)} contracts (nearest the money first, "
                         f"at most {qt.MAX_NBBO}); the others are marked at Massive fmv")
        rows = [contract_row(q, spot=spot, now=now, market=market, nbbo_tried=q.ticker in tried) for q in picked]
        if any(r["greeks_source"] in ("computed", "massive+computed") for r in rows):
            notes.append("greeks labelled 'computed' are Black–Scholes from the contract's mark (European, no "
                         f"dividends, r = {RISK_FREE}); Massive gave none for those contracts")
        fresh = ch.staleness(chain, cache_stale)
        fresh["mark_sources"] = sorted({r["mark_source"] for r in rows if r["mark_source"]})
        fresh["has_quotes"] = "quote" in fresh["mark_sources"]
        fresh["n_quoted"] = sum(1 for r in rows if r["mark_source"] == "quote")
        fresh["n_stale"] = sum(1 for r in rows if r["stale"])
        return qt.clean({**base, "available": True, "reason": None, "expiry": exp,
                         "dte": (dt.date.fromisoformat(exp) - today).days,
                         "expiries_listed": chain.expiries(), "underlying_price": underlying_price,
                         "snapshot_label": snapshot_label(market, chain.timeframe), "contracts": rows,
                         "n_contracts": len(rows), "freshness": fresh, "notes": notes})
    except Exception as e:  # noqa: BLE001 - never a 500
        return {**base, "available": False, "reason": f"chain could not be built ({type(e).__name__})",
                "contracts": []}
