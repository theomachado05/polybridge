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
    # fixture.jsonl has no .meta.json sidecar (its market is unknown), so a replay request names it explicitly
    named = {"replay_file": "fixture.jsonl"} if source == "replay" else {}
    return {"proposal_id": pid, "source": source, "market": {"source": "polymarket", "id": "m1", "token_id": "t1"},
            **named, **kw}


def write_meta(path, market: dict):
    """The replay file's sidecar: which market it records."""
    path.with_name(path.name + ".meta.json").write_text(json.dumps(
        {"source": market["source"], "id": market.get("id"), "token_id": market.get("token_id")}))


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


def test_replay_source_rebases_only_on_real_lateness(tmp_path, monkeypatch):
    """Sub-threshold sleep overshoot keeps the recorded schedule; a slow consumer (> 50 ms) shifts it."""
    import asyncio
    from types import SimpleNamespace

    from app import ticks as ticks_mod

    f = tmp_path / "r.jsonl"
    f.write_text("".join(f'{{"ts_ns": {i * 1_000_000_000}, "p": 0.{i + 1}}}\n' for i in range(4)))
    clock = {"now": 10_000_000_000_000}
    monkeypatch.setattr(ticks_mod, "time", SimpleNamespace(time_ns=lambda: clock["now"], monotonic=time.monotonic))

    async def fake_sleep(s):  # every sleep overshoots by 20 ms (below the re-base threshold)
        clock["now"] += int(s * 1e9) + 20_000_000

    monkeypatch.setattr(ticks_mod.asyncio, "sleep", fake_sleep)
    start = clock["now"]

    async def run(slow_after=None):
        out = []
        async for t in ReplaySource(f, speed=1):
            out.append(t[0])
            if slow_after == len(out):
                clock["now"] += 5_000_000_000  # the consumer stalls 5 s
        return out

    out = asyncio.run(run())
    assert [x - start for x in out] == [0, 1_000_000_000, 2_000_000_000, 3_000_000_000]  # no drift from jitter
    clock["now"] = start
    out = asyncio.run(run(slow_after=1))
    # tick 2 is handed over 5 s late: stamped now, and the gaps after it keep their exact 1 s spacing
    assert [x - start for x in out] == [0, 5_000_000_000, 6_000_000_000, 7_000_000_000]


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


def test_market_event_proposal_needs_approval_no_engine(client, monkeypatch):
    from tests.test_api import UI_MARKET_BODY
    monkeypatch.setattr(bridges, "_load_engine", lambda: None)
    pid = client.post("/proposals", json=UI_MARKET_BODY).json()["id"]
    assert client.post("/bridges", json={"proposal_id": pid, "source": "replay"}).status_code == 409
    client.post(f"/proposals/{pid}/approve")
    assert client.post("/bridges", json={"proposal_id": pid, "source": "replay"}).status_code == 503  # no market needed


def test_filing_proposal_still_needs_market(client):
    pid = _approved(client)
    assert client.post("/bridges", json={"proposal_id": pid, "source": "replay"}).status_code == 422


def test_high_speed_replay_of_hourly_history_is_never_stale(tmp_path):
    """Demo setting: hourly Polymarket history at 36000x (one tick per 0.1 s). Ticks are stamped on the wall clock,
    so the engine's staleness check (2 s) compares delivery time, never the 1 h gap in the recorded history."""
    import asyncio
    f = tmp_path / "hourly.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_788_415_213_000_000_000 + i * 3_600_000_000_000, "p": 0.2 + 0.01 * i}) + "\n"
                         for i in range(6)))

    async def go():
        out = []
        async for ts, p in ReplaySource(f, speed=36000):
            out.append((ts, time.time_ns()))
        return out
    got = asyncio.run(go())
    assert len(got) == 6
    assert all(0 <= now - ts < 2_000_000_000 for ts, now in got)  # fresh vs. the default max_staleness_ns
    gaps = [b[0] - a[0] for a, b in zip(got, got[1:])]
    assert all(80_000_000 <= g <= 400_000_000 for g in gaps)  # 1 h / 36000 = 0.1 s


# --- replay sidecars (no engine needed) ---------------------------------------------------------------------------

def test_replay_meta_and_matching(tmp_path):
    from app.models import MarketRef
    f = tmp_path / "x.jsonl"
    f.write_text("")
    assert bridges.replay_meta(f) is None
    f.with_name("x.jsonl.meta.json").write_text("not json")
    assert bridges.replay_meta(f) is None
    f.with_name("x.jsonl.meta.json").write_text(json.dumps({"source": "polymarket"}))  # no id / token: unknown
    assert bridges.replay_meta(f) is None
    write_meta(f, {"source": "polymarket", "id": "2589813", "token_id": "tok"})
    meta = bridges.replay_meta(f)
    assert meta == {"source": "polymarket", "id": "2589813", "token_id": "tok"}
    m = bridges._meta_matches
    assert m(meta, MarketRef(source="polymarket", id="2589813"))
    assert m(meta, MarketRef(source="polymarket", id="other", token_id="tok"))
    assert m(meta, MarketRef(source="polymarket", id="tok"))  # a market given by its token id
    assert not m(meta, MarketRef(source="kalshi", id="2589813"))
    assert not m(meta, MarketRef(source="polymarket", id="2589812", token_id="tok2"))


def test_check_replay_market(tmp_path):
    from fastapi import HTTPException
    from app.models import MarketRef
    f = tmp_path / "fed-history.jsonl"
    f.write_text("")
    fed = MarketRef(source="polymarket", id="fed")
    bridges._check_replay_market(f, fed, None)  # no sidecar, but the stem is "<market id>-history": named
    with pytest.raises(HTTPException) as e:
        bridges._check_replay_market(f, MarketRef(source="polymarket", id="m1"), None)
    assert e.value.status_code == 422 and "sidecar" in e.value.detail
    bridges._check_replay_market(f, MarketRef(source="polymarket", id="m1"), "fed-history.jsonl")  # named
    write_meta(f, {"source": "polymarket", "id": "2589813"})
    with pytest.raises(HTTPException) as e:  # the sidecar wins over the name
        bridges._check_replay_market(f, fed, "fed-history.jsonl")
    assert e.value.status_code == 422 and "polymarket:2589813" in e.value.detail
    bridges._check_replay_market(f, MarketRef(source="polymarket", id="2589813"), None)


def test_committed_replays_carry_sidecars():
    """Every recording in backend/replays/ says which market it records, with its YES token id."""
    expected = {"fed-hike-25bps-oct-2026": "2589813", "another-fed-hike-2026": "4620900",
                "russia-eu-military-2026": "4713962", "nvda-230-sep-2026": "3961215",
                "us-recession-in-2025-weekend": "516710"}
    files = sorted(bridges.REPLAYS_DIR.glob("*.jsonl"))
    assert files
    for f in files:
        meta = bridges.replay_meta(f)
        assert meta is not None, f.name
        want = next((mid for prefix, mid in expected.items() if f.name.startswith(prefix)), None)
        assert want is not None, f"{f.name}: add it to this test with the market id its sidecar names"
        assert meta["source"] == "polymarket" and meta["id"] == want and meta["token_id"], f.name


def test_demo_replays_are_indexed_for_their_market():
    """The default demo replay and the Russia/ITA alternative are found for their own market (the fit's offline
    fallback and a live bridge's fallback), and never for another market."""
    from app.models import MarketRef
    from app.pipeline.ticks import replay_points
    pts, name = replay_points("polymarket", "4620900")
    assert name == "another-fed-hike-2026-history.jsonl" and len(pts) >= 400
    pts, name = replay_points("polymarket", "4713962")
    assert name == "russia-eu-military-2026-history.jsonl" and len(pts) >= 340
    assert bridges._meta_matches(bridges.replay_meta(bridges.REPLAYS_DIR / "another-fed-hike-2026-history.jsonl"),
                                 MarketRef(source="polymarket", id="4620900"))
    assert not bridges._meta_matches(bridges.replay_meta(bridges.REPLAYS_DIR / "another-fed-hike-2026-history.jsonl"),
                                     MarketRef(source="polymarket", id="2589813"))
