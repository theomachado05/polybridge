import math

from polybridge_research.parity import implied_move, implied_scaled, parity_ratio, realized_move


def test_implied_move_is_straddle_over_spot():
    assert math.isclose(implied_move(3.0, 2.0, 100.0), 0.05)


def test_implied_scaled_uses_square_root_of_time():
    assert math.isclose(implied_scaled(0.10, sessions_held=21, dte_sessions=84), 0.05)


def test_implied_scaled_nan_when_no_sessions_to_expiry():
    assert math.isnan(implied_scaled(0.10, sessions_held=5, dte_sessions=0))


def test_realized_is_signed_ratio_uses_absolute():
    r = realized_move(100.0, 94.0)
    assert math.isclose(r, -0.06)
    assert math.isclose(parity_ratio(r, 0.03), 2.0)


def test_parity_ratio_nan_on_bad_inputs():
    assert math.isnan(parity_ratio(0.02, 0.0))
    assert math.isnan(parity_ratio(float("nan"), 0.03))
    assert math.isnan(realized_move(float("nan"), 100.0))


def test_degenerate_spot_gives_nan():
    for bad in (0.0, -5.0, float("nan"), float("inf")):
        assert math.isnan(implied_move(3.0, 2.0, bad))
        assert math.isnan(realized_move(bad, 100.0))


def test_implied_scaled_nan_for_negative_dte():
    assert math.isnan(implied_scaled(0.10, sessions_held=5, dte_sessions=-3))
