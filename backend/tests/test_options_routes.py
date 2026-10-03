"""/options/implied, /options/chain, /options/eightk with mocked Massive and mocked market lookups. Offline."""
import datetime as dt
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cache import TTLCache
from app.main import create_app
from app.options import chain as ch
from app.options import eightk as ek
from app.options import router as rt

TARGET = dt.date.today() + dt.timedelta(days=60)


def crow(kind, strike, mid, expiry=None, bid=None, ask=None, spot=None):
    r = {"details": {"contract_type": kind, "strike_price": strike, "expiration_date": (expiry or TARGET).isoformat(),
                     "ticker": f"O:T{kind[0]}{strike}"},
         "greeks": {"delta": 0.5 if kind == "call" else -0.5}, "implied_volatility": 0.3, "fmv": mid,
         "fmv_last_updated": 1_790_970_000_000_000_000,
         "underlying_asset": {"timeframe": "DELAYED", **({"price": spot} if spot else {})}}
    if bid is not None:
        r["last_quote"] = {"bid": bid, "ask": ask, "last_updated": 1_790_970_000_000_000_000}
    return r


NVDA_ROWS = [crow("call", 145.0, 8.0, bid=7.9, ask=8.1, spot=150.0), crow("call", 150.0, 5.0, bid=4.9, ask=5.1),
             crow("call", 155.0, 3.0, bid=2.9, ask=3.1), crow("put", 145.0, 2.0), crow("put", 155.0, 6.5)]
SPY_ROWS = [crow("call", 595.0, 12.0), crow("call", 605.0, 7.0)]


class _Resp:
    def __init__(self, p, status=200):
        self.p, self.status_code = p, status

    def json(self):
        return self.p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class FakeMassive:
    def __init__(self, books: dict[str, list], fail=False):
        self.books, self.fail, self.calls = books, fail, []
        self.session = self

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.fail:
            raise TimeoutError("stalled")
        und = url.rsplit("/", 1)[-1]
        return _Resp({"results": self.books.get(und, [])})


@pytest.fixture
def make(monkeypatch):
    def _make(massive=None, http_handler=None):
        monkeypatch.setattr(ch, "_CACHE", TTLCache(60))
        monkeypatch.setattr(ch, "_LAST", {})
        monkeypatch.setattr(ch, "_FOR", {})
        monkeypatch.setattr(ek, "_LIVE", {})
        monkeypatch.setattr(rt, "make_client", lambda: massive)
        app = create_app()
        handler = http_handler or (lambda req: httpx.Response(404, json={}))
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return TestClient(app)
    return _make


def q_nvda(level=150):
    return f"Will NVDA close above ${level} on {TARGET.isoformat()}?"


def test_implied_from_question_with_call_spread_and_bounds(make):
    c = make(FakeMassive({"NVDA": NVDA_ROWS}))
    r = c.get("/options/implied", params={"question": q_nvda()})
    assert r.status_code == 200
    j = r.json()
    assert j["supported"] and j["available"] and j["underlying_used"] == "NVDA" and j["strike_used"] == 150.0
    e = j["estimate"]
    T = 60 / 365
    assert e["method"] == "call_spread" and e["expiry"] == TARGET.isoformat() and e["expiry_gap_days"] == 0
    assert e["prob"] == pytest.approx(0.5 / math.exp(-0.04 * T))
    assert e["lo"] == pytest.approx(0.48 / math.exp(-0.04 * T)) and e["hi"] == pytest.approx(0.52 / math.exp(-0.04 * T))
    assert e["structure_mid"] == pytest.approx(5.0)
    assert j["spot"] == 150.0 and j["label"].startswith("options-implied")
    fr = j["freshness"]
    assert fr["source"] == "massive_snapshot" and fr["timeframe"] == "DELAYED" and set(fr["mark_sources"]) == {"quote", "fmv"}
    assert "staleness" in fr and "data_age_s" in fr
    json.dumps(j, allow_nan=False)


def test_implied_resolves_polymarket_market_and_reports_gap(make):
    def handler(req: httpx.Request):
        assert req.url.host == "gamma-api.polymarket.com" and req.url.path == "/markets/777"
        return httpx.Response(200, json={"question": q_nvda(), "endDate": f"{TARGET.isoformat()}T20:00:00Z",
                                         "outcomePrices": "[\"0.62\", \"0.38\"]"})
    c = make(FakeMassive({"NVDA": NVDA_ROWS}), handler)
    j = c.get("/options/implied", params={"market_source": "polymarket", "market_id": "777"}).json()
    assert j["market"]["origin"] == "live" and j["market"]["yes_price"] == 0.62
    assert j["pm_minus_option"] == pytest.approx(0.62 - j["estimate"]["prob"])


def test_implied_resolves_kalshi_market(make):
    def handler(req):
        assert req.url.path.endswith("/markets/KXNVDA-26")
        return httpx.Response(200, json={"market": {"title": f"Will NVDA be below $150 on {TARGET.isoformat()}?",
                                                    "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44"}})
    c = make(FakeMassive({"NVDA": NVDA_ROWS}), handler)
    j = c.get("/options/implied", params={"market_source": "kalshi", "market_id": "KXNVDA-26"}).json()
    assert j["match"]["direction"] == "below" and j["market"]["yes_price"] == pytest.approx(0.42)
    assert j["estimate"]["prob"] == pytest.approx(1 - 0.5 / math.exp(-0.04 * 60 / 365))
    assert j["estimate"]["structure_mid"] == pytest.approx(4.5)   # put spread P(155) - P(145)


def test_unsupported_question_is_200_with_reason(make):
    c = make(FakeMassive({}))
    j = c.get("/options/implied", params={"question": "Will NVDA hit $300 by December 31?"}).json()
    assert j["supported"] is False and j["available"] is False and "path question" in j["reason"]


def test_market_not_found_is_200(make):
    c = make(FakeMassive({}))
    j = c.get("/options/implied", params={"market_source": "polymarket", "market_id": "nope"}).json()
    assert j["supported"] is False and "not found" in j["reason"]


def test_no_key_degrades_gracefully(make):
    c = make(None)
    j = c.get("/options/implied", params={"question": q_nvda()}).json()
    assert j["supported"] and not j["available"] and j["reason"] == "MASSIVE_API_KEY not set"
    assert j["match"]["underlying"] == "NVDA"
    j = c.get("/options/chain", params={"ticker": "NVDA"}).json()
    assert j["available"] is False and j["reason"] == "MASSIVE_API_KEY not set"


def test_massive_outage_degrades_gracefully(make):
    c = make(FakeMassive({}, fail=True))
    r = c.get("/options/implied", params={"question": q_nvda()})
    assert r.status_code == 200 and r.json()["available"] is False
    r = c.get("/options/chain", params={"ticker": "NVDA"})
    assert r.status_code == 200 and r.json()["available"] is False and "Massive unavailable" in r.json()["reason"]


def test_spx_falls_back_to_spy_with_scaled_strike(make):
    m = FakeMassive({"I:SPX": [], "SPY": SPY_ROWS})
    c = make(m)
    j = c.get("/options/implied", params={"question": f"S&P 500 above 6000 on {TARGET.isoformat()}"}).json()
    assert j["available"] and j["underlying_used"] == "SPY" and j["strike_used"] == 600.0 and j["approx"]
    assert any("proxy SPY" in n for n in j["notes"])
    assert j["estimate"]["prob"] == pytest.approx(0.5 / math.exp(-0.04 * 60 / 365))


def test_threshold_outside_listed_strikes_is_unavailable_with_reason(make):
    c = make(FakeMassive({"NVDA": NVDA_ROWS}))
    j = c.get("/options/implied", params={"question": q_nvda(152)}).json()
    assert j["available"]  # 152 sits between 150 and 155
    j = c.get("/options/implied", params={"question": q_nvda(158)}).json()
    assert j["available"] is False and "outside the listed strikes" in j["reason"]


def test_implied_validation(make):
    c = make(FakeMassive({}))
    assert c.get("/options/implied").status_code == 422
    assert c.get("/options/implied", params={"market_source": "nyse", "market_id": "1"}).status_code == 422


def test_chain_route_groups_by_expiry_and_strike(make):
    m = FakeMassive({"NVDA": NVDA_ROWS})
    c = make(m)
    j = c.get("/options/chain", params={"ticker": "nvda", "strike_min": 140, "strike_max": 160}).json()
    assert j["available"] and j["ticker"] == "NVDA" and j["n_contracts"] == 5 and j["spot"] == 150.0
    (e,) = j["expiries"]
    assert e["expiry"] == TARGET.isoformat()
    s145 = e["strikes"][0]
    assert s145["strike"] == 145.0 and s145["call"]["bid"] == 7.9 and s145["call"]["mark_source"] == "quote"
    assert s145["put"]["bid"] is None and s145["put"]["mark_source"] == "fmv"
    assert e["strikes"][1]["put"] is None
    params = m.calls[0][1]
    assert params["strike_price.gte"] == 140 and params["expiration_date.gte"] == dt.date.today().isoformat()
    assert j["freshness"]["source"] == "massive_snapshot"
    json.dumps(j, allow_nan=False)


def test_chain_route_validation(make):
    c = make(FakeMassive({}))
    assert c.get("/options/chain", params={"ticker": "not a ticker"}).status_code == 422
    assert c.get("/options/chain", params={"ticker": "NVDA", "expiry_from": "bad"}).status_code == 422
    assert c.get("/options/chain", params={"ticker": "NVDA", "expiry_from": "2026-12-01",
                                           "expiry_to": "2026-11-01"}).status_code == 422
    j = c.get("/options/chain", params={"ticker": "I:SPX"}).json()
    assert j["available"] is False and j["reason"] == "no listed contracts in window"


def test_eightk_route_bundled_and_live(make, monkeypatch):
    monkeypatch.setattr(ek, "_FILE_CACHE", [{"ticker": "XYZ", "filing_date": "2025-06-20", "tags": ["material_litigation"]}])
    c = make(None)
    j = c.get("/options/eightk", params={"ticker": "xyz", "as_of": "2025-06-30"}).json()
    assert j["score"] == pytest.approx(-(1 - 10 / 30)) and j["filing"]["family"] == "hedge"
    assert "not a measured edge" in j["label"] and "live" not in j["source"]

    class Live:
        def get_all(self, path, params):
            assert params["filing_date.gte"] >= "2026-09-01"
            if params["tertiary_category"] == "facility_closure":
                return [{"tickers": ["XYZ"], "accession_number": "1", "filing_date": "2026-09-30"}]
            return []
    c = make(Live())
    j = c.get("/options/eightk", params={"ticker": "XYZ", "as_of": "2026-10-03"}).json()
    assert j["score"] == pytest.approx(1 - 3 / 30) and "live Massive" in j["source"] and j["coverage"] == "live"
    j = make(None).get("/options/eightk", params={"ticker": "XYZ", "as_of": "2026-05-01"}).json()   # OOS window
    assert j["available"] is False and j["score"] is None and j["coverage"] is None
    assert c.get("/options/eightk", params={"ticker": "XYZ", "window_days": 0}).status_code == 422
    assert c.get("/options/eightk", params={"ticker": "XYZ", "as_of": "x"}).status_code == 422


def test_implied_kalshi_threshold_in_subtitle(make):
    """Realistic Kalshi payload: the level lives in yes_sub_title, close_time is UTC (Dec 31 11:59 PM ET)."""
    exp = dt.date(TARGET.year, TARGET.month, TARGET.day)
    title = f"Nvidia price on {exp.strftime('%b')} {exp.day}?"
    close = dt.datetime.combine(exp + dt.timedelta(days=1), dt.time(4, 59)).isoformat() + "Z"

    def handler(req):
        return httpx.Response(200, json={"market": {"ticker": "KXNVDA-X", "title": title,
                                                    "yes_sub_title": "$150 or above", "subtitle": "",
                                                    "close_time": close, "yes_bid_dollars": "0.50",
                                                    "yes_ask_dollars": "0.54"}})
    c = make(FakeMassive({"NVDA": NVDA_ROWS}), handler)
    j = c.get("/options/implied", params={"market_source": "kalshi", "market_id": "KXNVDA-X"}).json()
    assert j["market"]["question"] == f"{title} $150 or above"
    assert j["supported"] and j["available"] and j["match"]["strike"] == 150.0
    assert j["match"]["expiry"] == exp.isoformat() and j["estimate"]["expiry_gap_days"] == 0


def test_kalshi_range_subtitle_is_refused(make):
    def handler(req):
        return httpx.Response(200, json={"market": {"title": f"Nvidia price on {TARGET.isoformat()}?",
                                                    "yes_sub_title": "$140 to $149.99"}})
    c = make(FakeMassive({"NVDA": NVDA_ROWS}), handler)
    j = c.get("/options/implied", params={"market_source": "kalshi", "market_id": "R"}).json()
    assert j["supported"] is False and "range" in j["reason"]


def test_implied_unavailable_when_nearest_expiry_is_a_different_date(make):
    far = TARGET + dt.timedelta(days=40)
    rows = [crow("call", 145.0, 8.0, expiry=far), crow("call", 155.0, 3.0, expiry=far)]
    c = make(FakeMassive({"NVDA": rows}))
    j = c.get("/options/implied", params={"question": q_nvda()}).json()
    assert j["supported"] and j["available"] is False
    assert j["estimate"]["expiry_gap_ok"] is False and "different date" in j["reason"]


def test_truncated_chain_is_labelled(make):
    class Paging(FakeMassive):
        def get(self, url, params=None, timeout=None):
            r = super().get(url.split("?")[0] if "next" not in url else "x/NVDA", params, timeout)
            r.p["next_url"] = "https://api.massive.com/next"
            return r
    c = make(Paging({"NVDA": NVDA_ROWS}))
    j = c.get("/options/chain", params={"ticker": "NVDA"}).json()
    assert j["freshness"]["truncated"] is True
