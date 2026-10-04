from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from polybridge_research.calendar import TradingCalendar

ET = ZoneInfo("America/New_York")
EARLY_CLOSES = {"2025-11-28", "2025-12-24"}
OPEN_MIN, OPEN_MAX = "2025-10-01", "2026-09-28"


def et(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


@dataclass(frozen=True)
class Closure:
    close_day: date
    open_day: date

    @property
    def key(self) -> str:
        return self.close_day.isoformat()

    @property
    def kind(self) -> str:
        return "weekend" if (self.open_day - self.close_day).days == 3 and self.close_day.weekday() == 4 else "holiday"

    @property
    def close(self) -> datetime:
        return et(self.close_day, 13 if self.key in EARLY_CLOSES else 16, 0)

    @property
    def opt_close(self) -> datetime:
        return self.close - timedelta(minutes=5)

    @property
    def open(self) -> datetime:
        return et(self.open_day, 9, 30)

    @property
    def opt_open(self) -> datetime:
        return et(self.open_day, 9, 45)

    @property
    def eod(self) -> datetime:
        return et(self.open_day, 16, 0)

    @property
    def opt_eod(self) -> datetime:
        return et(self.open_day, 15, 55)


def build_closures(open_min: str = OPEN_MIN, open_max: str = OPEN_MAX, cal: TradingCalendar | None = None) -> list[Closure]:
    cal = cal or TradingCalendar()
    s = cal.sessions
    out = []
    for a, b in zip(s[:-1], s[1:]):
        if (b - a).days < 2 or b < pd.Timestamp(open_min) or b > pd.Timestamp(open_max):
            continue
        out.append(Closure(a.date(), b.date()))
    return out


def eligible(c: Closure, listed: datetime | None, end_dt: datetime, res_date: date) -> str:
    if listed is None or listed > c.close - timedelta(minutes=15):
        return "listed_after_close"
    if end_dt < c.eod - timedelta(minutes=1) and res_date <= c.open_day:
        return "resolves_before_reopen_close"
    return ""
