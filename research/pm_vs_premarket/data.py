from __future__ import annotations

import numpy as np
import pandas as pd

from leadlag.data import CountingSession, fetch_pm_history  # noqa: F401  (re-exported)
from leadlag_closed.closures import Closure, equity_measures, pm_at
from leadlag_closed.data import fetch_equity_range  # noqa: F401  (re-exported)

from .config import (FUTURES_PATH, PARAMS, PROBE_MIN_BARS, PROBE_TICKERS, PROBE_WINDOW_ET, QUARTER_CODES, ROLL_DAYS,
                     TZ)


def _ns(ts: pd.Timestamp) -> int:
    return int(ts.value)


def parse_futures_rows(rows: list[dict]) -> pd.DataFrame:
    out_t, out_c = [], []
    for r in rows or []:
        t = r.get("window_start", r.get("t", r.get("timestamp")))
        c = r.get("close", r.get("c"))
        if t is None or c is None:
            continue
        t = int(t)
        unit = "ns" if t > 1e15 else "ms" if t > 1e12 else "s"
        out_t.append(pd.Timestamp(t, unit=unit, tz="UTC"))
        out_c.append(float(c))
    if not out_t:
        return pd.DataFrame(columns=["close"], index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame({"close": out_c}, index=pd.DatetimeIndex(out_t))
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_futures_bars(client, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = client.get_all(FUTURES_PATH.format(ticker=ticker),
                          {"resolution": "1min", "window_start.gte": _ns(start), "window_start.lt": _ns(end),
                           "limit": 50000, "sort": "window_start.asc"})
    return parse_futures_rows(rows)


def probe_futures(client) -> dict:
    a = pd.Timestamp(PROBE_WINDOW_ET[0], tz=TZ).tz_convert("UTC")
    b = pd.Timestamp(PROBE_WINDOW_ET[1], tz=TZ).tz_convert("UTC")
    log = []
    for tk in PROBE_TICKERS:
        try:
            n = len(fetch_futures_bars(client, tk, a, b))
            log.append(f"{tk}: {n} bars")
            if n >= PROBE_MIN_BARS:
                return {"benchmark": "ES", "spelling": "y2" if tk.endswith("24") else "y1", "log": log}
        except Exception as exc:  # noqa: BLE001
            log.append(f"{tk}: {type(exc).__name__}: {str(exc)[:120]}")
    return {"benchmark": "SPY", "spelling": None, "log": log}


def third_friday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1)
    return first + pd.Timedelta(days=(4 - first.weekday()) % 7 + 14)


def front_contract(root: str, open_day: pd.Timestamp, spelling: str = "y1") -> str:
    d = pd.Timestamp(open_day).normalize()
    y, mo = d.year, d.month
    for _ in range(8):
        q = ((mo - 1) // 3 + 1) * 3
        if q > 12:
            y, q = y + 1, 3
        exp = third_friday(y, q)
        if (exp - d).days > ROLL_DAYS:
            yy = str(y % 10) if spelling == "y1" else f"{y % 100:02d}"
            return f"{root}{QUARTER_CODES[q]}{yy}"
        mo = q + 1
        if mo > 12:
            y, mo = y + 1, 1
    raise ValueError("no contract found")


def at_or_before(bars: pd.DataFrame, t: pd.Timestamp, tol_min: int | None = None) -> float:
    tol = PARAMS.bar_tol_min if tol_min is None else tol_min
    if bars is None or bars.empty:
        return float("nan")
    ends = bars.index + pd.Timedelta(minutes=1)
    ok = (ends <= t) & (ends >= t - pd.Timedelta(minutes=tol))
    if not ok.any():
        return float("nan")
    return float(bars["close"].iloc[np.flatnonzero(ok)[-1]])


def bench_time(c: Closure, hm: tuple) -> pd.Timestamp:
    return (c.open_day.tz_localize(TZ) + pd.Timedelta(hours=hm[0], minutes=hm[1])).tz_convert("UTC")


def closure_measures(c: Closure, spy_bars: pd.DataFrame, points: list[tuple[int, float]], sign: int,
                     bench_bars: pd.DataFrame | None = None, times: dict | None = None) -> dict:
    times = times or {"0925": PARAMS.t_primary, "0800": PARAMS.t_sens}
    eq = equity_measures(spy_bars, c)
    nan = float("nan")
    t_close = eq["t_close"] if pd.notna(eq["t_close"]) else c.nominal_close
    pm_c = pm_at(points, t_close, PARAMS.pm_stale_min)
    pm_o = pm_at(points, c.nominal_open, PARAMS.pm_stale_min)
    row = {"closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind, "g": eq["gap_bp"],
           "pm_close": pm_c, "x_full": sign * (pm_o - pm_c) if np.isfinite(pm_c) and np.isfinite(pm_o) else nan}
    if bench_bars is None:
        ref = eq["prev_close"]
        src = spy_bars
    else:
        ref = at_or_before(bench_bars, t_close)
        src = bench_bars
    for name, hm in times.items():
        t = bench_time(c, hm)
        px = at_or_before(src, t)
        row[f"b_{name}"] = 1e4 * (px / ref - 1) if np.isfinite(px) and np.isfinite(ref) and ref > 0 else nan
        pm_t = pm_at(points, t, PARAMS.pm_stale_min)
        row[f"x_{name}"] = sign * (pm_t - pm_c) if np.isfinite(pm_t) and np.isfinite(pm_c) else nan
    return row


def arm_k_rows(df: pd.DataFrame) -> pd.DataFrame:
    d = df[(~df["news"].astype(bool)) & (df["reason"].isna() | (df["reason"].astype(str) == ""))].copy()
    g = d["gap_bp"].astype(float)
    r = d["resid_bp"].astype(float)
    out = pd.DataFrame({"closure": d["closure"].astype(str), "open_day": d["open_day"].astype(str), "market": d["market"],
                        "kind": d["kind"], "g": g, "b_0800": 1e4 * ((1 + g / 1e4) / (1 + r / 1e4) - 1),
                        "x_0800": d["dpm_early_o_pp"].astype(float), "x_full": d["dpm_o_pp"].astype(float)})
    return out.reset_index(drop=True)
