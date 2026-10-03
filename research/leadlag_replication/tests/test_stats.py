"""Date-level permutation, clustering, collapsing and the verdict rule on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from leadlag_replication.analysis import analyse, verdict
from leadlag_replication.stats import cluster_t, collapse_by_date, date_gap_index, date_perm_sign, date_perm_slope


def _panel(beta, n_dates=200, n_markets=3, seed=1, noise=30.0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_dates).strftime("%Y-%m-%d")
    common = rng.normal(0, 2, n_dates)                      # news shared by all markets on a date
    gap = beta * common + rng.normal(0, noise, n_dates)
    rows = []
    for k in range(n_markets):
        x = common + rng.normal(0, 1, n_dates)
        for d, xi, g in zip(dates, x, gap):
            rows.append({"market": f"m{k}", "rank": k + 1, "sign": 1, "cls": "geopolitics" if k else "US macro/policy",
                         "closure": d, "kind": "overnight" if k % 2 else "weekend", "fresh_date": d < "2024-04-01",
                         "pm_close": 10.0, "x_pp": xi, "gap_spy_bp": g, "gap_qqq_bp": 1.2 * g, "gap_iwm_bp": 0.8 * g, "reason": ""})
    return pd.DataFrame(rows)


def test_date_perm_detects_planted_relation():
    df = _panel(beta=25.0)
    r = date_perm_slope(df["x_pp"], df["gap_spy_bp"], df["closure"], 500, 7)
    assert r["b"] > 0 and r["t"] > 2 and r["p_perm"] < 0.01 and r["n_dates"] == 200


def test_date_perm_null_is_not_significant():
    df = _panel(beta=0.0, seed=3)
    r = date_perm_slope(df["x_pp"], df["gap_spy_bp"], df["closure"], 500, 7)
    assert r["p_perm"] > 0.05


def test_date_perm_is_wider_than_row_perm_when_dates_repeat():
    # with the same gap repeated for several markets, the row-level t overstates; clustered t must be smaller
    df = _panel(beta=8.0, n_markets=6, seed=5)
    c = cluster_t(df["x_pp"], df["gap_spy_bp"], df["closure"])
    r = date_perm_slope(df["x_pp"], df["gap_spy_bp"], df["closure"], 0, 7)
    assert abs(c["t"]) < abs(r["t"]) and c["G"] == 200


def test_date_gap_index_rejects_inconsistent_gaps():
    with pytest.raises(ValueError):
        date_gap_index(np.array([1.0, 2.0]), np.array(["2024-01-02", "2024-01-02"]))


def test_collapse_by_date_means_x():
    x, g = collapse_by_date([1.0, 3.0, 5.0], [10.0, 10.0, -4.0], ["d1", "d1", "d2"])
    assert list(x) == [2.0, 5.0] and list(g) == [10.0, -4.0]


def test_date_perm_sign_counts():
    r = date_perm_sign([2.0, -2.0, 0.5, 3.0], [5.0, -1.0, 9.0, -2.0], ["a", "b", "c", "d"], 1.0, 200, 1)
    assert (r["n"], r["k"]) == (3, 2) and 0 < r["p_perm"] <= 1


def test_verdict_rule():
    assert verdict({"b": 5.0, "p_perm": 0.01, "t": 2.5})[0] == "replicates"
    assert verdict({"b": 5.0, "p_perm": 0.01, "t": 1.5})[0] == "partial"
    assert verdict({"b": 5.0, "p_perm": 0.20, "t": 2.5})[0] == "partial"
    assert verdict({"b": 5.0, "p_perm": 0.20, "t": 1.0})[0] == "does not replicate"
    assert verdict({"b": -5.0, "p_perm": 0.001, "t": -4.0})[0] == "does not replicate"


def test_analyse_end_to_end_synthetic():
    res = analyse(_panel(beta=25.0), n_perm_secondary=200)
    assert res["verdict"] == "replicates" and res["n_markets"] == 3
    assert set(res["per_market"]) == {"m0", "m1", "m2"} and set(res["secondary_tickers"]) == {"QQQ", "IWM"}
    assert res["fresh"]["n_dates"] > 0 and set(res["by_class"]) == {"geopolitics", "US macro/policy"}
