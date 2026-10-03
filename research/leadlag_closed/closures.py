"""Closure calendar and per-closure measures (METHOD.md sections 1 and 3). Pure functions, no network."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import yaml

from polybridge_research.calendar import TradingCalendar

from .config import EVENTS_PATH, PARAMS, TZ

RTH_OPEN = pd.Timedelta(hours=9, minutes=30)
RTH_CLOSE = pd.Timedelta(hours=16)


@dataclass(frozen=True)
class Closure:
    close_day: pd.Timestamp  # trading day whose close starts the closure (tz-naive date)
    open_day: pd.Timestamp   # next trading day
    kind: str                # overnight | weekend | holiday

    @property
    def nominal_close(self) -> pd.Timestamp:
        return (self.close_day.tz_localize(TZ) + RTH_CLOSE).tz_convert("UTC")

    @property
    def nominal_open(self) -> pd.Timestamp:
        return (self.open_day.tz_localize(TZ) + RTH_OPEN).tz_convert("UTC")

    @property
    def key(self) -> str:
        return self.close_day.strftime("%Y-%m-%d")


def closure_kind(close_day: pd.Timestamp, open_day: pd.Timestamp) -> str:
    n = (open_day - close_day).days
    if n == 1:
        return "overnight"
    if n == 3 and close_day.weekday() == 4:
        return "weekend"
    return "holiday"


def build_closures(start: str, end: str, cal: TradingCalendar | None = None) -> list[Closure]:
    """Every closure whose START trading day lies in [start, end] (inclusive)."""
    cal = cal or TradingCalendar()
    s = cal.sessions
    out = []
    for i in range(len(s) - 1):
        d = s[i]
        if d < pd.Timestamp(start) or d > pd.Timestamp(end):
            continue
        out.append(Closure(d, s[i + 1], closure_kind(d, s[i + 1])))
    return out


def closure_for_news(news_et: str | pd.Timestamp, cals_closures: list[Closure]) -> Closure | None:
    """The closure that contains the news timestamp (naive ET string), by nominal 16:00 / 09:30 times."""
    t = pd.Timestamp(news_et)
    t = t.tz_localize(TZ).tz_convert("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    for c in cals_closures:
        if c.nominal_close <= t < c.nominal_open:
            return c
    return None


def load_events(path=EVENTS_PATH) -> tuple[dict, list[dict]]:
    doc = yaml.safe_load(open(path))
    return doc["markets"], doc["events"]


# ---------------------------------------------------------------- equity bars


def _et(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(TZ)


def rth_bars(bars: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """Bars whose START is inside RTH [09:30, 16:00) ET on `day`."""
    if bars.empty:
        return bars
    et = _et(bars.index)
    mask = (et.normalize().tz_localize(None) == day.normalize()) & (et.hour * 60 + et.minute >= 570) & (et.hour * 60 + et.minute < 960)
    return bars[mask]


def equity_measures(bars: pd.DataFrame, c: Closure) -> dict:
    """gap_bp, ret30_bp, px_0800 and the exact close/open instants. NaN where a bar is missing (never imputed)."""
    nan = float("nan")
    out = {"prev_close": nan, "open_px": nan, "gap_bp": nan, "ret30_bp": nan, "px_0800": nan, "resid_bp": nan,
           "t_close": pd.NaT, "t_open": pd.NaT, "t_0800": pd.NaT}
    prev = rth_bars(bars, c.close_day)
    nxt = rth_bars(bars, c.open_day)
    if not prev.empty:
        out["prev_close"] = float(prev["close"].iloc[-1])
        out["t_close"] = prev.index[-1] + pd.Timedelta(minutes=1)
    if not nxt.empty:
        first = nxt.index[0]
        if first <= c.nominal_open + pd.Timedelta(minutes=PARAMS.open_tol_min):
            out["open_px"] = float(nxt["open"].iloc[0])
            out["t_open"] = first
    if np.isfinite(out["prev_close"]) and np.isfinite(out["open_px"]):
        out["gap_bp"] = 1e4 * (out["open_px"] / out["prev_close"] - 1)
    if np.isfinite(out["open_px"]):
        t1000 = c.nominal_open + pd.Timedelta(minutes=29)  # bar starting 09:59
        if t1000 in nxt.index:
            out["ret30_bp"] = 1e4 * (float(nxt.loc[t1000, "close"]) / out["open_px"] - 1)
    # last bar ending at or before 08:00 ET on the open day, within tolerance
    cut = (c.open_day.tz_localize(TZ) + pd.Timedelta(hours=PARAMS.resid_cut_hour)).tz_convert("UTC")
    ends = bars.index + pd.Timedelta(minutes=1) if not bars.empty else bars.index
    if not bars.empty:
        ok = (ends <= cut) & (ends >= cut - pd.Timedelta(minutes=PARAMS.resid_tol_min))
        if ok.any():
            j = np.flatnonzero(ok)[-1]
            out["px_0800"] = float(bars["close"].iloc[j])
            out["t_0800"] = cut
    if np.isfinite(out["px_0800"]) and np.isfinite(out["open_px"]):
        out["resid_bp"] = 1e4 * (out["open_px"] / out["px_0800"] - 1)
    return out


# ------------------------------------------------------------------------ PM


def pm_at(points: list[tuple[int, float]], t: pd.Timestamp, stale_min: int | None = None) -> float:
    """Last CLOB point with timestamp <= t, in percentage points; NaN if none within `stale_min` minutes before t."""
    stale_min = PARAMS.pm_stale_min if stale_min is None else stale_min
    ts = int(t.timestamp())
    best = None
    for tt, p in points:
        if tt <= ts and (best is None or tt >= best[0]):
            best = (tt, p)
    if best is None or ts - best[0] > stale_min * 60:
        return float("nan")
    return 100.0 * best[1]


def closure_row(c: Closure, bars: pd.DataFrame, bars2: pd.DataFrame | None, points: list[tuple[int, float]],
                sign: int, market: str) -> dict:
    """One analysis row: equity measures (SPY), QQQ gap, PM change at the exact instants, oriented."""
    eq = equity_measures(bars, c)
    t_close = eq["t_close"] if pd.notna(eq["t_close"]) else c.nominal_close
    t_open = c.nominal_open
    pm_c = pm_at(points, t_close)
    pm_o = pm_at(points, t_open)
    pm_8 = pm_at(points, eq["t_0800"]) if pd.notna(eq["t_0800"]) else float("nan")
    dpm = pm_o - pm_c
    row = {
        "closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind, "market": market, "sign": sign,
        "pm_close": pm_c, "pm_open": pm_o, "dpm_pp": dpm, "dpm_o_pp": sign * dpm,
        "dpm_early_o_pp": sign * (pm_8 - pm_c) if np.isfinite(pm_8) and np.isfinite(pm_c) else float("nan"),
        "gap_bp": eq["gap_bp"], "ret30_bp": eq["ret30_bp"], "resid_bp": eq["resid_bp"],
    }
    if bars2 is not None:
        row["gap_qqq_bp"] = equity_measures(bars2, c)["gap_bp"]
    reasons = []
    if not (np.isfinite(pm_c) and np.isfinite(pm_o)):
        reasons.append("no PM quote")
    if not np.isfinite(eq["gap_bp"]):
        reasons.append("no equity bar")
    row["reason"] = "; ".join(reasons)
    return row
