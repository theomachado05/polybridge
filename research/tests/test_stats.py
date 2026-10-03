import math

import numpy as np

from polybridge_research.stats import benjamini_hochberg, bootstrap_ci, deflated_sharpe, expected_max_sharpe


def test_bootstrap_ci_brackets_the_mean_and_is_reproducible():
    x = np.random.default_rng(1).normal(0.02, 0.05, 400)
    lo, hi = bootstrap_ci(x, seed=0)
    assert lo < x.mean() < hi
    assert bootstrap_ci(x, seed=0) == (lo, hi)


def test_bootstrap_ci_wider_at_higher_level():
    x = np.random.default_rng(2).normal(0, 1, 200)
    lo95, hi95 = bootstrap_ci(x, level=0.95)
    lo975, hi975 = bootstrap_ci(x, level=0.975)
    assert lo975 < lo95 and hi975 > hi95


def test_bootstrap_ci_too_few_values_is_nan():
    lo, hi = bootstrap_ci([0.1, float("nan"), 0.2, 0.3, 0.4])
    assert math.isnan(lo) and math.isnan(hi)


def test_benjamini_hochberg_known_values():
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.20])
    # sorted p .01 .03 .04 .20 -> p*m/rank .04 .06 .0533 .20 -> step-up min .04 .0533 .0533 .20
    np.testing.assert_allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.20], rtol=1e-12)


def test_benjamini_hochberg_monotone_and_capped():
    q = benjamini_hochberg([0.9, 0.001, 0.5, 0.95])
    assert np.all(q <= 1.0)
    order = np.argsort([0.9, 0.001, 0.5, 0.95])
    assert np.all(np.diff(q[order]) >= 0)


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 0.01) == 0.0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0


def test_deflated_sharpe_penalizes_many_trials():
    one = deflated_sharpe(0.15, n_obs=500, n_trials=1, sharpe_variance=0.0025)
    many = deflated_sharpe(0.15, n_obs=500, n_trials=800, sharpe_variance=0.0025)
    assert 0.0 <= many < one <= 1.0
    assert one > 0.99


def test_benjamini_hochberg_ignores_nan_and_keeps_position():
    q = benjamini_hochberg([0.01, 0.04, float("nan"), 0.03])
    ref = benjamini_hochberg([0.01, 0.04, 0.03])
    np.testing.assert_allclose([q[0], q[1], q[3]], ref, rtol=1e-12)
    assert math.isnan(q[2])


def test_deflated_sharpe_nan_with_fewer_than_two_obs():
    assert math.isnan(deflated_sharpe(0.5, n_obs=1, n_trials=10, sharpe_variance=0.1))
