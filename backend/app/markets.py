"""Live prediction-market search (Polymarket + Kalshi). Every call has a 5 s timeout and a TTL cache."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .cache import TTLCache

TIMEOUT = httpx.Timeout(5.0)
GAMMA = "https://gamma-api.polymarket.com/public-search"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/events"
KALSHI_CATEGORIES = ("Economics", "Politics", "Companies", "Financials")


class Market(BaseModel):
    source: Literal["polymarket", "kalshi"]
    id: str
    question: str
    yes_price: float | None = None
    volume_24h: float = 0.0
    end_date: str | None = None
    url: str | None = None
    token_id: str | None = None


class SearchOut(BaseModel):
    markets: list[Market]
    stale: bool = False
    note: str | None = None


DATA = Path(__file__).parent / "data"
OFFLINE_NOTE = "offline: cached market list"


def offline_search(q: str, data_dir: Path = DATA) -> list[Market]:
    """Case-insensitive search of the bundled market list (market_universe.json + ai_map.json questions)."""
    words = q.lower().split()
    found: dict[tuple[str, str], Market] = {}
    try:
        uni = json.loads((data_dir / "market_universe.json").read_text()).get("markets", [])
    except (OSError, ValueError):
        uni = []
    for m in uni:
        try:
            mk = Market(source=m["source"], id=str(m["id"]), question=m.get("question") or "",
                        yes_price=_num(m.get("yes_price")), volume_24h=_num(m.get("volume_24h")) or 0.0,
                        end_date=m.get("end_date"), url=m.get("url"), token_id=m.get("token_id"))
        except (KeyError, ValueError):
            continue
        if all(w in mk.question.lower() for w in words):
            found[(mk.source, mk.id)] = mk
    try:
        items = json.loads((data_dir / "ai_map.json").read_text()).get("items", {})
    except (OSError, ValueError):
        items = {}
    for key, v in items.items():
        src, _, mid = str(key).partition(":")
        question = (v or {}).get("question") or ""
        if src not in ("polymarket", "kalshi") or not mid or (src, mid) in found:
            continue
        if all(w in question.lower() for w in words):
            found[(src, mid)] = Market(source=src, id=mid, question=question)
    return sorted(found.values(), key=lambda m: m.volume_24h, reverse=True)


class HistoryPoint(BaseModel):
    t: int
    p: float


def _num(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _jlist(x) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


async def search_polymarket(http: httpx.AsyncClient, q: str) -> list[Market]:
    r = await http.get(GAMMA, params={"q": q, "limit_per_type": 10}, timeout=TIMEOUT)
    r.raise_for_status()
    out: list[Market] = []
    for ev in r.json().get("events", []) or []:
        for m in ev.get("markets", []) or []:
            tokens = [str(t) for t in _jlist(m.get("clobTokenIds"))]
            prices = _jlist(m.get("outcomePrices"))
            out.append(Market(
                source="polymarket", id=str(m.get("id")), question=m.get("question") or ev.get("title") or "",
                yes_price=_num(prices[0]) if prices else None, volume_24h=_num(m.get("volume24hr")) or 0.0,
                end_date=m.get("endDate"), url=f"https://polymarket.com/event/{ev.get('slug')}" if ev.get("slug") else None,
                token_id=tokens[0] if tokens else None))
    return out


def _kalshi_price(m: dict) -> float | None:
    last = _num(m.get("last_price_dollars"))
    if last is not None:
        return last
    bid, ask = _num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars"))
    return (bid + ask) / 2 if bid is not None and ask is not None else None


def _kalshi_volume(m: dict) -> float:
    for k in ("volume_24h_fp", "volume_24h", "volume_fp", "volume"):
        v = _num(m.get(k))
        if v is not None:
            return v
    return 0.0


async def _kalshi_category(http: httpx.AsyncClient, category: str) -> list[dict]:
    r = await http.get(KALSHI, params={"status": "open", "limit": 100, "with_nested_markets": "true",
                                       "category": category}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("events", []) or []


async def search_kalshi(http: httpx.AsyncClient, q: str) -> list[Market]:
    results = await asyncio.gather(*(_kalshi_category(http, c) for c in KALSHI_CATEGORIES), return_exceptions=True)
    if all(isinstance(x, Exception) for x in results):
        raise results[0]  # type: ignore[misc]
    words = q.lower().split()
    out: list[Market] = []
    for events in results:
        if isinstance(events, Exception):
            continue
        for ev in events:
            title = ev.get("title") or ""
            if not all(w in title.lower() for w in words):
                continue
            for m in ev.get("markets", []) or []:
                tk = m.get("ticker")
                if not tk:
                    continue
                out.append(Market(source="kalshi", id=tk, question=m.get("title") or title, yes_price=_kalshi_price(m),
                                  volume_24h=_kalshi_volume(m), end_date=m.get("close_time") or m.get("expiration_time"),
                                  url=f"https://kalshi.com/markets/{tk}"))
    return out


async def search_all(http: httpx.AsyncClient, q: str) -> list[Market]:
    res = await asyncio.gather(search_polymarket(http, q), search_kalshi(http, q), return_exceptions=True)
    if all(isinstance(x, Exception) for x in res):
        raise res[0]  # type: ignore[misc]
    merged = [m for x in res if not isinstance(x, Exception) for m in x]
    return sorted(merged, key=lambda m: m.volume_24h, reverse=True)


async def polymarket_midpoint(http: httpx.AsyncClient, token_id: str) -> float | None:
    r = await http.get(f"{CLOB}/midpoint", params={"token_id": token_id}, timeout=TIMEOUT)
    r.raise_for_status()
    return _num(r.json().get("mid"))


async def polymarket_history(http: httpx.AsyncClient, token_id: str) -> list[HistoryPoint]:
    r = await http.get(f"{CLOB}/prices-history", params={"market": token_id, "interval": "1d", "fidelity": 60},
                       timeout=TIMEOUT)
    r.raise_for_status()
    return [HistoryPoint(t=int(h["t"]), p=float(h["p"])) for h in r.json().get("history", []) or []]


router = APIRouter()


def _http(request: Request) -> httpx.AsyncClient:
    if not hasattr(request.app.state, "http"):
        request.app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    return request.app.state.http


def _cache(request: Request, name: str, ttl: float) -> TTLCache:
    key = f"cache_{name}"
    if not hasattr(request.app.state, key):
        setattr(request.app.state, key, TTLCache(ttl))
    return getattr(request.app.state, key)


@router.get("/markets/search", response_model=SearchOut)
async def markets_search(q: str, request: Request) -> SearchOut:
    q = q.strip()
    if not q:
        raise HTTPException(422, "q must not be blank.")
    http = _http(request)
    try:
        markets, stale = await _cache(request, "search", 60).get_or_set(q.lower(), lambda: search_all(http, q))
    except Exception:
        offline = offline_search(q)
        if offline:
            return SearchOut(markets=offline, stale=True, note=OFFLINE_NOTE)
        raise HTTPException(502, "Both market sources are unavailable and nothing is cached.")
    return SearchOut(markets=markets, stale=stale)


@router.get("/markets/{source}/{id}/history", response_model=list[HistoryPoint])
async def markets_history(source: str, id: str, request: Request) -> list[HistoryPoint]:
    """For polymarket, `id` is the YES token id (Market.token_id). Kalshi history is not served (returns [])."""
    if source == "kalshi":
        return []
    if source != "polymarket":
        raise HTTPException(404, f"Unknown source {source}.")
    http = _http(request)
    try:
        pts, _ = await _cache(request, "history", 300).get_or_set(id, lambda: polymarket_history(http, id))
    except Exception:
        raise HTTPException(502, "Polymarket history is unavailable and nothing is cached.")
    return pts
