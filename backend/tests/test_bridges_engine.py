import json

import pytest

from app.ticks import SourceError

hedgecore = pytest.importorskip("hedgecore")

from tests.test_bridges import _approved, _body, _events, client, replay_file  # noqa: E402,F401


def test_replay_bridge_end_to_end(client):
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid, gap_per_share=1.0))
    assert r.status_code == 201
    bid = r.json()["bridge_id"]
    ev = _events(client, bid)
    kinds = [k for k, _ in ev]
    assert kinds.count("tick") == 20 and kinds.count("decision") == 20
    assert kinds[-1] == "status" and ev[-1][1]["status"] == "finished"
    decisions = [d for k, d in ev if k == "decision"]
    assert decisions[0]["action"] == "order" and decisions[0]["order_qty"] == 120.0  # 0.5*1200*0.20
    orders = [d for d in decisions if d["action"] == "order"]
    positions = [d for k, d in ev if k == "position"]
    assert len(orders) >= 2 and len(positions) == len(orders)  # a position follows every order (simulated fill)
    assert positions[-1]["hedge"] == pytest.approx(sum(o["order_qty"] for o in orders))
    assert positions[-1]["coverage"] == pytest.approx(positions[-1]["hedge"] / 1200)
    s = client.get(f"/bridges/{bid}").json()
    assert s["ticks"] == 20 and s["orders"] == len(orders) and s["status"] == "finished"
    assert sum(s["reasons"].values()) == 20 and s["latency_ns"]["p50"] is not None
    assert client.get("/proposals").json()[0]["bridge_started_at"]


def test_fee_gate_reaches_the_stream(client):
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, gap_per_share=0.0001)).json()["bridge_id"]
    reasons = {d["reason"] for k, d in _events(client, bid) if k == "decision"}
    assert "below_fees" in reasons


def test_start_is_idempotent_per_proposal(client):
    pid = _approved(client)
    first = client.post("/bridges", json=_body(pid))
    again = client.post("/bridges", json=_body(pid))
    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    assert client.post("/bridges", json=_body(pid, source="live")).status_code == 409
    assert len(client.app.state.bridges) == 1


class _FailingLive:
    def __init__(self, *_):
        pass

    async def __aiter__(self):
        raise SourceError("network down")
        yield  # pragma: no cover


def test_live_failure_switches_to_replay(client):
    client.app.state.live_source_factory = _FailingLive
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    ev = _events(client, bid)
    kinds = [k for k, _ in ev]
    assert kinds[0] == "error" and "network down" in ev[0][1]["message"]
    assert kinds.count("tick") == 20 and ev[-1][1]["status"] == "finished"
    assert client.get(f"/bridges/{bid}").json()["source"] == "replay"


def test_live_failure_without_replay_stops(client):
    client.app.state.live_source_factory = _FailingLive
    client.app.state.replay_path = None
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    ev = _events(client, bid)
    assert [k for k, _ in ev] == ["error", "status"]
    assert ev[-1][1] == {"status": "stopped", "reason": "source_failed"}
    assert client.get(f"/bridges/{bid}").json()["status"] == "stopped"


def test_up_on_yes_hedges_the_no_outcome(client):
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, gap_per_share=1.0, direction="up_on_yes")).json()["bridge_id"]
    ev = _events(client, bid)
    ticks = [d["p"] for k, d in ev if k == "tick"]
    assert ticks[0] == 0.20  # tick events keep the market's raw p
    decisions = [d for k, d in ev if k == "decision"]
    assert decisions[0]["order_qty"] == pytest.approx(480.0)  # 0.5*1200*(1-0.20)
    assert client.get(f"/bridges/{bid}").json()["direction"] == "up_on_yes"
    later = [i for i, d in enumerate(decisions) if d["action"] == "order" and i > 0]
    assert any(ticks[i] < ticks[i - 1] for i in later) or any(d["target_hedge"] > 480 for d in decisions)


def test_default_direction_unchanged(client):
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, gap_per_share=1.0)).json()["bridge_id"]
    _events(client, bid)
    assert client.get(f"/bridges/{bid}").json()["direction"] == "down_on_yes"
