import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cache import TTLCache
from app.main import create_app

POLY = {"events": [{"slug": "fed-cut", "title": "Fed", "markets": [{
    "id": "11", "question": "Fed cut in Dec?", "outcomePrices": json.dumps(["0.165", "0.835"]),
    "clobTokenIds": json.dumps(["tokYES", "tokNO"]), "volume24hr": 5000.5, "endDate": "2026-12-10"}]}]}
KALSHI = {"events": [
    {"title": "Fed rate decision", "markets": [
        {"ticker": "KXFED-1", "title": "Cut?", "last_price_dollars": "0.30", "yes_bid_dollars": None, "yes_ask_dollars": None},
        {"ticker": "KXFED-2", "title": "Hold?", "last_price_dollars": None, "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.50",
         "volume_24h_fp": "9000"}]},
    {"title": "Weather in NYC", "markets": [{"ticker": "KXW", "last_price_dollars": "0.5"}]}]}
HIST = {"history": [{"t": 1, "p": 0.1}, {"t": 2, "p": 0.2}]}


def make_client(handler):
    app = create_app()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TestClient(app)


def ok_handler(req: httpx.Request) -> httpx.Response:
    h = req.url.host
    if h == "gamma-api.polymarket.com":
        return httpx.Response(200, json=POLY)
    if h == "api.elections.kalshi.com":
        return httpx.Response(200, json=KALSHI if req.url.params["category"] == "Economics" else {"events": []})
    if h == "clob.polymarket.com":
        return httpx.Response(200, json=HIST)
    return httpx.Response(404)


def test_search_parses_and_filters_and_sorts():
    r = make_client(ok_handler).get("/markets/search", params={"q": "fed"})
    body = r.json()
    assert r.status_code == 200 and body["stale"] is False
    ms = body["markets"]
    assert [m["id"] for m in ms] == ["KXFED-2", "11", "KXFED-1"]  # by volume desc
    poly = next(m for m in ms if m["source"] == "polymarket")
    assert poly["yes_price"] == 0.165 and poly["token_id"] == "tokYES" and poly["volume_24h"] == 5000.5
    assert next(m for m in ms if m["id"] == "KXFED-1")["yes_price"] == 0.30
    assert next(m for m in ms if m["id"] == "KXFED-2")["yes_price"] == pytest.approx(0.45)
    assert all(m["id"] != "KXW" for m in ms)


def test_one_source_failing_returns_other():
    def h(req):
        return httpx.Response(500) if req.url.host == "gamma-api.polymarket.com" else ok_handler(req)
    body = make_client(h).get("/markets/search", params={"q": "fed"}).json()
    assert {m["source"] for m in body["markets"]} == {"kalshi"}


def test_total_failure_returns_stale_cache_then_502():
    state = {"down": False}

    def h(req):
        return httpx.Response(500) if state["down"] else ok_handler(req)
    c = make_client(h)
    assert c.get("/markets/search", params={"q": "fed"}).json()["stale"] is False
    state["down"] = True
    c.app.state.cache_search._clock = lambda: 1e12  # expire the entry
    body = c.get("/markets/search", params={"q": "fed"}).json()
    assert body["stale"] is True and len(body["markets"]) == 3
    assert c.get("/markets/search", params={"q": "never-seen"}).status_code == 502


def test_history():
    r = make_client(ok_handler).get("/markets/polymarket/tokYES/history")
    assert r.json() == [{"t": 1, "p": 0.1}, {"t": 2, "p": 0.2}]


def test_ttlcache_stale_and_raise():
    t = {"now": 0.0}
    cache = TTLCache(10, clock=lambda: t["now"])

    async def good():
        return "v"

    async def bad():
        raise RuntimeError

    async def run():
        assert await cache.get_or_set("k", good) == ("v", False)
        assert await cache.get_or_set("k", bad) == ("v", False)  # fresh, no fetch
        t["now"] = 100
        assert await cache.get_or_set("k", bad) == ("v", True)
        with pytest.raises(RuntimeError):
            await cache.get_or_set("other", bad)
    asyncio.run(run())


def test_both_sources_raising_falls_back_to_bundled_list():
    def h(req):
        raise httpx.ConnectError("offline", request=req)
    c = make_client(h)
    body = c.get("/markets/search", params={"q": "FED increase 25 BPS october"}).json()
    assert body["stale"] is True and body["note"] == "offline: cached market list"
    ids = [m["id"] for m in body["markets"]]
    assert "2589813" in ids  # the Fed October 25 bps hike market, from market_universe.json / ai_map.json
    assert all("fed" in m["question"].lower() for m in body["markets"])
    assert c.get("/markets/search", params={"q": "zzqx-never-seen"}).status_code == 502
