from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_bridges import _events
from tests.test_closed_bridge import approved, fake_engine, make_client, research_rate, write_rows  # noqa: F401
from tests.test_closed_staged import approved_proposal, make_app


def test_no_staged_plan_on_an_unvalidated_market_without_the_override(tmp_path, fake_engine, research_rate):
    f = write_rows(tmp_path / "wk.jsonl")
    with make_client(tmp_path, f) as c:
        pid = approved(c, override=False)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
    assert orders == []
    refused = [d for k, d in ev if k == "staged" and d.get("event") == "refused"]
    assert len(refused) == 1 and refused[0]["reason"] == "EVIDENCE_GATE"
    assert "act_on_unvalidated" in refused[0]["detail"] and refused[0]["evidence"]["validated"] is False
    assert s["closed_mode"]["plan_note"].startswith("EVIDENCE_GATE")
    assert "plan_refused" in [r["event"] for r in s["closed_mode"]["timeline"]]
    assert s["evidence_label"] == "unvalidated (acknowledged)" and s["act_on_unvalidated"] is False
    assert all(d.get("evidence") == "unvalidated (acknowledged)" for k, d in ev if k in ("decision", "fill"))


def test_the_bridge_can_set_the_override_on_an_acknowledged_proposal(tmp_path, fake_engine, research_rate):
    f = write_rows(tmp_path / "wk.jsonl")
    with make_client(tmp_path, f) as c:
        pid = approved(c, override=False)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay",
                                       "act_on_unvalidated": True}).json()["bridge_id"]
        _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
    assert s["act_on_unvalidated"] is True
    assert len(orders) == 1 and orders[0]["evidence_gate"] == "override"
    assert orders[0]["evidence"]["override"] is True and "EVIDENCE_OVERRIDE" in [d["code"] for d in orders[0]["decisions"]]


def test_post_staged_plan_refuses_an_unvalidated_market_without_the_override(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app, override=False)
    with TestClient(app) as c:
        r = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "rate_bp_per_pp": 7.5})
        assert r.status_code == 409 and r.json()["detail"].startswith("EVIDENCE_GATE")
        assert c.get("/staged").json()["orders"] == []
    ok = approved_proposal(app, override=True)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": ok.id, "pm_move_pp": 5.0, "rate_bp_per_pp": 7.5}).json()
        assert o["evidence_gate"] == "override"


def test_a_bridge_on_an_unvalidated_market_needs_the_acknowledged_approval(tmp_path, fake_engine):
    from app.models import MarketRef
    f = write_rows(tmp_path / "wk.jsonl")
    with make_client(tmp_path, f) as c:
        store = c.app.state.store
        p = store.propose(ticker="SPY", family="hedge", strategy="s", shares_held=100, target_coverage=0.5,
                          basis="market_event", market=MarketRef(source="polymarket", id="m-closed",
                                                                 token_id="tok-closed"), direction="down_on_yes")
        store.approve(p.id)
        r = c.post("/bridges", json={"proposal_id": p.id, "source": "replay"})
        assert r.status_code == 409 and r.json()["detail"].startswith("EVIDENCE_UNVALIDATED")


def test_the_proposal_override_counts_only_when_the_approval_acknowledged_it(tmp_path):
    recession = {"source": "polymarket", "id": "516710"}
    app = make_app(tmp_path)
    with TestClient(app) as c:
        p = c.post("/proposals", json={"ticker": "SPY", "market": recession, "direction": "down_on_yes",
                                       "shares_held": 1000, "act_on_unvalidated": True}).json()
        assert p["evidence"]["validated"] is True and p["act_on_unvalidated"] is True
        a = c.post(f"/proposals/{p['id']}/approve")
        assert a.status_code == 200 and a.json()["ack_unvalidated"] is False
        r = c.post("/staged/plan", json={"proposal_id": p["id"], "pm_move_pp": 8.0, "rate_bp_per_pp": 7.5})
        assert r.status_code == 409 and r.json()["detail"].startswith("EVIDENCE_GATE")
        assert "approved without ack_unvalidated" in r.json()["detail"]
        assert c.get("/staged").json()["orders"] == []
        q = c.post("/proposals", json={"ticker": "SPY", "market": recession, "direction": "down_on_yes",
                                       "shares_held": 1000, "act_on_unvalidated": True}).json()
        b = c.post(f"/proposals/{q['id']}/approve", json={"ack_unvalidated": True})
        assert b.status_code == 200 and b.json()["ack_unvalidated"] is True
        o = c.post("/staged/plan", json={"proposal_id": q["id"], "pm_move_pp": 8.0, "rate_bp_per_pp": 7.5})
        assert o.status_code == 201 and o.json()["evidence_gate"] == "override"
