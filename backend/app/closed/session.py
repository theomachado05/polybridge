"""NYSE session clock: classify any instant as regular, pre-market, after-hours, overnight, weekend or holiday.

Pure functions of an explicit instant (never the wall clock unless the caller passes ``now``), so a replay that passes
each tick's own time sees a replayed Saturday as a Saturday.

The holiday rules are a stdlib copy of ``research/polybridge_research/calendar.py`` (NYSEHolidays); the test suite
checks the two agree for 2015-2030. Early closes (13:00 ET): the day after Thanksgiving, Christmas Eve when it is a
trading day, and 3 July when it is a Monday-Thursday trading day. On an early-close day after-hours ends at 17:00 ET.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

PRE_OPEN = dt.time(4, 0)
REG_OPEN = dt.time(9, 30)
REG_CLOSE = dt.time(16, 0)
EARLY_CLOSE = dt.time(13, 0)
POST_CLOSE = dt.time(20, 0)
EARLY_POST_CLOSE = dt.time(17, 0)

PHASES = ("regular", "pre_market", "after_hours", "overnight", "weekend", "holiday")
CLOSED_PHASES = ("overnight", "weekend", "holiday")

# One-off closures the research calendar also carries (national days of mourning).
_SPECIAL_CLOSURES = {
    dt.date(2018, 12, 5): "National day of mourning, President Bush",
    dt.date(2025, 1, 9): "National day of mourning, President Carter",
}


# ------------------------------------------------------------------------------------------------- time parsing


def to_utc(x: Any) -> dt.datetime:
    """An aware UTC datetime from a datetime (naive = UTC), an epoch number (s, ms, us or ns, by magnitude), a numeric
    string, or an ISO-8601 string (naive = UTC). Raises ValueError on anything else, including an epoch the platform
    cannot represent (never OverflowError or OSError)."""
    if isinstance(x, dt.datetime):
        return x.replace(tzinfo=UTC) if x.tzinfo is None else x.astimezone(UTC)
    if isinstance(x, bool):
        raise ValueError(f"not a time: {x!r}")
    if isinstance(x, (int, float)):
        try:
            v = float(x)
        except OverflowError:
            raise ValueError(f"time out of range: {x!r}") from None
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"not a time: {x!r}")
        a = abs(v)
        secs = v / 1e9 if a >= 1e17 else v / 1e6 if a >= 1e14 else v / 1e3 if a >= 1e11 else v
        try:
            return dt.datetime.fromtimestamp(secs, UTC)
        except (OverflowError, OSError, ValueError):
            raise ValueError(f"time out of range: {x!r}") from None
    if isinstance(x, str):
        s = x.strip()
        for conv in (int, float):
            try:
                n = conv(s)
            except (ValueError, OverflowError):
                continue
            return to_utc(n)  # out of range: ValueError
        try:
            return to_utc(dt.datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            raise ValueError(f"not a time: {x!r}") from None
    raise ValueError(f"not a time: {x!r}")


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


# The calendar is answered for instants in [SUPPORTED_FROM, SUPPORTED_TO). Outside it the neighbouring trading days can
# fall off the ends of the datetime range, and nothing in the product needs such dates.
SUPPORTED_FROM = dt.datetime(1971, 1, 1, tzinfo=UTC)
SUPPORTED_TO = dt.datetime(2100, 1, 1, tzinfo=UTC)


def check_supported(at: Any) -> dt.datetime:
    """``to_utc(at)``, or ValueError when it falls outside [SUPPORTED_FROM, SUPPORTED_TO)."""
    t = to_utc(at)
    if not SUPPORTED_FROM <= t < SUPPORTED_TO:
        raise ValueError(f"time outside the supported range 1971-01-01..2100-01-01: {_iso(t)}")
    return t


# ---------------------------------------------------------------------------------------------------- calendar


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> dt.date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def _nearest_workday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> dict[dt.date, str]:
    """Full-day NYSE closures falling in ``year`` (observed dates), as {date: name}."""
    out: dict[dt.date, str] = {}
    ny = dt.date(year, 1, 1)
    out[ny + dt.timedelta(days=1) if ny.weekday() == 6 else ny] = "New Year's Day"  # Saturday: not observed
    out[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    out[_nth_weekday(year, 2, 0, 3)] = "Presidents' Day"
    out[_easter(year) - dt.timedelta(days=2)] = "Good Friday"
    out[_last_weekday(year, 5, 0)] = "Memorial Day"
    if year >= 2022:
        out[_nearest_workday(dt.date(year, 6, 19))] = "Juneteenth"
    out[_nearest_workday(dt.date(year, 7, 4))] = "Independence Day"
    out[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    out[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    out[_nearest_workday(dt.date(year, 12, 25))] = "Christmas Day"
    out.update({d: n for d, n in _SPECIAL_CLOSURES.items() if d.year == year})
    return {d: n for d, n in out.items() if d.year == year}


def holiday_name(d: dt.date) -> str | None:
    return nyse_holidays(d.year).get(d)


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and holiday_name(d) is None


def is_early_close(d: dt.date) -> bool:
    if not is_trading_day(d):
        return False
    if d == _nth_weekday(d.year, 11, 3, 4) + dt.timedelta(days=1):
        return True
    if d.month == 12 and d.day == 24:
        return True
    return d.month == 7 and d.day == 3 and d.weekday() <= 3


def next_trading_day(d: dt.date) -> dt.date:
    """First trading day strictly after ``d``."""
    d += dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def previous_trading_day(d: dt.date) -> dt.date:
    """Last trading day strictly before ``d``."""
    d -= dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def _at_et(d: dt.date, t: dt.time) -> dt.datetime:
    return dt.datetime.combine(d, t, ET).astimezone(UTC)


def regular_hours(d: dt.date) -> tuple[dt.datetime, dt.datetime] | None:
    """(open, close) of the regular session on ET date ``d`` in UTC, or None when it is not a trading day."""
    if not is_trading_day(d):
        return None
    return _at_et(d, REG_OPEN), _at_et(d, EARLY_CLOSE if is_early_close(d) else REG_CLOSE)


def extended_hours(d: dt.date) -> tuple[dt.datetime, dt.datetime] | None:
    """(pre-market start 04:00, after-hours end 20:00, or 17:00 on an early-close day) in UTC, or None."""
    if not is_trading_day(d):
        return None
    return _at_et(d, PRE_OPEN), _at_et(d, EARLY_POST_CLOSE if is_early_close(d) else POST_CLOSE)


def last_regular_close(at: Any) -> dt.datetime:
    """The most recent regular-session close at or before ``at`` (UTC). During regular hours: the previous session's."""
    t = to_utc(at)
    d = t.astimezone(ET).date()
    if is_trading_day(d):
        _, close = regular_hours(d)  # type: ignore[misc]
        if t >= close:
            return close
    return regular_hours(previous_trading_day(d))[1]  # type: ignore[index]


def next_regular_open(at: Any) -> dt.datetime:
    """The first regular-session open strictly after ``at`` (UTC). During regular hours: the next session's."""
    t = to_utc(at)
    d = t.astimezone(ET).date()
    if is_trading_day(d):
        op, _ = regular_hours(d)  # type: ignore[misc]
        if t < op:
            return op
    return regular_hours(next_trading_day(d))[0]  # type: ignore[index]


def next_extended_open(at: Any) -> dt.datetime:
    """The first 04:00 ET pre-market start strictly after ``at`` (UTC)."""
    t = to_utc(at)
    d = t.astimezone(ET).date()
    if is_trading_day(d):
        pre, _ = extended_hours(d)  # type: ignore[misc]
        if t < pre:
            return pre
    return extended_hours(next_trading_day(d))[0]  # type: ignore[index]


def closure_kind(close_day: dt.date, open_day: dt.date) -> str:
    """Same rule as research/leadlag_closed/closures.py: overnight (next day), weekend (Fri to Mon), else holiday."""
    n = (open_day - close_day).days
    if n == 1:
        return "overnight"
    if n == 3 and close_day.weekday() == 4:
        return "weekend"
    return "holiday"


# ------------------------------------------------------------------------------------------------------ session


@dataclass(frozen=True)
class Closure:
    """The regular-session closure containing an instant: from one regular close to the next regular open."""
    kind: str                  # overnight | weekend | holiday
    close_day: dt.date         # trading day whose close started the closure
    open_day: dt.date          # trading day whose open ends it
    started_at: dt.datetime    # UTC
    ends_at: dt.datetime       # UTC
    elapsed_s: float
    remaining_s: float

    def to_dict(self) -> dict:
        return {"kind": self.kind, "close_day": self.close_day.isoformat(), "open_day": self.open_day.isoformat(),
                "started_at": _iso(self.started_at), "ends_at": _iso(self.ends_at),
                "elapsed_s": self.elapsed_s, "remaining_s": self.remaining_s}


@dataclass(frozen=True)
class Session:
    at: dt.datetime                     # UTC
    phase: str                          # one of PHASES
    equities_open: bool                 # regular session in progress
    extended_open: bool                 # pre-market or after-hours in progress
    trading_day: bool                   # the ET date is an NYSE trading day
    early_close: bool                   # the ET date closes at 13:00
    holiday: str | None                 # the ET date's holiday name
    regular_open: dt.datetime | None    # today's regular hours (UTC), when a trading day
    regular_close: dt.datetime | None
    last_close: dt.datetime             # most recent regular close at or before `at` (previous session's when open)
    next_open: dt.datetime              # next regular open strictly after `at`
    next_extended_open: dt.datetime     # next 04:00 ET pre-market start strictly after `at`
    closure: Closure | None             # set whenever the regular session is not in progress
    label: str

    @property
    def closed(self) -> bool:
        return not self.equities_open

    def to_dict(self) -> dict:
        et = self.at.astimezone(ET)
        return {"at": _iso(self.at), "at_et": et.isoformat(), "et_date": et.date().isoformat(),
                "phase": self.phase, "equities_open": self.equities_open, "extended_open": self.extended_open,
                "closed": self.closed, "trading_day": self.trading_day, "early_close": self.early_close,
                "holiday": self.holiday,
                "regular_open": _iso(self.regular_open), "regular_close": _iso(self.regular_close),
                "last_close": _iso(self.last_close), "next_open": _iso(self.next_open),
                "next_open_et": self.next_open.astimezone(ET).isoformat(),
                "next_extended_open": _iso(self.next_extended_open),
                "next_extended_open_et": self.next_extended_open.astimezone(ET).isoformat(),
                "closure": self.closure.to_dict() if self.closure else None, "label": self.label}


def _iso(x: dt.datetime | None) -> str | None:
    return x.astimezone(UTC).isoformat().replace("+00:00", "Z") if x is not None else None


def _hm(t: dt.datetime) -> str:
    return t.astimezone(ET).strftime("%H:%M")


def _day(t: dt.datetime, ref: dt.datetime) -> str:
    """'Mon', or 'Mon 12 Jan' when it is six or more days after the reference."""
    e = t.astimezone(ET)
    return e.strftime("%a") if (e.date() - ref.astimezone(ET).date()).days < 6 else e.strftime("%a %d %b")


def _label(phase: str, t: dt.datetime, close: dt.datetime | None, nxt: dt.datetime, ext: dt.datetime) -> str:
    if phase == "regular":
        return f"Market open · closes {_hm(close)} ET" if close else "Market open"
    if phase == "pre_market":
        return f"Pre-market · regular open {_hm(nxt)} ET"
    head = "After-hours" if phase == "after_hours" else "Market closed"
    tail = f" / pre-market {_hm(ext)}" if ext < nxt else ""
    return f"{head} · reopens {_day(nxt, t)} {_hm(nxt)} ET{tail}"


def session_at(at: Any) -> Session:
    """Classify an explicit instant (datetime, epoch s/ms/us/ns, or ISO string). Replays pass the tick's own time.
    Raises ValueError for an unparseable time or one outside 1971-01-01..2100-01-01."""
    t = check_supported(at)
    d = t.astimezone(ET).date()
    hours = regular_hours(d)
    ext = extended_hours(d)
    if hours is None:
        phase = "weekend" if d.weekday() >= 5 else "holiday"
    elif hours[0] <= t < hours[1]:
        phase = "regular"
    elif ext[0] <= t < hours[0]:  # type: ignore[index]
        phase = "pre_market"
    elif hours[1] <= t < ext[1]:  # type: ignore[index]
        phase = "after_hours"
    else:
        phase = "overnight"
    last_close = last_regular_close(t)
    nxt = next_regular_open(t)
    nxt_ext = next_extended_open(t)
    closure = None
    if phase != "regular":
        cd, od = last_close.astimezone(ET).date(), nxt.astimezone(ET).date()
        closure = Closure(kind=closure_kind(cd, od), close_day=cd, open_day=od, started_at=last_close, ends_at=nxt,
                          elapsed_s=(t - last_close).total_seconds(), remaining_s=(nxt - t).total_seconds())
    return Session(at=t, phase=phase, equities_open=phase == "regular",
                   extended_open=phase in ("pre_market", "after_hours"), trading_day=hours is not None,
                   early_close=is_early_close(d), holiday=holiday_name(d),
                   regular_open=hours[0] if hours else None, regular_close=hours[1] if hours else None,
                   last_close=last_close, next_open=nxt, next_extended_open=nxt_ext, closure=closure,
                   label=_label(phase, t, hours[1] if hours else None, nxt, nxt_ext))
