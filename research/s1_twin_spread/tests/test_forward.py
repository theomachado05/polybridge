"""S1 forward paper test: fills only from recorded levels, the two-snapshot rule, fees, exits."""
import math

import pytest

from s1_twin_spread import forward as fw

M = {"ticker": "K", "token": "T", "deadline_ts": 1_000_000 + 90 * 86400, "k_mult": 1.0, "pm_rate": 0.0, "pm_exp": 1.0}
R = 0.04


def book(bid, ask, size=100.0, depth=1):
    return {"b": [[round(bid - 0.01 * i, 4), size] for i in range(depth)],
            "a": [[round(ask + 0.01 * i, 4), size] for i in range(depth)]}


def snap(t, pm, k):
    return (float(t), {**pm, "vts": int(t * 1000)}, k)


def test_walk_stops_where_the_marginal_edge_falls_below_theta():
    pm_asks = [[0.40, 50], [0.44, 50], [0.60, 50]]
    k_no_asks = [[0.50, 200]]
    w = fw.walk(pm_asks, k_no_asks, 0.0, 1.0, 1.0, 1.0, 0.0, 0.01, 500)
    # 0.40 + 0.50 + fee 0.0175 -> edge 0.0825; 0.44 + 0.50 + 0.0175 -> 0.0425; 0.60 -> negative
    assert w["qty"] == 100 and [f[0] for f in w["fills"]] == [0.40, 0.44]
    assert w["pm_gross"] == pytest.approx(50 * 0.40 + 50 * 0.44)
    assert w["k_fee"] == pytest.approx(math.ceil(0.07 * 100 * 0.25 * 100 - 1e-9) / 100)


def test_walk_never_fills_more_than_the_thinner_leg_or_the_cap():
    assert fw.walk([[0.40, 30]], [[0.50, 200]], 0.0, 1.0, 1.0, 1.0, 0.0, 0.01, 500)["qty"] == 30
    assert fw.walk([[0.40, 900]], [[0.50, 900]], 0.0, 1.0, 1.0, 1.0, 0.0, 0.01, 500)["qty"] == 500
    assert fw.walk([], [[0.50, 200]], 0.0, 1.0, 1.0, 1.0, 0.0, 0.01, 500)["qty"] == 0


def test_entry_needs_two_adjacent_snapshots_and_fills_from_the_second():
    wide = snap(1_000_000, book(0.38, 0.40), book(0.50, 0.52))        # A: 0.40 + (1 - 0.50) -> edge
    flat = snap(1_000_015, book(0.48, 0.50), book(0.50, 0.52))
    assert fw.paper_test([wide, flat], M, 0.01, True, 1.0, R, 500)[0] == []
    second = snap(1_000_015, book(0.39, 0.41, size=60), book(0.50, 0.52))
    tr = fw.paper_test([wide, second], M, 0.01, True, 1.0, R, 500)[0]
    assert len(tr) == 1 and tr[0]["dir"] == "A" and tr[0]["qty"] == 60 and tr[0]["pm_avg"] == pytest.approx(0.41)
    late = snap(1_000_060, book(0.39, 0.41, size=60), book(0.50, 0.52))   # a missed cycle breaks the run
    assert fw.paper_test([wide, late], M, 0.01, True, 1.0, R, 500)[0] == []


def test_one_position_per_pair_and_minimum_size():
    s = [snap(1_000_000 + 15 * i, book(0.38, 0.40), book(0.50, 0.52)) for i in range(6)]
    assert len(fw.paper_test(s, M, 0.01, True, 1.0, R, 500)[0]) == 1
    thin = [snap(1_000_000 + 15 * i, book(0.38, 0.40, size=3), book(0.50, 0.52)) for i in range(3)]
    assert fw.paper_test(thin, M, 0.01, True, 1.0, R, 500)[0] == []


def test_locked_pnl_is_payoff_less_cost_and_carry():
    s = [snap(1_000_000 + 15 * i, book(0.38, 0.40), book(0.50, 0.52)) for i in range(2)]
    tr = fw.paper_test(s, M, 0.01, True, 1.0, R, 500)[0][0]
    fee = math.ceil(0.07 * 100 * 0.25 * 100 - 1e-9) / 100
    cost = 100 * 0.40 + 100 * 0.50 + fee
    carry = R * (M["deadline_ts"] - s[1][0]) / fw.YEAR_S
    assert tr["cost"] == pytest.approx(cost)
    assert tr["locked_pnl"] == pytest.approx(100 - cost * (1 + carry))


def test_exit_when_both_bids_pay_the_present_value_twice_in_a_row():
    open_ = [snap(1_000_000 + 15 * i, book(0.38, 0.40), book(0.50, 0.52)) for i in range(2)]
    # the gap reverses: Polymarket YES bid 0.60, Kalshi YES ask 0.52 -> NO bid 0.48: 1.08 before fees
    rev = [snap(1_000_030 + 15 * i, book(0.60, 0.62), book(0.50, 0.52)) for i in range(2)]
    tr = fw.paper_test(open_ + rev, M, 0.01, True, 1.0, R, 500)[0]
    assert tr[0]["t_out"] == rev[1][0]
    assert tr[0]["proceeds"] == pytest.approx(100 * 0.60 + 100 * 0.48 - math.ceil(0.07 * 100 * 0.48 * 0.52 * 100 - 1e-9) / 100)
    hold = fw.paper_test(open_ + rev, M, 0.01, False, 1.0, R, 500)[0]
    assert hold[0]["t_out"] is None


def test_double_costs_widen_the_recorded_book():
    b = fw.widen(book(0.38, 0.40, depth=2), 2.0)
    assert b["a"][0][0] == pytest.approx(0.41) and b["b"][0][0] == pytest.approx(0.37) and b["a"][1][0] == pytest.approx(0.42)


def test_capacity_is_the_uncapped_fill():
    s = [snap(1_000_000 + 15 * i, book(0.38, 0.40, size=2000), book(0.50, 0.52, size=1500)) for i in range(2)]
    tr, cap = fw.paper_test(s, M, 0.01, True, 1.0, R, 500)
    assert tr[0]["qty"] == 500 and cap["max_fillable_qty"] == 1500 and cap["depth_share_at_max"] == pytest.approx(1.0)


def test_snapshots_pair_the_two_venues_by_time():
    rows = [{"t": 100.0, "v": "pm", "id": "T", "b": [], "a": []}, {"t": 100.3, "v": "k", "id": "K", "b": [], "a": []},
            {"t": 115.0, "v": "pm", "id": "T", "b": [], "a": []}, {"t": 140.0, "v": "k", "id": "K", "b": [], "a": []}]
    assert [s[0] for s in fw.snapshots(rows, [M])["K"]] == [100.3]
