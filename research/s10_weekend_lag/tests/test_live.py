import numpy as np
import pandas as pd

from s10_weekend_lag.live_analyze import fee_pts, trades


def _df(rows):
    return pd.DataFrame(rows, columns=["ts", "start", "market", "el", "fair", "bid", "ask", "bid_size", "ask_size"])


def test_buy_fills_at_next_ask_and_holds_to_result():
    rows = [[1000 + k, 900, "m", 100 + k, 0.70, 0.59, 0.60, 50, 40] for k in range(3)]
    rows[1][6] = 0.605                                     # next second's ask, half a point worse
    t = trades(_df(rows), {"m": {"fee_rate": 0.07}}, {"m": 1.0})
    assert len(t) == 1 and t[0]["side"] == "buy Up" and t[0]["fill"] == 0.605 and t[0]["size"] == 40
    assert abs(t[0]["net_points"] - 100 * ((1 - 0.605) - fee_pts(0.605, 0.07))) < 1e-9


def test_no_trade_when_gap_below_threshold_or_quote_gone():
    rows = [[1000 + k, 900, "m", 100 + k, 0.62, 0.59, 0.60, 50, 40] for k in range(3)]
    assert trades(_df(rows), {"m": {"fee_rate": 0.07}}, {"m": 1.0}) == []
    rows = [[1000 + k, 900, "m", 100 + k, 0.70, 0.59, 0.60, 50, 40] for k in range(2)]
    rows[1][6] = 0.63                                      # ask moved 3 points: the quote is gone
    assert trades(_df(rows), {"m": {"fee_rate": 0.07}}, {"m": 1.0}) == []


def test_sell_side_and_doubled_costs():
    rows = [[1000 + k, 900, "m", 100 + k, 0.30, 0.40, 0.41, 80, 50] for k in range(2)]
    t1 = trades(_df(rows), {"m": {"fee_rate": 0.07}}, {"m": 0.0}, 1.0)[0]
    t2 = trades(_df(rows), {"m": {"fee_rate": 0.07}}, {"m": 0.0}, 2.0)[0]
    assert t1["side"] == "sell Up" and t1["size"] == 80 and t2["net_points"] < t1["net_points"]
