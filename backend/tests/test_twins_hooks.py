from __future__ import annotations

import json
import math
import time

import numpy as np
import pytest

from app.pipeline.ticks import available_requirements, build_ticks
from app.ticks import Tick
from app.twins import store
from app.twins.overlay import MAX_STALE_S, asof_join, overlay_other_venue
from tests.test_bridges import _events, client, replay_file  # noqa: F401
from tests.test_bridges_algo import FED, fake_hc, proposal  # noqa: F401
from tests.test_broker_support import run
from tests.test_pipeline import N_POINTS, T0, FakeMassive, Router, candles, history, mock_http

GAMMA = {"clobTokenIds": '["tokYES", "tokNO"]', "question": "q"}
K_MARKET = {"event_ticker": "KXTWIN-26", "title": "Twin?"}
K_EVENT = {"series_ticker": "KXTWIN"}


def entry(pid, tok, ticker, direction="same"):
    return {"polymarket": {"id": pid, "token_id": tok, "question": "q"}, "kalshi": {"ticker": ticker, "question": "q"},
            "direction": direction, "verification": {"verified_at": "2026-10-03T00:00:00Z", "note": "n", "checks": {}}}


@pytest.fixture
def twin_map(tmp_path, monkeypatch):
    def install(*pairs):
        p = tmp_path / "twins.json"
        p.write_text(json.dumps({"schema": 1, "pairs": list(pairs)}))
        monkeypatch.setattr(store, "DEFAULT_PATH", p)
        return p
    install()
    return install


def test_asof_join_is_causal_and_bounded():
    other = [(1000, 0.40), (2000, 0.50), (2000 + MAX_STALE_S + 500, 0.60)]
    out = asof_join([500, 1000, 1500, 2000, 2000 + MAX_STALE_S, 2000 + MAX_STALE_S + 1], other)
    assert math.isnan(out[0])
    assert out[1] == 0.40 and out[2] == 0.40 and out[3] == 0.50
    assert out[4] == 0.50
    assert math.isnan(out[5])
    assert asof_join([10], [(5, float("nan"))])[0] != asof_join([10], [(5, float("nan"))])[0]


def twinned_router(**kw):
    return Router(prices=history(), gamma=GAMMA, kalshi_market=K_MARKET, kalshi_event=K_EVENT, candles=candles(), **kw)


def test_polymarket_market_with_a_kalshi_twin_meets_both_venues(twin_map):
    twin_map(entry("777", "tokYES", "KXTWIN-26-T1"))
    r = twinned_router()
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(r), massive=lambda: FakeMassive()))
    pov = ts.ticks["p_other_venue"]
    assert np.isfinite(pov).sum() >= N_POINTS - 2
    assert pov[0] == pytest.approx(0.32)
    assert "both_venues" in available_requirements(ts)
    assert any("p_other_venue from kalshi twin KXTWIN-26-T1" in n for n in ts.notes)
    assert any(q.url.path == "/trade-api/v2/series/KXTWIN/markets/KXTWIN-26-T1/candlesticks" for q in r.requests)
    assert ts.source == "live_history" and ts.has_underlying


def test_market_without_a_twin_keeps_both_venues_unmet(twin_map):
    twin_map(entry("999", "tokOther", "KXTWIN-26-T1"))
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(twinned_router()),
                         massive=lambda: FakeMassive()))
    assert np.isnan(ts.ticks["p_other_venue"]).all()
    assert "both_venues" not in available_requirements(ts)
    assert not any("twin" in n for n in ts.notes)


def test_unverified_pairs_never_feed_p_other_venue(twin_map):
    twin_map(entry("777", "tokYES", "KXTWIN-26-T1", direction="inverted"))
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(twinned_router()),
                         massive=lambda: FakeMassive()))
    assert "both_venues" not in available_requirements(ts)


def test_twin_history_failure_degrades_to_nan_with_a_note(twin_map):
    twin_map(entry("777", "tokYES", "KXTWIN-26-T1"))
    r = Router(prices=history(), gamma=GAMMA, kalshi_market=K_MARKET, kalshi_event=K_EVENT, candles=None)
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(r), massive=lambda: FakeMassive()))
    assert ts.source == "live_history" and ts.n == N_POINTS
    assert np.isnan(ts.ticks["p_other_venue"]).all() and "both_venues" not in available_requirements(ts)
    assert any("twin" in n and "p_other_venue stays NaN" in n for n in ts.notes)


def test_kalshi_market_with_a_polymarket_twin_reads_the_twin_token_history(twin_map):
    twin_map(entry("777", "tokYES777", "KXTWIN-26-T1"))
    r = twinned_router()
    ts = run(build_ticks({"source": "kalshi", "id": "KXTWIN-26-T1"}, "SPY", http=mock_http(r),
                         massive=lambda: FakeMassive()))
    assert ts.source == "live_history" and (ts.ticks["venue"] == 1).all()
    assert np.isfinite(ts.ticks["p_other_venue"]).any() and "both_venues" in available_requirements(ts)
    hist = [q for q in r.requests if q.url.path == "/prices-history"]
    assert [q.url.params["market"] for q in hist] == ["tokYES777"]


def test_no_overlay_offline_or_from_a_replay(twin_map):
    twin_map(entry("777", "tokYES", "KXTWIN-26-T1"))
    ticks = {"p_other_venue": np.full(3, np.nan)}
    pts = [(T0, 0.3), (T0 + 60, 0.3), (T0 + 120, 0.3)]
    assert run(overlay_other_venue(ticks, pts, source=None, market_id="777", token_id=None,
                                   http=mock_http(twinned_router()))) is None
    assert run(overlay_other_venue(ticks, pts, source="polymarket", market_id="nope", token_id=None,
                                   http=mock_http(twinned_router()))) is None
    r = twinned_router()
    ts = run(build_ticks({"source": "polymarket", "id": "2589813"}, "SPY", http=mock_http(r), offline=True))
    assert not any("candlesticks" in q.url.path for q in r.requests)
    assert "both_venues" not in available_requirements(ts)


class Scripted:
    seen: dict = {}

    def __init__(self, market_id, *, primary, twin, equity):
        Scripted.seen = {"market_id": market_id, "primary": primary, "twin": twin}

    async def __aiter__(self):
        for i in range(3):
            yield Tick(time.time_ns(), 0.31, {"yes_bid": 0.30, "yes_ask": 0.32, "no_bid": 0.68, "no_ask": 0.70,
                                              "p_other_venue": 0.33, "under_px": 500.0})


def start_live(client, market=FED, **body):
    client.app.state.live_source_factory = Scripted
    p = proposal(client, {"family": "macro_fed_hedge"}, market=market)
    r = client.post("/bridges", json={"proposal_id": p["id"], "source": "live", **body})
    assert r.status_code == 201, r.text
    _events(client, r.json()["bridge_id"])
    return client.get(f"/bridges/{r.json()['bridge_id']}").json()


def test_live_bridge_with_no_twin_given_uses_the_twin_map(client, twin_map):
    twin_map(entry("2589813", "tokYES", "KXFEDDECISION-26OCT-H25"))
    s = start_live(client)
    assert Scripted.seen["twin"] == ("kalshi", "KXFEDDECISION-26OCT-H25") and Scripted.seen["primary"] == "polymarket"
    assert s["twin"] == {"source": "kalshi", "id": "KXFEDDECISION-26OCT-H25", "origin": "twin_map"}


def test_live_bridge_twin_map_matches_by_token_id_too(client, twin_map):
    twin_map(entry("some-other-gamma-id", "tokYES", "KXFEDDECISION-26OCT-H25"))
    start_live(client)
    assert Scripted.seen["twin"] == ("kalshi", "KXFEDDECISION-26OCT-H25")


def test_an_explicit_twin_wins_over_the_map(client, twin_map):
    twin_map(entry("2589813", "tokYES", "KXFROM-MAP"))
    s = start_live(client, twin={"source": "kalshi", "id": "KXFROM-REQUEST"})
    assert Scripted.seen["twin"] == ("kalshi", "KXFROM-REQUEST")
    assert s["twin"]["origin"] == "request"


def test_a_bad_explicit_twin_is_still_a_422_not_a_silent_map_fallback(client, twin_map):
    twin_map(entry("2589813", "tokYES", "KXFROM-MAP"))
    client.app.state.live_source_factory = Scripted
    p = proposal(client, {"family": "macro_fed_hedge"})
    r = client.post("/bridges", json={"proposal_id": p["id"], "source": "live",
                                      "twin": {"source": "polymarket", "id": "x", "token_id": "t"}})
    assert r.status_code == 422


def test_live_bridge_without_a_mapped_twin_runs_as_before(client, twin_map):
    twin_map(entry("999", "tokOther", "KXOTHER"))
    s = start_live(client)
    assert Scripted.seen["twin"] is None and s["twin"] is None


def test_kalshi_primary_gets_its_polymarket_twin_with_the_yes_token(client, twin_map):
    twin_map(entry("777", "tokYES777", "KXFOO-26"))
    s = start_live(client, market={"source": "kalshi", "id": "KXFOO-26"})
    assert Scripted.seen["primary"] == "kalshi" and Scripted.seen["market_id"] == "KXFOO-26"
    assert Scripted.seen["twin"] == ("polymarket", "tokYES777")
    assert s["twin"] == {"source": "polymarket", "id": "tokYES777", "origin": "twin_map"}


def test_replay_bridge_ignores_the_twin_map(client, twin_map):
    twin_map(entry("2589813", "tokYES", "KXFEDDECISION-26OCT-H25"))
    p = proposal(client, {"family": "macro_fed_hedge"})
    r = client.post("/bridges", json={"proposal_id": p["id"], "source": "replay"})
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert client.get(f"/bridges/{r.json()['bridge_id']}").json()["twin"] is None
