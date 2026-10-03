"""Listed option chain snapshots from Massive (`/v3/snapshot/options/{underlying}`).

- Live snapshot calls never go through the research client's permanent on-disk cache (a snapshot is only true for
  a moment); they use the same bounded session (6 s per HTTP call, 8 s per threaded call via ``app.chain.bounded``)
  and an in-memory TTL cache (``CHAIN_TTL_S``). On a fetch error the last snapshot is served, marked stale.
- Quote fields depend on the Massive plan. ``bid``/``ask`` come from ``last_quote`` when the plan has quotes;
  otherwise they are NaN and ``mid`` falls back to ``fmv`` (Massive's fair-market value), then the session close.
  ``mark_source`` says which one was used, so nothing downstream mistakes a close for a quote.
- Everything missing is NaN, never invented. No key -> ``make_client()`` is None and callers degrade gracefully.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..cache import TTLCache
from ..chain import bounded, make_client

SNAPSHOT = "/v3/snapshot/options/{underlying}"
BASE_URL = "https://api.massive.com"
CHAIN_TTL_S = 60.0
PAGE_LIMIT = 250
MAX_PAGES = 8
NAN = math.nan

_CACHE = TTLCache(CHAIN_TTL_S)
_LAST: dict[str, "Chain"] = {}  # most recent snapshot per underlying, for the network-free enrich() path


class NoClient(RuntimeError):
    """MASSIVE_API_KEY is not configured."""


def _f(x: Any) -> float:
    """Finite float or NaN."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return NAN
    return v if math.isfinite(v) else NAN


def _ns(x: Any) -> int | None:
    v = _f(x)
    return int(v) if math.isfinite(v) and v > 0 else None


@dataclass
class OptionQuote:
    ticker: str
    kind: str          # "call" | "put"
    strike: float
    expiry: str        # YYYY-MM-DD
    bid: float = NAN
    ask: float = NAN
    mid: float = NAN
    mark_source: str | None = None   # "quote" | "fmv" | "day_close" | None
    iv: float = NAN
    delta: float = NAN
    open_interest: float = NAN
    volume: float = NAN
    updated_ns: int | None = None
    exercise_style: str | None = None


@dataclass
class Chain:
    underlying: str
    fetched_at: float                      # unix seconds
    quotes: list[OptionQuote] = field(default_factory=list)
    spot: float = NAN                      # Massive underlying_asset.price when the plan provides it
    timeframe: str | None = None           # Massive's label, e.g. "DELAYED" / "REAL-TIME"
    source: str = "massive_snapshot"

    def expiries(self) -> list[str]:
        return sorted({q.expiry for q in self.quotes})

    def slice(self, expiry: str) -> dict[float, dict[str, OptionQuote]]:
        """{strike: {"call": q, "put": q}} for one expiry, strikes ascending."""
        out: dict[float, dict[str, OptionQuote]] = {}
        for q in self.quotes:
            if q.expiry == expiry and math.isfinite(q.strike):
                out.setdefault(q.strike, {})[q.kind] = q
        return dict(sorted(out.items()))

    def latest_update_ns(self) -> int | None:
        ts = [q.updated_ns for q in self.quotes if q.updated_ns]
        return max(ts) if ts else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["quotes"] = [_clean(asdict(q)) for q in self.quotes]
        d["spot"] = None if math.isnan(self.spot) else self.spot
        return d


def _clean(d: dict) -> dict:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}


def parse_result(r: dict) -> OptionQuote | None:
    """One snapshot row -> OptionQuote; None when the row has no usable contract details."""
    det = r.get("details") or {}
    kind = det.get("contract_type")
    strike, expiry = _f(det.get("strike_price")), det.get("expiration_date")
    if kind not in ("call", "put") or not math.isfinite(strike) or not expiry:
        return None
    lq, day, greeks = r.get("last_quote") or {}, r.get("day") or {}, r.get("greeks") or {}
    bid, ask = _f(lq.get("bid")), _f(lq.get("ask"))
    if math.isfinite(bid) and math.isfinite(ask) and (bid < 0 or ask <= 0 or bid > ask):
        bid = ask = NAN  # crossed or empty book: trust neither side
    mid, src = NAN, None
    if math.isfinite(bid) and math.isfinite(ask):
        mid, src = (bid + ask) / 2.0, "quote"
    elif math.isfinite(_f(lq.get("midpoint"))) and _f(lq.get("midpoint")) > 0:
        mid, src = _f(lq.get("midpoint")), "quote"
    elif math.isfinite(_f(r.get("fmv"))) and _f(r.get("fmv")) >= 0:
        mid, src = _f(r.get("fmv")), "fmv"
    elif math.isfinite(_f(day.get("close"))) and _f(day.get("close")) >= 0:
        mid, src = _f(day.get("close")), "day_close"
    upd = _ns(lq.get("last_updated")) if src == "quote" else _ns(r.get("fmv_last_updated")) if src == "fmv" else _ns(day.get("last_updated"))
    iv = _f(r.get("implied_volatility"))
    return OptionQuote(ticker=str(det.get("ticker") or ""), kind=kind, strike=strike, expiry=str(expiry)[:10],
                       bid=bid, ask=ask, mid=mid, mark_source=src, iv=iv if iv >= 0 else NAN,
                       delta=_f(greeks.get("delta")), open_interest=_f(r.get("open_interest")),
                       volume=_f(day.get("volume")), updated_ns=upd, exercise_style=det.get("exercise_style"))


def parse_snapshot(underlying: str, pages: list[dict], fetched_at: float | None = None) -> Chain:
    ch = Chain(underlying=underlying, fetched_at=time.time() if fetched_at is None else fetched_at)
    for page in pages:
        for r in (page or {}).get("results") or []:
            q = parse_result(r)
            if q is not None:
                ch.quotes.append(q)
            ua = r.get("underlying_asset") or {}
            if math.isnan(ch.spot) and math.isfinite(_f(ua.get("price"))):
                ch.spot = _f(ua.get("price"))
            ch.timeframe = ch.timeframe or ua.get("timeframe")
    ch.quotes.sort(key=lambda q: (q.expiry, q.strike, q.kind))
    return ch


def _get(client, url: str, params: dict | None) -> dict:
    """GET without the research client's permanent disk cache (snapshots go stale); bounded by the session."""
    full = url if url.startswith("http") else BASE_URL + url
    resp = client.session.get(full, params=params, timeout=6.0)
    resp.raise_for_status()
    return resp.json()


def fetch_pages(client, underlying: str, params: dict, max_pages: int = MAX_PAGES) -> list[dict]:
    page = _get(client, SNAPSHOT.format(underlying=underlying), {**params, "limit": PAGE_LIMIT})
    pages = [page]
    while page.get("next_url") and len(pages) < max_pages:
        page = _get(client, page["next_url"], None)
        pages.append(page)
    return pages


def _iso(d: dt.date | str | None) -> str | None:
    if d is None:
        return None
    return d.isoformat() if isinstance(d, dt.date) else str(d)[:10]


def snapshot_params(expiry_from=None, expiry_to=None, strike_min: float | None = None,
                    strike_max: float | None = None, contract_type: str | None = None) -> dict:
    p: dict[str, Any] = {}
    if _iso(expiry_from):
        p["expiration_date.gte"] = _iso(expiry_from)
    if _iso(expiry_to):
        p["expiration_date.lte"] = _iso(expiry_to)
    if strike_min is not None and math.isfinite(strike_min):
        p["strike_price.gte"] = round(float(strike_min), 4)
    if strike_max is not None and math.isfinite(strike_max):
        p["strike_price.lte"] = round(float(strike_max), 4)
    if contract_type in ("call", "put"):
        p["contract_type"] = contract_type
    return p


def fetch_chain_sync(underlying: str, params: dict, client=None) -> Chain:
    client = client if client is not None else make_client()
    if client is None:
        raise NoClient("MASSIVE_API_KEY is not set")
    ch = parse_snapshot(underlying, fetch_pages(client, underlying, params))
    _LAST[underlying.upper()] = ch
    return ch


async def get_chain(underlying: str, *, expiry_from=None, expiry_to=None, strike_min: float | None = None,
                    strike_max: float | None = None, client=None, cache: TTLCache | None = None) -> tuple[Chain, bool]:
    """(chain, cache_stale). Raises NoClient without a key; TimeoutError / HTTP errors when nothing is cached."""
    underlying = underlying.strip().upper()
    params = snapshot_params(expiry_from, expiry_to, strike_min, strike_max)
    key = (underlying, tuple(sorted(params.items())))
    cache = cache if cache is not None else _CACHE
    if client is None:
        client = make_client()
        if client is None:
            raise NoClient("MASSIVE_API_KEY is not set")
    return await cache.get_or_set(key, lambda: bounded(fetch_chain_sync, underlying, params, client))


def last_chain(underlying: str) -> Chain | None:
    """Most recent snapshot fetched for this underlying in this process (no network)."""
    return _LAST.get(underlying.strip().upper())


def remember(chain: Chain) -> None:
    _LAST[chain.underlying.upper()] = chain


def staleness(chain: Chain, cache_stale: bool, now: float | None = None) -> dict:
    """Honest freshness labels for a response."""
    now = time.time() if now is None else now
    upd = chain.latest_update_ns()
    age = None if upd is None else max(0.0, now - upd / 1e9)
    srcs = sorted({q.mark_source for q in chain.quotes if q.mark_source})
    if cache_stale:
        label = "stale_cache"
    elif age is None:
        label = "unknown"
    elif age <= 20 * 60:
        label = "live" if (chain.timeframe or "").upper().startswith("REAL") else "delayed"
    else:
        label = "prior_session"
    return {"source": chain.source, "timeframe": chain.timeframe, "fetched_at": chain.fetched_at,
            "data_age_s": None if age is None else round(age, 1), "cache_stale": cache_stale, "staleness": label,
            "mark_sources": srcs, "has_quotes": "quote" in srcs}
