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
    monkeypatch.setattr(mapping, "_cache", None)


def test_exact(client):
    r = client.post("/map", json={"source": "polymarket", "market_id": "1"}).json()
    assert r["source"] == "precomputed" and r["items"][0]["ticker"] == "VRT"
    assert r["label"] == "AI estimate (precomputed)" and r["generated_at"] == FIX["generated_at"]


def test_fuzzy(client):
    r = client.post("/map", json={"question": "Indiana data center moratorium enacted in 2027?"}).json()
    assert r["source"] == "precomputed" and r["matched_question"].startswith("Will Indiana")


def test_no_match(client):
    r = client.post("/map", json={"question": "Who wins the Oscar for best picture?"}).json()
    assert r["source"] == "none" and r["items"] == []
    assert r["note"] == "no precomputed mapping; pick stocks manually"


def test_empty_mappings(client):
    r = client.post("/map", json={"source": "kalshi", "market_id": "K1"}).json()
    assert r["source"] == "precomputed" and r["items"] == []


def test_422(client):
    assert client.post("/map", json={}).status_code == 422
    assert client.post("/map", json={"source": "kalshi"}).status_code == 422


def test_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mapping, "MAP_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(mapping, "_cache", None)
    r = TestClient(create_app()).post("/map", json={"question": "anything at all"})
    assert r.status_code == 200 and r.json()["source"] == "none" and "missing" in r.json()["note"]
    monkeypatch.setattr(mapping, "_cache", None)


def test_shipped_library_loads():
    mapping._cache = None
    assert len(mapping._load()["items"]) > 100
    mapping._cache = None
