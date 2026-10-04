import numpy as np

import reopen_taker  # noqa: F401
from reopen_taker import config as C
from reopen_taker import core


def test_first_trades_and_taus():
    prints = [{"ts": 1, "px": 0.50, "side": "BUY", "size": 10}, {"ts": 2, "px": 0.46, "side": "BUY", "size": 5},
              {"ts": 3, "px": 0.69, "side": "SELL", "size": 7}, {"ts": 4, "px": 0.35, "side": "BUY", "size": 1}]
    t = core.first_trades(prints, 0.50 + 0.04)
    assert t[0.03]["ts"] == 1 and t[0.05]["ts"] == 2 and t[0.10]["ts"] == 3


def test_net_and_verdict():
    assert abs(core.net("BUY", 0.40, 1, 0.01, False, 0.04, 1.0) - 0.59) < 1e-12
    assert abs(core.net("SELL", 0.70, 0, 0.01, True, 0.04, 1.0) - (1 - 0.31 - 0.04 * 0.21)) < 1e-12
    assert core.verdict(29, 10, 0.1, 0.2) == "INSUFFICIENT"
    assert core.verdict(30, 8, 0.01, 0.2) == "PASS"
    assert core.verdict(30, 8, -0.2, -0.01) == "NEGATIVE"
    assert core.verdict(30, 8, -0.1, 0.1) == "NULL"


def test_usable_and_window():
    assert core.usable(0.5, 0.45, 0.6) and not core.usable(0.5, 0.3, 0.6) and not core.usable(0.99, 0.98, 0.99)
    w0, w1 = core.window("2026-02-17")
    assert w1 - w0 == (6 * 60 + 10) * 60


def test_summarize_ci_covers_mean():
    rng = np.random.default_rng(0)
    v = rng.normal(0.05, 0.3, 200)
    s = core.summarize(v, np.repeat(np.arange(20), 10))
    assert s["lo"] < s["mean"] < s["hi"] and s["clusters"] == 20 and C.MIN_TRADES == 30
