"""S4 engine: sessions, prices without look-ahead, beta from earlier days only, the walk-forward gate, trade costs."""
import math

import numpy as np
import pandas as pd
import pytest

from s4_linked_assets import config as cfg
from s4_linked_assets import engine as en

OPEN = int(pd.Timestamp("2026-03-02 09:30", tz="America/New_York").timestamp())
DAY = 86400


def bars(days=2, price=100.0, step=0.0):
    """78 five-minute bars a day; the close of bar k is price + step * (k + 1)."""
    t, o, c = [], [], []
    for d in range(days):
        for k in range(78):
            t.append(OPEN + d * DAY + k * 300)
            o.append(price + step * k)
            c.append(price + step * (k + 1))
    n = len(t)
    return {"t": np.array(t, dtype=np.int64), "o": np.array(o), "c": np.array(c), "v": np.full(n, 10.0), "vw": np.array(c)}


def test_sessions_come_from_the_spy_bars():
    s = en.sessions_from(bars(2)["t"])
    assert list(s.day) == ["2026-03-02", "2026-03-03"]
    assert s.open[0] == OPEN and s.close[0] == OPEN + 78 * 300


def test_session_prices_use_only_bars_before_each_boundary():
    b = bars(1, 100.0, 1.0)
    s = en.sessions_from(b["t"])
    p = en.session_prices(b, s)
    assert p["px"][0, 0] == 100.0                 # the open of the first bar
    assert p["px"][0, 1] == 106.0                 # close of the 09:55 bar: the 10:00 price
    assert p["px"][0, 13] == p["close"][0] == 178.0
    assert p["vol5"][0] == pytest.approx(10 * 101.0)
    assert p["vol30"][0] == pytest.approx(10 * sum(range(101, 107)))


def test_a_missing_first_bar_voids_the_session_for_that_ticker():
    spy = bars(1)
    late = {k: v[4:] for k, v in bars(1).items()}             # first bar at 09:50
    p = en.session_prices(late, en.sessions_from(spy["t"]))
    assert math.isnan(p["px"][0, 0]) and math.isnan(p["close"][0])


def test_beta_uses_earlier_days_only():
    days = [f"2026-01-{d:02d}" for d in range(1, 29)]
    spy_c = np.cumprod(1 + np.tile([0.01, -0.01], 14))
    asset_c = np.cumprod(1 + 2 * np.tile([0.01, -0.01], 14))
    b = en.betas({"day": np.array(days), "c": asset_c}, {"day": np.array(days), "c": spy_c}, [days[5], days[25]])
    assert b[0] == 1.0                                           # fewer than 20 earlier returns: default
    assert b[1] == pytest.approx(2.0, rel=1e-6)
    spiked = asset_c.copy()
    spiked[25:] *= 5                                             # a move on or after the day cannot change its beta
    assert en.betas({"day": np.array(days), "c": spiked}, {"day": np.array(days), "c": spy_c}, [days[25]])[0] == pytest.approx(2.0, rel=1e-6)


def test_link_days_signs_the_odds_and_stops_at_0929():
    spy, asset = bars(2), bars(2, 50.0, 0.1)
    s = en.sessions_from(spy["t"])
    ap, sp = en.session_prices(asset, s), en.session_prices(spy, s)
    close0, open1 = int(s.close[0]), int(s.open[1])
    pm_t = np.array([close0 - 60, open1 - 120, open1 - 30, open1 + 600], dtype=np.int64)
    pm_p = np.array([0.40, 0.45, 0.90, 0.10])
    up = en.link_days(pm_t, pm_p, 1, s, ap, sp, np.ones(2))
    assert up.x_night[1] == pytest.approx(5.0)                   # 0.45 - 0.40; the 09:29:30 print is after the signal
    down = en.link_days(pm_t, pm_p, -1, s, ap, sp, np.ones(2))
    assert down.x_night[1] == pytest.approx(-5.0)
    assert math.isnan(up.x_night[0])
    # the equity rises 7.8 a day from 50 and SPY is flat: excess day move = 1560 bp
    assert up.e_day[0] == pytest.approx(1e4 * (57.8 / 50 - 1))


def test_stale_odds_give_no_signal():
    spy = bars(2)
    s = en.sessions_from(spy["t"])
    pr = en.session_prices(spy, s)
    pm_t = np.array([int(s.close[0]) - 60, int(s.open[1]) - 4000], dtype=np.int64)     # the last print is over 30 min old
    out = en.link_days(pm_t, np.array([0.4, 0.5]), 1, s, pr, pr, np.ones(2))
    assert math.isnan(out.x_night[1])


def test_gate_is_walk_forward_and_needs_enough_bins_sessions_and_a_t_of_two():
    n = 12
    sxx, nbin = np.full(n, 10.0), np.full(n, 12)
    sxy = np.array([30, 28, 32, 29, 31, 30, 27, 33, 30, 29, 31, 30], dtype=float)       # slope about 3 every session
    g = en.gate(sxx, sxy, nbin)
    assert g["bins"][0] == 0 and not g["confirmed"][:5].any()                             # under 60 bins before day 5
    assert g["confirmed"][5:].all() and g["slope"][6] == pytest.approx(sxy[:6].sum() / 60)
    changed = sxy.copy()
    changed[8:] = -500                                                                     # later days cannot reach back
    assert en.gate(sxx, changed, nbin)["confirmed"][8] and en.gate(sxx, changed, nbin)["slope"][8] == g["slope"][8]
    assert not en.gate(sxx, changed, nbin)["confirmed"][11]
    noisy = np.array([300, -280, 310, -290, 305, -300, 295, -285, 300, -310, 290, -295], dtype=float)
    assert not en.gate(sxx, noisy, nbin)["confirmed"].any()                                # no stable sign: t under 2
    assert not en.gate(sxx, -sxy, nbin)["confirmed"].any()                                 # the wrong direction never passes
    one_day = np.where(np.arange(n) == 0, 100, 0)
    assert not en.gate(np.where(one_day > 0, 1000.0, 0.0), np.where(one_day > 0, 3000.0, 0.0), one_day)["confirmed"].any()


def test_costs_and_trade_direction():
    assert en.cost_bp("EWZ", 1.0, 1.0) == 2 * cfg.COST_LIQUID + 2 * cfg.COST_SPY
    assert en.cost_bp("MARA", 2.5, 2.0) == 2 * (2 * cfg.COST_OTHER + 2.5 * 2 * cfg.COST_SPY)
    gross, net = en.trade_bp(-3.0, -40.0, "EWZ", 1.0, 1.0)                                # odds fell, the equity fell: a short wins
    assert gross == 40.0 and net == 40.0 - 6.0
    assert en.trade_bp(3.0, -40.0, "EWZ", 1.0, 1.0)[0] == -40.0


def test_pick_takes_the_largest_moves_above_the_threshold():
    s = pd.DataFrame({"ticker": list("abcdefghijkl"), "x": [1.9, -2.0, 3, -4, 5, 6, 7, 8, 9, 10, 11, 12]})
    p = en.pick(s)
    assert len(p) == cfg.MAX_POSITIONS and "a" not in set(p.ticker) and "b" not in set(p.ticker)
    assert list(p.ticker[:2]) == ["l", "k"]


def test_clustered_slope_and_date_bootstrap():
    x = np.array([1.0, 2.0, -1.0, -2.0, 0.0])
    y = 3 * x
    r = en.clustered_slope(x, y, np.array(["a", "a", "b", "b", "c"]))
    assert r["slope"] == pytest.approx(3.0) and r["sign_agree"] == 1.0 and r["n_nonzero"] == 4
    mean, lo, hi = en.date_bootstrap({d: [1.0, 3.0] for d in "abcdef"}, 200, 0)
    assert mean == 2.0 and lo == hi == 2.0


def test_day_metrics():
    m = en.day_metrics(np.array([1000.0, -500.0, 1500.0, 0.0]), ["2026-03-02", "2026-03-03", "2026-04-01", "2026-04-02"], 80_000.0)
    r = np.array([0.01, -0.005, 0.015, 0.0])
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(252))
    assert m["max_drawdown"] == pytest.approx(0.005) and m["worst_month"] == pytest.approx(0.005)
