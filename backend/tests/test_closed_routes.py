import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.closed import gap as G
from app.closed.router import closed_fields
from app.closed.session import ET, to_utc
from app.closed.tracker import market_key, tracker_for
from app.main import create_app


def et(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


def iso(t):
    return to_utc(t).isoformat()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "GAP_RATES_PATH", tmp_path / "no_gap_rates.json")  # pooled default

    async def no_network(*a):
        raise AssertionError("network fetch in an offline test")

    a = create_app()
    a.state.closed_history_fetcher = no_network
    return a


def test_session_route_at_and_now(app):
    c = TestClient(app)
    r = c.get("/session", params={"at": iso(et(2026, 10, 3, 12, 0))}).json()
    assert r["phase"] == "weekend" and r["closure"]["kind"] == "weekend"
    assert r["label"] == "Market closed · reopens Mon 09:30 ET / pre-market 04:00"
    assert r["next_open"] == "2026-10-05T13:30:00Z"
    ts = int(to_utc(et(2026, 10, 5, 10, 0)).timestamp())
    assert c.get("/session", params={"at": str(ts)}).json()["phase"] == "regular"
    assert c.get("/session").json()["phase"] in ("regular", "pre_market", "after_hours", "overnight", "weekend",
                                                 "holiday")
    assert c.get("/session", params={"at": "tomorrow"}).status_code == 422
    # never a 500: unrepresentable epochs and instants at the ends of the datetime range are 422
    for bad in ("1e30", "-1e30", "1e400", "9" * 400, "9999-12-31T23:00:00Z", "0001-01-01T00:00:00Z",
                "1970-06-01T00:00:00Z", "2100-01-01T00:00:00Z"):
        assert c.get("/session", params={"at": bad}).status_code == 422, bad
        assert c.get("/closed/expected-gap", params={"market_source": "polymarket", "market_id": "x",
                                                     "at": bad}).status_code == 422, bad


def test_expected_gap_from_tracker(app):
    tr = tracker_for(app)
    k = market_key("polymarket", "m1")
    tr.observe(k, et(2026, 10, 2, 15, 59), 0.30)
    tr.observe(k, et(2026, 10, 3, 11, 0), 0.40)
    c = TestClient(app)
    r = c.get("/closed/expected-gap", params={"market_source": "polymarket", "market_id": "m1", "ticker": "SPY",
                                              "direction": "up_on_yes", "at": iso(et(2026, 10, 3, 12, 0))}).json()
    assert r["move_source"] == "tracker" and r["closure"]["status"] == "TRACKING"
    g = r["expected_gap"]
    assert g["label"] == "pooled" and g["n_closures"] == 380
    assert g["expected_gap_bp"] == pytest.approx(10 * G.POOLED_RATE)
    assert g["band_bp"][0] < g["expected_gap_bp"] < g["band_bp"][1]
    assert r["session"]["phase"] == "weekend"


def test_expected_gap_seeds_from_history(app):
    calls = []

    async def fetch(source, hid, start, end):
        calls.append((source, hid, start, end))
        close = int(to_utc(et(2026, 10, 2, 16, 0)).timestamp())
        return [(close - 60, 0.50), (close + 19 * 3600, 0.47), (end + 999, 0.10)]  # point after `at` is dropped

    app.state.closed_history_fetcher = fetch
    c = TestClient(app)
    r = c.get("/closed/expected-gap", params={"market_source": "polymarket", "market_id": "g1", "token_id": "tok",
                                              "direction": "down_on_yes", "at": iso(et(2026, 10, 3, 12, 0))}).json()
    assert calls and calls[0][1] == "tok"
    assert r["move_source"] == "history_seed" and r["seeded_points"] == 2
    assert r["closure"]["move_pp"] == pytest.approx(-3.0)
    assert r["expected_gap"]["expected_gap_bp"] == pytest.approx(3.0 * G.POOLED_RATE)
    # second call: anchor now known, no refetch
    c.get("/closed/expected-gap", params={"market_source": "polymarket", "market_id": "g1",
                                          "at": iso(et(2026, 10, 3, 12, 5))})
    assert len(calls) == 1


def test_expected_gap_fetch_failure_and_kalshi(app):
    async def boom(*a):
        raise RuntimeError("down")

    app.state.closed_history_fetcher = boom
    c = TestClient(app)
    at = iso(et(2026, 10, 3, 12, 0))
    r = c.get("/closed/expected-gap", params={"market_source": "polymarket", "market_id": "g2", "at": at}).json()
    assert r["closure"]["status"] == "NO_PM_DATA" and r["expected_gap"]["expected_gap_bp"] is None
    assert "GAP_NO_MOVE" in r["expected_gap"]["reasons"]
    r = c.get("/closed/expected-gap", params={"market_source": "kalshi", "market_id": "KX", "at": at}).json()
    assert r["expected_gap"]["expected_gap_bp"] is None


def test_expected_gap_what_if_and_validation(app):
    c = TestClient(app)
    at = iso(et(2026, 10, 3, 12, 0))
    r = c.get("/closed/expected-gap", params={"market_source": "kalshi", "market_id": "KX", "move_pp": 4,
                                              "direction": "up_on_yes", "at": at}).json()
    assert r["move_source"] == "what_if" and r["expected_gap"]["expected_gap_bp"] == pytest.approx(4 * G.POOLED_RATE)
    assert c.get("/closed/expected-gap", params={"market_source": "kalshi", "market_id": "KX", "move_pp": 500,
                                                 "at": at}).status_code == 422
    assert c.get("/closed/expected-gap", params={"market_source": "kalshi"}).status_code == 422
    open_r = c.get("/closed/expected-gap", params={"market_source": "kalshi", "market_id": "KX", "move_pp": 4,
                                                   "at": iso(et(2026, 10, 5, 11, 0))}).json()
    assert open_r["expected_gap"]["expected_gap_bp"] is None
    assert "GAP_NOT_IN_CLOSURE" in open_r["expected_gap"]["reasons"]


def test_closed_fields_for_bridge_summary(app):
    tr = tracker_for(app)
    k = market_key("polymarket", "m1")
    tr.observe(k, et(2026, 10, 2, 15, 59), 0.30)
    tr.observe(k, et(2026, 10, 3, 11, 0), 0.25)
    f = closed_fields(tr, "polymarket", "m1", et(2026, 10, 3, 12, 0), direction="down_on_yes",
                      rates=G.GapRates())
    assert set(f) == {"session", "closure", "expected_gap"}
    assert f["expected_gap"]["expected_gap_bp"] == pytest.approx(5 * G.POOLED_RATE)


def test_no_seed_during_regular_hours_and_failed_seed_not_retried(app):
    calls = []

    async def empty(source, hid, start, end):
        calls.append(start)
        return []

    app.state.closed_history_fetcher = empty
    c = TestClient(app)
    q = {"market_source": "polymarket", "market_id": "g3", "token_id": "tok"}
    c.get("/closed/expected-gap", params={**q, "at": iso(et(2026, 10, 5, 11, 0))})  # Monday, regular hours
    assert calls == []
    for mm in (0, 1, 2):  # Saturday polls: one fetch, then the miss is remembered for this close
        r = c.get("/closed/expected-gap", params={**q, "at": iso(et(2026, 10, 3, 12, mm))}).json()
        assert r["closure"]["status"] == "NO_PM_DATA"
    assert len(calls) == 1
    app.state.closed_seed_misses.clear()  # after the retry window it fetches again
    c.get("/closed/expected-gap", params={**q, "at": iso(et(2026, 10, 3, 12, 3))})
    assert len(calls) == 2


def test_historical_seed_on_market_with_live_ticks(app):
    """A historical `at` must not seed points into the live key (they would be pruned) and must report truthfully."""
    tr = tracker_for(app)
    k = market_key("polymarket", "g4")
    tr.observe(k, et(2026, 10, 3, 11, 0), 0.60)  # live tick
    close = int(to_utc(et(2024, 7, 5, 16, 0)).timestamp())

    async def fetch(source, hid, start, end):
        return [(close - 60, 0.50), (close + 20 * 3600, 0.55)]

    app.state.closed_history_fetcher = fetch
    r = TestClient(app).get("/closed/expected-gap", params={
        "market_source": "polymarket", "market_id": "g4", "token_id": "tok", "direction": "up_on_yes",
        "at": iso(et(2024, 7, 6, 12, 0))}).json()
    assert r["move_source"] == "history_seed" and r["seeded_points"] == 2
    assert r["closure"]["status"] == "TRACKING" and r["closure"]["move_pp"] == pytest.approx(5.0)
    assert len(tr._t[k]) == 1  # the live series is untouched
