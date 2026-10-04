from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from typing import Any

import httpx

from ..chain import bounded, make_client
from . import model as m

log = logging.getLogger(__name__)
EQUITY_TTL_S = 300.0
QUOTE_TTL_S = 30.0
PM_TTL_S = 15.0
STALE_MAX_S = 24 * 3600.0
BOOK_TIMEOUT = httpx.Timeout(4.0)
MASSIVE = "https://api.massive.com"
CLOB = "https://clob.polymarket.com"
GAMMA_MARKET = "https://gamma-api.polymarket.com/markets/{id}"
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_MISSING = object()


def _now() -> float:
    return time.time()


def default_http() -> httpx.AsyncClient:
    return httpx.AsyncClient()


def _iso_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _is_open_bar(ms: int) -> bool:
    from ..closed.session import ET
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).astimezone(ET)
    return t.hour == 9 and t.minute == 30


def _get_json(client, path: str, params: dict | None = None) -> dict:
    r = client.session.get(MASSIVE + path, params=params, timeout=6.0)
    r.raise_for_status()
    return r.json() or {}


def _daily_sync(client, ticker: str, today: dt.date) -> list[dict]:
    start = today - dt.timedelta(days=45)
    j = _get_json(client, f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{today}",
                  {"adjusted": "true", "sort": "asc", "limit": 5000})
    return [b for b in j.get("results") or [] if isinstance(b, dict)]


def completed_daily(bars: list[dict], now: dt.datetime) -> tuple[list[dict], dict | None]:
    from ..closed.session import ET, regular_hours
    today = now.astimezone(ET).date()
    hours = regular_hours(today)
    if hours is not None and now >= hours[1]:
        return bars, None
    keep, partial = [], None
    for b in bars:
        t = m.fin(b.get("t"))
        d = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).astimezone(ET).date() if t is not None else None
        if d is not None and d >= today:
            partial = b
            continue
        keep.append(b)
    return keep, partial


def _five_min_sync(client, ticker: str, today: dt.date) -> list[dict]:
    start = today - dt.timedelta(days=35)
    j = _get_json(client, f"/v2/aggs/ticker/{ticker}/range/5/minute/{start}/{today}",
                  {"adjusted": "true", "sort": "asc", "limit": 50000})
    return [b for b in j.get("results") or [] if isinstance(b, dict)]


def _quote_sync(client, ticker: str) -> dict | None:
    j = _get_json(client, f"/v3/quotes/{ticker}", {"order": "desc", "sort": "timestamp", "limit": 1})
    rows = j.get("results") or []
    if not rows:
        return None
    q = rows[0]
    bid, ask = m.pos(q.get("bid_price")), m.pos(q.get("ask_price"))
    if bid is None or ask is None or ask < bid:
        return None
    ts = m.fin(q.get("sip_timestamp") or q.get("participant_timestamp"))
    return {"bid": bid, "ask": ask, "ts_ns": int(ts) if ts else None, "timeframe": j.get("status")}


class LiquidityService:

    def __init__(self, client_factory=None, http_factory=None, clock=_now) -> None:
        self._client_factory = client_factory
        self._http_factory = http_factory
        self._clock = clock
        self._wall = lambda: dt.datetime.now(dt.timezone.utc)
        self._client: Any = _MISSING
        self.equity_raw: dict[str, tuple[float, dict]] = {}
        self.pm_raw: dict[tuple, tuple[float, dict]] = {}
        self._pending: dict[str, asyncio.Task] = {}

    def client(self):
        if self._client is _MISSING:
            try:
                self._client = (self._client_factory or make_client)()
            except Exception:
                self._client = None
        return self._client

    def set_equity(self, ticker: str, raw: dict, at: float | None = None) -> None:
        self.equity_raw[ticker.upper()] = (self._clock() if at is None else at, {"available": True, **raw})

    def cached_equity(self, ticker: str) -> tuple[dict | None, float | None]:
        hit = self.equity_raw.get((ticker or "").upper())
        if hit is None:
            return None, None
        age = self._clock() - hit[0]
        if age > STALE_MAX_S or not hit[1].get("available"):
            return None, None
        return hit[1], age

    async def _fetch_equity(self, ticker: str) -> dict:
        client = self.client()
        if client is None:
            return {"available": False, "reason": "no MASSIVE_API_KEY: liquidity data unavailable"}
        now = self._wall()
        today = now.date()
        res = await asyncio.gather(bounded(_daily_sync, client, ticker, today),
                                   bounded(_five_min_sync, client, ticker, today),
                                   bounded(_quote_sync, client, ticker), return_exceptions=True)
        daily, five, quote = (None if isinstance(x, BaseException) else x for x in res)
        errors = {n: type(x).__name__ for n, x in zip(("daily_bars", "open5", "quote"), res)
                  if isinstance(x, BaseException)}
        daily, partial = completed_daily(daily or [], now)
        if not daily:
            return {"available": False, "reason": "no daily bars from Massive" + (f" ({errors})" if errors else ""),
                    "errors": errors}
        stats = m.daily_stats(daily)
        price_basis = "last_completed_close"
        if partial is not None and m.pos(partial.get("c")) is not None:
            stats["price"], price_basis = float(partial["c"]), "current_session_partial_bar"
        open5, n5 = m.open5_median(five or [], _is_open_bar)
        spread_bp = spread_src = quote_phase = quote_at = None
        if quote:
            mid = (quote["bid"] + quote["ask"]) / 2.0
            spread_bp, spread_src = (quote["ask"] - quote["bid"]) / mid * 1e4, "quote"
            if quote.get("ts_ns"):
                from ..closed.session import session_at
                qt = dt.datetime.fromtimestamp(quote["ts_ns"] / 1e9, dt.timezone.utc)
                quote_at = qt.isoformat().replace("+00:00", "Z")
                try:
                    quote_phase = session_at(qt).phase
                except ValueError:
                    quote_phase = None
        elif stats.get("cs_spread_bp") is not None:
            spread_bp, spread_src = stats["cs_spread_bp"], "corwin_schultz_estimate"
        return {"available": True, "price": stats["price"], "adv_shares": stats["adv_shares"],
                "adv_usd": stats["adv_usd"], "sigma_daily": stats["sigma_daily"], "adv_sessions": stats["n_sessions"],
                "open5_median_shares": open5, "open5_sessions": n5, "spread_bp": spread_bp,
                "spread_source": spread_src, "cs_spread_bp": stats["cs_spread_bp"], "quote": quote,
                "quote_at": quote_at, "quote_phase": quote_phase, "bars_as_of": _iso_ms(stats.get("as_of_ms")),
                "price_basis": price_basis, "partial_session_excluded": partial is not None, "errors": errors}

    async def equity_raw_for(self, ticker: str, refresh: bool = False) -> tuple[dict, float, bool]:
        t = ticker.upper()
        hit = self.equity_raw.get(t)
        now = self._clock()
        if hit is not None and not refresh and now - hit[0] < EQUITY_TTL_S:
            return hit[1], now - hit[0], False
        try:
            raw = await self._fetch_equity(t)
        except Exception as e:
            raw = {"available": False, "reason": f"liquidity fetch failed: {type(e).__name__}"}
        if not raw.get("available") and hit is not None and hit[1].get("available"):
            return hit[1], now - hit[0], True
        self.equity_raw[t] = (now, raw)
        return raw, 0.0, False

    def warm_equity(self, ticker: str) -> None:
        t = (ticker or "").upper()
        hit = self.equity_raw.get(t)
        if not t or (hit is not None and self._clock() - hit[0] < EQUITY_TTL_S):
            return
        task = self._pending.get(t)
        if task is not None and not task.done():
            return
        try:
            self._pending[t] = asyncio.get_running_loop().create_task(self._warm(t))
        except RuntimeError:
            pass

    async def _warm(self, t: str) -> None:
        try:
            await self.equity_raw_for(t)
        except Exception as e:  # pragma: no cover - equity_raw_for never raises
            log.warning("liquidity warm failed: %s", type(e).__name__)

    async def equity(self, ticker: str, coverage: float = 0.5, qty: float | None = None,
                     refresh: bool = False) -> dict:
        t = ticker.strip().upper()
        if not TICKER_RE.match(t):
            return {"kind": "equity", "ticker": t, "available": False, "reason": "not a ticker"}
        raw, age, stale = await self.equity_raw_for(t, refresh)
        return equity_view(t, raw, age, stale, coverage, qty)

    async def option(self, underlying: str, strike: float, expiry: str, right: str, coverage: float = 0.5) -> dict:
        from ..options.chain import NoClient, get_chain, staleness
        u = underlying.strip().upper()
        base = {"kind": "option", "underlying": u, "strike": strike, "expiry": expiry, "right": right,
                "caps": m.CAPS["option"]}
        client = self.client()
        if client is None:
            return {**base, "available": False, "reason": "no MASSIVE_API_KEY: option liquidity unavailable"}
        try:
            chain, cache_stale = await get_chain(u, expiry_from=expiry, expiry_to=expiry, strike_min=strike,
                                                 strike_max=strike, client=client)
        except NoClient:
            return {**base, "available": False, "reason": "no MASSIVE_API_KEY: option liquidity unavailable"}
        except Exception as e:
            return {**base, "available": False, "reason": f"option chain unavailable ({type(e).__name__})"}
        q = next((x for x in chain.quotes if x.kind == right and abs(x.strike - strike) < 1e-6
                  and x.expiry == expiry), None)
        if q is None:
            return {**base, "available": False, "reason": "contract not listed in the Massive snapshot",
                    "freshness": staleness(chain, cache_stale)}
        spot = m.fin(chain.spot)
        if spot is None:
            cached, _ = self.cached_equity(u)
            spot = (cached or {}).get("price")
        vol, oi = m.fin(q.volume), m.fin(q.open_interest)
        cap = m.option_capacity(vol, oi, m.fin(q.bid), m.fin(q.ask), m.fin(q.mid), spot, m.fin(q.delta), coverage)
        return {**base, "available": True, "contract": q.ticker, "open_interest": oi, "volume": vol,
                "bid": m.fin(q.bid), "ask": m.fin(q.ask), "mid": m.fin(q.mid), "mark_source": q.mark_source,
                "delta": m.fin(q.delta), "spot": spot, **cap,
                "freshness": staleness(chain, cache_stale),
                "label": "Massive option snapshot: volume is the latest session's (Friday's on a weekend); spread "
                         "from the last quote when the plan has quotes",
                "cost_model": {"formula": "cost_bp = half the quoted spread (bp of mid); option impact not "
                                          "modelled, the volume / open-interest caps keep orders small"}}

    async def _book(self, http: httpx.AsyncClient, source: str, key: str) -> tuple[list, list]:
        from ..ticks import _kalshi_side, _levels
        if source == "kalshi":
            r = await http.get(f"{KALSHI_API}/markets/{key}/orderbook", timeout=BOOK_TIMEOUT)
            r.raise_for_status()
            ob = (r.json() or {}).get("orderbook") or {}
            bids = _kalshi_side(ob, "yes")
            asks = [(1.0 - p, q) for p, q in _kalshi_side(ob, "no")]
            return bids, asks
        r = await http.get(f"{CLOB}/book", params={"token_id": key}, timeout=BOOK_TIMEOUT)
        r.raise_for_status()
        j = r.json() or {}
        return _levels(j.get("bids")), _levels(j.get("asks"))

    async def _poly_token(self, http: httpx.AsyncClient, mid: str, token_id: str | None) -> str | None:
        if token_id:
            return token_id
        if mid.isdigit() and len(mid) > 30:
            return mid
        r = await http.get(GAMMA_MARKET.format(id=mid), timeout=BOOK_TIMEOUT)
        r.raise_for_status()
        ids = (r.json() or {}).get("clobTokenIds")
        if isinstance(ids, str):
            try:
                ids = json.loads(ids)
            except ValueError:
                ids = None
        return str(ids[0]) if isinstance(ids, list) and ids else None

    async def _venue_view(self, http, source: str, mid: str, token_id: str | None) -> dict:
        key = (source, mid, token_id)
        hit = self.pm_raw.get(key)
        now = self._clock()
        if hit is not None and now - hit[0] < PM_TTL_S:
            return {**hit[1], "freshness": {"fetched_at": hit[0], "age_s": round(now - hit[0], 1),
                                            "cache_stale": False}}
        try:
            book_key = mid if source == "kalshi" else await self._poly_token(http, mid, token_id)
            if not book_key:
                raise LookupError("no Polymarket YES token id for this market")
            bids, asks = await self._book(http, source, book_key)
            depth = m.pm_depth(bids, asks)
            caps = {"buy": m.pm_cap(depth, "buy"), "sell": m.pm_cap(depth, "sell")}
            cost = {s: (m.walk_cost(asks if s == "buy" else bids, caps[s], depth["mid"], s) if caps[s] else None)
                    for s in ("buy", "sell")}
            view = {"available": depth["mid"] is not None, "source": source, "id": mid, "book_key": book_key,
                    "depth": depth, "max_order_contracts": caps, "est_cost_at_cap": cost,
                    "levels": {"bids": len(bids), "asks": len(asks)},
                    "reason": None if depth["mid"] is not None else "one-sided or empty book"}
        except Exception as e:
            if hit is not None:
                return {**hit[1], "freshness": {"fetched_at": hit[0], "age_s": round(now - hit[0], 1),
                                                "cache_stale": True}}
            return {"available": False, "source": source, "id": mid,
                    "reason": f"{source} book unavailable ({type(e).__name__})"}
        self.pm_raw[key] = (now, view)
        return {**view, "freshness": {"fetched_at": now, "age_s": 0.0, "cache_stale": False}}

    async def pm(self, source: str, mid: str, token_id: str | None = None) -> dict:
        from ..twins import twin_of
        base = {"kind": "pm", "caps": m.CAPS["pm"], "bands_cents": [round(b * 100) for b in m.PM_BANDS],
                "label": "depth within 1/2/5 cents of the mid (buy = asks, sell = bids); Polymarket fills are "
                         "simulated (no trading account)"}
        if source not in ("polymarket", "kalshi"):
            return {**base, "available": False, "source": source, "id": mid, "reason": "source must be polymarket "
                                                                                       "or kalshi"}
        try:
            twin = twin_of(source, mid, token_id)
        except Exception:
            twin = None
        try:
            async with (self._http_factory or default_http)() as http:
                primary = await self._venue_view(http, source, mid, token_id)
                tw = None
                if twin is not None:
                    tw = await self._venue_view(http, twin.source, twin.id, twin.token_id)
        except Exception as e:
            return {**base, "available": False, "source": source, "id": mid,
                    "reason": f"book unavailable ({type(e).__name__})"}
        return {**base, **primary, "twin": tw}


def equity_view(ticker: str, raw: dict, age: float | None, stale: bool, coverage: float,
                qty: float | None = None) -> dict:
    base = {"kind": "equity", "ticker": ticker, "caps": m.CAPS["equity"], "cost_model": m.COST_MODEL,
            "freshness": {"age_s": None if age is None else round(age, 1), "cache_stale": stale,
                          "staleness": "stale_cache" if stale else ("cached" if (age or 0) > 0 else "fresh")}}
    if not raw.get("available"):
        return {**base, "available": False, "reason": raw.get("reason") or "unavailable"}
    stats = {"adv_shares": raw.get("adv_shares"), "price": raw.get("price"), "sigma_daily": raw.get("sigma_daily")}
    cap = m.equity_capacity(stats, raw.get("open5_median_shares"), raw.get("spread_bp"), coverage, qty)
    q = raw.get("quote") or {}
    sources = {
        "daily_bars": {"source": "massive /v2/aggs day", "as_of": raw.get("bars_as_of"),
                       "sessions": raw.get("adv_sessions")},
        "open5": {"source": "massive /v2/aggs 5 minute (09:30 ET bar)", "sessions": raw.get("open5_sessions")},
        "spread": {"source": raw.get("spread_source"), "at": raw.get("quote_at"), "phase": raw.get("quote_phase"),
                   "timeframe": q.get("timeframe"),
                   "note": ("last quote outside the regular session: its spread may be wider than at the open"
                            if raw.get("quote_phase") not in (None, "regular") else
                            ("no quote: Corwin-Schultz estimate from daily highs and lows"
                             if raw.get("spread_source") == "corwin_schultz_estimate" else None))},
    }
    return {**base, "available": True, "price": raw.get("price"), "adv_shares": raw.get("adv_shares"),
            "adv_usd": raw.get("adv_usd"), "sigma_daily": raw.get("sigma_daily"),
            "open5_median_shares": raw.get("open5_median_shares"), "spread_bp": raw.get("spread_bp"),
            "spread_source": raw.get("spread_source"), **cap, "sources": sources,
            "errors": raw.get("errors") or None}


def service_for(app) -> LiquidityService:
    st = app.state
    svc = getattr(st, "liquidity", None)
    if svc is None:
        pinned = getattr(st, "massive", _MISSING)
        factory = (lambda: pinned) if pinned is not _MISSING else None
        svc = st.liquidity = LiquidityService(client_factory=factory)
    return svc
