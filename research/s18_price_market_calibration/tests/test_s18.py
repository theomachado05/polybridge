import numpy as np
import pandas as pd
import pytest

from s18_price_market_calibration import config as cfg
from s18_price_market_calibration import run as s18

V0, V1, V2, V3, V4 = cfg.VARIANTS


def test_first_entry_is_the_first_weekend_start_with_a_fresh_price():
    t, p = np.array([1000, 5000, 5100]), np.array([0.30, 0.40, 0.41])
    assert s18.first_entry(np.array([500, 4000, 5200, 9000]), t, p) == (5200.0, 0.41)
    assert s18.first_entry(np.array([1500, 5200]), t, p) == (1500.0, 0.30)
    assert s18.first_entry(np.array([500]), t, p) is None


def test_buckets_cover_two_to_ninety_eight_percent():
    assert [s18.bucket(x) for x in (0.02, 0.0999, 0.10, 0.249, 0.25, 0.60, 0.80, 0.95, 0.98)] == \
        ["2 to 10%", "2 to 10%", "10 to 25%", "10 to 25%", "25 to 50%", "50 to 75%", "75 to 90%", "90 to 98%", "90 to 98%"]


def test_selling_a_cheap_market_keeps_the_premium_unless_it_pays():
    entry, pnl, cap = s18.hold_to_result("sell YES", 0.10, 0.0, 0.005, 0.04, 1.0, 1.0)
    assert entry == pytest.approx(0.095) and cap == pytest.approx(0.905)
    assert pnl == pytest.approx(0.095 - 0.04 * 0.095 * 0.905)
    assert s18.hold_to_result("sell YES", 0.10, 1.0, 0.005, 0.04, 1.0, 1.0)[1] == pytest.approx(0.095 - 0.04 * 0.095 * 0.905 - 1.0)
    entry, pnl, cap = s18.hold_to_result("buy YES", 0.80, 1.0, 0.005, 0.0, 1.0, 1.0)
    assert entry == pytest.approx(0.805) and pnl == pytest.approx(0.195) and cap == pytest.approx(0.805)
    two = s18.hold_to_result("sell YES", 0.10, 0.0, 0.005, 0.04, 1.0, 2.0)
    assert two[0] == pytest.approx(0.09) and two[1] == pytest.approx(0.09 - 0.08 * 0.09 * 0.91)


def test_select_applies_the_price_range_universe_and_class():
    df = pd.DataFrame([{"market": "a", "p": 0.10, "universe": "S9", "asset_class": "crude"}, {"market": "b", "p": 0.30, "universe": "S9", "asset_class": "crude"},
                       {"market": "c", "p": 0.20, "universe": "S15", "asset_class": "stock"}, {"market": "d", "p": 0.80, "universe": "S15", "asset_class": "gold"},
                       {"market": "e", "p": 0.04, "universe": "S9", "asset_class": "crude"}])
    assert list(s18.select(df, V0).market) == ["a", "c"] and list(s18.select(df, V1).market) == ["d"]
    assert list(s18.select(df, V2).market) == ["a"] and list(s18.select(df, V3).market) == ["a"]
    assert list(s18.select(df, V4).market) == ["a", "b", "c", "d"]


def test_capital_locked_at_one_time_counts_overlapping_trades_only():
    trades = [{"entry_epoch": 0, "result_epoch": 10, "capital": 90.0}, {"entry_epoch": 5, "result_epoch": 20, "capital": 80.0},
              {"entry_epoch": 10, "result_epoch": 30, "capital": 70.0}]
    assert s18.max_locked(trades) == pytest.approx(170.0)


def test_prints_are_read_in_yes_terms_and_weighted_by_size():
    from s18_price_market_calibration import prints as pr
    assert pr.yes_terms({"outcome": "Yes", "side": "SELL", "price": 0.30, "size": 10}) == (0.30, "SELL", 10.0)
    px, side, size = pr.yes_terms({"outcome": "No", "side": "BUY", "price": 0.70, "size": 5})
    assert px == pytest.approx(0.30) and side == "SELL" and size == 5.0
    assert pr.yes_terms({"outcome": "maybe", "side": "BUY", "price": 0.5}) is None
    ps, tot, n = pr.weighted([(0.30, "SELL", 10.0), (0.40, "SELL", 30.0), (0.90, "BUY", 100.0)], "SELL")
    assert ps == pytest.approx(0.375) and tot == 40.0 and n == 2
    assert np.isnan(pr.weighted([(0.30, "SELL", 10.0)], "BUY")[0])
