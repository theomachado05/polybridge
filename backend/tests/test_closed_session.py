import datetime as dt

import pytest

from app.closed import session as S
from app.closed.session import ET, session_at, to_utc


def et(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


@pytest.mark.parametrize("when,phase", [
    (et(2026, 10, 5, 3, 59), "overnight"),
    (et(2026, 10, 5, 4, 0), "pre_market"),
    (et(2026, 10, 5, 9, 29), "pre_market"),
    (et(2026, 10, 5, 9, 30), "regular"),
    (et(2026, 10, 5, 15, 59), "regular"),
    (et(2026, 10, 5, 16, 0), "after_hours"),
    (et(2026, 10, 5, 19, 59), "after_hours"),
    (et(2026, 10, 5, 20, 0), "overnight"),
    (et(2026, 10, 3, 12, 0), "weekend"),
    (et(2026, 10, 4, 23, 0), "weekend"),
    (et(2026, 11, 26, 12, 0), "holiday"),   # Thanksgiving
    (et(2026, 7, 3, 12, 0), "holiday"),     # Independence Day observed (4 July is a Saturday)
    (et(2026, 4, 3, 12, 0), "holiday"),     # Good Friday
])
def test_phase(when, phase):
    assert session_at(when).phase == phase


def test_early_closes():
    # day after Thanksgiving and Christmas Eve close at 13:00, after-hours to 17:00
    for d in (dt.date(2026, 11, 27), dt.date(2026, 12, 24), dt.date(2025, 7, 3), dt.date(2024, 7, 3)):
        assert S.is_early_close(d), d
        s = session_at(dt.datetime.combine(d, dt.time(12, 59), ET))
        assert s.phase == "regular" and s.early_close and s.label == "Market open · closes 13:00 ET"
        assert session_at(dt.datetime.combine(d, dt.time(13, 0), ET)).phase == "after_hours"
        assert session_at(dt.datetime.combine(d, dt.time(17, 0), ET)).phase == "overnight"
    # 3 July on a Friday is a holiday (2026) and 3 July 2022 is a Sunday: no early close
    assert not S.is_early_close(dt.date(2026, 7, 3)) and not S.is_early_close(dt.date(2026, 7, 2))
    assert not S.is_early_close(dt.date(2026, 12, 23))


def test_last_close_and_next_open_across_weekend():
    s = session_at(et(2026, 10, 3, 12, 0))  # Saturday
    assert s.last_close == to_utc(et(2026, 10, 2, 16, 0))
    assert s.next_open == to_utc(et(2026, 10, 5, 9, 30))
    assert s.next_extended_open == to_utc(et(2026, 10, 5, 4, 0))
    assert s.closure.kind == "weekend" and s.closure.close_day == dt.date(2026, 10, 2)
    assert s.closure.elapsed_s == 20 * 3600 and s.closure.remaining_s == (24 + 21.5) * 3600
    assert s.label == "Market closed · reopens Mon 09:30 ET / pre-market 04:00"
    assert not s.equities_open and s.closed


def test_regular_session_has_no_closure_and_previous_close():
    s = session_at(et(2026, 10, 6, 11, 0))
    assert s.equities_open and s.closure is None
    assert s.last_close == to_utc(et(2026, 10, 5, 16, 0))
    assert s.next_open == to_utc(et(2026, 10, 7, 9, 30))


def test_holiday_closure_after_early_close():
    s = session_at(et(2026, 11, 26, 12, 0))  # Thanksgiving: closed Wed 16:00 to Fri 09:30
    assert s.holiday == "Thanksgiving Day" and s.closure.kind == "holiday"
    assert s.next_open == to_utc(et(2026, 11, 27, 9, 30))
    # Friday after the 13:00 early close: closure until Monday
    s = session_at(et(2026, 11, 27, 14, 0))
    assert s.phase == "after_hours" and s.last_close == to_utc(et(2026, 11, 27, 13, 0))
    assert s.closure.kind == "weekend"


def test_friday_evening_is_overnight_phase_in_a_weekend_closure():
    s = session_at(et(2026, 10, 2, 21, 0))
    assert s.phase == "overnight" and s.closure.kind == "weekend"


def test_dst_boundaries():
    # 2026-03-09 (after spring forward) open = 13:30 UTC; 2026-11-02 (after fall back) open = 14:30 UTC
    assert S.regular_hours(dt.date(2026, 3, 9))[0] == dt.datetime(2026, 3, 9, 13, 30, tzinfo=dt.timezone.utc)
    assert S.regular_hours(dt.date(2026, 11, 2))[0] == dt.datetime(2026, 11, 2, 14, 30, tzinfo=dt.timezone.utc)


def test_to_utc_accepts_all_epoch_units_and_iso():
    ref = dt.datetime(2026, 10, 3, 16, 0, tzinfo=dt.timezone.utc)
    s = int(ref.timestamp())
    for x in (s, s * 1000, s * 1_000_000, s * 1_000_000_000, str(s), "2026-10-03T16:00:00Z",
              "2026-10-03T12:00:00-04:00", dt.datetime(2026, 10, 3, 16, 0), ref):
        assert to_utc(x) == ref, x
    for bad in ("soon", None, float("nan"), True):
        with pytest.raises(ValueError):
            to_utc(bad)


def test_replayed_saturday_is_a_saturday():
    ts_ns = int(to_utc(et(2024, 7, 13, 19, 0)).timestamp() * 1e9)  # tick time of a recorded Saturday
    s = session_at(ts_ns)
    assert s.phase == "weekend" and s.closure.close_day == dt.date(2024, 7, 12)


def test_matches_research_calendar():
    pytest.importorskip("pandas")
    from polybridge_research.calendar import TradingCalendar

    sessions = {d.date() for d in TradingCalendar("2015-01-01", "2030-12-31").sessions}
    d = dt.date(2015, 1, 1)
    while d <= dt.date(2030, 12, 31):
        assert S.is_trading_day(d) == (d in sessions), d
        d += dt.timedelta(days=1)


def test_out_of_range_times_raise_value_error_only():
    import pytest

    from app.closed.session import check_supported, session_at
    for bad in (1e30, -1e30, 10 ** 400, "1e30", "9999-12-31T23:00:00Z", "0001-01-01T00:00:00Z"):
        with pytest.raises(ValueError):
            session_at(bad)
    assert check_supported("2026-10-03T12:00:00Z").year == 2026
