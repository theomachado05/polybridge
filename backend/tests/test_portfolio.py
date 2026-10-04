import json

import pytest

from app import mapping, portfolio
from .conftest import research_fakes as rf
from .test_equities import StubClient, make


def test_remaining_exposure_math_and_empty_cases():
    assert portfolio.remaining_exposure(10, 100, 2, 0.4) == pytest.approx(12.0)
    assert portfolio.remaining_exposure(10, 100, -2, 1.0) == 0.0
    assert portfolio.remaining_exposure(10, 100, 2, 0.4, "up_on_yes") == pytest.approx(8.0)
    assert portfolio.remaining_exposure(10, 100, 2, 0.4, "sideways") is None
    assert portfolio.remaining_exposure(10, 100, 2, 0.4, None) is None
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
    p = c.post("/proposals", json={"ticker": "AAPL", "tags": ["material_litigation"], "shares_held": 10})
    assert p.status_code == 201
    pid = p.json()["id"]
    assert c.get("/portfolio").json()["holdings"][0]["hedge"] == {"status": "proposed", "proposal_id": pid, "bridge_id": None}
    c.post(f"/proposals/{pid}/approve", json={"ack_unvalidated": True})
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


def test_exposure_up_on_yes(tmp_path, monkeypatch):
    lib = {"items": {"polymarket:Apple": {"question": "Apple q", "mappings": [
        {"ticker": "AAPL", "direction": "up_on_yes", "impact_pct": 2.0, "rationale": "r"}]}}}
    setup(tmp_path, monkeypatch, [{"ticker": "AAPL", "shares": 10}], lib)
    c = make(StubClient(market=rf.FakeMarket({"AAPL": 100.0})), monkeypatch)
    h = c.get("/portfolio").json()["holdings"][0]
    assert h["exposure"]["remaining_usd"] == pytest.approx(8.0, rel=5e-3) and h["exposure"]["direction"] == "up_on_yes"


def test_seeded_portfolio_shows_fed_exposure_offline(monkeypatch):
    c = make(StubClient(market=rf.FakeMarket({"IWM": 200.0})), monkeypatch, http_fail=True)
    d = c.get("/portfolio").json()
    iwm = next(h for h in d["holdings"] if h["ticker"] == "IWM")
    assert iwm["shares"] == 400
    ex = iwm["exposure"]
    assert ex["market"]["id"] == "2589813" and ex["direction"] == "down_on_yes" and ex["impact_pct"] == 3.0
    assert ex["match_type"] == "exact"
    assert ex["remaining_usd"] == pytest.approx(400 * 200 * 0.03 * (1 - 0.175), rel=5e-3)
    assert d["stale"] is True and d["total_includes_fuzzy"] is False


def test_seeded_portfolio_pins_the_demo_market_offline(monkeypatch):
    c = make(StubClient(market=rf.FakeMarket({"TLT": 80.0})), monkeypatch, http_fail=True)
    d = c.get("/portfolio").json()
    tlt = next(h for h in d["holdings"] if h["ticker"] == "TLT")
    assert tlt["shares"] == 1000
    ex = tlt["exposure"]
    assert ex["market"]["id"] == "4620900" and ex["direction"] == "down_on_yes" and ex["impact_pct"] == 2.5


def test_total_flags_fuzzy_mappings(tmp_path, monkeypatch):
    lib = {"items": {"polymarket:Apple": {"question": "Apple q", "mappings": [
        {"ticker": "AAPL", "direction": "down_on_yes", "impact_pct": 2.0, "rationale": "r"}]}}}
    setup(tmp_path, monkeypatch, [{"ticker": "AAPL", "shares": 10}], lib)
    real = portfolio.lookup_precomputed
    monkeypatch.setattr(portfolio, "lookup_precomputed", lambda req: {**real(req), "match_type": "fuzzy"})
    d = make(StubClient(market=rf.FakeMarket({"AAPL": 100.0})), monkeypatch).get("/portfolio").json()
    assert d["total_includes_fuzzy"] is True
