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
    assert CAL.offset("2027-12-30", 10) is None


def test_last_completed_session():
    assert CAL.last_completed(T("2024-06-09")) == T("2024-06-07")   # Sunday -> Friday
    assert CAL.last_completed(T("2024-06-10")) == T("2024-06-10")
