from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from s9_weekend_price_markets import config as cfg
from s9_weekend_price_markets import run as s9
from s9_weekend_price_markets import universe as uni

ET = ZoneInfo("America/New_York")
V0, V1, V2, V3, V4 = cfg.VARIANTS


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ET).timestamp()


def test_weekends_need_a_saturday_and_a_sunday_inside_the_closure():
    w = {}
    for days in (["2026-03-05", "2026-03-06", "2026-03-09"], ["2026-04-01", "2026-04-02", "2026-04-06"],
                 ["2026-05-21", "2026-05-22", "2026-05-26"], ["2026-11-25", "2026-11-27"]):
        opens = np.array([at(*map(int, d.split("-")), 9, 30) for d in days])
        w.update({x["key"]: x for x in s9.weekends(days, opens)})
    assert sorted(w) == ["2026-03-09", "2026-04-06", "2026-05-26"]
    plain = w["2026-03-09"]
    assert plain["start"] == at(2026, 3, 6, 20, 0) and plain["entry"] == at(2026, 3, 8, 17, 55)
    assert plain["early"] == at(2026, 3, 8, 19, 0) and plain["exit"] == at(2026, 3, 9, 9, 40)
    assert w["2026-04-06"]["start"] == at(2026, 4, 2, 20, 0)
    assert w["2026-05-26"]["entry"] == at(2026, 5, 24, 17, 55)
    assert w["2026-05-26"]["exit"] == at(2026, 5, 26, 9, 40)


def test_universe_rules_read_the_asset_and_the_side_from_the_text():
    assert uni.asset_class("What will WTI Crude Oil (WTI) hit in April 2026?") == "crude"
    assert uni.asset_class("Will Gold (GC) hit __ by end of March?") == "gold"
    assert uni.asset_class("What will Tesla (TSLA) hit in November 2025?") == "stock"
    assert uni.asset_class("What will Bitcoin hit in April?") is None
    assert uni.wanted("What will Crude Oil (CL) settle at in March?") and not uni.wanted("Crude Oil all time high by April 30?")
    assert not uni.wanted("Will Crude Oil reserves fall?")
    assert uni.strike_sign("Will WTI Crude Oil (WTI) hit (HIGH) $105 in April?", "↑ $105") == 1
    assert uni.strike_sign("Will WTI Crude Oil (WTI) hit (LOW) $90 in April?", "↓ $90") == -1
    assert uni.strike_sign("Will Crude Oil (CL) settle at $60-$65 in March?", "$60-$65") == 0


def test_fade_sells_a_rise_follow_buys_it_and_each_fill_pays_the_markets_own_fee():
    f = lambda p: 0.04 * p * (1 - p)                                           # noqa: E731
    side, entry, pnl = s9.trade("fade", 8.0, 0.50, 0.46, False, 0.005, 0.04, 1.0, 1.0)
    assert side == "sell YES" and entry == pytest.approx(0.495)
    assert pnl == pytest.approx(0.495 - 0.465 - f(0.495) - f(0.465))
    side, entry, pnl = s9.trade("follow", 8.0, 0.50, 0.46, False, 0.005, 0.04, 1.0, 1.0)
    assert side == "buy YES" and entry == pytest.approx(0.505)
    assert pnl == pytest.approx(0.455 - 0.505 - f(0.505) - f(0.455))
    assert s9.trade("fade", -8.0, 0.50, 0.54, False, 0.005, 0.0, 1.0, 1.0) == ("buy YES", pytest.approx(0.505), pytest.approx(0.535 - 0.505))
    two = s9.trade("fade", 8.0, 0.50, 0.46, False, 0.005, 0.04, 1.0, 2.0)
    assert two[1] == pytest.approx(0.49) and two[2] == pytest.approx(0.49 - 0.47 - 0.08 * 0.49 * 0.51 - 0.08 * 0.47 * 0.53)


def test_a_market_that_resolves_before_the_exit_settles_at_its_result_without_exit_costs():
    side, entry, pnl = s9.trade("fade", 8.0, 0.50, 1.0, True, 0.005, 0.04, 1.0, 1.0)
    assert pnl == pytest.approx(0.495 - 1.0 - 0.04 * 0.495 * 0.505)
    side, entry, pnl = s9.trade("fade", -8.0, 0.50, 0.0, True, 0.005, 0.04, 1.0, 1.0)
    assert pnl == pytest.approx(0.0 - 0.505 - 0.04 * 0.505 * 0.495)


def frame(rows) -> pd.DataFrame:
    base = {"weekend": "2026-03-09", "market": "m", "asset_class": "crude", "w": 8.0, "p_entry": 0.5, "p_exit": 0.45, "p_early": 0.47,
            "settled": False, "settled_early": False}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_select_applies_threshold_band_class_exit_and_cap():
    df = frame([{"market": "a"}, {"market": "b", "w": -4.0}, {"market": "c", "p_entry": 0.97}, {"market": "d", "p_exit": np.nan},
                {"market": "e", "asset_class": "stock", "w": -12.0}])
    assert list(s9.select(df, V0).market) == ["e", "a"]
    assert list(s9.select(df, V1).market) == ["e"]
    assert list(s9.select(df, V2).market) == ["a"]
    assert sorted(s9.select(df, V3).market) == ["a", "d"]
    assert s9.select(df, V3).p_out.tolist() == [0.47, 0.47]
    many = frame([{"market": f"m{i:02d}", "w": 5.0 + i} for i in range(13)])
    assert len(s9.select(many, V0)) == cfg.MAX_POSITIONS and s9.select(many, V0).w.min() == 8.0


def test_timestamps_from_the_catalogue_parse():
    assert s9._ts("2026-04-01 07:14:35+00") == s9._ts("2026-04-01T07:14:35Z") == s9._ts("2026-04-01T07:14:35+00:00")
    assert s9._ts(None) is None
