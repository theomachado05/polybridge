import pytest

from .conftest import research_fakes as rf
from .test_equities import StubClient, make


def menu(monkeypatch, qs="", quote=None, spot=100.0):
    c = make(StubClient(market=rf.FakeMarket({"AAA": spot}), quote=quote), monkeypatch)
    r = c.get(f"/hedges/AAA{qs}")
    assert r.status_code == 200
    return r.json()


def by(d):
    return {o["strategy"]: o for o in d["options"]}


def test_prices_and_legs(monkeypatch):
    d = menu(monkeypatch, "?shares=200")
    assert d["spot"] == pytest.approx(100.0, rel=2e-3) and d["expiry"]
    o, sp = by(d), d["spot"]
    assert set(o) == {"protective_put", "collar", "cash_secured_put", "covered_call", "long_call"}
    # FakeMarket: OTM options trade at 1.0, ATM call at 1.0 (flat spot, intrinsic 0)
    assert o["protective_put"]["premium_per_share"] == pytest.approx(1.0)
    assert o["protective_put"]["premium_total"] == pytest.approx(200.0)
    assert o["protective_put"]["breakeven"] == pytest.approx(sp + 1.0)
    assert o["protective_put"]["max_loss"] == pytest.approx(sp - o["protective_put"]["legs"][0]["strike"] + 1.0)
    assert o["collar"]["premium_per_share"] == pytest.approx(0.0)
    assert o["covered_call"]["premium_per_share"] == pytest.approx(-1.0)
    assert o["cash_secured_put"]["max_loss"] == pytest.approx(o["cash_secured_put"]["legs"][0]["strike"] - 1.0)
    assert o["long_call"]["legs"][0]["strike"] == pytest.approx(100.0)
    assert o["collar"]["fees"] == pytest.approx(0.0035 * 200 * 2)
    assert o["protective_put"]["legs"][0]["contract"].startswith("O:AAA")


def test_missing_quotes_spread_null_then_present(monkeypatch):
    assert all(o["half_spread_cost"] is None for o in menu(monkeypatch)["options"])
    d = menu(monkeypatch, "?shares=100", quote=(0.9, 1.1))
    o = by(d)
    assert o["protective_put"]["half_spread_cost"] == pytest.approx(0.1 * 100)
    assert o["collar"]["half_spread_cost"] == pytest.approx(0.2 * 100)


@pytest.mark.parametrize("label,first_two", [("hedge", {"protective_put", "collar"}),
                                             ("opportunity", {"cash_secured_put", "covered_call"})])
def test_ranking_by_label(monkeypatch, label, first_two):
    d = menu(monkeypatch, f"?label={label}")
    assert {o["strategy"] for o in d["options"][:2]} == first_two
    assert d["options"][0]["strategy"] == ("protective_put" if label == "hedge" else "cash_secured_put")
    assert [o["rank"] for o in d["options"]] == [1, 2, 3, 4, 5]


def test_no_edge_cheapest_protection_first(monkeypatch):
    d = menu(monkeypatch, "?label=no_edge")
    assert d["options"][0]["strategy"] == "collar"  # net 0.0 beats the 1.0 put
    assert all("no edge found for this event; hedge only if you want insurance" in o["why"] for o in d["options"])


def test_bad_input_and_no_key(monkeypatch):
    c = make(StubClient(market=rf.FakeMarket({"AAA": 100.0})), monkeypatch)
    assert c.get("/hedges/AAA?shares=0").status_code == 422
    assert c.get("/hedges/AAA?label=bogus").status_code == 422
    d = make(None, monkeypatch).get("/hedges/AAA").json()
    assert d["options"] == [] and "Massive key not configured" in d["notes"]
