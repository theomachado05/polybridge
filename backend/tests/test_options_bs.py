import math

import pytest

from app.options import bs

S, K, T, R, SIG = 100.0, 100.0, 1.0, 0.05, 0.2


def test_price_matches_hand_computed():
    assert bs.price(S, K, T, R, SIG, True) == pytest.approx(10.4506, abs=1e-4)
    assert bs.price(S, K, T, R, SIG, False) == pytest.approx(5.5735, abs=1e-4)


def test_put_call_parity():
    c, p = bs.price(S, 95, 0.5, R, 0.3, True), bs.price(S, 95, 0.5, R, 0.3, False)
    assert c - p == pytest.approx(S - 95 * math.exp(-R * 0.5), abs=1e-9)


def test_greeks_match_hand_computed():
    gc, gp = bs.greeks(S, K, T, R, SIG, True), bs.greeks(S, K, T, R, SIG, False)
    assert gc["delta"] == pytest.approx(0.636831, abs=1e-5)
    assert gp["delta"] == pytest.approx(-0.363169, abs=1e-5)
    assert gc["gamma"] == pytest.approx(0.018762, abs=1e-5) and gp["gamma"] == pytest.approx(gc["gamma"])
    assert gc["vega"] == pytest.approx(0.37524, abs=1e-4) and gp["vega"] == pytest.approx(gc["vega"])
    assert gc["theta"] == pytest.approx(-6.41401 / 365, abs=1e-6)
    assert gp["theta"] == pytest.approx(-1.65788 / 365, abs=1e-6)


def test_implied_vol_round_trips_and_rejects_impossible_prices():
    assert bs.implied_vol(10.4506, S, K, T, R, True) == pytest.approx(0.2, abs=1e-4)
    assert bs.implied_vol(5.5735, S, K, T, R, False) == pytest.approx(0.2, abs=1e-4)
    assert math.isnan(bs.implied_vol(0.5, S, 50, T, R, True))
    assert math.isnan(bs.implied_vol(150.0, S, K, T, R, True))
    assert math.isnan(bs.implied_vol(1.0, S, K, 0.0, R, True))


def test_edges_are_nan_or_intrinsic_never_raise():
    assert bs.price(90, 100, 0.0, R, SIG, False) == 10.0
    assert bs.price(90, 100, -1.0, R, SIG, True) == 0.0
    assert math.isnan(bs.price(float("nan"), 100, 1, R, SIG, True))
    assert all(math.isnan(v) for v in bs.greeks(100, 100, 0.0, R, SIG, True).values())
    assert all(math.isnan(v) for v in bs.greeks(100, 100, 1.0, R, 0.0, True).values())
