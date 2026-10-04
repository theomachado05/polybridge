import numpy as np
import pytest

from s14_link_ceiling import config as cfg
from s14_link_ceiling import run as s14


def test_slope_t_is_through_the_origin_and_needs_enough_moves():
    x = np.tile([1.0, -2.0, 3.0, -1.0], 10)
    b, t, n = s14.slope_t(x, 2.0 * x + np.tile([0.1, -0.1], 20))
    assert b == pytest.approx(2.0, abs=0.05) and t > 20 and n == 40
    b, t, n = s14.slope_t(x[:20], 2.0 * x[:20])
    assert np.isnan(b) and np.isnan(t) and n == 20
    y = 2.0 * x
    y[0] = np.nan
    assert s14.slope_t(x, y)[2] == 39
    assert s14.slope_t(np.where(np.arange(40) < 15, 0.0, x), y)[2] < cfg.MIN_MOVES


def test_pick_separates_continuation_from_reversal_and_ignores_links_without_a_slope():
    cont, rev = s14.pick(np.array([2.5, -2.5, 1.9, np.nan, 2.0, -2.0]))
    assert list(cont) == [True, False, False, False, True, False]
    assert list(rev) == [False, True, False, False, False, True]


def test_shares_count_strong_links_on_both_tails_after_the_open_and_one_tail_for_the_gap():
    t_after = np.array([2.5, -3.0, 0.1, 0.2, -0.3, 0.4, 0.5, 0.6, 0.7, np.nan])
    t_gap = np.array([4.0, 2.0, 1.0, -3.0, np.nan, 0.0, 0.0, 0.0, 0.0, 0.0])
    share, top, gap = s14.shares(t_after, t_gap)
    assert share == pytest.approx(2 / 9)
    assert top == pytest.approx(3.0)
    assert gap == pytest.approx(2 / 9)
