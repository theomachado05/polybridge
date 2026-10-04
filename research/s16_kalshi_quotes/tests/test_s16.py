import numpy as np
import pytest

from s16_kalshi_quotes import run as s16


def test_the_quote_in_force_is_the_last_candle_and_a_one_sided_candle_cancels_it():
    t = np.array([100, 200, 300, 400])
    bid = np.array([0.40, 0.42, 0.99, 0.50])
    ask = np.array([0.42, 0.44, 1.00, 0.52])
    b, a = s16.standing_quote(np.array([50, 150, 250, 350, 450, 5000]), t, bid, ask, 1000)
    assert np.isnan(b[0])
    assert (b[1], a[1]) == (0.40, 0.42) and (b[2], a[2]) == (0.42, 0.44)
    assert np.isnan(b[3]) and np.isnan(a[3])
    assert (b[4], a[4]) == (0.50, 0.52)
    assert np.isnan(b[5])


def test_fade_sells_at_the_bid_buys_back_at_the_ask_and_pays_the_fee_twice():
    f = s16.fade_at_quotes(8.0, 0.60, 0.62, 0.55, 0.57, 1.0, 1.0)
    fee = lambda p: np.ceil(0.07 * 100 * p * (1 - p) * 100 - 1e-9) / 100 / 100      # noqa: E731
    assert f["side"] == "sell YES" and f["entry"] == 0.60 and f["exit"] == 0.57
    assert f["gross_mid"] == pytest.approx(0.61 - 0.56)
    assert f["spread_cost"] == pytest.approx(0.02)
    assert f["fee_cost"] == pytest.approx(fee(0.60) + fee(0.57))
    assert f["net"] == pytest.approx(0.03 - fee(0.60) - fee(0.57))
    assert f["capital"] == pytest.approx(40.0)
    g = s16.fade_at_quotes(-8.0, 0.40, 0.42, 0.45, 0.47, 1.0, 1.0)
    assert g["side"] == "buy YES" and g["entry"] == 0.42 and g["exit"] == 0.45
    assert g["net"] == pytest.approx(0.03 - fee(0.42) - fee(0.45)) and g["capital"] == pytest.approx(42.0)


def test_double_costs_move_each_fill_half_a_spread_further_and_double_the_fee():
    one = s16.fade_at_quotes(8.0, 0.60, 0.62, 0.55, 0.57, 1.0, 1.0)
    two = s16.fade_at_quotes(8.0, 0.60, 0.62, 0.55, 0.57, 1.0, 2.0)
    assert two["entry"] == pytest.approx(0.59) and two["exit"] == pytest.approx(0.58)
    assert two["spread_cost"] == pytest.approx(2 * one["spread_cost"])
    assert two["net"] < one["net"]
