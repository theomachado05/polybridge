import math
import random

import pytest

import live_books  # noqa: F401
from live_books import detector as D


def test_python_buy_yes_and_no():
    s, e, n, px, sz = D.decide_py(0.38, 100, 0.40, 50, 0.46)
    assert (s, px, sz) == (D.BUY_YES, 0.40, 50)
    assert e == pytest.approx(6.0) and n == pytest.approx(6.0 - 100 * 0.04 * 0.24)
    s, e, n, px, sz = D.decide_py(0.60, 30, 0.62, 10, 0.55, fees_enabled=False)
    assert (s, sz) == (D.BUY_NO, 30) and px == pytest.approx(0.40) and e == pytest.approx(5.0) == n


def test_python_none_cases():
    assert D.decide_py(0.48, 10, 0.52, 10, 0.50)[0] == D.NONE
    assert D.decide_py(0.10, 10, 0.20, 0, 0.50)[0] == D.NONE
    assert D.decide_py(0.10, 10, 0.20, 10, float("nan"))[0] == D.NONE
    assert D.decide_py(0.10, 10, 0.20, 10, 0.99)[0] == D.NONE


@pytest.mark.skipif(D.decide_cpp is None, reason="hedgecore_stale not built (engine/hedgecore/scripts/build_stale.sh)")
def test_cpp_matches_python():
    rng = random.Random(7)
    for _ in range(5000):
        p = rng.uniform(0.0, 1.0)
        bid = round(rng.uniform(0.0, 1.0), 2)
        ask = round(min(1.0, bid + rng.choice([0.01, 0.02, 0.05, 0.2])), 2)
        args = (bid, rng.choice([0.0, 5.0, 100.0]), ask, rng.choice([0.0, 7.0, 250.0]), p, rng.choice([0.03, 0.05, 0.10]),
                0.04, rng.choice([1.0, 2.0]), rng.random() < 0.5)
        a, b = D.decide_cpp(*args), D.decide_py(*args)
        assert a[0] == b[0]
        for x, y in zip(a[1:], b[1:]):
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y, abs=1e-9)
