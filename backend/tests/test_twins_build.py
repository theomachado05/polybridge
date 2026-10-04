from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.twins import build, sources
from app.twins.build import build_map

run = asyncio.run


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def instant(_):
        return None
    monkeypatch.setattr(sources.asyncio, "sleep", instant)


def gamma_market(id_, question, end="2026-12-31T16:59:00Z", desc="", tokens=True, **kw):
    m = {"id": id_, "question": question, "description": desc, "endDate": end, "active": True, "closed": False,
         "clobTokenIds": json.dumps([f"tokYES{id_}", f"tokNO{id_}"]) if tokens else "[]", "slug": f"s{id_}",
         "events": [{"slug": f"ev{id_}"}], "volume24hr": 10}
    m.update(kw)
    return m


def kalshi_market(ticker, title, close="2027-01-01T04:59:00Z", rules="", **kw):
    m = {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "title": title, "yes_sub_title": "",
         "rules_primary": rules, "rules_secondary": "", "close_time": close, "market_type": "binary",
         "status": "active"}
    m.update(kw)
    return m


class Venues:

    def __init__(self, poly_top, poly_by_id, search, kalshi_pages, fail_kalshi_first=0):
        self.poly_top, self.poly_by_id, self.search = poly_top, poly_by_id, search
        self.kalshi_pages, self.fail_first, self.requests = kalshi_pages, fail_kalshi_first, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        q = req.url.params
        if req.url.host == "gamma-api.polymarket.com" and req.url.path == "/markets":
            if q.get_list("id"):
                return httpx.Response(200, json=[m for m in self.poly_by_id if m["id"] in q.get_list("id")])
            off = int(q.get("offset", 0))
            if off >= len(self.poly_top) or off >= 200:
                return httpx.Response(422, json={"error": "offset"}) if off >= 200 else httpx.Response(200, json=[])
            return httpx.Response(200, json=self.poly_top[off: off + int(q["limit"])])
        if req.url.host == "gamma-api.polymarket.com" and req.url.path == "/public-search":
            return httpx.Response(200, json={"events": self.search.get(q["q"], [])})
        if req.url.host == "api.elections.kalshi.com" and req.url.path == "/trade-api/v2/events":
            if self.fail_first > 0:
                self.fail_first -= 1
                return httpx.Response(429, json={"error": "too_many_requests"})
            page = int(q.get("cursor", "0"))
            body = {"events": self.kalshi_pages[page]}
            if page + 1 < len(self.kalshi_pages):
                body["cursor"] = str(page + 1)
            return httpx.Response(200, json=body)
        return httpx.Response(404)


def client(v: Venues) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(v))


def event(category, *markets, title="ev"):
    return {"title": title, "category": category, "markets": list(markets)}


def test_fetch_polymarket_ids_top_search_dedup_and_filters():
    keep = gamma_market("1", "Will Discord IPO by October 31, 2026?")
    dead = gamma_market("2", "closed one", closed=True)
    no_tok = gamma_market("3", "no token", tokens=False)
    searched = gamma_market("4", "Will OpenAI IPO by March 31 2027?")
    v = Venues(poly_top=[keep, dead, no_tok, gamma_market("5", "Top five")], poly_by_id=[keep],
               search={"recession": [{"slug": "x", "markets": [searched, keep]}]}, kalshi_pages=[[]])
    out = run(sources.fetch_polymarket(client(v), ids=["1"], top_n=300, page=2, search_terms=("recession",)))
    ids = sorted(m["id"] for m in out)
    assert ids == ["1", "4", "5"]
    m = next(m for m in out if m["id"] == "1")
    assert m["token_id"] == "tokYES1" and m["event_slug"] == "ev1"
    assert any(r.url.params.get("offset") for r in v.requests)


def test_fetch_kalshi_paginates_skips_sports_and_retries_429():
    pages = [[event("Economics", kalshi_market("KXA-1", "A?")), event("Sports", kalshi_market("KXNFL-1", "Game?"))],
             [event("Politics", kalshi_market("KXB-1", "B?"), kalshi_market("KXB-2", "B2?", market_type="scalar"))]]
    v = Venues([], [], {}, pages, fail_kalshi_first=2)
    out = run(sources.fetch_kalshi(client(v), pause_s=0))
    assert [m["ticker"] for m in out] == ["KXA-1", "KXB-1"]
    assert out[0]["category"] == "Economics" and out[0]["event_title"] == "ev"
    assert len([r for r in v.requests if r.url.path.endswith("/events")]) == 4
    assert "category" not in v.requests[0].url.params


def test_fetch_kalshi_keeps_what_it_has_when_a_later_page_keeps_failing(monkeypatch):
    pages = [[event("Economics", kalshi_market("KXA-1", "A?"))], [event("Economics", kalshi_market("KXA-2", "A2?"))]]
    v = Venues([], [], {}, pages)
    real = v.__call__
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return real(req) if calls["n"] == 1 else httpx.Response(503)
    out = run(sources.fetch_kalshi(httpx.AsyncClient(transport=httpx.MockTransport(flaky)), pause_s=0))
    assert [m["ticker"] for m in out] == ["KXA-1"]


POLY = [
    gamma_market("1", "Will Discord IPO by October 31, 2026?", end="2026-11-01T03:59:00Z",
                 desc='Resolves to "Yes" if Discord shares are listed on a public securities exchange.'),
    gamma_market("2", "Will the price of Bitcoin be above $100,000 on December 31?", end="2027-01-01T04:59:00Z",
                 desc="Per Binance."),
    gamma_market("3", "Will the Fed decrease interest rates by 25 bps after the October 2026 meeting?",
                 end="2026-10-29T03:59:00Z", desc="Upper bound of the target range per the FOMC statement."),
]
KAL = [
    kalshi_market("KXIPODISCORD-26NOV01", "When will Discord IPO?", close="2026-11-01T04:59:00Z",
                  rules="If Discord confirms an IPO before Nov 1, 2026, then the market resolves to Yes.",
                  yes_sub_title="Before Nov 1, 2026"),
    kalshi_market("KXBTC-100", "Will the price of Bitcoin be above $100,000 on December 31?", close="2027-01-01T04:59:00Z",
                  rules="Per CF Benchmarks."),
    kalshi_market("KXFEDDECISION-26OCT-H25", "Will the Federal Reserve Hike rates by 25bps at their October 2026 meeting?",
                  close="2026-10-28T18:00:00Z", rules="If the Federal Reserve does a Hike of 25bps, Yes.",
                  yes_sub_title="Hike 25bps"),
]


def slim_poly(ms):
    return [sources.slim_polymarket(m) for m in ms]


def slim_kal(ms):
    return [sources.slim_kalshi_market(m, {"title": "ev", "category": "Economics"}) for m in ms]


def test_build_map_only_verified_pairs_are_in_pairs_with_notes_and_ids():
    doc = build_map(slim_poly(POLY), slim_kal(KAL), verified_at="2026-10-03T00:00:00Z")
    assert doc["schema"] == 1 and doc["generated_at"] == "2026-10-03T00:00:00Z"
    assert [e["kalshi"]["ticker"] for e in doc["pairs"]] == ["KXIPODISCORD-26NOV01"]
    e = doc["pairs"][0]
    assert e["polymarket"]["id"] == "1" and e["polymarket"]["token_id"] == "tokYES1"
    assert e["direction"] == "same" and e["verification"]["verified_at"] == "2026-10-03T00:00:00Z"
    assert "deadline" in e["verification"]["note"] and e["verification"]["checks"]["deadline"]["ok"] is True
    amb = {a["kalshi"]["ticker"]: a for a in doc["ambiguous"]}
    assert set(amb) == {"KXBTC-100", "KXFEDDECISION-26OCT-H25"}
    assert "source" in amb["KXBTC-100"]["reasons"] and "direction_inverted" in amb["KXFEDDECISION-26OCT-H25"]["reasons"]
    assert all(a["used"] is False for a in doc["ambiguous"])
    assert doc["stats"]["verified"] == 1 and doc["stats"]["ambiguous"] == 2
    assert not any(a["kalshi"]["ticker"] in {p["kalshi"]["ticker"] for p in doc["pairs"]} for a in doc["ambiguous"])


def test_run_refuses_when_a_venue_is_empty():
    v = Venues([], [], {}, [[]])
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        run(build.run(client(v), top_n=100, log=lambda s: None))


def test_run_end_to_end_with_mocked_venues():
    v = Venues(poly_top=POLY, poly_by_id=[], search={},
               kalshi_pages=[[event("Economics", *KAL)]])
    doc = run(build.run(client(v), top_n=100, log=lambda s: None, verified_at="2026-10-03T00:00:00Z"))
    assert [e["kalshi"]["ticker"] for e in doc["pairs"]] == ["KXIPODISCORD-26NOV01"]
    assert doc["stats"]["polymarket_markets"] == 3 and doc["stats"]["kalshi_markets"] == 3
