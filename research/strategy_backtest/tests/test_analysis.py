from math import ceil

import numpy as np
import pandas as pd
import pytest

from strategy_backtest.analysis import oos_length, segment_metrics, segments, verdict

from .synth import sessions


def test_oos_length_rule():
    days = sessions(700)
    ret = days[1:]
    assert oos_length(ret) == ceil(0.2 * 700)
    short = sessions(50)[1:]
    assert oos_length(short) == 10


def test_segments_partition():
    days = sessions(100)
    s = segments(days)
    assert s["IS"] + s["OOS"] == s["full"] == days[1:]
    assert len(s["OOS"]) == 20


def test_segment_metrics_known_path():
    days = sessions(4)
    eq = pd.Series([100.0, 110.0, 99.0, 108.9, 108.9], index=days)
    m = segment_metrics(eq, days[1:])
    assert m["max_dd"] == pytest.approx(-0.1)
    r = np.array([0.1, -0.1, 0.1, 0.0])
    assert m["ann_return"] == pytest.approx(np.prod(1 + r) ** (252 / 4) - 1)
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))
    m2 = segment_metrics(eq, days[3:])
    assert m2["max_dd"] == pytest.approx(0.0)
    assert m2["n_days"] == 2


def test_segment_metrics_hedge_columns():
    days = sessions(4)
    eq = pd.Series(100.0, index=days)
    d = pd.DataFrame({"f": [0, 0.2, 0, 0.1, 0], "traded_usd": [0, 40.0, 0, 20.0, 0], "hedge_net": [0, 1.0, 0, -1.0, 0]},
                     index=days)
    m = segment_metrics(eq, days[1:], d)
    assert m["hedge_days"] == 2
    assert m["mean_hedge_fraction"] == pytest.approx(0.15)
    assert m["hit_rate"] == pytest.approx(0.5)
    assert m["turnover"] == pytest.approx(60.0 / 100.0 / (4 / 252))


def test_verdict_rules():
    bh = {"max_dd": -0.10, "ann_vol": 0.15, "sharpe": 1.0}
    assert verdict({"hedge_days": 0}, bh)["verdict"] == "Fail"
    ok = {"hedge_days": 3, "max_dd": -0.098, "ann_vol": 0.1499, "sharpe": 1.0}
    assert verdict(ok, bh)["verdict"] == "Pass"
    small = {"hedge_days": 3, "max_dd": -0.0995, "ann_vol": 0.1490, "sharpe": 1.2}
    assert verdict(small, bh)["verdict"] == "Fail"
    lower_sharpe = {"hedge_days": 3, "max_dd": -0.05, "ann_vol": 0.10, "sharpe": 0.99}
    assert verdict(lower_sharpe, bh)["verdict"] == "Fail"
    vol_only = {"hedge_days": 3, "max_dd": -0.11, "ann_vol": 0.148, "sharpe": 1.0}
    assert verdict(vol_only, bh)["verdict"] == "Pass"
