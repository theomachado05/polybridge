import json

import pytest
from fastapi.testclient import TestClient

from app import mapping
from app.main import create_app

FIX = {
    "generated_at": "2026-01-01T00:00:00",
    "items": {
        "polymarket:1": {
            "question": "Will Indiana enact a data center moratorium by December 31, 2027?",
            "mappings": [{"ticker": "VRT", "direction": "down_on_yes", "impact_pct": 1.6, "rationale": "x"}],
        },
        "kalshi:K1": {"question": "Will the Fed cut rates in December?", "mappings": []},
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(FIX))
    monkeypatch.setattr(mapping, "MAP_PATH", p)
    monkeypatch.setattr(mapping, "_cache", None)
    yield TestClient(create_app())


def test_exact(client):
    r = client.post("/map", json={"source": "polymarket", "market_id": "1"}).json()
    assert r["source"] == "ai_precomputed" and r["items"][0]["ticker"] == "VRT"
    assert r["label"] == "AI estimate (precomputed)" and r["generated_at"] == FIX["generated_at"]
    assert r["ai"]["provider"] == "precomputed" and r["ai"]["live"] is False


def test_fuzzy(client):
    r = client.post("/map", json={"question": "Indiana enact data center moratorium 2027?"}).json()
    assert r["source"] == "ai_precomputed" and r["match_type"] == "fuzzy" and r["score"] >= 0.5
    assert r["matched_question"].startswith("Will Indiana")


def _lib(tmp_path, monkeypatch, items):
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"items": items}))
    monkeypatch.setattr(mapping, "MAP_PATH", p)
    monkeypatch.setattr(mapping, "_cache", None)
    return TestClient(create_app())


@pytest.mark.parametrize("q", ["fed", "bitcoin"])
def test_short_queries_none(client, q):
    assert client.post("/map", json={"question": q}).json()["source"] == "none"


def test_opposite_direction_none(tmp_path, monkeypatch):
    c = _lib(tmp_path, monkeypatch, {"k:1": {"question": "Will the Fed increase rates in December?", "mappings": []}})
    assert c.post("/map", json={"question": "Will the Fed cut rates in December?"}).json()["source"] == "none"


def test_tie_none_with_candidates(tmp_path, monkeypatch):
    c = _lib(tmp_path, monkeypatch, {
        "k:1": {"question": "Fed cut rates December 2026 meeting again", "mappings": []},
        "k:2": {"question": "Fed cut rates December 2026 meeting soon", "mappings": []}})
    r = c.post("/map", json={"question": "Will Fed cut rates December 2026 meeting"}).json()
    assert r["source"] == "none" and len(r["candidates"]) == 2 and r["items"] == []


def test_just_under_threshold(tmp_path, monkeypatch):
    c = _lib(tmp_path, monkeypatch, {"k:1": {"question": "alpha beta gamma delta epsilon zeta", "mappings": []}})
    # shared 3, union 7 -> 0.43
    assert c.post("/map", json={"question": "alpha beta gamma eta"}).json()["source"] == "none"


def test_id_without_exact_or_question(client):
    assert client.post("/map", json={"source": "kalshi", "market_id": "nope"}).json()["source"] == "none"


def test_non_dict_items_skipped(tmp_path, monkeypatch):
    c = _lib(tmp_path, monkeypatch, {"k:1": "junk", "k:2": None})
    assert c.post("/map", json={"question": "anything goes here today"}).json()["source"] == "none"


def test_no_match(client):
    r = client.post("/map", json={"question": "Who wins the Oscar for best picture?"}).json()
    assert r["source"] == "none" and r["items"] == []
    # no key in tests: the precomputed miss, and the note says why no live AI answer was tried
    assert r["note"].startswith("no precomputed mapping; pick stocks manually")
    assert "live AI mapping unavailable" in r["note"] and "GEMINI_API_KEY" in r["note"]
    assert r["ai"]["provider"] == "rules" and r["ai"]["live"] is False


def test_empty_mappings(client):
    r = client.post("/map", json={"source": "kalshi", "market_id": "K1"}).json()
    assert r["source"] == "ai_precomputed" and r["items"] == []


def test_422(client):
    assert client.post("/map", json={}).status_code == 422
    assert client.post("/map", json={"source": "kalshi"}).status_code == 422


def test_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mapping, "MAP_PATH", tmp_path / "nope.json")
    r = TestClient(create_app()).post("/map", json={"question": "anything at all"})
    assert r.status_code == 200 and r.json()["source"] == "none" and "missing" in r.json()["note"]


def test_shipped_library_loads():
    mapping._cache = None
    assert len(mapping._load()["items"]) > 100
    mapping._cache = None


# ---------------------------------------------------------------- live AI mapping (Gemini over mocked HTTP)

import httpx  # noqa: E402

from app.pipeline.llm import GeminiProvider  # noqa: E402

UNIVERSE = [{"ticker": t, "name": n} for t, n in [("ABNB", "Airbnb"), ("MAR", "Marriott"), ("SPY", None),
                                                   ("TLT", None), ("XLE", None)]]
NOVEL = "Will the US ban short-term rentals nationwide by 2027?"


def _gemini(rows, calls: list | None = None, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if status != 200:
            return httpx.Response(status)
        text = json.dumps({"mappings": rows})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return handler


def _live_client(tmp_path, monkeypatch, handler):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(FIX))
    monkeypatch.setattr(mapping, "MAP_PATH", p)
    monkeypatch.setattr(mapping, "_cache", None)
    monkeypatch.setattr(mapping, "_universe", UNIVERSE)
    app = create_app()
    app.state.pipeline_provider = GeminiProvider("k", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return TestClient(app)


def test_live_mapping_validated_labelled_and_cached(tmp_path, monkeypatch):
    calls: list = []
    rows = [{"ticker": "abnb", "direction": "down_on_yes", "impact_pct": 6.5,
             "rationale": "A nationwide ban removes most of its US listings. Second sentence dropped."},
            {"ticker": "MAR", "direction": "up_on_yes", "impact_pct": 1.2, "rationale": "Travellers shift to hotels."},
            {"ticker": "ZZZZ", "direction": "down_on_yes", "impact_pct": 3, "rationale": "Invented ticker."},
            {"ticker": "SPY", "direction": "sideways", "impact_pct": 1, "rationale": "Bad direction."},
            {"ticker": "TLT", "direction": "up_on_yes", "impact_pct": 80, "rationale": "Out of bounds."},
            {"ticker": "ABNB", "direction": "up_on_yes", "impact_pct": 1, "rationale": "Duplicate."}]
    c = _live_client(tmp_path, monkeypatch, _gemini(rows, calls))
    r = c.post("/map", json={"question": NOVEL}).json()
    assert r["source"] == "ai_live:gemini:gemini-2.5-flash" and r["match_type"] == "live"
    assert r["items"] == [
        {"ticker": "ABNB", "direction": "down_on_yes", "impact_pct": 6.5,
         "rationale": "A nationwide ban removes most of its US listings."},
        {"ticker": "MAR", "direction": "up_on_yes", "impact_pct": 1.2, "rationale": "Travellers shift to hotels."}]
    assert "4 of 6 rows dropped" in r["note"] and "ZZZZ" in r["note"]
    assert r["ai"] == {"provider": "gemini", "model": "gemini-2.5-flash", "live": True, "cached": False,
                       "fell_back_reason": None}
    assert r["label"] == "AI estimate (live, Gemini gemini-2.5-flash)"
    sent = json.loads(calls[0].content)
    enum = sent["generationConfig"]["responseSchema"]["properties"]["mappings"]["items"]["properties"]["ticker"]["enum"]
    assert enum == ["ABNB", "MAR", "SPY", "TLT", "XLE"] and NOVEL in sent["contents"][0]["parts"][0]["text"]
    assert "k" == calls[0].headers["x-goog-api-key"] and "key=" not in str(calls[0].url)
    again = c.post("/map", json={"question": "  will the US ban SHORT-TERM rentals nationwide by 2027 "}).json()
    assert len(calls) == 1 and again["ai"]["cached"] is True and again["items"] == r["items"]


def test_precomputed_questions_never_call_gemini(tmp_path, monkeypatch):
    calls: list = []
    c = _live_client(tmp_path, monkeypatch, _gemini([], calls))
    assert c.post("/map", json={"source": "polymarket", "market_id": "1"}).json()["source"] == "ai_precomputed"
    assert c.post("/map", json={"question": "Indiana enact data center moratorium 2027?"}).json()["source"] == \
        "ai_precomputed"
    assert calls == []


def test_live_mapping_all_rows_invalid_is_not_an_ai_answer(tmp_path, monkeypatch):
    rows = [{"ticker": "NOPE", "direction": "down_on_yes", "impact_pct": 2, "rationale": "x."}]
    r = _live_client(tmp_path, monkeypatch, _gemini(rows)).post("/map", json={"question": NOVEL}).json()
    assert r["source"] == "none" and r["items"] == [] and "rejected" in r["note"]
    assert r["ai"]["provider"] == "rules" and r["ai"]["live"] is False


def test_live_mapping_empty_answer_is_honest(tmp_path, monkeypatch):
    r = _live_client(tmp_path, monkeypatch, _gemini([])).post("/map", json={"question": NOVEL}).json()
    assert r["source"].startswith("ai_live:gemini:") and r["items"] == [] and "no stock" in r["note"]


def test_live_mapping_gemini_error_falls_back_with_reason(tmp_path, monkeypatch):
    r = _live_client(tmp_path, monkeypatch, _gemini([], status=500)).post("/map", json={"question": NOVEL}).json()
    assert r["source"] == "none" and r["items"] == []
    assert "live AI mapping failed (Gemini call failed: HTTP 500)" in r["note"]
    assert r["ai"]["fell_back_reason"] == "Gemini call failed: HTTP 500"


def test_live_mapping_resolves_a_universe_market_id(tmp_path, monkeypatch):
    calls: list = []
    c = _live_client(tmp_path, monkeypatch, _gemini([], calls))
    monkeypatch.setattr(mapping, "_universe_question", lambda s, i: NOVEL if (s, i) == ("polymarket", "77") else None)
    r = c.post("/map", json={"source": "polymarket", "market_id": "77"}).json()
    assert r["source"].startswith("ai_live:") and r["matched_question"] == NOVEL and len(calls) == 1


def test_validate_mappings_bounds():
    rows = [{"ticker": "SPY", "direction": "down_on_yes", "impact_pct": True, "rationale": "bool is not a number."},
            {"ticker": "SPY", "direction": "down_on_yes", "impact_pct": float("nan"), "rationale": "nan."},
            {"ticker": "SPY", "direction": "down_on_yes", "impact_pct": 0, "rationale": "zero."},
            {"ticker": "SPY", "direction": "down_on_yes", "impact_pct": -2, "rationale": "negative."},
            {"ticker": "SPY", "direction": "down_on_yes", "impact_pct": "2.5", "rationale": "   "},
            "junk",
            {"ticker": "SPY", "direction": "down_on_yes", "impact_pct": 20, "rationale": "At the bound."}]
    items, dropped = mapping.validate_mappings(rows, {"SPY"})
    assert items == [{"ticker": "SPY", "direction": "down_on_yes", "impact_pct": 20.0, "rationale": "At the bound."}]
    assert len(dropped) == 6
    many = [{"ticker": t, "direction": "up_on_yes", "impact_pct": 1, "rationale": "r."} for t in "ABCDEFGH"]
    items, dropped = mapping.validate_mappings(many, set("ABCDEFGH"))
    assert [i["ticker"] for i in items] == list("ABCDEF") and len(dropped) == 2


def test_ticker_universe_covers_portfolio_proxies_and_map(monkeypatch):
    monkeypatch.setattr(mapping, "_universe", None)
    tickers = {u["ticker"] for u in mapping.ticker_universe()}
    assert {"TLT", "IWM", "ABNB", "KRE", "XHB", "VRT"} <= tickers  # portfolio, proxies, precomputed map
    assert next(u for u in mapping.ticker_universe() if u["ticker"] == "ABNB")["name"] == "Airbnb"
