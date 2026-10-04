import json

import pytest

from app.ticks import SourceError

hedgecore = pytest.importorskip("hedgecore")

from tests.test_bridges import _approved, _body, _events, client, replay_file, write_meta  # noqa: E402,F401


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
    _events(client, first.json()["bridge_id"])
    client.app.state.bridges[pid].status = "running"  # as if still running (replays at speed 0 finish at once)
    again = client.post("/bridges", json=_body(pid))
    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    assert client.post("/bridges", json=_body(pid, source="live")).status_code == 409
    assert len(client.app.state.bridges) == 1


def test_a_finished_bridge_is_never_handed_back_a_new_post_starts_a_fresh_run_not_a_fresh_budget(client):
    pid = _approved(client)
    first = client.post("/bridges", json=_body(pid)).json()["bridge_id"]
    assert _events(client, first)[-1][1]["status"] == "finished"
    again = client.post("/bridges", json=_body(pid))
    assert again.status_code == 201 and again.json()["bridge_id"] != first
    ev = _events(client, again.json()["bridge_id"])
    assert [k for k, _ in ev].count("tick") == 20  # a full fresh run, not the old history in one burst
    assert client.app.state.bridges[pid].id == again.json()["bridge_id"]
    assert client.get(f"/bridges/{first}").json()["status"] == "finished"  # the old run is still readable by id
    # fresh events, but not a fresh budget: the run starts from what earlier runs left at the account (none here:
    # replay sandbox), see test_bridges_restart_and_replay_lookup for the cap across restarts
    assert (client.get(f"/bridges/{again.json()['bridge_id']}").json()["account_hedge"]
            == client.get(f"/bridges/{first}").json()["account_hedge"] == 0.0)
    # a stopped one (e.g. a live source that failed) can be restarted too, with another source
    client.app.state.bridges[pid].status = "stopped"
    assert client.post("/bridges", json=_body(pid, source="live")).status_code == 201


class _FailingLive:
    def __init__(self, *_, **__):
        pass

    async def __aiter__(self):
        raise SourceError("network down")
        yield  # pragma: no cover


def test_live_failure_switches_to_replay(client, replay_file):
    client.app.state.live_source_factory = _FailingLive
    own = replay_file.with_name("m1.jsonl")  # a recording of THIS market (replays/<market id>.jsonl naming)
    own.write_text(replay_file.read_text())
    client.app.state.replay_path = str(own)
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    ev = _events(client, bid)
    kinds = [k for k, _ in ev]
    assert kinds[0] == "error" and "network down" in ev[0][1]["message"]
    assert kinds.count("tick") == 20 and ev[-1][1]["status"] == "finished"
    s = client.get(f"/bridges/{bid}").json()
    assert s["source"] == "replay" and s["replay_file"] == "m1.jsonl" and s["replay_market"] is None


def test_live_failure_never_replays_another_markets_recording(client):
    client.app.state.live_source_factory = _FailingLive  # replay_path is fixture.jsonl: not market m1's recording
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    ev = _events(client, bid)
    assert [k for k, _ in ev] == ["error", "status"]
    assert ev[-1][1] == {"status": "stopped", "reason": "source_failed"}
    assert client.get(f"/bridges/{bid}").json()["source"] == "live"


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


def test_market_event_proposal_runs_a_bridge(client):
    from tests.test_api import UI_MARKET_BODY
    p = client.post("/proposals", json=UI_MARKET_BODY).json()
    assert client.post("/bridges", json={"proposal_id": p["id"], "source": "replay", "gap_per_share": 1.0}).status_code == 409
    client.post(f"/proposals/{p['id']}/approve", json={"ack_unvalidated": True})
    # the body's direction/market are ignored: the proposal's own market and direction drive the engine
    body = {"proposal_id": p["id"], "source": "replay", "gap_per_share": 1.0, "direction": "up_on_yes",
            "market": {"source": "polymarket", "id": "fed-hike-25bps-oct-2026"}, "replay_file": "fixture.jsonl"}
    r = client.post("/bridges", json=body)
    assert r.status_code == 201
    bid = r.json()["bridge_id"]
    ev = _events(client, bid)
    decisions = [d for k, d in ev if k == "decision"]
    assert decisions[0]["order_qty"] == pytest.approx(0.5 * 400 * 0.20)  # down_on_yes: engine sees p
    s = client.get(f"/bridges/{bid}").json()
    assert s["direction"] == "down_on_yes" and s["market"]["id"] == "2589813" and s["basis"] == "market_event"
    assert s["label"] == "Product hedge, not a tested claim"
    client.app.state.bridges[p["id"]].status = "running"  # as if still running
    assert client.post("/bridges", json=body).status_code == 200
    assert client.post("/bridges", json={**body, "source": "live"}).status_code == 409


def test_summary_carries_shares_and_coverage(client):
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, gap_per_share=1.0)).json()["bridge_id"]
    _events(client, bid)
    s = client.get(f"/bridges/{bid}").json()
    assert s["shares_held"] == 1200 and s["target_coverage"] == 0.5
    assert s["coverage"] == pytest.approx(s["hedge"] / 1200)


# --- the configured replay file must record the requested market ------------------------------------------------

def test_replay_of_another_markets_file_is_a_422(client, replay_file):
    """POLYBRIDGE_REPLAY_PATH recording market X is never replayed under market m1's title, named or not."""
    write_meta(replay_file, {"source": "polymarket", "id": "2589813", "token_id": "tokFED"})
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid))  # names fixture.jsonl, but its sidecar says another market
    assert r.status_code == 422 and "polymarket:2589813" in r.json()["detail"] and "polymarket:m1" in r.json()["detail"]
    assert not getattr(client.app.state, "bridges", {})  # nothing started


def test_replay_whose_sidecar_names_the_market_runs_and_reports_it(client, replay_file):
    write_meta(replay_file, {"source": "polymarket", "id": "m1", "token_id": "t1"})
    pid = _approved(client)
    body = {k: v for k, v in _body(pid).items() if k != "replay_file"}  # no explicit name needed
    r = client.post("/bridges", json=body)
    assert r.status_code == 201, r.text
    _events(client, r.json()["bridge_id"])
    s = client.get(f"/bridges/{r.json()['bridge_id']}").json()
    assert s["replay_file"] == "fixture.jsonl"
    assert s["replay_market"] == {"source": "polymarket", "id": "m1", "token_id": "t1"}


def test_matching_by_token_id_alone(client, replay_file):
    write_meta(replay_file, {"source": "polymarket", "token_id": "t1"})
    pid = _approved(client)
    body = {k: v for k, v in _body(pid).items() if k != "replay_file"}
    assert client.post("/bridges", json=body).status_code == 201


def test_unknown_market_file_needs_the_request_to_name_it(client):
    pid = _approved(client)
    body = {k: v for k, v in _body(pid).items() if k != "replay_file"}
    r = client.post("/bridges", json=body)  # fixture.jsonl has no sidecar and the request does not name it
    assert r.status_code == 422 and "sidecar" in r.json()["detail"]
    r = client.post("/bridges", json={**body, "replay_file": "other.jsonl"})  # naming a different file does not count
    assert r.status_code == 422
    r = client.post("/bridges", json={**body, "replay_file": "fixture.jsonl"})
    assert r.status_code == 201
    s = client.get(f"/bridges/{r.json()['bridge_id']}").json()
    assert s["replay_file"] == "fixture.jsonl" and s["replay_market"] is None


def test_live_bridge_summary_has_no_replay_file(client):
    client.app.state.live_source_factory = _FailingLive
    client.app.state.replay_path = None
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    _events(client, bid)
    s = client.get(f"/bridges/{bid}").json()
    assert s["replay_file"] is None and s["replay_market"] is None


def test_live_fallback_follows_the_sidecar(client, replay_file):
    """A live bridge falls back to the configured file when its sidecar names this market (whatever the file is
    called), and never to a file whose sidecar names another market (even one named like this market)."""
    client.app.state.live_source_factory = _FailingLive
    write_meta(replay_file, {"source": "polymarket", "id": "m1"})
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    _events(client, bid)
    s = client.get(f"/bridges/{bid}").json()
    assert s["source"] == "replay" and s["replay_market"] == {"source": "polymarket", "id": "m1", "token_id": None}

    own = replay_file.with_name("m1.jsonl")
    own.write_text(replay_file.read_text())
    write_meta(own, {"source": "kalshi", "id": "KXOTHER"})
    client.app.state.replay_path = str(own)
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, source="live")).json()["bridge_id"]
    ev = _events(client, bid)
    assert ev[-1][1] == {"status": "stopped", "reason": "source_failed"}
