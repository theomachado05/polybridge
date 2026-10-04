import numpy as np
import pandas as pd
import pytest

from s15_weekend_scare import config as cfg
from s15_weekend_scare import run as s15
from s15_weekend_scare import universe as uni

V0, V1, V2 = cfg.VARIANTS


def test_groups_split_at_five_and_two_points():
    assert [s15.group(w) for w in (5.0, 12.0, -5.0, 1.9, -1.9, 2.0, 4.9, -3.0)] == \
        ["riser", "riser", "faller", "quiet", "quiet", "between", "between", "between"]


def test_universe_rules_add_natural_gas_and_tag_the_kind():
    assert uni.asset_class("What will Natural Gas (NG) hit in May 2026?") == "natgas"
    assert uni.asset_class("What will Rocket Lab (RKLB) hit in November 2025?") == "stock"
    assert uni.asset_class("Will gas hit __ by end of April?") is None
    assert uni.wanted("What will WTI Crude Oil (WTI) hit Week of May 4 2026?")
    assert uni.kind("What will WTI Crude Oil (WTI) hit Week of May 4 2026?", False) == "weekly"
    assert uni.kind("What will S&P 500 (SPY) hit in June 2026?", False) == "other event"
    assert uni.kind("What will WTI Crude Oil (WTI) hit in April 2026?", True) == "leftover of an S9 event"


def test_weekly_markets_pay_the_wider_spread():
    assert s15.half_spread("crude", "other event") == 0.005 and s15.half_spread("crude", "weekly") == 0.03
    assert s15.half_spread("natgas", "other event") == 0.02 and s15.half_spread("stock", "leftover of an S9 event") == 0.025


def frame(rows) -> pd.DataFrame:
    base = {"weekend": "2026-03-09", "market": "m", "asset_class": "stock", "w": 8.0, "p_entry": 0.5, "p_exit": 0.45}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_the_trade_sells_only_rises_inside_the_band_with_an_exit():
    df = frame([{"market": "a"}, {"market": "b", "w": -9.0}, {"market": "c", "w": 4.0}, {"market": "d", "p_entry": 0.97},
                {"market": "e", "p_exit": np.nan}, {"market": "f", "w": 15.0, "asset_class": "crude"}])
    assert list(s15.select(df, V0).market) == ["f", "a"]
    assert list(s15.select(df, V1).market) == ["f"]
    assert list(s15.select(df, V2).market) == ["f"]
    many = frame([{"market": f"m{i:02d}", "w": 5.0 + i} for i in range(13)])
    assert len(s15.select(many, V0)) == cfg.MAX_POSITIONS and s15.select(many, V0).w.min() == 8.0


def test_selling_a_rise_wins_when_the_price_falls_back():
    from s9_weekend_price_markets.run import trade
    side, entry, pnl = trade("fade", 8.0, 0.50, 0.44, False, 0.025, 0.0, 1.0, 1.0)
    assert side == "sell YES" and entry == pytest.approx(0.475) and pnl == pytest.approx(0.475 - 0.465)
