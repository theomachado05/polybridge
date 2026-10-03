"""Alignment to a common 1-minute grid (METHOD.md section 3).

The grid is labelled by the END of each minute (UTC). Equity price at g = close of the bar that started at g-1min.
PM price at g = last CLOB point with timestamp <= g, carried forward. Both use only information available at g.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ET = "America/New_York"


def make_grid(fetch_start: pd.Timestamp, window_end: pd.Timestamp) -> pd.DatetimeIndex:
    """Minute-end labels g with fetch_start <= g < window_end."""
    return pd.date_range(fetch_start.ceil("min"), window_end.floor("min"), freq="1min", inclusive="left", tz="UTC")


def pm_series(points: list[tuple[int, float]], grid: pd.DatetimeIndex) -> pd.DataFrame:
    """PM price on the grid. `px` is NaN before the first observation; `obs` counts raw points in (g-1min, g]."""
    if not points:
        return pd.DataFrame({"px": np.nan, "obs": 0}, index=grid)
    idx = pd.to_datetime([t for t, _ in points], unit="s", utc=True)
    s = pd.Series([p for _, p in points], index=idx).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    px = s.reindex(grid, method="ffill")
    # count points per grid minute: a point at time t belongs to the grid label ceil(t) (g-1min < t <= g)
    labels = idx.ceil("min")
    obs = pd.Series(1, index=labels).groupby(level=0).sum().reindex(grid, fill_value=0)
    return pd.DataFrame({"px": px.to_numpy(), "obs": obs.to_numpy()}, index=grid)


def equity_series(bars: pd.DataFrame, grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Equity price on the grid, forward-filled only inside each trading session (never across the overnight gap).

    Sessions are defined per New York calendar date as [first bar label, last bar label]. `obs` = a real bar exists.
    """
    if bars is None or len(bars) == 0:
        return pd.DataFrame({"px": np.nan, "obs": False, "valid": False}, index=grid)
    s = bars["close"].copy()
    s.index = s.index + pd.Timedelta(minutes=1)  # bar start -> bar end label
    s = s[~s.index.duplicated(keep="last")]
    full = s.reindex(grid)
    obs = full.notna()
    valid = pd.Series(False, index=grid)
    for _, grp in pd.Series(s.index, index=s.index).groupby(s.index.tz_convert(ET).date):
        lo, hi = grp.index.min(), grp.index.max()
        valid |= (grid >= lo) & (grid <= hi)
    px = full.ffill()
    px[~valid.to_numpy()] = np.nan
    return pd.DataFrame({"px": px.to_numpy(), "obs": obs.to_numpy(), "valid": valid.to_numpy()}, index=grid)


def build_frame(pm: pd.DataFrame, eq: pd.DataFrame, expected_sign: int, window_start: pd.Timestamp,
                window_end: pd.Timestamp) -> pd.DataFrame:
    """One row per grid minute: levels, 1-minute changes, oriented PM change, window flag.

    eq_lvl = 1e4*ln(P) (bp), pm_lvl = 100*p (pp). x = diff(eq_lvl), y = diff(pm_lvl), ys = expected_sign * y.
    """
    grid = pm.index
    eq_lvl = 1e4 * np.log(eq["px"].astype(float))
    pm_lvl = 100.0 * pm["px"].astype(float)
    df = pd.DataFrame({
        "pm_px": pm["px"].to_numpy(), "pm_obs": pm["obs"].to_numpy(),
        "eq_px": eq["px"].to_numpy(), "eq_obs": eq["obs"].to_numpy(), "eq_valid": eq["valid"].to_numpy(),
        "eq_lvl": eq_lvl.to_numpy(), "pm_lvl": pm_lvl.to_numpy(),
    }, index=grid)
    df["x"] = df["eq_lvl"].diff()
    df["y"] = df["pm_lvl"].diff()
    df["ys"] = expected_sign * df["y"]
    df["in_window"] = (grid >= window_start) & (grid < window_end)
    return df
