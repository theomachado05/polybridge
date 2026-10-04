import numpy as np
import pandas as pd
import pytest

from s8_open_referee import config as cfg
from s8_open_referee import run as s8

V0, V1, V2, V3, V4 = cfg.VARIANTS


def test_first_bar_close_needs_the_bar_that_starts_at_the_open():
    bars = {"t": np.array([1000, 1300, 5000, 5600]), "c": np.array([10.0, 11.0, 20.0, 21.0])}
    out = s8.first_bar_close(bars, np.array([1000, 5000, 5300, 9000]))
    assert out[0] == 10.0 and out[1] == 20.0
    assert np.isnan(out[2]) and np.isnan(out[3])


def test_vote_is_signed_by_the_odds_and_by_the_link_direction():
    x = np.array([8.0, 8.0, -8.0, 8.0])
    up, down = np.array([40.0, -40.0, 40.0, np.nan]), np.array([-20.0, 60.0, np.nan, np.nan])
    a, n = s8.asset_vote(x, [up, down], [1, -1])
    assert a[0] == pytest.approx(30.0)
    assert a[1] == pytest.approx(-50.0)
    assert a[2] == pytest.approx(-40.0)
    assert np.isnan(a[3]) and list(n) == [2, 2, 1, 0]
    assert [s8.label(v) for v in a] == ["confirmed", "not confirmed", "not confirmed", "no vote"]
    assert s8.label(0.0) == "not confirmed"


def test_fade_sells_a_rise_and_buys_a_fall_across_the_spread_and_fee():
    side, entry, pnl = s8.fade(8.0, 0.60, 0.55, 1.0)
    f = lambda p: 0.04 * p * (1 - p)                        # noqa: E731
    assert side == "sell YES" and entry == pytest.approx(0.595)
    assert pnl == pytest.approx(0.595 - f(0.595) - 0.555 - f(0.555))
    side, entry, pnl = s8.fade(-8.0, 0.40, 0.45, 1.0)
    assert side == "buy YES" and entry == pytest.approx(0.405)
    assert pnl == pytest.approx(0.445 - f(0.445) - 0.405 - f(0.405))
    assert s8.fade(8.0, 0.60, 0.60, 1.0)[2] < 0


def test_double_costs_double_the_half_spread_and_the_fee():
    one, two = s8.fade(8.0, 0.60, 0.55, 1.0), s8.fade(8.0, 0.60, 0.55, 2.0)
    assert two[1] == pytest.approx(0.59)
    assert two[2] == pytest.approx(0.59 - 0.08 * 0.59 * 0.41 - 0.56 - 0.08 * 0.56 * 0.44)
    assert two[2] < one[2]


def frame(**over) -> pd.DataFrame:
    base = {"day": "2026-03-02", "market": "m", "x": 8.0, "vote": "not confirmed", "p_0940": 0.5, "p_close": 0.48, "p_next": 0.47,
            "weekend": False}
    return pd.DataFrame([{**base, **o} for o in over["rows"]])


def test_select_applies_threshold_vote_band_exit_and_weekend():
    df = frame(rows=[{"market": "a"}, {"market": "b", "x": -4.0}, {"market": "c", "vote": "confirmed"}, {"market": "d", "vote": "no vote"},
                     {"market": "e", "p_0940": 0.97}, {"market": "f", "p_close": np.nan}, {"market": "g", "x": -12.0, "weekend": True}])
    assert list(s8.select(df, V0).market) == ["g", "a"]
    assert list(s8.select(df, V1).market) == ["g"]
    assert sorted(s8.select(df, V2).market) == ["a", "f", "g"]
    assert sorted(s8.select(df, V3).market) == ["a", "c", "g"]
    assert list(s8.select(df, V4).market) == ["g"]
    assert s8.select(df, V2).p_exit.tolist() == [0.47, 0.47, 0.47]


def test_select_caps_a_session_at_the_largest_moves():
    rows = [{"market": f"m{i:02d}", "x": 5.0 + i} for i in range(14)] + [{"market": "other day", "day": "2026-03-03", "x": 5.0}]
    out = s8.select(frame(rows=rows), V0)
    first = out[out.day == "2026-03-02"]
    assert len(first) == cfg.MAX_POSITIONS and first.x.min() == 9.0
    assert list(out[out.day == "2026-03-03"].market) == ["other day"]
