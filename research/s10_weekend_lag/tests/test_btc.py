import math

import numpy as np

from s10_weekend_lag.btc import fair_value, verify


def test_fair_value_at_the_start_price_is_one_half():
    assert abs(fair_value(5, 100.0, np.full(5, 100.0), 0.001) - 0.5) < 1e-12


def test_fair_value_monotone_and_certain_at_the_end():
    lo = fair_value(10, 100.0, np.full(10, 99.9), 0.001)
    hi = fair_value(10, 100.0, np.full(10, 100.1), 0.001)
    assert lo < 0.5 < hi
    assert fair_value(15, 100.0, np.full(15, 100.01), 0.001) == 1.0
    assert fair_value(15, 100.0, np.full(15, 99.99), 0.001) == 0.0


def test_fair_value_formula():
    m, n, s0, sig = 9, 6, 100.0, 0.0008
    c = np.array([100.0] * 8 + [100.05])
    a, s = c.mean(), c[-1]
    z = (m * a + n * s - 15 * s0) / (n * s * sig * math.sqrt(n / 3))
    assert abs(fair_value(m, s0, c, sig) - 0.5 * (1 + math.erf(z / math.sqrt(2)))) < 1e-12


def test_verify_up_and_down_prints():
    pr = [{"timestamp": 1010, "price": 0.60, "side": "BUY", "outcome": "Up", "size": 10},
          {"timestamp": 1020, "price": 0.45, "side": "SELL", "outcome": "Down", "size": 5},    # = an Up purchase at 0.55
          {"timestamp": 1200, "price": 0.50, "side": "BUY", "outcome": "Up", "size": 7}]        # outside two minutes
    assert verify(pr, True, 0.60, 1000) == (2, 15.0)
    assert verify(pr, True, 0.56, 1000) == (1, 5.0)
    assert verify(pr, False, 0.60, 1000) == (0, 0.0)


def test_yes_result():
    from s10_weekend_lag.hold import yes_result
    assert yes_result({"closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]'}) == 0.0
    assert yes_result({"closed": True, "outcomes": '["No", "Yes"]', "outcomePrices": '["0", "1"]'}) == 1.0
    assert yes_result({"closed": False, "outcomes": '["Yes", "No"]', "outcomePrices": '["0.4", "0.6"]'}) is None
    assert yes_result({"closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["0.5", "0.5"]'}) is None
