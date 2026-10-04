import datetime as dt

import pytest

from app.closed.session import ET, to_utc
from app.closed.tracker import (MARKET_OPEN, NO_CLOSE_PRICE, NO_PM_DATA, TRACKING, ClosureTracker, market_key,
                                replay_key, tracker_for)

K = market_key("polymarket", "m1")


def et(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


def ns(t):
    return int(to_utc(t).timestamp() * 1_000_000_000)


def test_move_since_friday_close_on_saturday():
    tr = ClosureTracker()
    tr.observe(K, ns(et(2026, 10, 2, 15, 50)), 0.40)
    tr.observe(K, ns(et(2026, 10, 2, 15, 59)), 0.42)
    tr.observe(K, ns(et(2026, 10, 3, 9, 0)), 0.55)
    tr.observe(K, ns(et(2026, 10, 3, 11, 0)), 0.50)
    s = tr.state(K, et(2026, 10, 3, 12, 0))
    assert s.status == TRACKING and s.active
    assert s.p_close == 0.42 and s.p_now == 0.50
    assert abs(s.move_pp - 8.0) < 1e-9
    assert s.high_pp == 55.0 and s.low_pp == 50.0 and s.n_points == 2
    assert s.session.closure.kind == "weekend"


def test_explicit_time_ignores_later_points():
    tr = ClosureTracker()
    tr.observe(K, et(2026, 10, 2, 15, 59), 0.42)
    tr.observe(K, et(2026, 10, 3, 9, 0), 0.55)
    tr.observe(K, et(2026, 10, 3, 11, 0), 0.30)
    assert abs(tr.state(K, et(2026, 10, 3, 10, 0)).move_pp - 13.0) < 1e-9


def test_stale_close_anchor_and_missing_data():
    tr = ClosureTracker()
    assert tr.state(K, et(2026, 10, 3, 12, 0)).status == NO_PM_DATA
    tr.observe(K, et(2026, 10, 2, 15, 0), 0.42)
    tr.observe(K, et(2026, 10, 3, 11, 0), 0.50)
    s = tr.state(K, et(2026, 10, 3, 12, 0))
    assert s.status == NO_CLOSE_PRICE and s.move_pp is None and s.p_now == 0.50
    assert not tr.has_close_anchor(K, et(2026, 10, 3, 12, 0))


def test_regular_hours_reports_market_open():
    tr = ClosureTracker()
    tr.observe(K, et(2026, 10, 5, 15, 59), 0.30)
    tr.observe(K, et(2026, 10, 6, 10, 0), 0.35)
    s = tr.state(K, et(2026, 10, 6, 10, 30))
    assert s.status == MARKET_OPEN and not s.active and abs(s.move_pp - 5.0) < 1e-9


def test_out_of_order_duplicate_and_invalid_points():
    tr = ClosureTracker()
    tr.observe(K, et(2026, 10, 3, 11, 0), 0.50)
    tr.observe(K, et(2026, 10, 2, 15, 59), 0.40)
    tr.observe(K, et(2026, 10, 2, 15, 59), 0.42)
    assert not tr.observe(K, et(2026, 10, 3, 11, 30), float("nan"))
    assert not tr.observe(K, et(2026, 10, 3, 11, 30), 1.5)
    assert abs(tr.state(K, et(2026, 10, 3, 12, 0)).move_pp - 8.0) < 1e-9


def test_prunes_old_history():
    tr = ClosureTracker(keep_s=86400)
    tr.observe(K, et(2026, 9, 1, 12, 0), 0.1)
    tr.observe(K, et(2026, 10, 3, 12, 0), 0.2)
    assert tr.price_at(K, et(2026, 9, 1, 12, 0)) is None


def test_tracker_for_app_is_shared():
    class A:
        class state:
            pass
    a = A()
    assert tracker_for(a) is tracker_for(a)


def test_old_point_behind_live_series_is_rejected_not_silently_dropped():
    tr = ClosureTracker()
    assert tr.observe(K, et(2026, 10, 3, 12, 0), 0.5)
    assert not tr.observe(K, et(2024, 7, 1, 12, 0), 0.4)
    assert len(tr._t[K]) == 1
    assert not tr.accepts(K, et(2024, 7, 1, 12, 0)) and tr.accepts(K, et(2026, 9, 30, 12, 0))
    rk = replay_key("polymarket", "m1")
    assert rk != K and tr.observe(rk, et(2024, 7, 1, 12, 0), 0.4) and tr.has(rk)


def test_bad_timestamp_returns_false_never_raises():
    tr = ClosureTracker()
    for bad in (1e30, -1e30, "garbage", None, object(), "9" * 400):
        assert tr.observe(K, bad, 0.5) is False
    assert not tr.has(K)


def test_repeated_price_is_downsampled_but_lookups_hold():
    tr = ClosureTracker()
    t0 = to_utc(et(2026, 10, 2, 15, 0)).timestamp()
    for s in range(0, 3600):
        assert tr.observe(K, t0 + s, 0.42)
    assert len(tr) <= 61
    tr.observe(K, et(2026, 10, 3, 11, 0), 0.50)
    s = tr.state(K, et(2026, 10, 3, 12, 0))
    assert s.status == TRACKING and abs(s.move_pp - 8.0) < 1e-9
    tr.observe(K, t0 + 3600 + 1, 0.43)
    assert tr.price_at(K, t0 + 3600 + 2)[0] == 0.43


def test_high_low_incremental_matches_full_recompute():
    tr = ClosureTracker(min_gap_s=0)
    close = to_utc(et(2026, 10, 2, 16, 0)).timestamp()
    tr.observe(K, close - 60, 0.40)
    vals = [0.41, 0.47, 0.38, 0.44, 0.52, 0.36, 0.45]
    for i, v in enumerate(vals):
        tr.observe(K, close + 3600 * (i + 1), v)
        s = tr.state(K, close + 3600 * (i + 1) + 1)
        assert s.high_pp == pytest.approx(100 * max(vals[:i + 1]))
        assert s.low_pp == pytest.approx(100 * min(vals[:i + 1])) and s.n_points == i + 1
    tr.observe(K, close + 1800, 0.99)
    s = tr.state(K, close + 3600 * 8)
    assert s.high_pp == pytest.approx(99.0) and s.low_pp == pytest.approx(36.0)
    s = tr.state(K, close + 3600 * 2 + 1)
    assert s.high_pp == pytest.approx(99.0) and s.low_pp == pytest.approx(41.0)
