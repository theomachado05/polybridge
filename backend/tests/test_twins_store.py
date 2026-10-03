"""Twin map reader, plus invariants of the committed map (offline: only reads files)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.twins import store
from app.twins.store import DEFAULT_PATH, Twin, twin_of


def entry(pid="777", tok="tokYES777", ticker="KXFOO-26", direction="same", note="same event; gap 0d",
          verified_at="2026-10-03T00:00:00Z"):
    return {"polymarket": {"id": pid, "token_id": tok, "question": "q"}, "kalshi": {"ticker": ticker, "question": "q"},
            "direction": direction, "verification": {"verified_at": verified_at, "note": note, "checks": {}}}


def write(tmp_path, pairs, **extra):
    p = tmp_path / "twins.json"
    p.write_text(json.dumps({"schema": 1, "pairs": pairs, **extra}))
    return p


def test_polymarket_market_finds_its_kalshi_twin_by_id_or_token(tmp_path):
    p = write(tmp_path, [entry()])
    t = twin_of("polymarket", "777", None, path=p)
    assert t == Twin("kalshi", "KXFOO-26", None, "same event; gap 0d")
    assert twin_of("polymarket", None, "tokYES777", path=p).id == "KXFOO-26"
    assert twin_of("polymarket", "999", "other", path=p) is None


def test_kalshi_market_finds_its_polymarket_twin_with_the_yes_token(tmp_path):
    p = write(tmp_path, [entry()])
    t = twin_of("kalshi", "KXFOO-26", path=p)
    assert (t.source, t.id, t.token_id) == ("polymarket", "777", "tokYES777")
    assert t.as_market_ref() == {"source": "polymarket", "id": "777", "token_id": "tokYES777"}
    assert twin_of("kalshi", "KXNOPE", path=p) is None


def test_ambiguous_inverted_and_unverified_entries_are_never_served(tmp_path):
    bad = [entry("1", "t1", "K1", direction="inverted"), entry("2", "t2", "K2", note=""),
           entry("3", "t3", "K3", verified_at=""), entry("4", "", "K4"), {"polymarket": {}, "kalshi": {}}, "junk"]
    p = write(tmp_path, bad, ambiguous=[entry("5", "t5", "K5")])
    for src, ident in [("polymarket", "1"), ("polymarket", "2"), ("polymarket", "3"), ("polymarket", "4"),
                       ("polymarket", "5"), ("kalshi", "K1"), ("kalshi", "K2"), ("kalshi", "K3"), ("kalshi", "K5")]:
        assert twin_of(src, ident, path=p) is None, (src, ident)


def test_missing_or_corrupt_file_is_an_empty_map(tmp_path):
    assert twin_of("polymarket", "777", path=tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert twin_of("polymarket", "777", path=bad) is None
    notdict = tmp_path / "list.json"
    notdict.write_text("[1, 2]")
    assert twin_of("polymarket", "777", path=notdict) is None
    nopairs = tmp_path / "np.json"
    nopairs.write_text(json.dumps({"pairs": "x"}))
    assert twin_of("polymarket", "777", path=nopairs) is None


def test_the_map_reloads_when_the_file_changes(tmp_path):
    p = write(tmp_path, [entry()])
    assert twin_of("polymarket", "777", path=p) is not None
    p.write_text(json.dumps({"pairs": []}))
    import os
    os.utime(p, ns=(10**18, 10**18 + 5))
    assert twin_of("polymarket", "777", path=p) is None


def test_default_path_is_patchable(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DEFAULT_PATH", write(tmp_path, [entry()]))
    assert twin_of("polymarket", "777").id == "KXFOO-26"


# ---------------------------------------------------------------- the committed map

def committed():
    return json.loads(DEFAULT_PATH.read_text())


def test_committed_map_exists_and_every_pair_is_verified_complete_and_same_direction():
    doc = committed()
    assert doc["schema"] == 1 and doc["pairs"], "the committed twin map must hold verified pairs"
    seen_p, seen_k = set(), set()
    for e in doc["pairs"]:
        assert e["direction"] == "same"
        assert e["polymarket"]["id"] and e["polymarket"]["token_id"] and e["kalshi"]["ticker"]
        v = e["verification"]
        assert v["note"] and v["verified_at"] and all(c["ok"] for c in v["checks"].values())
        dp, dk = date.fromisoformat(e["polymarket"]["deadline_et"]), date.fromisoformat(e["kalshi"]["deadline_et"])
        assert abs((dp - dk).days) <= 1, e["kalshi"]["ticker"]       # spec: same deadline within 1 day
        assert e["polymarket"]["id"] not in seen_p and e["kalshi"]["ticker"] not in seen_k, "one twin per market"
        seen_p.add(e["polymarket"]["id"])
        seen_k.add(e["kalshi"]["ticker"])


@pytest.mark.real_twins
def test_committed_map_ambiguous_pairs_are_flagged_and_disjoint_from_pairs():
    doc = committed()
    used = {(e["polymarket"]["id"], e["kalshi"]["ticker"]) for e in doc["pairs"]}
    for a in doc["ambiguous"]:
        assert a["used"] is False and a["reasons"]
        assert (a["polymarket"]["id"], a["kalshi"]["ticker"]) not in used
    # none of them is served by the reader
    for a in doc["ambiguous"]:
        t = twin_of("polymarket", a["polymarket"]["id"])
        assert t is None or t.id != a["kalshi"]["ticker"]


@pytest.mark.real_twins
@pytest.mark.parametrize("e", committed()["pairs"][:50], ids=lambda e: e["kalshi"]["ticker"])
def test_committed_pairs_resolve_through_the_reader(e):
    assert twin_of("polymarket", e["polymarket"]["id"]).id == e["kalshi"]["ticker"]
    assert twin_of("kalshi", e["kalshi"]["ticker"]).token_id == e["polymarket"]["token_id"]


def test_tests_get_an_empty_twin_map_unless_they_opt_in():
    """conftest's autouse fixture: a committed pair is invisible to a test that did not mark itself real_twins."""
    e = committed()["pairs"][0]
    assert twin_of("polymarket", e["polymarket"]["id"]) is None


@pytest.mark.real_twins
def test_real_twins_marker_reads_the_committed_map():
    e = committed()["pairs"][0]
    assert twin_of("polymarket", e["polymarket"]["id"]).id == e["kalshi"]["ticker"]
