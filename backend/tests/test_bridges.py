import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app import bridges
from app.ticks import ReplaySource, SourceError

PS = [0.20, 0.20, 0.21, 0.30, 0.30, 0.31, 0.45, 0.45, 0.46, 0.60,
      0.60, 0.61, 0.50, 0.50, 0.40, 0.40, 0.41, 0.30, 0.30, 0.31]  # 20 ticks


@pytest.fixture
def replay_file(tmp_path):
    f = tmp_path / "fixture.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_000_000_000 * (i + 1), "p": p}) + "\n" for i, p in enumerate(PS)))
    return f


@pytest.fixture
def client(replay_file):
    app = create_app()
    app.state.replay_speed = 0  # no sleeping between replayed ticks
    app.state.replay_path = str(replay_file)
    with TestClient(app) as c:  # keep one event loop so the bridge task survives between requests
        yield c


def _approved(client, tags=("material_litigation",)):
    pid = client.post("/proposals", json={"ticker": "ABNB", "tags": list(tags), "shares_held": 1200}).json()["id"]
    client.post(f"/proposals/{pid}/approve")
    return pid


def _body(pid, source="replay", **kw):
    return {"proposal_id": pid, "source": source, "market": {"source": "polymarket", "id": "m1", "token_id": "t1"}, **kw}


def _events(client, bridge_id):
    out, kind = [], None
    with client.stream("GET", f"/bridges/{bridge_id}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                out.append((kind, json.loads(line[6:])))
    return out


# --- no engine needed -------------------------------------------------------------------

def test_unknown_proposal_404(client):
    assert client.post("/bridges", json=_body("nope")).status_code == 404


def test_unapproved_409(client):
    pid = client.post("/proposals", json={"ticker": "ABNB", "tags": ["material_litigation"], "shares_held": 10}).json()["id"]
    assert client.post("/bridges", json=_body(pid)).status_code == 409


def test_opportunity_never_reaches_hedgecore(client):
    pid = _approved(client, tags=("workforce_reduction",))
    r = client.post("/bridges", json=_body(pid))
    assert r.status_code == 409 and "single simulated options order" in r.json()["detail"]


def test_no_engine_returns_503(client, monkeypatch):
    monkeypatch.setattr(bridges, "_load_engine", lambda: None)
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid))
    assert r.status_code == 503 and r.json()["detail"] == "engine not installed (uv sync --group engine)"


def test_unknown_bridge_404(client):
    assert client.get("/bridges/nope").status_code == 404
    assert client.get("/bridges/nope/stream").status_code == 404


async def _collect(src):
    return [t async for t in src]


def test_replay_source_reads_jsonl(replay_file):
    import asyncio
    ticks = asyncio.run(_collect(ReplaySource(replay_file, speed=0)))
    assert len(ticks) == 20 and ticks[0] == (1_000_000_000, 0.20)


# --- needs hedgecore (engine group / CI engine job) ---------------------------------------

hedgecore = pytest.importorskip("hedgecore")


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
