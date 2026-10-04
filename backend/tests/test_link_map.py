"""The link agent's map: the loader keeps ai_map.json's shape, and /map serves it only when POLYBRIDGE_LINK_MAP=1."""
import json

import pytest
from fastapi.testclient import TestClient

from app import link_map, mapping
from app.main import create_app

AI = {"generated_at": "2026-01-01T00:00:00", "generator": "text map",
      "items": {"polymarket:1": {"question": "Strait of Hormuz traffic returns to normal by December 31?",
                                 "mappings": [{"ticker": "XOM", "direction": "down_on_yes", "impact_pct": 1.0, "rationale": "x"}]}}}
LM = {"generated_at": "2026-10-03T22:00:00", "generator": "link agent v3", "as_of": "2026-10-02", "summary": {"trusted_links": 1},
      "items": {
          "polymarket:1": {"question": "Strait of Hormuz traffic returns to normal by December 31?", "cluster": None, "signal": [["polymarket:1", 1.0]],
                           "alternative": "", "ends": "2026-12-31", "kind": "event", "no_instrument": False, "no_instrument_reason": "",
                           "mappings": [
                               {"ticker": "USO", "direction": "down_on_yes", "impact_pct": 5.0, "rationale": "Gulf crude returns.", "score": 0.67,
                                "verdict": "confirmed", "trusted": True,
                                "option": {"contract": "O:USO270115P00147000", "expiry": "2027-01-15", "strike": 147.0, "call": "c", "put": "p"}},
                               {"ticker": "XLE", "direction": "down_on_yes", "impact_pct": 2.0, "rationale": "y", "score": 0.2, "verdict": "unproven",
                                "trusted": False, "option": None}]},
          "polymarket:5": {"question": "Will the Federal Reserve chair resign before June?", "no_instrument": False, "no_instrument_reason": "",
                           "mappings": [{"ticker": "TLT", "direction": "up_on_yes", "impact_pct": 1.0, "rationale": "z", "score": 0.1,
                                         "verdict": "unproven", "trusted": False, "option": None}]},
          "polymarket:9": {"question": "Will the city council pass the zoning bill?", "mappings": [], "no_instrument": True,
                           "no_instrument_reason": "nothing listed moves 1%"}}}


@pytest.fixture
def files(tmp_path, monkeypatch):
    a, b = tmp_path / "ai.json", tmp_path / "lm.json"
    a.write_text(json.dumps(AI))
    b.write_text(json.dumps(LM))
    monkeypatch.setattr(mapping, "MAP_PATH", a)
    monkeypatch.setattr(mapping, "_cache", None)
    monkeypatch.setattr(link_map, "PATH", b)
    monkeypatch.setattr(link_map.load, "__defaults__", (b, True))
    link_map._cache.clear()
    return a, b


def _post(**body):
    return TestClient(create_app()).post("/map", json=body).json()


def test_loader_keeps_ai_map_shape_and_trusted_only(files):
    lib = link_map.load(files[1])
    assert lib["generated_at"] == LM["generated_at"] and set(lib["items"]) == {"polymarket:1", "polymarket:9"}  # 5 has only untrusted links
    rows = lib["items"]["polymarket:1"]["mappings"]
    assert [m["ticker"] for m in rows] == ["USO"] and rows[0]["option"]["contract"] == "O:USO270115P00147000"
    assert {"ticker", "direction", "impact_pct", "rationale"} <= set(rows[0])
    allrows = link_map.load(files[1], trusted_only=False)["items"]
    assert len(allrows["polymarket:1"]["mappings"]) == 2 and allrows["polymarket:5"]["mappings"][0]["ticker"] == "TLT"
    e = link_map.entry("polymarket:9", files[1])
    assert e["mappings"] == [] and e["no_instrument"] and e["no_instrument_reason"] == "nothing listed moves 1%"
    assert link_map.option_for("polymarket:1", "USO", files[1])["expiry"] == "2027-01-15"


def test_loader_missing_and_malformed(tmp_path):
    assert link_map.load(tmp_path / "nope.json") == {"items": {}, "error": "missing"}
    (tmp_path / "bad.json").write_text(json.dumps({"items": []}))
    assert link_map.load(tmp_path / "bad.json") == {"items": {}, "error": "malformed"}


@pytest.mark.parametrize("env", [None, "0", "", "true"])
def test_default_is_unchanged(files, monkeypatch, env):
    if env is None:
        monkeypatch.delenv("POLYBRIDGE_LINK_MAP", raising=False)
    else:
        monkeypatch.setenv("POLYBRIDGE_LINK_MAP", env)
    monkeypatch.setattr(link_map, "load", lambda *a, **k: pytest.fail("link map read without the switch"))
    r = _post(source="polymarket", market_id="1")
    assert r == {"label": "AI estimate (precomputed)", "generated_at": AI["generated_at"], "source": "ai_precomputed", "match_type": "exact",
                 "score": 1.0, "items": AI["items"]["polymarket:1"]["mappings"], "matched_question": AI["items"]["polymarket:1"]["question"],
                 "candidates": [], "note": None,
                 "ai": {"provider": "precomputed", "model": None, "live": False, "cached": False, "generator": "text map", "fell_back_reason": None}}


def test_switch_serves_trusted_links(files, monkeypatch):
    monkeypatch.setenv("POLYBRIDGE_LINK_MAP", "1")
    r = _post(source="polymarket", market_id="1")
    assert r["source"] == "ai_precomputed" and r["ai"]["generator"] == "link agent v3"
    assert [m["ticker"] for m in r["items"]] == ["USO"] and r["items"][0]["option"]["strike"] == 147.0
    r9 = _post(source="polymarket", market_id="9")
    assert r9["source"] == "ai_precomputed" and r9["items"] == [] and r9["note"] == "nothing listed moves 1%"
    assert _post(question="Hormuz traffic returns to normal by December 31")["items"][0]["ticker"] == "USO"


def test_untrusted_only_item_is_a_miss_not_an_empty_hit(files, monkeypatch):
    """An open question with only untrusted links must not answer as an empty precomputed hit (that blocks the live
    fallback and looks like an explicit "no listed instrument")."""
    monkeypatch.setenv("POLYBRIDGE_LINK_MAP", "1")
    r = _post(source="polymarket", market_id="5")
    assert r["source"] == "none" and r["match_type"] is None and r["note"]
    r = _post(question="Will the Federal Reserve chair resign before June?")
    assert r["source"] != "ai_precomputed" and "live AI mapping unavailable" in r["note"]


def test_shipped_file_loads():
    lib = link_map.load()
    if lib.get("error") == "missing":
        pytest.skip("data/link_map.json not generated")
    assert "error" not in lib
    for e in lib["items"].values():
        assert e["mappings"] or e["no_instrument"]
        for m in e["mappings"]:
            assert m["trusted"] and m["direction"] in ("up_on_yes", "down_on_yes") and m["rationale"]
