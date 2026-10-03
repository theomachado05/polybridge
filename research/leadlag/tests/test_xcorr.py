import numpy as np
import pandas as pd

from leadlag.xcorr import cross_correlation

T0 = pd.Timestamp("2025-03-19 12:00:00", tz="UTC")


def make(n=600, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(T0, periods=n, freq="1min")
    return idx, pd.Series(rng.normal(0, 1, n), index=idx)


def test_pm_leading_by_five_minutes_gives_positive_peak_lag():
    idx, y = make()
    x = y.shift(5).fillna(0) + 0.2 * pd.Series(np.random.default_rng(1).normal(size=len(idx)), index=idx)
    xc = cross_correlation(x, y, pd.Series(True, index=idx))
    assert xc.peak_lag == 5 and xc.peak_rho > 0.9 and xc.significant
    assert xc.pm_lead_mass is not None and abs(xc.pm_lead_mass) < 0.5   # mean over 1..10 includes just one big lag


def test_equity_leading_gives_negative_peak_lag():
    idx, x = make(seed=2)
    y = x.shift(4).fillna(0) + 0.2 * pd.Series(np.random.default_rng(3).normal(size=len(idx)), index=idx)
    xc = cross_correlation(x, y, pd.Series(True, index=idx))
    assert xc.peak_lag == -4


def test_negative_relationship_peaks_on_absolute_value():
    idx, y = make(seed=4)
    x = -y.shift(2).fillna(0)
    xc = cross_correlation(x, y, pd.Series(True, index=idx))
    assert xc.peak_lag == 2 and xc.peak_rho < -0.99


def test_window_mask_and_min_n():
    idx, y = make(n=200, seed=5)
    x = y.shift(1).fillna(0)
    short = pd.Series(False, index=idx)
    short.iloc[100:130] = True          # only 30 window minutes: below the 60 minimum
    xc = cross_correlation(x, y, short)
    assert xc.peak_lag is None and xc.peak_rho is None


def test_constant_series_has_no_peak():
    idx, y = make(seed=6)
    x = pd.Series(0.0, index=idx)
    assert cross_correlation(x, y, pd.Series(True, index=idx)).peak_lag is None
