from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gap_model import model
from gap_model.model import (band_coverage, between_market_sd, bucket_of, calibration_table, fit_rate, oos_r2,
                             sign_accuracy, slope_test, verdict, walk_forward)


def _panel(n=120, rate=8.0, noise=10.0, seed=0, market="m1", start="2024-01-01"):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n + 1)
    x = rng.choice([-2, -1, -0.5, 0, 0.5, 1, 2], size=n).astype(float)
    g = rate * x + rng.normal(0, noise, n)
    return pd.DataFrame({"market": market, "closure": days[:-1].strftime("%Y-%m-%d"),
                         "open_day": days[1:].strftime("%Y-%m-%d"), "x": x, "gap": g, "kind": "overnight"})


def test_fit_rate_through_origin_exact():
    f = fit_rate([1, 2, -1, 0], [5, 10, -5, 3])
    assert f["rate"] == pytest.approx(5.0)
    assert f["n"] == 4 and f["n_nonzero"] == 3
    assert f["resid_sd"] == pytest.approx(np.sqrt(3.0))
    assert f["se"] == pytest.approx(0.0, abs=1e-12)


def test_fit_rate_hc3_matches_formula():
    x = np.array([1.0, -2.0, 0.5, 3.0])
    g = np.array([2.0, -3.0, 1.5, 7.0])
    f = fit_rate(x, g)
    sxx = (x ** 2).sum()
    r = (x * g).sum() / sxx
    e = g - r * x
    h = x ** 2 / sxx
    se = np.sqrt((x ** 2 * (e / (1 - h)) ** 2).sum()) / sxx
    assert f["rate"] == pytest.approx(r) and f["se"] == pytest.approx(se)


def test_fit_rate_no_moves_is_nan():
    f = fit_rate([0, 0, 0], [1, 2, 3])
    assert np.isnan(f["rate"]) and f["n_nonzero"] == 0


def test_between_market_sd():
    assert between_market_sd([4.0, 8.0], 6.0) == pytest.approx(np.std([4, 8], ddof=1))
    assert between_market_sd([4.0], -6.0) == pytest.approx(6.0)
    assert between_market_sd([], 3.0) == pytest.approx(3.0)


def test_walk_forward_no_lookahead():
    d = _panel(80)
    a = walk_forward(d, "gap", n_min=10)
    d2 = d.copy()
    d2.loc[d2.index[-1], "gap"] = 1e6
    b = walk_forward(d2, "gap", n_min=10)
    pd.testing.assert_series_equal(a["pred_bp"].iloc[:-1], b["pred_bp"].iloc[:-1])
    first = a.iloc[0]
    tr = d[d["open_day"] <= first["closure"]]
    assert first["train_n"] == len(tr)
    assert fit_rate(tr["x"], tr["gap"])["rate"] == pytest.approx(first["rate"])


def test_walk_forward_burn_in_and_pooled_fallback():
    a = _panel(60, rate=8, seed=1, market="a", start="2024-01-01")
    b = _panel(60, rate=8, seed=2, market="b", start="2024-06-03")
    pr = walk_forward(pd.concat([a, b], ignore_index=True), "gap", n_min=10)
    nz_a = (a["x"] != 0).cumsum()
    assert len(pr[pr["market"] == "a"]) < len(a)
    first_a = pr[pr["market"] == "a"].iloc[0]
    assert first_a["source"] == "own" and first_a["train_n_nonzero"] >= 10
    assert nz_a.max() >= 10
    pb = pr[pr["market"] == "b"]
    assert pb.iloc[0]["source"] == "pooled"
    assert (pb["source"] == "own").any()
    sw = pb["source"].tolist()
    assert sw.index("own") > 0 and "pooled" not in sw[sw.index("own"):]
    r0 = pb.iloc[0]
    assert r0["se_eff"] == pytest.approx(np.sqrt(r0["rate_se"] ** 2 + r0["rate"] ** 2))


def test_walk_forward_test_column_limits_predictions_not_training():
    a = _panel(60, seed=3, market="a")
    b = _panel(40, seed=4, market="b", start="2024-02-01")
    d = pd.concat([a.assign(test=False), b.assign(test=True)], ignore_index=True)
    pr = walk_forward(d, "gap", n_min=10)
    assert set(pr["market"]) == {"b"}
    assert pr["train_n"].max() > len(b)


def test_recovers_signal_and_detects_null():
    sig = walk_forward(_panel(300, rate=10, noise=5, seed=5), "gap", n_min=20)
    g1, g2 = sign_accuracy(sig["pred_bp"], sig["gap_bp"]), slope_test(sig["pred_bp"], sig["gap_bp"], n_perm=500)
    assert g1["rate"] > 0.8 and g1["p"] < 0.01
    assert g2["c"] == pytest.approx(1.0, abs=0.15) and g2["p_perm"] < 0.01
    assert verdict(g1, g2)[0] == "Accurate out of sample"
    null = walk_forward(_panel(300, rate=0, noise=10, seed=6), "gap", n_min=20)
    n1, n2 = sign_accuracy(null["pred_bp"], null["gap_bp"]), slope_test(null["pred_bp"], null["gap_bp"], n_perm=500)
    assert n2["p_perm"] > 0.01
    assert verdict(n1, n2)[0] in ("Not accurate out of sample", "Partial")


def test_sign_accuracy_excludes_zeros_and_theta():
    s = sign_accuracy([1, -1, 0, 2, 3], [1, 1, 5, 0, 4])
    assert s["n"] == 3 and s["k"] == 2
    t = sign_accuracy([1, -1, 2], [1, 1, 1], x=[0.5, 1.0, 0.9999999999], theta=1.0)
    assert t["n"] == 2 and t["k"] == 1


def test_slope_test_date_permutation_keeps_shared_gap():
    rng = np.random.default_rng(7)
    dates = np.repeat(np.arange(50), 2)
    gap = np.repeat(rng.normal(0, 10, 50), 2)
    pred = gap * 0.5 + rng.normal(0, 1, 100)
    r = slope_test(pred, gap, n_perm=300, groups=dates)
    assert r["c"] > 0 and r["p_perm"] < 0.01


def test_oos_r2_and_buckets_and_calibration():
    assert oos_r2([1, 2], [1, 2], [0, 0]) == pytest.approx(1.0)
    assert oos_r2([0, 0], [1, 2], [0, 0]) == pytest.approx(0.0)
    assert [bucket_of(v) for v in (-10, -5, -3, -0.1, 0, 0.1, 3, 9.9, 10)] == [
        "<= -10", "(-10, -3]", "(-10, -3]", "(-3, 0)", "= 0", "(0, 3)", "[3, 10)", "[3, 10)", ">= 10"]
    ct = calibration_table([-12, 0, 0, 5, 11], [-3, 2, -1, 4, -1])
    assert list(ct["bucket"]) == list(model.PARAMS.buckets)
    assert ct.set_index("bucket").loc["= 0", "n"] == 2
    assert np.isnan(ct.set_index("bucket").loc["= 0", "hit_rate"])
    assert ct.set_index("bucket").loc[">= 10", "hit_rate"] == 0.0


def test_band_coverage_nominal_on_gaussian():
    pr = walk_forward(_panel(400, rate=5, noise=10, seed=8), "gap", n_min=20)
    cov = band_coverage(pr)
    assert 0.72 < cov["all"]["coverage"] < 0.88
