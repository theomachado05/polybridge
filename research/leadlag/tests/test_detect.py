import numpy as np
import pandas as pd

from leadlag.config import PARAMS
from leadlag.detect import first_move, lead_class, lead_minutes, rolling_sigma

T0 = pd.Timestamp("2025-03-19 12:00:00", tz="UTC")
N = 400


def series(noise_sd=1.0, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(T0, periods=N, freq="1min")
    chg = pd.Series(rng.normal(0, noise_sd, N), index=idx)
    chg.iloc[0] = np.nan
    return idx, chg


def level_of(chg):
    return chg.fillna(0).cumsum()


def window(idx, start_i, end_i=None):
    w = pd.Series(False, index=idx)
    w.iloc[start_i:end_i] = True
    return w


def test_step_move_detected_at_the_jump_minute():
    idx, chg = series()
    chg.iloc[250] += 25.0
    lvl = level_of(chg)
    m = first_move(lvl, chg, window(idx, 200), floor=0.1)
    assert m is not None and m.time == idx[250] and m.direction == 1 and m.z > 4


def test_negative_step_has_negative_direction():
    idx, chg = series(seed=2)
    chg.iloc[260] -= 30.0
    m = first_move(level_of(chg), chg, window(idx, 200), floor=0.1)
    assert m.time == idx[260] and m.direction == -1


def test_one_minute_spike_that_reverts_is_rejected_by_persistence():
    idx, chg = series(seed=3)
    chg.iloc[250] += 30.0
    chg.iloc[251] -= 30.0
    assert first_move(level_of(chg), chg, window(idx, 200), floor=0.1) is None


def test_move_before_the_window_is_ignored():
    idx, chg = series(seed=4)
    chg.iloc[150] += 30.0
    assert first_move(level_of(chg), chg, window(idx, 200), floor=0.1) is None


def test_floor_prevents_tiny_moves_in_a_flat_series_from_counting():
    idx = pd.date_range(T0, periods=N, freq="1min")
    chg = pd.Series(0.0, index=idx)
    chg.iloc[0] = np.nan
    chg.iloc[250] = 0.5
    lvl = level_of(chg)
    assert first_move(lvl, chg, window(idx, 200), floor=0.25) is None
    chg.iloc[251] = 2.0
    assert first_move(level_of(chg), chg, window(idx, 200), floor=0.25) is not None


def test_not_enough_history_means_no_detection():
    idx, chg = series(seed=5)
    chg.iloc[10] += 40.0
    assert first_move(level_of(chg), chg, window(idx, 0), floor=0.1) is None


def test_move_needs_five_minutes_of_data_after_it():
    idx, chg = series(seed=6)
    chg.iloc[N - 3] += 40.0
    assert first_move(level_of(chg), chg, window(idx, 200), floor=0.1) is None


def test_rolling_sigma_excludes_current_minute_and_applies_floor():
    idx, chg = series(noise_sd=1.0, seed=7)
    sig = rolling_sigma(chg, PARAMS, floor=0.5)
    assert 0.8 < sig.iloc[300] < 1.2
    chg2 = chg * 0.01
    assert np.isclose(rolling_sigma(chg2, PARAMS, floor=0.5).iloc[300], 0.5)


def test_lead_minutes_sign_and_classes():
    from leadlag.detect import Move
    pm = Move(T0, 5.0, 1.0, 5.0)
    eq = Move(T0 + pd.Timedelta(minutes=7), 9.0, 1.0, 5.0)
    assert lead_minutes(pm, eq) == 7.0 and lead_class(7.0) == "PM first"
    assert lead_minutes(eq, pm) == -7.0 and lead_class(-7.0) == "equity first"
    assert lead_class(1.0) == "simultaneous" and lead_class(-1.0) == "simultaneous" and lead_class(0.0) == "simultaneous"
    assert lead_minutes(None, eq) is None and lead_class(None) == "NA"
