"""End-to-end demo path: Fed market -> mapped ticker -> market-event proposal -> approve -> replay bridge -> SSE
-> summary (needs hedgecore)."""
import json

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("hedgecore")

from app.main import create_app  # noqa: E402

PS = [round(0.20 + 0.015 * i, 3) for i in range(30)]  # 30 rising ticks: the hedge must be sized and grow
MAX_LINES = 500  # bound on SSE lines read


@pytest.fixture
def client(tmp_path, monkeypatch):
    f = tmp_path / "fed.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_000_000_000 * (i + 1), "p": p}) + "\n" for i, p in enumerate(PS)))
    monkeypatch.setenv("POLYBRIDGE_REPLAY_PATH", str(f))
    monkeypatch.setenv("POLYBRIDGE_REPLAY_SPEED", "0")  # no sleeping between ticks
    with TestClient(create_app()) as c:
        yield c


def _read_stream(client, bridge_id):
    events, kind = [], None
    with client.stream("GET", f"/bridges/{bridge_id}/stream") as r:
        for n, line in enumerate(r.iter_lines()):
            if n > MAX_LINES:
                break
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                events.append((kind, json.loads(line[6:])))
    return events


def test_market_event_propose_approve_bridge_stream(client):
    fed = {"source": "polymarket", "id": "2589813"}
    m = client.post("/map", json={"question": "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
                                  "source": "polymarket", "market_id": "2589813"}).json()
    item = next(i for i in m["items"] if i["ticker"] == "SPY")

    p = client.post("/proposals", json={"ticker": "SPY", "market": fed, "direction": item["direction"],
                                        "shares_held": 100, "target_coverage": 0.5})
    assert p.status_code == 201 and p.json()["family"] == "hedge" and p.json()["basis"] == "market_event"
    assert p.json()["shares_held"] == 100
    pid = p.json()["id"]
    assert client.post(f"/proposals/{pid}/approve").json()["status"] == "approved"

    body = {"proposal_id": pid, "source": "replay", "gap_per_share": 1.0}
    r = client.post("/bridges", json=body)
    assert r.status_code == 201
    bid = r.json()["bridge_id"]

    events = _read_stream(client, bid)
    kinds = [k for k, _ in events]
    assert "decision" in kinds and "position" in kinds
    assert kinds.count("tick") == 30

    s = client.get(f"/bridges/{bid}").json()
    assert s["ticks"] == 30 and s["orders"] >= 1 and s["status"] == "finished"
    assert sum(s["reasons"].values()) == 30

    again = client.post("/bridges", json=body)
    assert again.status_code == 200 and again.json()["bridge_id"] == bid
