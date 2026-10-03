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
    a = client.post(f"/proposals/{p['id']}/approve")
    assert a.status_code == 200 and a.json()["status"] == "approved" and a.json()["decided_at"]
    assert [x["status"] for x in client.get("/proposals").json()] == ["approved"]


def test_approve_twice_is_conflict(client):
    pid = _propose(client).json()["id"]
    assert client.post(f"/proposals/{pid}/approve").status_code == 200
    assert client.post(f"/proposals/{pid}/approve").status_code == 409
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
    assert client.post(f"/proposals/{p['id']}/approve").json()["status"] == "approved"


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
