"""S3: the strike map, the as-of Kalshi quote, the outlier rule, payoffs with a split resolution, the print check."""
import math

import pytest

from s3_three_way import config as cfg
from s3_three_way import run as s3

V0, V1, V2, V3 = cfg.VARIANTS
R = 0.04


def make(pb, pa, kb, ka, lo, hi, y_pm=1.0, y_k=1.0):
    return {"pb": pb, "pa": pa, "kb": kb, "ka": ka, "lo": lo, "hi": hi, "y_pm": y_pm, "y_k": y_k, "tau_years": 0.0}


def test_event_ticker_and_strike_map():
    assert s3.event_ticker("2026-10-05") == "KXINXU-26OCT05H1600"
    listed = [7590.0, 7595.0, 7600.0, 7605.0]
    assert s3.map_strike(760.0, 10.0, listed) == (7600.0, 0.0)
    k, gap = s3.map_strike(760.0, 10.002, listed)             # target 7601.52
    assert k == 7600.0 and gap == pytest.approx(-1.52)
    assert s3.map_strike(770.0, 10.0, listed) is None          # 7700 is off the ladder
    assert s3.map_strike(760.0, 10.0, []) is None


def test_ratio_uses_the_last_session_strictly_before_the_date():
    spx, spy = {"2026-10-01": 7600.0, "2026-10-02": 7650.0}, {"2026-10-01": 760.0, "2026-10-02": 762.0}
    assert s3.ratio_for("2026-10-02", spx, spy) == ("2026-10-01", 10.0)
    assert s3.ratio_for("2026-10-05", spx, spy)[0] == "2026-10-02"
    assert s3.ratio_for("2026-10-01", spx, spy) is None


def test_kalshi_quote_is_as_of_and_needs_two_sides():
    def c(t, b, a):
        return {"end_period_ts": t, "yes_bid": {"close_dollars": b}, "yes_ask": {"close_dollars": a}}

    assert s3.kalshi_quote([c(100, "0.40", "0.44"), c(200, "0.50", "0.52")], 150) == {"kb": 0.40, "ka": 0.44, "k_age_s": 50}
    assert s3.kalshi_quote([c(200, "0.50", "0.52")], 150) is None                       # only a later candle
    assert s3.kalshi_quote([c(100, "0.00", "0.44")], 150) is None                       # empty bid side
    assert s3.kalshi_quote([c(100, "0.40", "0.44")], 100 + cfg.KALSHI_MAX_AGE_S + 1) is None


def test_lock_needs_an_outlier_and_trades_against_it():
    # Polymarket rich (bid above the band), Kalshi inside it: buy Kalshi YES and Polymarket NO
    s = make(pb=0.60, pa=0.62, kb=0.48, ka=0.50, lo=0.47, hi=0.52)
    t = s3.evaluate(s, V0, 1.0, R, 1.0)
    assert t["dir"] == "B" and t["outlier"] == "pm" and t["outlier_side"] == "rich"
    fees = 0.04 * 0.40 * 0.60 + math.ceil(0.07 * 100 * 0.25 * 100 - 1e-9) / 100 / 100
    assert t["edge"] == pytest.approx(1 - (0.50 + 0.40 + fees))
    assert t["pnl"] == pytest.approx(100 * t["edge"])          # both resolve YES: the pair pays $1
    # both venues outside the band on the same side: no outlier, no trade under the filter
    both = make(pb=0.60, pa=0.62, kb=0.58, ka=0.59, lo=0.47, hi=0.52)
    assert s3.evaluate(both, V0, 1.0, R, 1.0) is None
    # neither disagrees
    assert s3.evaluate(make(0.48, 0.52, 0.48, 0.50, 0.47, 0.52), V0, 1.0, R, 1.0) is None


def test_without_the_filter_the_lock_only_needs_the_edge():
    both = make(pb=0.60, pa=0.62, kb=0.50, ka=0.51, lo=0.20, hi=0.25)
    assert s3.evaluate(both, V0, 1.0, R, 1.0) is None
    assert s3.evaluate(both, V2, 1.0, R, 1.0)["dir"] == "B"


def test_theta_and_double_costs():
    s = make(pb=0.54, pa=0.56, kb=0.48, ka=0.50, lo=0.47, hi=0.52)     # edge about 1.3 cents at 1x
    assert s3.evaluate(s, V0, 1.0, R, 1.0) is None and s3.evaluate(s, V1, 1.0, R, 1.0) is not None
    assert s3.evaluate(s, V1, 2.0, R, 1.0) is None


def test_split_resolution_is_paid_leg_by_leg():
    s = make(pb=0.60, pa=0.62, kb=0.48, ka=0.50, lo=0.47, hi=0.52, y_pm=1.0, y_k=0.0)
    t = s3.evaluate(s, V0, 1.0, R, 1.0)                    # holds Kalshi YES (pays 0) and Polymarket NO (pays 0)
    assert t["split"] and t["payoff"] == 0.0 and t["pnl"] == pytest.approx(-100 * t["cost"])
    lucky = s3.evaluate({**s, "y_pm": 0.0, "y_k": 1.0}, V0, 1.0, R, 1.0)
    assert lucky["payoff"] == 2.0


def test_fade_buys_the_outliers_cheap_side():
    rich = make(pb=0.60, pa=0.62, kb=0.48, ka=0.50, lo=0.47, hi=0.52, y_pm=0.0)
    t = s3.evaluate(rich, V3, 1.0, R, 1.0)
    fee = 0.04 * 0.40 * 0.60
    assert t["dir"] == "buy pm NO" and t["edge"] == pytest.approx(0.60 - 0.52 - fee)
    assert t["pnl"] == pytest.approx(100 * (1.0 - (0.40 + fee)))
    cheap = make(pb=0.30, pa=0.32, kb=0.48, ka=0.50, lo=0.47, hi=0.52, y_pm=1.0)
    assert s3.evaluate(cheap, V3, 1.0, R, 1.0)["dir"] == "buy pm YES"


def test_print_check_direction():
    buy_yes = {"dir": "A", "pm_px": 0.40}
    buy_no = {"dir": "B", "pm_px": 0.60}
    prints = [{"timestamp": 1000, "price": 0.39, "side": "BUY", "outcome": "Yes", "size": 50},
              {"timestamp": 1000, "price": 0.39, "side": "BUY", "outcome": "No", "size": 30},      # = taker sold YES at 0.61
              {"timestamp": 5000, "price": 0.10, "side": "BUY", "outcome": "Yes", "size": 999}]    # outside the window
    assert s3.verify(prints, buy_yes, 1000) == (1, 50.0)
    assert s3.verify(prints, buy_no, 1000) == (1, 30.0)
    assert s3.verify(prints, {"dir": "A", "pm_px": 0.30}, 1000) == (0, 0.0)


def test_day_metrics():
    m = s3.day_metrics(__import__("numpy").array([10.0, -5.0, 0.0, 15.0]), 1000.0, 400.0)
    assert m["total_return"] == pytest.approx(0.02) and m["max_drawdown"] == pytest.approx(0.005)
