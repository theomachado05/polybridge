from __future__ import annotations

import bisect
import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Iterable

from .session import Session, session_at, to_utc

CLOSE_STALE_S = 30 * 60
NOW_STALE_S = 6 * 3600
KEEP_S = 10 * 86400
PRUNE_SLACK_S = 86400
MIN_GAP_S = 60.0

TRACKING = "TRACKING"
MARKET_OPEN = "MARKET_OPEN"
NO_CLOSE_PRICE = "NO_CLOSE_PRICE"
NO_PM_DATA = "NO_PM_DATA"


def market_key(source: str, market_id: str) -> str:
    return f"{source}:{market_id}"


def replay_key(source: str, market_id: str) -> str:
    return market_key(f"replay:{source}", market_id)


def _ts_s(ts: Any) -> float:
    return to_utc(ts).timestamp()


@dataclass(frozen=True)
class ClosureState:
    key: str
    status: str
    session: Session
    close_at: dt.datetime
    p_close: float | None
    p_close_at: dt.datetime | None
    p_now: float | None
    p_now_at: dt.datetime | None
    move_pp: float | None
    high_pp: float | None
    low_pp: float | None
    n_points: int

    @property
    def active(self) -> bool:
        return self.status == TRACKING

    def to_dict(self) -> dict:
        iso = lambda x: x.isoformat().replace("+00:00", "Z") if x else None  # noqa: E731
        return {"key": self.key, "status": self.status, "active": self.active, "close_at": iso(self.close_at),
                "p_close": self.p_close, "p_close_at": iso(self.p_close_at), "p_now": self.p_now,
                "p_now_at": iso(self.p_now_at), "move_pp": self.move_pp, "high_pp": self.high_pp,
                "low_pp": self.low_pp, "n_points": self.n_points,
                "closure": self.session.closure.to_dict() if self.session.closure else None}


class ClosureTracker:

    def __init__(self, close_stale_s: float = CLOSE_STALE_S, now_stale_s: float = NOW_STALE_S,
                 keep_s: float = KEEP_S, min_gap_s: float = MIN_GAP_S) -> None:
        self.close_stale_s = close_stale_s
        self.now_stale_s = now_stale_s
        self.keep_s = keep_s
        self.min_gap_s = min_gap_s
        self._t: dict[str, list[float]] = {}
        self._p: dict[str, list[float]] = {}
        self._epoch: dict[str, int] = {}
        self._ext: dict[str, tuple[int, float, int, int, float, float]] = {}

    def accepts(self, key: str, ts: Any) -> bool:
        try:
            t = _ts_s(ts)
        except ValueError:
            return False
        ts_list = self._t.get(key)
        return not ts_list or t >= ts_list[-1] - self.keep_s

    def observe(self, key: str, ts: Any, p: float) -> bool:
        try:
            p = float(p)
            t = _ts_s(ts)
        except (TypeError, ValueError, OverflowError, OSError):
            return False
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            return False
        ts_list, ps = self._t.setdefault(key, []), self._p.setdefault(key, [])
        if ts_list and t < ts_list[-1] - self.keep_s:
            return False
        i = bisect.bisect_left(ts_list, t)
        if i < len(ts_list) and ts_list[i] == t:
            if ps[i] != p:
                ps[i] = p
                self._bump(key)
            return True
        if i > 0 and ps[i - 1] == p and t - ts_list[i - 1] < self.min_gap_s:
            return True
        if i < len(ts_list):
            self._bump(key)
        ts_list.insert(i, t)
        ps.insert(i, p)
        if t - ts_list[0] > self.keep_s + PRUNE_SLACK_S:
            cut = bisect.bisect_left(ts_list, ts_list[-1] - self.keep_s)
            del ts_list[:cut], ps[:cut]
            self._bump(key)
        return True

    def _bump(self, key: str) -> None:
        self._epoch[key] = self._epoch.get(key, 0) + 1
        self._ext.pop(key, None)

    def observe_many(self, key: str, points: Iterable[tuple[Any, float]]) -> int:
        return sum(self.observe(key, t, p) for t, p in points)

    def has(self, key: str) -> bool:
        return bool(self._t.get(key))

    def keys(self) -> list[str]:
        return [k for k, v in self._t.items() if v]

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._t.clear()
            self._p.clear()
            self._ext.clear()
            self._epoch.clear()
        else:
            self._t.pop(key, None)
            self._p.pop(key, None)
            self._ext.pop(key, None)
            self._epoch.pop(key, None)

    def __len__(self) -> int:
        return sum(len(v) for v in self._t.values())

    def price_at(self, key: str, at: Any, stale_s: float | None = None) -> tuple[float, dt.datetime] | None:
        ts_list = self._t.get(key) or []
        t = _ts_s(at)
        i = bisect.bisect_right(ts_list, t) - 1
        if i < 0:
            return None
        if stale_s is not None and t - ts_list[i] > stale_s:
            return None
        return self._p[key][i], dt.datetime.fromtimestamp(ts_list[i], dt.timezone.utc)

    def has_close_anchor(self, key: str, at: Any) -> bool:
        return self.price_at(key, session_at(at).last_close, self.close_stale_s) is not None

    def state(self, key: str, at: Any) -> ClosureState:
        sess = session_at(at)
        close = sess.last_close
        anchor = self.price_at(key, close, self.close_stale_s)
        cur = self.price_at(key, sess.at, self.now_stale_s)
        ts_list = self._t.get(key) or []
        lo_i = bisect.bisect_right(ts_list, close.timestamp())
        hi_i = bisect.bisect_right(ts_list, sess.at.timestamp())
        hl = self._high_low(key, close.timestamp(), lo_i, hi_i)
        high = round(100.0 * hl[0], 9) if hl else None
        low = round(100.0 * hl[1], 9) if hl else None
        move = None
        if cur is None:
            status = NO_PM_DATA
        elif anchor is None:
            status = NO_CLOSE_PRICE
        else:
            move = round(100.0 * (cur[0] - anchor[0]), 9)
            status = MARKET_OPEN if sess.equities_open else TRACKING
        return ClosureState(key=key, status=status, session=sess, close_at=close,
                            p_close=anchor[0] if anchor else None, p_close_at=anchor[1] if anchor else None,
                            p_now=cur[0] if cur else None, p_now_at=cur[1] if cur else None, move_pp=move,
                            high_pp=high, low_pp=low, n_points=max(0, hi_i - lo_i))


    def _high_low(self, key: str, close_ts: float, lo_i: int, hi_i: int) -> tuple[float, float] | None:
        if hi_i <= lo_i:
            return None
        ps = self._p[key]
        epoch = self._epoch.get(key, 0)
        c = self._ext.get(key)
        if c is not None and c[0] == epoch and c[1] == close_ts and c[2] == lo_i and c[3] <= hi_i:
            high, low, start = c[4], c[5], c[3]
        else:
            high, low, start = -math.inf, math.inf, lo_i
        for i in range(start, hi_i):
            v = ps[i]
            if v > high:
                high = v
            if v < low:
                low = v
        self._ext[key] = (epoch, close_ts, lo_i, hi_i, high, low)
        return high, low


_DEFAULT: ClosureTracker | None = None


def default_tracker() -> ClosureTracker:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ClosureTracker()
    return _DEFAULT


def tracker_for(app: Any) -> ClosureTracker:
    state = app.state
    if getattr(state, "closure_tracker", None) is None:
        state.closure_tracker = ClosureTracker()
    return state.closure_tracker
