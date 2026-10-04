import numpy as np
import pytest

from s7_weekend_straddle import config as cfg
from s7_weekend_straddle import run as s7

V0, V1, V2 = cfg.VARIANTS


def test_put_ticker_swaps_only_the_right_letter():
    assert s7.put_ticker("O:EWZ261009C00038000") == "O:EWZ261009P00038000"
    assert s7.put_ticker("O:CCJ261016C00055000") == "O:CCJ261016P00055000"


def test_activity_uses_the_five_nights_ending_on_the_friday_only():
    x = np.array([9.0, 1.0, 2.0, 3.0, 4.0, 5.0, 99.0])
    assert s7.activity(x, 5) == pytest.approx(3.0)
    assert np.isnan(s7.activity(np.array([np.nan, np.nan, np.nan, 4.0, 5.0]), 4))


def test_flag_needs_live_odds_and_activity_on_the_same_question():
    assert s7.flagged([(0.50, 4.0)], V0) and s7.flagged([(0.50, 2.0)], V1) and not s7.flagged([(0.50, 2.0)], V0)
    assert not s7.flagged([(0.95, 9.0)], V0)
    assert not s7.flagged([(0.95, 9.0), (0.50, 1.0)], V0)
    assert s7.flagged([(0.20, 5.0)], V0) and not s7.flagged([(0.20, 5.0)], V2)
    assert not s7.flagged([(float("nan"), 5.0)], V0)


def test_controls_are_the_nearest_earlier_unflagged_weekend_used_once():
    assert s7.match_controls([10, 20], [5, 8, 15, 30]) == {10: 8, 20: 15}
    assert s7.match_controls([10, 11], [5, 8]) == {10: 8, 11: 5}
    assert s7.match_controls([3], [5, 8]) == {3: 5}
    assert s7.match_controls([3, 4], [5]) == {3: 5}


def test_straddle_buys_at_the_ask_and_sells_at_the_bid():
    q = {"call_fri": (1.00, 1.10), "put_fri": (0.90, 1.00), "call_mon": (1.50, 1.60), "put_mon": (0.40, 0.50)}
    s = s7.straddle(q, 1.0)
    assert s["cost"] == pytest.approx((1.10 + 1.00) * 100 + 1.30)
    assert s["proceeds"] == pytest.approx((1.50 + 0.40) * 100 - 1.30)
    assert s["ret"] == pytest.approx((188.70 - 211.30) / 211.30)
    assert s["mid_ret"] == pytest.approx((200.0 - 200.0) / 200.0)


def test_double_costs_double_every_half_spread_and_commission():
    q = {"call_fri": (1.00, 1.10), "put_fri": (0.90, 1.00), "call_mon": (1.50, 1.60), "put_mon": (0.40, 0.50)}
    one, two = s7.straddle(q, 1.0), s7.straddle(q, 2.0)
    assert two["cost"] == pytest.approx((1.15 + 1.05) * 100 + 2.60)
    assert two["proceeds"] == pytest.approx((1.45 + 0.35) * 100 - 2.60)
    assert (one["cost"] - one["proceeds"]) * 2 == pytest.approx(two["cost"] - two["proceeds"])


def test_bootstrap_of_a_difference():
    a = {f"w{i}": [0.10] for i in range(8)}
    b = {f"w{i}": [-0.05] for i in range(8)}
    d, lo, hi = s7.boot_diff(a, b)
    assert d == pytest.approx(0.15) and lo == pytest.approx(0.15) and hi == pytest.approx(0.15)
