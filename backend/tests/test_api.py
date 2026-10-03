import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _propose(client, tags=("material_litigation",)):
    return client.post("/proposals", json={"ticker": "ABNB", "tags": list(tags), "shares_held": 1200})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_classify(client):
    assert client.post("/classify", json={"tags": ["workforce_reduction"]}).json() == {
        "family": "opportunity", "strategy": "cash_secured_put"}
    assert client.post("/classify", json={"tags": ["restructuring_plan", "asset_impairment"]}).json() == {
        "family": None, "strategy": None}


def test_propose_then_approve(client):
    r = _propose(client)
    assert r.status_code == 201
    p = r.json()
    assert (p["family"], p["strategy"], p["status"], p["target_coverage"]) == ("hedge", "protective_put", "proposed", 0.5)
    assert p["evidence"]["validated"] is False and p["evidence"]["status"] == "unvalidated estimate"
    gated = client.post(f"/proposals/{p['id']}/approve")  # a filing proposal names no market: unvalidated
    assert gated.status_code == 409 and "EVIDENCE_UNVALIDATED" in gated.json()["detail"]
    assert "ack_unvalidated" in gated.json()["detail"]
    a = client.post(f"/proposals/{p['id']}/approve", json={"ack_unvalidated": True})
    assert a.status_code == 200 and a.json()["status"] == "approved" and a.json()["decided_at"]
    assert a.json()["ack_unvalidated"] is True
    assert [x["status"] for x in client.get("/proposals").json()] == ["approved"]


def test_approve_twice_is_conflict(client):
    pid = _propose(client).json()["id"]
    assert client.post(f"/proposals/{pid}/approve", json={"ack_unvalidated": True}).status_code == 200
    assert client.post(f"/proposals/{pid}/approve", json={"ack_unvalidated": True}).status_code == 409
    assert client.post(f"/proposals/{pid}/reject").status_code == 409


def test_unknown_id_is_not_found(client):
    assert client.post("/proposals/nope/approve").status_code == 404


def test_no_family_cannot_be_proposed(client):
    assert _propose(client, tags=("cfo_appointment",)).status_code == 422


def test_input_validation(client):
    bad = client.post("/proposals", json={"ticker": "X", "tags": ["material_litigation"], "shares_held": 0})
    assert bad.status_code == 422
    bad = client.post("/proposals", json={"ticker": "X", "tags": ["material_litigation"], "shares_held": 10,
                                          "target_coverage": 1.5})
    assert bad.status_code == 422


def test_infinite_shares_rejected(client):
    r = client.post("/proposals", content='{"ticker":"X","tags":["material_litigation"],"shares_held":Infinity}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_blank_ticker_rejected(client):
    r = client.post("/proposals", json={"ticker": "   ", "tags": ["material_litigation"], "shares_held": 10})
    assert r.status_code == 422


def test_share_class_ticker_normalized(client):
    r = client.post("/proposals", json={"ticker": "brk/b", "tags": ["material_litigation"], "shares_held": 10})
    assert r.status_code == 201
    assert r.json()["ticker"] == "BRK.B"


# --- market-event proposals (the exact body web/src/components/ProposePanel.tsx sends) -------------

FED = {"source": "polymarket", "id": "2589813", "token_id": "55159722761418013044126414276680602270318000841690689684819994448621694923050"}
UI_MARKET_BODY = {"ticker": "IWM", "market": FED, "direction": "down_on_yes", "shares_held": 400, "target_coverage": 0.5}


def test_market_event_proposal_from_ui_body(client):
    r = client.post("/proposals", json=UI_MARKET_BODY)
    assert r.status_code == 201
    p = r.json()
    assert p["family"] == "hedge" and p["strategy"] == "protective_put" and p["basis"] == "market_event"
    assert p["label"] == "Product hedge — no confirmatory claim"
    assert p["market"]["id"] == "2589813" and p["direction"] == "down_on_yes" and p["status"] == "proposed"
    assert client.post(f"/proposals/{p['id']}/approve").status_code == 409  # Fed market -> IWM: unvalidated
    assert client.post(f"/proposals/{p['id']}/approve", json={"ack_unvalidated": True}).json()["status"] == "approved"


RECESSION = {"source": "polymarket", "id": "516710"}


def test_the_validated_market_on_its_own_ticker_approves_without_an_acknowledgement(client):
    """The evidence gate: US recession 2025 on SPY passed R2 out of sample, so no ack is needed; the same market on
    another ticker borrows SPY's rate (a proxy) and needs one."""
    p = client.post("/proposals", json={"ticker": "SPY", "market": RECESSION, "direction": "down_on_yes",
                                        "shares_held": 100}).json()
    assert p["evidence"]["validated"] is True and p["evidence"]["status"] == "validated"
    a = client.post(f"/proposals/{p['id']}/approve")
    assert a.status_code == 200 and a.json()["ack_unvalidated"] is False
    q = client.post("/proposals", json={"ticker": "TLT", "market": RECESSION, "direction": "down_on_yes",
                                        "shares_held": 100}).json()
    assert q["evidence"]["validated"] is False and "proxy" in q["evidence"]["evidence"]
    assert client.post(f"/proposals/{q['id']}/approve").status_code == 409


def test_act_on_unvalidated_is_a_hedge_override_confirmed_by_the_approval(client):
    p = client.post("/proposals", json={**UI_MARKET_BODY, "act_on_unvalidated": True}).json()
    assert p["act_on_unvalidated"] is True
    r = client.post(f"/proposals/{p['id']}/approve")
    assert r.status_code == 409 and "act_on_unvalidated" in r.json()["detail"]
    assert client.post(f"/proposals/{p['id']}/approve", json={"ack_unvalidated": True}).status_code == 200
    bad = client.post("/proposals", json={"ticker": "NVDA", "market": FED, "division": "opportunity",
                                          "act_on_unvalidated": True,
                                          "algo": {"family": "binary_vs_spread_arb", "preset_index": 0}})
    assert bad.status_code == 422


def test_a_proposal_carries_a_capacity_block_before_approval(client):
    """Offline (no Massive key in tests): the block says what is unavailable instead of failing; with pinned numbers
    it sizes the hedge against the participation caps."""
    from app.liquidity.service import service_for
    p = client.post("/proposals", json=UI_MARKET_BODY).json()
    cap = p["capacity"]
    assert cap["equity"]["available"] is False and cap["equity"]["hedge_shares"] == 200
    assert "caps" in cap and cap["caps"]["equity"]["per_day"].startswith("<= 1%")
    service_for(client.app).set_equity("IWM", {"price": 200.0, "adv_shares": 10_000.0, "sigma_daily": 0.01,
                                               "open5_median_shares": 1_000.0, "spread_bp": 2.0,
                                               "spread_source": "quote"})
    p = client.post("/proposals", json=UI_MARKET_BODY).json()
    eq = p["capacity"]["equity"]
    # 200-share hedge vs 10% of the opening 5-minute volume (100) and 1% of ADV (100): capped, two sessions
    assert (eq["max_order_shares"], eq["per_day_shares"], eq["inside_caps"], eq["sessions_needed"]) == (100, 100, False, 2)
    assert eq["book_usd_capacity"] == 100 * 200.0 / 0.5
    assert abs(eq["est_cost_bp"] - (1.0 + 1e4 * 0.01 * (200 / 10_000) ** 0.5)) < 1e-9
    assert p["capacity"]["capital"]["checked"] is True and p["capacity"]["capital"]["fits"] is True


def test_filing_proposal_basis(client):
    assert _propose(client).json()["basis"] == "filing_tags"


@pytest.mark.parametrize("body", [
    {"ticker": "IWM", "market": FED, "shares_held": 400},  # no direction
    {"ticker": "IWM", "market": FED, "direction": "sideways", "shares_held": 400},
    {"ticker": "IWM", "market": FED, "direction": "down_on_yes", "tags": ["material_litigation"], "shares_held": 400},
    {"ticker": "IWM", "shares_held": 400},  # neither tags nor market
    {"ticker": "IWM", "tags": [], "shares_held": 400},
])
def test_proposal_body_must_pick_one_basis(client, body):
    assert client.post("/proposals", json=body).status_code == 422
