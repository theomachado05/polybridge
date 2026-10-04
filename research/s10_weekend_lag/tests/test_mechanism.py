import numpy as np

from s4_linked_assets import engine as en
from s10_weekend_lag.mechanism import Acc, activity, jumps_vec, pair_bins, pickoffs
from s10_weekend_lag.run import jumps


def test_jumps_vec_matches_loop():
    rng = np.random.default_rng(1)
    for _ in range(50):
        P = np.clip(50 + np.cumsum(rng.normal(0, 2.5, 200)), 1, 99)
        P[rng.integers(0, 200, 10)] = np.nan
        assert jumps_vec(P, 3) == {i: float(v) for i, v in jumps(P, 1.0, 3).items()}


def test_activity_counts_changes():
    t = np.arange(0, 600, 60)
    p = np.array([.5, .5, .51, .51, .52, .52, .52, .52, .52, .53])
    assert list(activity(t, p, np.array([540.0, 300.0]), 300)) == [1.0, 2.0]


def test_acc_matches_clustered_slope():
    rng = np.random.default_rng(2)
    x, c = rng.normal(size=500), rng.integers(0, 20, 500)
    y = 0.3 * x + rng.normal(size=500)
    acc = Acc(20)
    acc.add("k", x, y, c)
    r, ref = acc.slope("k"), en.clustered_slope(x, y, c)
    assert abs(r["slope"] - ref["slope"]) < 1e-12 and abs(r["se"] - ref["se"]) < 1e-12


def _g(P, A, stale, id_):
    return {"id": id_, "P": np.asarray(P, float), "A": np.asarray(A, float), "stale": np.asarray(stale, bool), "J": jumps_vec(np.asarray(P, float), 3)}


def test_pair_bins_active_leads_thin_and_sign():
    # a is active and moves at bin 1; b (pair sign -1) follows one bin later in the opposite YES direction
    n = 400
    rng = np.random.default_rng(3)
    xa = rng.normal(0, 1, n)
    Pa = 50 + np.cumsum(xa) * 0.2
    Pb = 50 - np.concatenate([[0], np.cumsum(xa)[:-1]]) * 0.2
    a, b = _g(Pa, np.full(n, 30), np.zeros(n), "a"), _g(Pb, np.full(n, 1), np.ones(n), "b")
    acc = Acc(1)
    pair_bins(acc, "B", "x", a, b, -1.0, np.zeros(n, int))
    assert acc.slope(("B", "x", "active->thin", 5, "all"))["slope"] > 0.9
    assert abs(acc.slope(("B", "x", "thin->active", 5, "all"))["slope"]) < 0.2
    assert acc.slope(("B", "x", "active->thin", 5, "stale"))["n"] > 0
    assert acc.slope(("B", "x", "active->thin", 5, "active"))["n"] == 0


def test_pickoff_direction_follows_pair_sign():
    P = np.array([50, 50, 50, 50, 55, 55, 55, 55], float)
    a = _g(P, np.full(8, 20), np.zeros(8), "a")
    b = _g(np.full(8, 40.0), np.zeros(8), np.ones(8), "b")
    s = pickoffs("B", a, b, -1.0, np.arange(8) * 300.0, np.array(["d"] * 8))
    assert len(s) == 1 and s[0]["stale_market"] == "b" and s[0]["dir"] == -1.0
