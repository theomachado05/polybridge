from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday)
from pandas.tseries.offsets import CustomBusinessDay


class NYSEHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=lambda d: d + pd.Timedelta(days=1) if d.weekday() == 6 else d),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
        Holiday("National day of mourning, President Carter", year=2025, month=1, day=9),
        Holiday("National day of mourning, President Bush", year=2018, month=12, day=5),
    ]


class TradingCalendar:
    def __init__(self, start: str = "2015-01-01", end: str = "2030-12-31"):
        hol = NYSEHolidays().holidays(pd.Timestamp(start) - pd.Timedelta(days=7), pd.Timestamp(end) + pd.Timedelta(days=7))
        self.sessions = pd.bdate_range(start, end, freq=CustomBusinessDay(holidays=hol))

    def on_or_after(self, day) -> pd.Timestamp:
        i = self.sessions.searchsorted(pd.Timestamp(day), side="left")
        if i >= len(self.sessions):
            raise ValueError(f"{day} is after the last calendar session {self.sessions[-1].date()}")
        return self.sessions[i]

    def before(self, day) -> pd.Timestamp:
        i = self.sessions.searchsorted(pd.Timestamp(day), side="left") - 1
        if i < 0:
            raise ValueError(f"{day} is on or before the first calendar session {self.sessions[0].date()}")
        return self.sessions[i]

    def after(self, day) -> pd.Timestamp:
        i = self.sessions.searchsorted(pd.Timestamp(day), side="right")
        if i >= len(self.sessions):
            raise ValueError(f"{day} is on or after the last calendar session {self.sessions[-1].date()}")
        return self.sessions[i]

    def between(self, a, b) -> int:
        return int(self.sessions.searchsorted(pd.Timestamp(b), side="right")
                   - self.sessions.searchsorted(pd.Timestamp(a), side="right"))

    def offset(self, day, n: int) -> pd.Timestamp | None:
        i = self.sessions.searchsorted(pd.Timestamp(day), side="left") + n
        return self.sessions[i] if 0 <= i < len(self.sessions) else None

    def last_completed(self, today=None) -> pd.Timestamp:
        today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today)
        return self.sessions[self.sessions.searchsorted(today, side="right") - 1]
