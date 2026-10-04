"""S20: the three windows of a market (METHOD.md section 1) and the two inclusion rules (section 3). Pure functions."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config as cfg

ET = ZoneInfo("America/New_York")


def at_et(day: str, hhmm: str) -> float:
    d, (h, m) = date.fromisoformat(day), (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ET).timestamp()


def session_spans(sess: pd.DataFrame) -> list[tuple[float, float]]:
    """(open, close) of every session of the calendar: 09:30 to 16:00 New York, or to 13:00 on an early close."""
    out = []
    for op, cl in zip(sess.open.to_numpy(), sess.close.to_numpy()):
        out.append((float(op), float(op) + (cfg.EARLY_SESSION_S if cl - op < cfg.EARLY_IF_SHORTER_THAN_S else cfg.SESSION_S)))
    return out


def weekend_starts(calendar: list[dict], sess: pd.DataFrame) -> np.ndarray:
    """Every weekend start of S9's and S18's calendar, plus the one after the calendar's last session day."""
    last = at_et(str(sess.day.iloc[-1]), cfg.WEEKEND_START_ET)
    return np.array(sorted({float(w["start"]) for w in calendar} | {last}))


def market_windows(entry: float, starts: np.ndarray, spans: list[tuple[float, float]]) -> dict:
    """W1: 48 hours from the entry. W2: 48 hours from the next weekend start. D1: the sessions between the two.
    A window is a list of (start, end) spans; W2 and D1 are empty if the calendar holds no later weekend start."""
    later = starts[starts > entry]
    w = {"W1": [(entry, entry + cfg.WINDOW_S)], "D1": [], "W2": []}
    if len(later):
        w2 = float(later[0])
        w["W2"] = [(w2, w2 + cfg.WINDOW_S)]
        w["D1"] = [(a, b) for a, b in spans if entry < a and b <= w2]
    return w


def bounds(spans: list[tuple[float, float]]) -> tuple[float, float] | None:
    return (spans[0][0], spans[-1][1]) if spans else None


def inside(ts: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= ts <= b for a, b in spans)


def status(rule: str, spans: list[tuple[float, float]], result_epoch: float, now: float) -> str:
    """'in', or why the market is left out of the window under the rule."""
    b = bounds(spans)
    if b is None:
        return "no window in the calendar"
    if b[1] > now:
        return "window not over at the pull"
    if rule == "A":
        return "in" if result_epoch > b[1] else "resolved before or during the window"
    return "in" if result_epoch > b[0] else "resolved before the window"
