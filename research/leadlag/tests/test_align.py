import numpy as np
import pandas as pd

from leadlag.align import build_frame, equity_series, make_grid, pm_series

T0 = pd.Timestamp("2025-03-19 14:00:00", tz="UTC")


def test_grid_is_minute_end_labels_half_open():
    g = make_grid(T0, T0 + pd.Timedelta(minutes=5))
    assert list(g) == [T0 + pd.Timedelta(minutes=i) for i in range(5)]


def test_pm_forward_fill_uses_only_points_at_or_before_label():
    g = make_grid(T0, T0 + pd.Timedelta(minutes=10))
    ts1 = int((T0 + pd.Timedelta(seconds=62)).timestamp())
    ts2 = int((T0 + pd.Timedelta(seconds=270)).timestamp())
    out = pm_series([(ts1, 0.40), (ts2, 0.55)], g)
    assert np.isnan(out["px"].iloc[0]) and np.isnan(out["px"].iloc[1])
    assert out["px"].iloc[2] == 0.40 and out["px"].iloc[4] == 0.40
    assert out["px"].iloc[5] == 0.55
    assert out["obs"].iloc[2] == 1 and out["obs"].iloc[5] == 1 and out["obs"].iloc[3] == 0


def test_pm_empty_history_is_all_nan():
    g = make_grid(T0, T0 + pd.Timedelta(minutes=3))
    out = pm_series([], g)
    assert out["px"].isna().all() and (out["obs"] == 0).all()


def _bars(start, closes):
    idx = pd.DatetimeIndex([start + pd.Timedelta(minutes=i) for i in range(len(closes))])
    return pd.DataFrame({"close": closes, "volume": 1.0}, index=idx)


def test_equity_label_is_bar_end_and_ffill_stays_inside_session():
    g = make_grid(T0 - pd.Timedelta(minutes=2), T0 + pd.Timedelta(minutes=10))
    bars = _bars(T0, [100.0, 101.0, 102.0])
    bars = bars.drop(bars.index[1])
    out = equity_series(bars, g)
    at = lambda m: out.loc[T0 + pd.Timedelta(minutes=m)]
    assert at(1)["px"] == 100.0 and at(1)["obs"]
    assert at(2)["px"] == 100.0 and not at(2)["obs"] and at(2)["valid"]
    assert at(3)["px"] == 102.0
    assert not at(0)["valid"] and np.isnan(at(0)["px"])
    assert not at(4)["valid"] and np.isnan(at(4)["px"])


def test_equity_no_fill_across_overnight_gap():
    d1 = pd.Timestamp("2025-03-19 19:50:00", tz="UTC")
    d2 = pd.Timestamp("2025-03-20 13:30:00", tz="UTC")
    bars = pd.concat([_bars(d1, [10.0, 10.1]), _bars(d2, [11.0, 11.1])])
    g = make_grid(d1, d2 + pd.Timedelta(minutes=5))
    out = equity_series(bars, g)
    gap = out.loc[pd.Timestamp("2025-03-20 02:00", tz="UTC")]
    assert not gap["valid"] and np.isnan(gap["px"])
    x = build_frame(pd.DataFrame({"px": np.nan, "obs": 0}, index=g), out, 1, d2, d2 + pd.Timedelta(minutes=5))["x"]
    assert np.isnan(x.loc[d2 + pd.Timedelta(minutes=1)])


def test_build_frame_units_and_orientation():
    g = make_grid(T0, T0 + pd.Timedelta(minutes=4))
    pm = pd.DataFrame({"px": [0.50, 0.52, 0.52, 0.49], "obs": 1}, index=g)
    eq = pd.DataFrame({"px": [100.0, 100.0 * np.exp(0.0010), 100.0 * np.exp(0.0010), 100.0 * np.exp(-0.0005)],
                       "obs": True, "valid": True}, index=g)
    fr = build_frame(pm, eq, -1, T0, T0 + pd.Timedelta(minutes=4))
    assert np.isclose(fr["x"].iloc[1], 10.0)
    assert np.isclose(fr["y"].iloc[1], 2.0)
    assert np.isclose(fr["ys"].iloc[1], -2.0)
    assert np.isclose(fr["y"].iloc[3], -3.0)
    assert fr["in_window"].all()
