"""Voice-agent tool surface: schema shape, dispatch, confirm gating, never a 500. Fully offline."""
import pytest
from fastapi.testclient import TestClient

from app.agent.tools import HANDLERS, NAMES
from app.main import create_app

EXPECTED = {"search_markets", "fit", "propose", "approve", "start_bridge", "bridge_status", "account", "positions"}


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def call(client, name, body=None):
    return client.post(f"/agent/tool/{name}", json=body or {})


def test_tool_list_shape(client):
    r = client.get("/agent/tools")
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert {t["name"] for t in tools} == EXPECTED == NAMES == set(HANDLERS)
    routes = {(p, m.upper()) for p, ops in client.app.openapi()["paths"].items() for m in ops}
    for t in tools:
        assert t["method"] in ("GET", "POST") and t["path"].startswith("/")
        assert (t["path"], t["method"]) in routes, f"{t['name']} maps to a missing route"
        assert 0 < len(t["description"]) < 140
        p = t["parameters"]
        assert p["type"] == "object" and set(p["required"]) <= set(p["properties"])
        assert t["webhook"] == {"method": "POST", "path": f"/agent/tool/{t['name']}"}
    for n in ("approve", "start_bridge"):
        t = next(t for t in tools if t["name"] == n)
        assert "confirm" in t["parameters"]["required"]


def test_unknown_tool_is_404(client):
    assert call(client, "nope").status_code == 404


def test_dispatch_calls_the_route_function(client, monkeypatch):
    from app import markets
    from app.markets import Market, SearchOut
    seen = {}

    async def fake(q, request):
        seen["q"] = q
        return SearchOut(markets=[Market(source="polymarket", id="m1", question="Fed cuts in March?", yes_price=0.42)])
    monkeypatch.setattr(markets, "markets_search", fake)
    r = call(client, "search_markets", {"q": "fed"})
    assert r.status_code == 200
    j = r.json()
    assert seen == {"q": "fed"} and j["ok"] is True
    assert "Fed cuts in March" in j["summary"] and "42 percent" in j["summary"]
    assert j["data"]["markets"][0]["id"] == "m1"


def test_fit_dispatch_builds_request(client, monkeypatch):
    from app.pipeline import router as pr
    from app.pipeline.service import FitResponse
    seen = {}

    async def fake(req, request):
        seen["req"] = req
        return FitResponse(event_class="rates", division="hedge", family="protective_put", preset_index=1, params={},
                           score=0.5, alternatives=[], rationale="Short.", llm="rules", ticks_source="none", n_ticks=0)
    monkeypatch.setattr(pr, "pipeline_fit", fake)
    j = call(client, "fit", {"ticker": "abnb", "market_id": "m1", "market_source": "kalshi"}).json()
    assert j["ok"] and seen["req"].ticker == "ABNB" and (seen["req"].market.source, seen["req"].market.id) == ("kalshi", "m1")
    assert "ABNB" in j["summary"]


def test_propose_then_approve_requires_confirm(client):
    j = call(client, "propose", {"ticker": "ABNB", "shares_held": 100, "market_id": "m1", "direction": "down_on_yes"}).json()
    assert j["ok"], j
    pid = j["data"]["id"]
    for bad in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
        r = call(client, "approve", {"proposal_id": pid, **bad})
        assert r.status_code == 200 and r.json()["ok"] is False and r.json()["needs_confirmation"] is True
    assert client.get("/proposals").json()[0]["status"] == "proposed"
    gated = call(client, "approve", {"proposal_id": pid, "confirm": True}).json()  # evidence gate: m1 is unvalidated
    assert gated["ok"] is False and gated["status"] == 409 and "ack_unvalidated" in gated["summary"]
    ok = call(client, "approve", {"proposal_id": pid, "confirm": True, "ack_unvalidated": True}).json()
    assert ok["ok"] and ok["data"]["status"] == "approved" and ok["data"]["ack_unvalidated"] is True
    again = call(client, "approve", {"proposal_id": pid, "confirm": True})
    assert again.status_code == 200 and again.json()["ok"] is False


def test_start_bridge_requires_confirm_and_never_reaches_route(client, monkeypatch):
    from app import bridges
    called = []

    async def fake(body, request, response):
        called.append(body)
        return {"bridge_id": "b1"}
    monkeypatch.setattr(bridges, "start_bridge", fake)
    for bad in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
        r = call(client, "start_bridge", {"proposal_id": "p1", **bad}).json()
        assert r["ok"] is False and r["needs_confirmation"] and called == []
    r = call(client, "start_bridge", {"proposal_id": "p1", "confirm": True, "source": "replay"}).json()
    assert r["ok"] and called[0].proposal_id == "p1" and called[0].source == "replay" and "b1" in r["summary"]
    assert "replay" in r["summary"] and "not live" in r["summary"]


def test_account_and_positions(client):
    a = call(client, "account").json()
    assert a["ok"] and a["data"]["broker"] and "cash" in a["summary"]
    p = call(client, "positions").json()
    assert p["ok"] and p["data"] == []


@pytest.mark.parametrize("name,body", [
    ("search_markets", {}), ("search_markets", {"q": "   "}), ("fit", {}), ("fit", {"ticker": "!!"}),
    ("propose", {"ticker": "A"}), ("propose", {"ticker": "A", "shares_held": -5, "market_id": "m"}),
    ("approve", {"confirm": True}), ("approve", {"proposal_id": "zzz", "confirm": True}),
    ("start_bridge", {"proposal_id": "zzz", "confirm": True}), ("bridge_status", {"bridge_id": "zzz"}),
    ("bridge_status", {}),
])
def test_bad_input_never_500(client, name, body):
    r = call(client, name, body)
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["summary"]


def test_handler_crash_is_contained(client, monkeypatch):
    from app.broker import routes as br

    async def boom(request):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(br, "get_account", boom)
    r = call(client, "account")
    assert r.status_code == 200 and r.json()["ok"] is False and "secret" not in r.text


def test_non_object_body_is_not_500(client):
    assert client.post("/agent/tool/account", content="not json", headers={"content-type": "application/json"}).status_code < 500
    assert client.post("/agent/tool/account", json=[1, 2]).status_code < 500


def test_bridge_status_flags_fallback(client, monkeypatch):
    from app import bridges
    monkeypatch.setattr(bridges, "bridge_summary", lambda bid, request: {
        "status": "running", "source": "replay", "requested_source": "live", "account_scope": "replay_sandbox"})
    r = call(client, "bridge_status", {"bridge_id": "b1"}).json()
    assert r["ok"] and "asked for live" in r["summary"] and "replay" in r["summary"] and "intent" in r["summary"]


def test_agent_secret_enforced_when_set(client, monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_SECRET", "s3")
    assert client.post("/agent/tool/account", json={}).status_code == 401
    assert client.post("/agent/tool/account", json={}, headers={"X-Agent-Secret": "s3"}).status_code == 200
