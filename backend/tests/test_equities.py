import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from .conftest import research_fakes as rf

FIX = Path(__file__).parent / "fixtures" / "results"
TODAY = "2026-10-05"


class StubClient(rf.FakeClient):

    def __init__(self, rows=None, market=None, quote=None):
        super().__init__(market=market)
        self.rows, self.quote = rows or [], quote

    def get_all(self, path, params=None, max_pages=500):
        if path == "/stocks/filings/8-K/vX/disclosures" and "tickers" in (params or {}):
            self.calls.append((path, params))
            return list(self.rows)
        return super().get_all(path, params, max_pages)

    def get(self, path, params=None):
        if path.startswith("/v3/quotes/") and self.quote is not None:
            return {"results": [{"bid_price": self.quote[0], "ask_price": self.quote[1]}]}
        return super().get(path, params)


def row(acc, tag, date="2026-09-01", ticker="AAA"):
    return {**rf.disclosure(acc, "1", [ticker], date), "tertiary_category": tag}


def mk_handler(fail=False):
    def h(req: httpx.Request):
        if fail:
            return httpx.Response(500)
        if req.url.host == "gamma-api.polymarket.com":
            q = req.url.params["q"]
            return httpx.Response(200, json={"events": [{"slug": q, "markets": [{
                "id": q, "question": f"{q} q", "outcomePrices": json.dumps(["0.4", "0.6"]), "volume24hr": 10}]}]})
        return httpx.Response(200, json={"events": []})
    return h


def make(massive, monkeypatch, http_fail=False):
    monkeypatch.setenv("RESULTS_DIR", str(FIX))
    app = create_app()
    app.state.massive = massive
    app.state.today = TODAY
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(mk_handler(http_fail)))
    return TestClient(app)


def test_card_with_move_filings_and_markets(monkeypatch):
    other = [row("o1", "Results of Operations", ticker="BBB"), {k: v for k, v in row("o2", "X").items() if k != "tickers"}]
    client = StubClient(other + [row("a1", "Entry into Material Agreement"), row("a1", "Results of Operations"), row("a2", "X", "2026-08-01")],
                        market=rf.FakeMarket({"AAA": 100.0}))
    d = make(client, monkeypatch).get("/equities/aaa").json()
    assert d["ticker"] == "AAA"
    assert d["implied_move"]["spot"] == pytest.approx(100.0, rel=2e-3)
    assert d["implied_move"]["value"] == pytest.approx(0.02, rel=5e-3)
    assert d["implied_move"]["as_of"] == "2026-10-02"
    assert len(d["filings"]) == 2 and d["filings"][0]["date"] == "2026-09-01"
    assert sorted(d["filings"][0]["tags"]) == ["Entry into Material Agreement", "Results of Operations"]
    assert d["filings"][0]["verdict"]["label"] in {"hedge", "opportunity", "no_edge"}
    assert {m["source"] for m in d["markets"]} == {"polymarket"} and d["notes"] == []


def test_name_used_for_market_search(monkeypatch):
    c = make(StubClient(market=rf.FakeMarket({"AAPL": 100.0})), monkeypatch)
    assert {m["id"] for m in c.get("/equities/AAPL").json()["markets"]} == {"Apple", "AAPL"}


def test_no_options_and_no_filings(monkeypatch):
    c = make(StubClient(market=None), monkeypatch)
    d = c.get("/equities/ZZZ").json()
    assert d["implied_move"] is None and d["filings"] == []
    assert "no listed options" in d["notes"] and "no 8-K filings in the last 180 days" in d["notes"]


def test_missing_key_never_500(monkeypatch):
    d = make(None, monkeypatch).get("/equities/AAPL").json()
    assert d["implied_move"] is None and "Massive key not configured" in d["notes"]
    assert d["markets"]


def test_markets_down_is_a_note(monkeypatch):
    c = make(StubClient(market=rf.FakeMarket({"AAA": 100.0})), monkeypatch, http_fail=True)
    r = c.get("/equities/AAA")
    assert r.status_code == 200 and "prediction-market search unavailable" in r.json()["notes"]
    assert r.json()["implied_move"] is not None


def test_stale_option_prices_note_and_no_accession(monkeypatch):
    nr = {k: v for k, v in row("zz", "X").items() if k != "accession_number"}
    c = make(StubClient([nr], market=rf.FakeMarket({"AAA": 100.0}, end="2026-09-30")), monkeypatch)
    d = c.get("/equities/AAA").json()
    assert d["implied_move"] is not None and any("option prices from 2026-09-30" in n for n in d["notes"])
    assert d["filings"][0]["accession"] is None
    c = make(StubClient(market=rf.FakeMarket({"AAA": 100.0}, end="2026-09-25")), monkeypatch)
    assert c.get("/equities/AAA").json()["implied_move"] is None


class SlowClient(StubClient):

    def get(self, path, params=None):
        import time
        time.sleep(0.3)
        return super().get(path, params)

    def get_all(self, path, params=None, max_pages=500):
        import time
        time.sleep(0.3)
        return super().get_all(path, params, max_pages)


def test_slow_massive_degrades_within_bound(monkeypatch):
    import time
    from app import chain
    monkeypatch.setattr(chain, "CALL_TIMEOUT_S", 0.2)
    with make(SlowClient(market=rf.FakeMarket({"AAA": 100.0})), monkeypatch) as c:
        t0 = time.monotonic()
        eqr = c.get("/equities/AAA")
        hr = c.get("/hedges/AAA")
        pr = c.get("/portfolio")
        assert time.monotonic() - t0 < 3.0
    assert eqr.status_code == 200 and eqr.json()["implied_move"] is None
    assert "options data unavailable" in eqr.json()["notes"]
    assert hr.status_code == 200 and hr.json()["notes"] == ["options data unavailable"]
    assert pr.status_code == 200 and all("options data unavailable" in h["notes"] for h in pr.json()["holdings"])


def test_api_massive_client_is_bounded(monkeypatch, tmp_path):
    from app import chain
    monkeypatch.setattr(chain, "load_api_key", lambda interactive=False: "k")
    monkeypatch.setattr(chain, "CACHE_DIR", tmp_path)
    cl = chain.make_client()
    assert cl._max_attempts == 2 and isinstance(cl.session, chain._BoundedSession)
    seen = {}

    def fake_get(self, url, **kw):
        seen.update(kw)
        raise RuntimeError("stop")
    monkeypatch.setattr(chain.requests.Session, "get", fake_get)
    with pytest.raises(RuntimeError):
        cl.session.get("http://x", timeout=60)
    assert seen["timeout"] <= 6
