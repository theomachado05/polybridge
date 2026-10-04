import math

import numpy as np
import pytest

from s1_twin_spread import engine as en

R = 0.04


def make_pair(pm, kb, ka, h=0.01, tau_years=0.25, pm_rate=0.0, k_mult=1.0):
    n = len(pm)
    t = np.arange(n, dtype=np.int64) * 60 + 1_700_000_000 // 60 * 60
    return en.Pair("K", t, np.array(kb, float), np.array(ka, float), np.array(pm, float),
                   np.full(n, tau_years), h, k_mult, pm_rate, 1.0)


def test_kalshi_fee_rounds_the_order_up_to_a_cent():
    assert en.kalshi_fee(0.5, 100) == pytest.approx(0.0175)
    assert en.kalshi_fee(0.5, 1) == pytest.approx(0.02)
    assert en.kalshi_fee(0.0, 100) == 0.0 and en.kalshi_fee(1.0, 100) == 0.0
    assert en.kalshi_fee(0.3, 100) == en.kalshi_fee(0.7, 100)


def test_pm_fee():
    assert en.pm_fee(0.5, 0.04) == pytest.approx(0.01)
    assert en.pm_fee(0.5, 0.0) == 0.0


def test_asof_never_looks_ahead_and_drops_stale_quotes():
    grid = np.array([60, 120, 180, 2000], dtype=np.int64)
    ts = np.array([100, 170], dtype=np.int64)
    out = en.asof(grid, ts, np.array([0.4, 0.5]), max_age=900)
    assert math.isnan(out[0])
    assert out[1] == 0.4
    assert out[2] == 0.5
    assert math.isnan(out[3])


def test_build_pair_drops_empty_kalshi_sides():
    P = en.build_pair("K", 0, 240, np.array([0, 60, 120, 180]), np.array([0.0, 0.4, 0.4, 0.5]),
                      np.array([0.5, 1.0, 0.45, 0.45]), np.array([0, 60, 120, 180]), np.array([0.4] * 4),
                      deadline=1e6, h=0.01, k_mult=1.0, pm_rate=0.0, pm_exp=1.0)
    assert math.isnan(P.kb[0]) and math.isnan(P.ka[1])
    assert P.kb[2] == pytest.approx(0.4)
    assert math.isnan(P.kb[3])


def test_edge_matches_the_hand_calculation():
    P = make_pair(pm=[0.40], kb=[0.50], ka=[0.52], h=0.01, tau_years=0.5, pm_rate=0.04)
    L = en.legs(P, 1.0, R, 100)
    pa, kb = 0.41, 0.50
    cost = pa + 0.04 * pa * (1 - pa) + (1 - kb) + math.ceil(0.07 * 100 * 0.25 * 100 - 1e-9) / 100 / 100
    assert L.cost["A"][0] == pytest.approx(cost)
    assert L.edge["A"][0] == pytest.approx(1 - cost * (1 + R * 0.5))
    assert L.edge["B"][0] < 0


def test_double_costs_widen_both_spreads_and_double_fees_and_carry():
    P = make_pair(pm=[0.40], kb=[0.50], ka=[0.52], h=0.01, tau_years=0.5, pm_rate=0.04)
    L1, L2 = en.legs(P, 1.0, R, 100), en.legs(P, 2.0, R, 100)
    assert L2.spread["A"][0] == pytest.approx(2 * L1.spread["A"][0])
    assert L2.pm_px["A"][0] == pytest.approx(0.42) and L2.k_px["A"][0] == pytest.approx(0.49)
    assert L2.carry_rate[0] == pytest.approx(2 * L1.carry_rate[0])
    assert L2.edge["A"][0] < L1.edge["A"][0]


def test_a_gap_of_one_minute_is_never_traded():
    pm = [0.50, 0.40, 0.50, 0.50]
    P = make_pair(pm, kb=[0.50] * 4, ka=[0.51] * 4)
    L = en.legs(P, 1.0, R, 100)
    assert L.edge["A"][1] > 0.01
    assert en.simulate(P, L, 0.01, True, 0, 4, 100) == []


def test_entry_fills_at_the_second_observation():
    pm = [0.50, 0.40, 0.42, 0.42]
    P = make_pair(pm, kb=[0.50] * 4, ka=[0.51] * 4)
    L = en.legs(P, 1.0, R, 100)
    tr = en.simulate(P, L, 0.01, True, 0, 4, 100)
    assert len(tr) == 1 and tr[0].i_in == 2 and tr[0].dir == "A"
    assert tr[0].pm_px == pytest.approx(0.43)


def test_signal_does_not_reach_back_before_the_segment_start():
    pm = [0.40, 0.40, 0.50, 0.50]
    P = make_pair(pm, kb=[0.50] * 4, ka=[0.51] * 4)
    L = en.legs(P, 1.0, R, 100)
    assert en.simulate(P, L, 0.01, True, 1, 4, 100) == []
    assert len(en.simulate(P, L, 0.01, True, 0, 4, 100)) == 1


def test_missing_quote_blocks_entry():
    pm = [0.40, np.nan, 0.40, 0.50]
    P = make_pair(pm, kb=[0.50] * 4, ka=[0.51] * 4)
    assert en.simulate(P, en.legs(P, 1.0, R, 100), 0.01, True, 0, 4, 100) == []


def test_exit_when_the_market_pays_the_present_value_and_reentry_is_allowed():
    pm = [0.40, 0.40, 0.40, 0.60, 0.60, 0.40, 0.40, 0.40]
    P = make_pair(pm, kb=[0.50] * 8, ka=[0.51] * 8, tau_years=0.25)
    L = en.legs(P, 1.0, R, 100)
    tr = en.simulate(P, L, 0.01, True, 0, 8, 100)
    assert [(x.i_in, x.i_out) for x in tr] == [(1, 4), (6, None)]
    assert tr[0].liq_out == pytest.approx(L.liq["A"][4])
    hold = en.simulate(P, L, 0.01, False, 0, 8, 100)
    assert [(x.i_in, x.i_out) for x in hold] == [(1, None)]


def test_locked_pnl_is_the_entry_edge_and_realised_pnl_is_frozen_after_exit():
    pm = [0.40, 0.40, 0.40, 0.60, 0.60, 0.60]
    P = make_pair(pm, kb=[0.50] * 6, ka=[0.51] * 6, tau_years=0.25)
    L = en.legs(P, 1.0, R, 100)
    hold = en.simulate(P, L, 0.01, False, 0, 6, 100)[0]
    for i in (1, 2, 5):
        accrued = R * hold.cost_in * (P.t[i] - hold.t_in) / en.YEAR_S * 100
        assert en.pnl_at(P, L, hold, i, 1.0, R, "locked") == pytest.approx(100 * hold.edge_in - accrued)
    tr = en.simulate(P, L, 0.01, True, 0, 6, 100)[0]
    assert tr.i_out == 4
    realised = en.pnl_at(P, L, tr, 4, 1.0, R, "mid")
    assert realised == pytest.approx(100 * (tr.liq_out - tr.cost_in), abs=1e-3)
    assert en.pnl_at(P, L, tr, 5, 1.0, R, "liq") == realised
    assert en.pnl_at(P, L, tr, 0, 1.0, R, "mid") == 0.0


def test_mid_mark_at_entry_loses_the_half_spreads_and_fees():
    P = make_pair([0.40, 0.40], kb=[0.50] * 2, ka=[0.52] * 2, h=0.01)
    L = en.legs(P, 1.0, R, 100)
    tr = en.simulate(P, L, 0.01, True, 0, 2, 100)[0]
    mid_value = 0.40 + 1 - 0.51
    assert en.pnl_at(P, L, tr, 1, 1.0, R, "mid") == pytest.approx(100 * (mid_value - tr.cost_in))


def test_metrics_on_a_known_path():
    marks = np.array([86400, 2 * 86400, 3 * 86400, 4 * 86400], dtype=np.int64)
    m = en.metrics(np.array([10.0, 5.0, 20.0, 20.0]), marks, 1000.0, 500.0, 0)
    r = np.array([0.01, -0.005, 0.015, 0.0])
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(365))
    assert m["max_drawdown"] == pytest.approx(0.005)
    assert m["total_return"] == pytest.approx(0.02)


def test_pair_bootstrap_resamples_pairs():
    mean, lo, hi = en.pair_bootstrap({"a": [1.0, 1.0], "b": [3.0], "c": [2.0], "d": []}, 500, 0)
    assert mean == pytest.approx(1.75) and lo <= mean <= hi
