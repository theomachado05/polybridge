import numpy as np

from s10_weekend_lag import config as cfg
from s10_weekend_lag.run import fwd, jumps, pick_signals, trade, verify


def test_fwd_mean_of_valid_rows():
    S = np.array([[0.0, 1.0, 3.0], [10.0, np.nan, 14.0]])
    f1 = fwd(S, 1)
    assert f1[0] == 1.0 and f1[1] == 2.0 and np.isnan(f1[2])
    assert fwd(S, 2)[0] == 3.5


def test_jumps_rules_and_band():
    P = np.array([50, 50, 50, 50, 54, 54, 54, 54, 55, 56, 58, 58], dtype=float)
    j = jumps(P, -1.0, 3)
    assert j[4] == -4.0
    assert 10 not in j
    P2 = np.array([2, 2, 2, 2, 6, 6], dtype=float)
    assert jumps(P2, 1.0, 3) == {}


def test_jump_15_minute_rule():
    P = np.array([50, 50, 50, 50, 52, 54, 55.5], dtype=float)
    j = jumps(P, 1.0, 3)
    assert 6 in j and j[6] == 5.5 and 4 not in j


def test_pick_signals_refractory_and_cap():
    c = {3: 1.0, 4: -2.0, 9: 1.0, 10: 1.0, 20: 1.0, 30: 1.0}
    assert pick_signals(c, 6) == [(3, 1.0), (9, 1.0), (20, 1.0), (30, 1.0)]
    assert pick_signals(c, 6, last=20, cap=2) == [(3, 1.0), (9, 1.0)]


def test_trade_costs_and_settlement():
    entry, gross, net = trade(True, 0.40, 0.45, False, 0.005, 0.0, 1.0, 1.0)
    assert abs(entry - 0.405) < 1e-12 and abs(gross - 0.05) < 1e-12 and abs(net - 0.04) < 1e-12
    entry, gross, net = trade(False, 0.40, 1.0, True, 0.005, 0.04, 1.0, 1.0)
    assert abs(net - (0.395 - 1.0 - 0.04 * 0.395 * 0.605)) < 1e-12


def test_verify_window_and_side():
    pr = [{"timestamp": 1000 + 10, "price": 0.41, "side": "SELL", "outcome": "Yes", "size": 50},
          {"timestamp": 1000 + cfg.PRINT_WINDOW_S + 1, "price": 0.50, "side": "SELL", "outcome": "Yes", "size": 50},
          {"timestamp": 999, "price": 0.50, "side": "SELL", "outcome": "Yes", "size": 50},
          {"timestamp": 1100, "price": 0.58, "side": "BUY", "outcome": "No", "size": 20}]
    assert verify(pr, False, 0.40, 1000) == (2, 70.0)
    assert verify(pr, True, 0.40, 1000) == (0, 0.0)
