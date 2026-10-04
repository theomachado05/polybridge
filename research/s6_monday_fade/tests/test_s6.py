"""S6: the entry rule against the options' band, costs, both exits, the print check."""
import numpy as np
import pytest

from s6_monday_fade import config as cfg
from s6_monday_fade import run as s6

H = 0.02


def test_fee_is_four_percent_of_p_times_one_minus_p():
    assert s6.fee(0.5) == pytest.approx(0.01)
    assert s6.fee(0.5, 2.0) == pytest.approx(0.02)
    assert s6.fee(0.0) == 0.0 and s6.fee(1.0) == 0.0


def test_sell_yes_when_polymarket_is_above_the_band_after_costs():
    side, entry, edge = s6.decide(0.60, 0.40, 0.45, H, 1.0, 0.02)
    assert side == "sell YES" and entry == pytest.approx(0.58)
    assert edge == pytest.approx(0.58 - 0.04 * 0.58 * 0.42 - 0.45)


def test_buy_yes_when_polymarket_is_below_the_band_after_costs():
    side, entry, edge = s6.decide(0.30, 0.45, 0.50, H, 1.0, 0.02)
    assert side == "buy YES" and entry == pytest.approx(0.32)
    assert edge == pytest.approx(0.45 - 0.32 - 0.04 * 0.32 * 0.68)


def test_no_trade_inside_the_band_or_when_costs_eat_the_gap():
    assert s6.decide(0.47, 0.45, 0.50, H, 1.0, 0.02) is None
    assert s6.decide(0.54, 0.45, 0.50, H, 1.0, 0.02) is None            # 0.52 - fee - 0.50 is under 2 points
    assert s6.decide(0.60, 0.40, 0.45, H, 1.0, 0.02) is not None
    assert s6.decide(0.52, 0.40, 0.45, H, 2.0, 0.02) is None            # doubled costs remove a trade that 1x allowed
    assert s6.decide(0.52, 0.40, 0.45, H, 1.0, 0.02) is not None


def test_pnl_held_to_resolution():
    assert s6.pnl_resolution("sell YES", 0.58, 0.0, 1.0) == pytest.approx(0.58 - s6.fee(0.58))
    assert s6.pnl_resolution("sell YES", 0.58, 1.0, 1.0) == pytest.approx(0.58 - s6.fee(0.58) - 1.0)
    assert s6.pnl_resolution("buy YES", 0.32, 1.0, 1.0) == pytest.approx(1.0 - 0.32 - s6.fee(0.32))
    assert s6.pnl_resolution("buy YES", 0.32, 0.0, 2.0) == pytest.approx(-0.32 - s6.fee(0.32, 2.0))


def test_pnl_closed_at_the_end_of_the_day_pays_the_spread_again():
    p = s6.pnl_end_of_day("sell YES", 0.58, 0.50, H, 1.0)
    assert p == pytest.approx(0.58 - s6.fee(0.58) - 0.52 - s6.fee(0.52))
    q = s6.pnl_end_of_day("buy YES", 0.32, 0.40, H, 1.0)
    assert q == pytest.approx(0.38 - s6.fee(0.38) - 0.32 - s6.fee(0.32))


def test_capital_is_what_the_position_costs():
    assert s6.capital("buy YES", 0.32) == pytest.approx(32.0)
    assert s6.capital("sell YES", 0.58) == pytest.approx(42.0)            # buying NO at 0.42


def test_print_check_side_and_window():
    at = s6.entry_epoch("2026-03-02")
    prints = [{"timestamp": at + 60, "price": 0.59, "side": "SELL", "outcome": "Yes", "size": 40},       # a YES bid at 0.59 was hit
              {"timestamp": at + 60, "price": 0.40, "side": "BUY", "outcome": "No", "size": 25},        # = taker sold YES at 0.60
              {"timestamp": at + 60, "price": 0.57, "side": "SELL", "outcome": "Yes", "size": 99},      # worse than our 0.58
              {"timestamp": at + 5000, "price": 0.70, "side": "SELL", "outcome": "Yes", "size": 99}]    # outside the window
    assert s6.verify(prints, "sell YES", 0.58, at) == (2, 65.0)
    assert s6.verify(prints, "buy YES", 0.32, at) == (0, 0.0)
    assert s6.verify([{"timestamp": at, "price": 0.31, "side": "BUY", "outcome": "Yes", "size": 10}], "buy YES", 0.32, at) == (1, 10.0)


def test_entry_time_is_0945_new_york():
    import pandas as pd
    assert pd.Timestamp(s6.entry_epoch("2026-03-09"), unit="s", tz="America/New_York").strftime("%H:%M") == "09:45"   # after the DST change
    assert pd.Timestamp(s6.entry_epoch("2026-01-05"), unit="s", tz="America/New_York").strftime("%H:%M") == "09:45"


def test_closure_metrics():
    m = s6.closure_metrics(np.array([10.0, -5.0, 15.0, 0.0]), ["2026-01-05", "2026-01-12", "2026-02-02", "2026-02-09"], 1000.0, 3000.0, 52.0)
    r = np.array([0.01, -0.005, 0.015, 0.0])
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * 52 ** 0.5)
    assert m["max_drawdown"] == pytest.approx(0.005) and m["total_return"] == pytest.approx(0.02)
    assert cfg.PRIMARY == "V0"
