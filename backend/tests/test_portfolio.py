import json

import pytest

from app import mapping, portfolio
from .conftest import research_fakes as rf
from .test_equities import StubClient, make


def test_remaining_exposure_math_and_empty_cases():
    assert portfolio.remaining_exposure(10, 100, 2, 0.4) == pytest.approx(12.0)
    assert portfolio.remaining_exposure(10, 100, -2, 1.0) == 0.0
    assert portfolio.remaining_exposure(10, None, 2, 0.4) is None
    assert portfolio.remaining_exposure(10, 100, 2, None) is None
    assert portfolio.remaining_exposure(0, 100, 2, 0.4) is None
    assert portfolio.remaining_exposure(10, 100, float("nan"), 0.4) is None


def setup(tmp_path, monkeypatch, holdings, lib=None):
    pf = tmp_path / "pf.json"
    pf.write_text(json.dumps({"holdings": holdings}))
    monkeypatch.setattr(portfolio, "PORTFOLIO_PATH", pf)
    ml = tmp_path / "map.json"
    ml.write_text(json.dumps(lib or {"items": {}}))
    monkeypatch.setattr(mapping, "MAP_PATH", ml)


def test_exposure_when_mapping_exists(tmp_path, monkeypatch):
    lib = {"items": {"polymarket:Apple": {"question": "Apple q", "mappings": [
        {"ticker": "AAPL", "direction": "down_on_yes", "impact_pct": 2.0, "rationale": "r"}]}}}
    setup(tmp_path, monkeypatch, [{"ticker": "AAPL", "shares": 10}], lib)
    c = make(StubClient(market=rf.FakeMarket({"AAPL": 100.0})), monkeypatch)
    d = c.get("/portfolio").json()
    h = d["holdings"][0]
    assert h["ticker"] == "AAPL" and h["hedge"]["status"] == "none"
    assert h["exposure"]["remaining_usd"] == pytest.approx(12.0, rel=5e-3)
    assert h["exposure"]["label"] == "AI estimate (precomputed)" and h["exposure"]["match_type"] == "exact"
    assert d["total_exposure"] == pytest.approx(h["exposure"]["remaining_usd"])


def test_no_mapping_and_hedge_status(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, [{"ticker": "AAPL", "shares": 10}])
    c = make(StubClient(market=rf.FakeMarket({"AAPL": 100.0})), monkeypatch)
    p = c.post("/proposals", json={"ticker": "AAPL", "tags": ["Results of Operations"], "shares_held": 10})
    if p.status_code == 201:
        pid = p.json()["id"]
        assert c.get("/portfolio").json()["holdings"][0]["hedge"] == {"status": "proposed", "proposal_id": pid, "bridge_id": None}
        c.post(f"/proposals/{pid}/approve")
        assert c.get("/portfolio").json()["holdings"][0]["hedge"]["status"] == "approved"
    d = c.get("/portfolio").json()
    assert d["holdings"][0]["exposure"] is None and d["total_exposure"] is None


def test_sources_failing_never_500(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, [{"ticker": "AAPL", "shares": 10}, {"ticker": "ZZZ", "shares": 5}])
    r = make(None, monkeypatch, http_fail=True).get("/portfolio")
    assert r.status_code == 200
    hs = r.json()["holdings"]
    assert len(hs) == 2 and all(h["exposure"] is None for h in hs)
    assert "prediction-market search unavailable" in hs[0]["notes"] and "Massive key not configured" in hs[0]["notes"]


def test_empty_portfolio(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, [])
    d = make(None, monkeypatch).get("/portfolio").json()
    assert d["holdings"] == [] and d["total_value"] is None
