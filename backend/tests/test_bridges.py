import json
import time

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
    assert len(ticks) == 20 and ticks[0][1] == 0.20
    assert all(abs(t - time.time_ns()) < 5e9 for t, _ in ticks)  # stamped on the wall clock




def test_replay_source_skips_non_finite_and_shifts_time(tmp_path):
    import asyncio
    f = tmp_path / "r.jsonl"
    f.write_text('{"ts_ns": 5, "p": 0.1}\n{"ts_ns": 6, "p": NaN}\n{"ts_ns": 2000000005, "p": 0.2}\n')
    ticks = asyncio.run(_collect(ReplaySource(f, speed=1000)))  # 2 s gap -> 2 ms
    assert [p for _, p in ticks] == [0.1, 0.2]
    assert 1_500_000 <= ticks[1][0] - ticks[0][0] <= 50_000_000
    assert abs(ticks[0][0] - time.time_ns()) < 5e9


def test_replay_market_id_is_sanitized(client, monkeypatch):
    monkeypatch.setattr(bridges, "_load_engine", lambda: object())
    client.app.state.replay_path = None
    pid = _approved(client)
    bad = _body(pid)
    bad["market"]["id"] = "../../etc/passwd"
    assert client.post("/bridges", json=bad).status_code == 422


def test_invalid_direction_422(client):
    pid = _approved(client)
    assert client.post("/bridges", json=_body(pid, direction="sideways")).status_code == 422
