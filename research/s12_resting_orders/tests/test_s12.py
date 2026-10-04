import numpy as np

from s12_resting_orders import config as cfg
from s12_resting_orders.run import cboot, cboot_diff, fill, keep_window, post_price, simulate, yes_terms


def P(rows):
    a = np.array(rows, float).reshape(-1, 4)
    return a[:, 0], a[:, 1], a[:, 2].astype(int), a[:, 3]


def test_post_price_passive_side():
    assert post_price(0.555, 1, 0) == 0.56
    assert post_price(0.555, -1, 0) == 0.55
    assert post_price(0.55, 1, 0) == 0.55
    assert post_price(0.55000001, 1, 0) == 0.55
    assert abs(post_price(0.555, 1, 1) - 0.55) < 1e-12
    assert abs(post_price(0.555, -1, 1) - 0.56) < 1e-12
    assert post_price(0.999, 1, 0) == 0.99


def test_yes_terms_converts_no_prints():
    ts, px, sd, sz = yes_terms([
        {"timestamp": 2, "price": 0.40, "side": "SELL", "outcome": "No", "size": 10},
        {"timestamp": 1, "price": 0.60, "side": "BUY", "outcome": "Yes", "size": 5},
        {"timestamp": 3, "price": 0.30, "side": "BUY", "outcome": "No", "size": 7},
        {"timestamp": 4, "price": 0.5, "side": "BUY", "outcome": "Maybe", "size": 7},
    ])
    assert list(ts) == [1, 2, 3]
    assert np.allclose(px, [0.60, 0.60, 0.70])
    assert list(sd) == [1, 1, -1]
    assert list(sz) == [5, 10, 7]


def test_sale_filled_only_by_buys_through_or_beyond_queue():
    pr = P([(5, 0.57, -1, 1000),
            (6, 0.55, 1, 1000),
            (7, 0.56, 1, 450),
            (8, 0.56, 1, 80),
            (9, 0.57, 1, 50),
            (40, 0.60, 1, 500)])
    frac, t, q = fill(*pr, side=1, q=0.56, t0=0, window_s=30, size=100, allowance=500)
    assert np.isclose(q, 80) and np.isclose(frac, 0.8) and t == 9


def test_full_fill_instant_and_print_at_t0_excluded():
    pr = P([(0, 0.70, 1, 1000), (3, 0.58, 1, 60), (4, 0.59, 1, 60)])
    frac, t, q = fill(*pr, side=1, q=0.56, t0=0, window_s=30, size=100, allowance=500)
    assert frac == 1.0 and t == 4 and q == 120


def test_purchase_mirror_and_two_x_shift():
    pr = P([(1, 0.44, -1, 100), (2, 0.45, 1, 1000)])
    assert fill(*pr, side=-1, q=0.45, t0=0, window_s=30, size=100, allowance=500)[0] == 1.0
    assert fill(*pr, side=-1, q=0.45, t0=0, window_s=30, size=100, allowance=500, shift=0.01)[0] == 0.0


def _order(**k):
    o = {"side": 1, "t_in": 0.0, "mid_in": 0.60, "t_exit": 1000.0, "mid_exit": 0.50, "settled": False,
         "half_spread": 0.005, "fee_rate": 0.04, "fee_exponent": 1.0}
    o.update(k)
    return o


def test_simulate_rest_in_rest_out_pays_no_cost():
    pr = P([(10, 0.61, 1, 200), (1010, 0.49, -1, 200)])
    v = cfg.Variant("x", 30, 0)
    s = simulate(_order(), pr, v, 1.0, mid_deadline=0.52)
    assert s["exit_how"] == "rest" and np.isclose(s["net"], 0.10) and np.isclose(s["gross"], 0.10)


def test_simulate_unfilled_exit_crosses_at_deadline_with_fee():
    pr = P([(10, 0.61, 1, 200)])
    s = simulate(_order(), pr, cfg.Variant("x", 30, 0), 1.0, mid_deadline=0.52)
    assert s["exit_how"] == "cross at deadline"
    assert np.isclose(s["net"], 0.60 - 0.52 - 0.005 - 0.04 * 0.52 * 0.48)


def test_simulate_two_x_crosses_at_exit_with_double_costs():
    pr = P([(10, 0.62, 1, 200)])
    s = simulate(_order(), pr, cfg.Variant("x", 30, 0), 2.0, mid_deadline=0.52)
    assert s["exit_how"] == "cross at exit"
    assert np.isclose(s["net"], 0.10 - 0.01 - 2 * 0.04 * 0.25)
    assert not simulate(_order(), P([(10, 0.61, 1, 200)]), cfg.Variant("x", 30, 0), 2.0, 0.52)["filled"]


def test_simulate_purchase_sign():
    pr = P([(10, 0.39, -1, 200), (1010, 0.51, 1, 200)])
    s = simulate(_order(side=-1, mid_in=0.40), pr, cfg.Variant("x", 30, 0), 1.0, 0.5)
    assert np.isclose(s["net"], 0.10)


def test_partial_fill_scales():
    pr = P([(10, 0.61, 1, 25)])
    s = simulate(_order(settled=True), pr, cfg.Variant("x", 30, 0), 1.0, 0.5)
    assert np.isclose(s["fill_frac"], 0.25) and s["exit_how"] == "settled"


def test_keep_window():
    ts = np.array([0, 5, 15, 25, 100])
    assert list(keep_window(ts, np.array([4, 20]), 10)) == [False, True, False, True, False]


def test_bootstraps():
    g = ["a", "b", "c", "d", "e", "f"] * 5
    v = np.arange(30, dtype=float)
    m, lo, hi = cboot(g, v)
    assert np.isclose(m, v.mean()) and lo < m < hi
    d, lo, hi = cboot_diff(g, v + 10, g, v)
    assert np.isclose(d, 10) and np.isclose(lo, 10) and np.isclose(hi, 10)
