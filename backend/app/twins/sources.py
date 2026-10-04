from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"
GAMMA_SEARCH = "https://gamma-api.polymarket.com/public-search"
SEARCH_TERMS = ("fed rate decision", "fed funds rate", "cpi inflation", "recession", "unemployment rate", "jobs report",
                "gdp", "bitcoin price", "ethereum price", "solana price", "s&p 500", "nasdaq", "gold price",
                "oil price", "senate control", "house control", "balance of power", "government shutdown",
                "tariff", "supreme court", "debt ceiling", "treasury yield", "mortgage rate", "gas prices",
                "ipo", "trump approval", "president 2028", "nobel", "hurricane", "ai model")
KALSHI_EVENTS = "https://api.elections.kalshi.com/trade-api/v2/events"
SKIP_CATEGORIES = frozenset({"Sports", "Entertainment", "Mentions"})
DATA = Path(__file__).resolve().parents[1] / "data"
TIMEOUT = httpx.Timeout(30.0)

KALSHI_KEEP = ("ticker", "event_ticker", "title", "yes_sub_title", "no_sub_title", "rules_primary", "rules_secondary",
               "close_time", "expiration_time", "expected_expiration_time", "strike_type", "floor_strike",
               "cap_strike", "market_type", "status", "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
               "volume_24h_fp")


def _jlist(x: Any) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def slim_polymarket(m: dict) -> dict | None:
    tokens = [str(t) for t in _jlist(m.get("clobTokenIds"))]
    if not tokens or m.get("id") is None or m.get("closed") or m.get("active") is False:
        return None
    ev = (m.get("events") or [{}])[0] or {}
    return {"id": str(m["id"]), "question": m.get("question") or "", "description": (m.get("description") or "")[:4000],
            "resolutionSource": m.get("resolutionSource") or "", "endDate": m.get("endDate"), "token_id": tokens[0],
            "slug": m.get("slug"), "event_slug": ev.get("slug"), "volume24hr": m.get("volume24hr"),
            "outcomes": _jlist(m.get("outcomes"))}


def slim_kalshi_market(m: dict, event: dict) -> dict | None:
    if m.get("market_type") not in (None, "binary") or not m.get("ticker"):
        return None
    out = {k: m[k] for k in KALSHI_KEEP if k in m}
    for k in ("rules_primary", "rules_secondary"):
        if isinstance(out.get(k), str):
            out[k] = out[k][:2000]
    out["event_title"] = event.get("title")
    out["category"] = event.get("category")
    return out


async def _get_json(http: httpx.AsyncClient, url: str, params: dict, tries: int = 5) -> Any:
    err: Exception | None = None
    for i in range(tries):
        try:
            r = await http.get(url, params=params, timeout=TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            err = e
            await asyncio.sleep(min(2.0 ** i * 0.5, 8.0))
    raise err  # type: ignore[misc]


def universe_ids(data_dir: Path = DATA) -> list[str]:
    try:
        uni = json.loads((data_dir / "market_universe.json").read_text()).get("markets", [])
    except (OSError, ValueError):
        return []
    return [str(m["id"]) for m in uni if m.get("source") == "polymarket" and m.get("id") is not None]


async def fetch_polymarket(http: httpx.AsyncClient, ids: list[str] | None = None, top_n: int = 2000,
                           page: int = 100, search_terms: tuple[str, ...] = SEARCH_TERMS, log: Callable[[str], None] = lambda s: None) -> list[dict]:
    out: dict[str, dict] = {}
    ids = ids or []
    for i in range(0, len(ids), 50):
        try:
            rows = await _get_json(http, GAMMA_MARKETS, {"id": ids[i:i + 50], "limit": 50})
        except Exception as e:
            log(f"polymarket id batch {i} failed ({type(e).__name__})")
            continue
        for m in rows or []:
            s = slim_polymarket(m)
            if s:
                out[s["id"]] = s
    got = 0
    for off in range(0, top_n, page):
        try:
            rows = await _get_json(http, GAMMA_MARKETS, {"active": "true", "closed": "false", "limit": page,
                                                         "offset": off, "order": "volume24hr", "ascending": "false"})
        except Exception as e:
            log(f"polymarket top page offset={off} failed ({type(e).__name__})")
            break
        if not rows:
            break
        for m in rows:
            s = slim_polymarket(m)
            if s:
                out.setdefault(s["id"], s)
                got += 1
        if len(rows) < page:
            break
    found = 0
    for term in search_terms:
        try:
            j = await _get_json(http, GAMMA_SEARCH, {"q": term, "limit_per_type": 25})
        except Exception as e:
            log(f"polymarket search {term!r} failed ({type(e).__name__})")
            continue
        for ev in (j or {}).get("events") or []:
            for m in ev.get("markets") or []:
                m = {**m, "events": m.get("events") or [ev]}
                s = slim_polymarket(m)
                if s and s["id"] not in out:
                    out[s["id"]] = s
                    found += 1
    log(f"polymarket: {len(out)} markets ({len(ids)} bundled-universe ids, {got} top-by-volume, {found} new from "
        f"{len(search_terms)} live searches)")
    return list(out.values())


async def fetch_kalshi(http: httpx.AsyncClient, max_pages: int = 120, pause_s: float = 0.4,
                       log: Callable[[str], None] = lambda s: None) -> list[dict]:
    out: list[dict] = []
    cur: str | None = None
    for n in range(max_pages):
        params: dict[str, Any] = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cur:
            params["cursor"] = cur
        try:
            j = await _get_json(http, KALSHI_EVENTS, params)
        except Exception as e:
            log(f"kalshi events page {n} failed ({type(e).__name__}); keeping {len(out)} markets")
            break
        for ev in j.get("events") or []:
            if ev.get("category") in SKIP_CATEGORIES:
                continue
            for m in ev.get("markets") or []:
                s = slim_kalshi_market(m, ev)
                if s:
                    out.append(s)
        cur = j.get("cursor")
        if not cur:
            break
        await asyncio.sleep(pause_s)
    log(f"kalshi: {len(out)} open binary markets (sports/entertainment/mentions skipped)")
    return out


Fetcher = Callable[..., Awaitable[list[dict]]]
