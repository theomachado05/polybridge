"""Voice tools for the micro-markets product (ladders, tickets, evidence): read-only, speakable, never a 500."""
import pytest
from fastapi.testclient import TestClient

from app.agent import tools as T
from app.main import create_app

TICKETS = {"ok": True, "counts": {"tickets": 3, "linked": 2, "decided_by": "engine"},
           "evidence": {"touch_ticket": {"id": "touch", "status": "OPEN_LEAD", "status_label": "Open lead: unvalidated"}},
           "tickets": [
               {"id": "t1", "question": "Will AAPL hit $320?", "type": "touch_ticket", "best_bid": 0.55, "best_ask": 0.57,
                "reference": {"available": True, "touch": {"mid": 0.497, "lo": 0.431, "hi": 0.562},
                              "session_label": "Friday's close"},
                "engine": {"family": "touch_ticket_reference", "source": "engine", "action": "propose",
                           "reason": "bid_above_reference", "latency_ns": 41}},
               {"id": "t2", "question": "Will SPY hit $700?", "type": "touch_ticket", "best_bid": 0.10, "best_ask": 0.12,
                "reference": {"available": True, "touch": {"mid": 0.2, "lo": 0.15, "hi": 0.25}}},
               {"id": "t3", "question": "Will EWY hit $190?", "type": "touch_ticket", "best_bid": 0.1, "best_ask": 0.9,
                "reference": {"available": False, "reason": "budget"}}]}
LADDERS = {"ok": True, "counts": {"ladders": 5, "pairs": 5, "nested_pairs": 2, "violations": 0, "actionable": 0,
                                  "decided_by": "engine"},
           "evidence": {"id": "ladders", "status_label": "Lead: not validated"},
           "ladders": [{"event_title": "Fed rate cut by...?"}]}


@pytest.fixture
def client(monkeypatch):
    from app.contracts import router as cr

    async def tickets():
        return TICKETS

    async def ladders():
        return LADDERS
    monkeypatch.setattr(cr, "tickets", tickets)
    monkeypatch.setattr(cr, "ladders", ladders)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def call(c, name, body=None):
    r = c.post(f"/agent/tool/{name}", json=body or {})
    assert r.status_code == 200
    return r.json()


def test_gap_matches_the_web_ticket_gap():
    assert T.ticket_gap(TICKETS["tickets"][0]) == pytest.approx(100 * (0.56 - 0.497))
    assert T.ticket_gap(TICKETS["tickets"][2]) is None


def test_show_ladders_summarises_counts_and_status(client):
    j = call(client, "show_ladders")
    assert j["ok"] and "5 date ladders" in j["summary"] and "C++ engine" in j["summary"]
    assert "Lead: not validated" in j["summary"]


def test_show_tickets_above_reference(client):
    j = call(client, "show_tickets", {"filter": "above_reference"})
    assert j["ok"] and "3 open tickets" in j["summary"] and "2 priced" in j["summary"] and "1 above it" in j["summary"]
    assert "AAPL" in j["summary"] and "+6.3 points" in j["summary"]
    assert [t["id"] for t in j["data"]["tickets"]] == ["t1"] and "Open lead: unvalidated" in j["summary"]


def test_explain_ticket_reads_decision_band_and_status(client):
    j = call(client, "explain_ticket", {"ticket_id": "t1"})
    s = j["summary"]
    assert j["ok"] and "C++ engine" in s and "41 nanoseconds" in s and "propose" in s
    assert "49.7 cents" in s and "43.1 cents to 56.2 cents" in s and "Open lead: unvalidated" in s and "nothing is sent" in s
    miss = call(client, "explain_ticket", {"ticket_id": "nope"})
    assert miss["ok"] is False and "cannot find ticket nope" in miss["summary"]
    assert call(client, "explain_ticket", {})["ok"] is False


def test_evidence_tools_read_the_real_registry(client):
    j = call(client, "explain_mechanism", {"mechanism_id": "foundation"})
    assert j["ok"] and "Confirmed foundation" in j["summary"] and "sample" in j["summary"] and "range" in j["summary"]
    w = call(client, "what_we_tested")
    assert w["ok"] and "None of them is a validated trading edge" in w["summary"]
    bad = call(client, "explain_mechanism", {"mechanism_id": "zzz"})
    assert bad["ok"] is False and "foundation" in bad["summary"]


def test_board_down_is_speakable(client, monkeypatch):
    from app.contracts import router as cr

    async def down():
        return {"ok": False, "error": "upstream timeout"}
    monkeypatch.setattr(cr, "tickets", down)
    j = call(client, "show_tickets")
    assert j["ok"] is False and "not available" in j["summary"] and "upstream timeout" in j["summary"]


def test_navigate_knows_the_product_screens(client):
    for s in ("ladders", "tickets", "tested"):
        assert call(client, "navigate", {"screen": s})["ok"]


def test_public_web_host_accepts_a_comma_separated_list(monkeypatch):
    from app.agent import elevenlabs as el
    monkeypatch.setenv("PUBLIC_WEB_HOST", "https://abc.ngrok-free.dev/, localhost:3041")
    assert el.web_hosts() == ["localhost:3000", "127.0.0.1:3000", "abc.ngrok-free.dev", "localhost:3041"]
