import pytest
import pandas as pd

from polybridge_research.calendar import TradingCalendar

CAL = TradingCalendar()
T = pd.Timestamp


def test_nyse_specific_closures_and_openings():
    s = set(CAL.sessions)
    assert T("2025-01-09") not in s          # national day of mourning, President Carter
    assert T("2024-03-29") not in s          # Good Friday
    assert T("2024-10-14") in s              # Columbus Day: NYSE open
    assert T("2024-11-11") in s              # Veterans Day: NYSE open
    assert T("2024-07-04") not in s


def test_navigation():
    assert CAL.on_or_after("2024-06-08") == T("2024-06-10")   # Saturday -> Monday
    assert CAL.on_or_after("2024-06-10") == T("2024-06-10")
    assert CAL.before("2024-06-10") == T("2024-06-07")
    assert CAL.after("2024-06-07") == T("2024-06-10")
    assert CAL.between("2024-06-07", "2024-06-12") == 3
    assert CAL.offset("2024-06-07", 2) == T("2024-06-11")
    assert CAL.offset("2030-12-30", 10) is None


def test_last_completed_session():
    assert CAL.last_completed(T("2024-06-09")) == T("2024-06-07")   # Sunday -> Friday
    assert CAL.last_completed(T("2024-06-10")) == T("2024-06-10")


def test_default_range_is_wide():
    assert CAL.sessions[0] == T("2015-01-02") and CAL.sessions[-1] == T("2030-12-31")


def test_nyse_weekend_rules():
    s = set(CAL.sessions)
    assert T("2021-12-31") in s and T("2022-01-03") in s     # New Year 2022 is a Saturday: no Friday closure
    assert T("2022-06-20") not in s and T("2022-06-17") in s  # Juneteenth 2022 (Sun) observed Monday
    assert T("2026-07-03") not in s                           # July 4 2026 (Sat) observed Friday
    assert T("2022-12-26") not in s                           # Christmas 2022 (Sun) observed Monday
    assert T("2023-01-02") not in s                           # New Year 2023 (Sun) observed Monday


def test_out_of_range_navigation_raises_clearly():
    with pytest.raises(ValueError, match="first calendar session"):
        CAL.before(CAL.sessions[0])
    with pytest.raises(ValueError, match="after the last"):
        CAL.on_or_after("2031-01-02")
    with pytest.raises(ValueError, match="last calendar session"):
        CAL.after(CAL.sessions[-1])
