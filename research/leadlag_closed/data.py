from __future__ import annotations

import pandas as pd

from leadlag.data import CountingSession, fetch_pm_history  # noqa: F401  (re-exported)

from .closures import Closure
from .config import CACHE_DIR, PARAMS, TZ


def fetch_equity_ohlc(client, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    path = f"/v2/aggs/ticker/{ticker}/range/1/minute/{int(start.timestamp() * 1000)}/{int(end.timestamp() * 1000)}"
    rows = client.get_all(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
    cols = ["open", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame(rows)
    idx = pd.to_datetime(df["t"], unit="ms", utc=True)
    out = pd.DataFrame({"open": df["o"].astype(float).to_numpy(), "close": df["c"].astype(float).to_numpy(),
                        "volume": df["v"].astype(float).to_numpy()}, index=idx)
    return out[~out.index.duplicated(keep="last")].sort_index()


YEAR_END_CLAMP = pd.Timestamp("2025-12-31 23:59", tz="UTC")


def month_chunks(start: str, end: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out = []
    cur = s.replace(day=1)
    while cur <= e:
        nxt = (cur + pd.offsets.MonthBegin(1))
        out.append((max(cur, s) .tz_localize("UTC") - pd.Timedelta(days=1), min(min(nxt, e + pd.Timedelta(days=1)).tz_localize("UTC") + pd.Timedelta(days=1), YEAR_END_CLAMP)))
        cur = nxt
    return out


def fetch_equity_range(client, ticker: str, start: str, end: str) -> pd.DataFrame:
    parts = [fetch_equity_ohlc(client, ticker, a, b) for a, b in month_chunks(start, end)]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=["open", "close", "volume"], index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_closure_pm(token_id: str, c: Closure, pm_session=None, cache_dir=None) -> list[tuple[int, float]]:
    start = c.nominal_close - pd.Timedelta(minutes=PARAMS.pm_pad_before_min)
    end = c.nominal_open + pd.Timedelta(minutes=PARAMS.pm_pad_after_min)
    return fetch_pm_history(token_id, start, end, cache_dir or (CACHE_DIR / "pm"), session=pm_session)
