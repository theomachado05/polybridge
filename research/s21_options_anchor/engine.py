from __future__ import annotations

import calendar as _cal
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "arb"))
from arbscan.implied import Quote, Spread, bracket_indices  # noqa: E402  (the existing call-spread code, imported unchanged)

from . import config as cfg  # noqa: E402

MONTHS = {m.lower(): i for i, m in enumerate(_cal.month_name) if m}
_SYMBOL = re.compile(r"\(([A-Z]{1,5})\)")
_LEVEL = re.compile(r"(?:reach|dip to|hit)\s+(?:\((?:HIGH|LOW)\)\s+)?\$?([\d,]+(?:\.\d+)?)")
_NUMBER = re.compile(r"\$?([\d,]+(?:\.\d+)?)")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def window_end(title: str, listed: date) -> date | None:
    t = title.strip().rstrip("?").strip()
    m = re.search(r"before (\d{4})$", t)
    if m:
        return date(int(m.group(1)) - 1, 12, 31)
    m = re.search(r"Week of (\w+) (\d{1,2}) (\d{4})$", t)
    if m and m.group(1).lower() in MONTHS:
        d = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        return d + timedelta(days=(4 - d.weekday()) % 7)
    m = re.search(r"(?:in|by end of) (\w+)(?: (\d{4}))?$", t)
    if m and m.group(1).lower() in MONTHS:
        mo = MONTHS[m.group(1).lower()]
        if m.group(2):
            y = int(m.group(2))
        else:
            y = listed.year if date(listed.year, mo, _cal.monthrange(listed.year, mo)[1]) >= listed else listed.year + 1
        return date(y, mo, _cal.monthrange(y, mo)[1])
    return None


def last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse_market(m: dict) -> tuple[dict | None, str]:
    q, title, label = str(m.get("question", "")), str(m.get("event_title", "")), str(m.get("label", ""))
    sym = _SYMBOL.findall(title)
    if len(sym) != 1:
        return None, "no single ticker in the event title"
    ticker = sym[0]
    q_sym = [s for s in _SYMBOL.findall(q) if s not in ("HIGH", "LOW")]
    if q_sym and q_sym != [ticker]:
        return None, "the question's ticker and the event's ticker disagree"
    lv = _LEVEL.search(q)
    if not lv:
        return None, "no level in the question"
    level = _num(lv.group(1))
    lab = _NUMBER.search(label)
    if not lab or abs(_num(lab.group(1)) - level) > 1e-9:
        return None, "the question's level and the label's level disagree"
    up = bool(re.search(r"\breach\b", q)) or "(HIGH)" in q
    down = bool(re.search(r"\bdip\b", q)) or "(LOW)" in q
    if up and down:
        return None, "both directions in the question"
    if up or down:
        direction = 1 if up else -1
    elif "↑" in label or "↓" in label:
        direction = 1 if "↑" in label else -1
    else:
        return None, "no direction in the question or the label"
    if int(m.get("sign", 0)) != direction:
        return None, "the parsed direction and the universe's sign disagree"
    listed = date.fromisoformat(str(m.get("start", ""))[:10])
    end = window_end(title, listed)
    if end is None:
        return None, "no window end in the event title"
    return {"ticker": ticker, "level": level, "direction": direction, "window_end": end.isoformat(),
            "end_session": last_weekday(end).isoformat()}, ""


def put_ticker(call: str) -> str:
    assert call[-9] == "C", call
    return call[:-9] + "P" + call[-8:]


def usable(q: Quote | None, at: float) -> bool:
    if q is None or not (q.ask > 0 and q.ask >= q.bid >= 0):
        return False
    return not math.isnan(q.ts) and -1.0 <= at - q.ts <= cfg.STALE_OPTION_S


def finish_beyond(strikes: Sequence[float], level: float, direction: int, get_quote: Callable[[float], Quote | None],
                  t_years: float, at: float) -> Spread | None:
    s = sorted(strikes)
    ij = bracket_indices(s, level)
    if ij is None:
        return None
    lo, hi = ij
    q_lo = q_hi = None
    stepped = 0
    for n in range(cfg.MAX_STEP_OUT + 1):
        if q_lo is None and lo - n >= 0:
            q = get_quote(s[lo - n])
            if usable(q, at):
                q_lo, lo, stepped = q, lo - n, stepped + n
        if q_hi is None and hi + n < len(s):
            q = get_quote(s[hi + n])
            if usable(q, at):
                q_hi, hi, stepped = q, hi + n, stepped + n
        if q_lo is not None and q_hi is not None:
            break
    if q_lo is None or q_hi is None:
        return None
    long_leg, short_leg = (q_lo, q_hi) if direction > 0 else (q_hi, q_lo)
    return Spread(s[lo], s[hi], long_leg, short_leg, t_years, rate=cfg.RATE, stepped=stepped)


def anchors(p: float) -> tuple[float, float]:
    return p, min(1.0, cfg.CENTRAL_MULTIPLE * p)


def bucket_label(lo: float | None, hi: float | None) -> str:
    if lo is None:
        return f"below {hi:+.0f}"
    if hi is None:
        return f"{lo:+.0f} or more"
    return f"{lo:+.0f} to {hi:+.0f}"


def gap_bucket(gap_points: float) -> str:
    for lo, hi in cfg.GAP_BUCKETS:
        if (lo is None or gap_points >= lo) and (hi is None or gap_points < hi):
            return bucket_label(lo, hi)
    return "n/a"


def selected(book: cfg.Book, traded: float, anchor: float) -> bool:
    if traded != traded or anchor != anchor:
        return False
    gap = 100.0 * (traded - anchor)
    return gap >= book.threshold - 1e-9 if book.side == "sell" else -gap >= book.threshold - 1e-9


def ols_cluster(y: np.ndarray, X: np.ndarray, groups: Sequence) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(y)), np.asarray(X, float)])
    n, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    b = xtx_inv @ X.T @ y
    e = y - X @ b
    g = np.asarray([str(x) for x in groups])
    meat = np.zeros((k, k))
    keys = sorted(set(g))
    for key in keys:
        idx = g == key
        s = X[idx].T @ e[idx]
        meat += np.outer(s, s)
    G = len(keys)
    adj = (G / (G - 1.0)) * ((n - 1.0) / (n - k)) if G > 1 and n > k else float("nan")
    V = adj * xtx_inv @ meat @ xtx_inv
    return b, np.sqrt(np.diag(V))


def brier(p: np.ndarray, outcome: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(outcome, float)) ** 2))
