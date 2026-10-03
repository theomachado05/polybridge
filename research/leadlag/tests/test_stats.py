import math

import numpy as np
import pandas as pd
import pytest

from leadlag.stats import (betainc, binom_two_sided, chi2_sf, cumulative, distributed_lag, f_sf, fe_ols, gammaq,
                           granger, build_block)

T0 = pd.Timestamp("2025-03-19 12:00:00", tz="UTC")


def test_special_functions_match_known_values():
    assert math.isclose(chi2_sf(3.841458820694124, 1), 0.05, rel_tol=1e-6)
    assert math.isclose(chi2_sf(5.991464547107979, 2), 0.05, rel_tol=1e-6)
    assert math.isclose(chi2_sf(43.77297182574219, 30), 0.05, rel_tol=1e-6)
    assert math.isclose(gammaq(1.0, 1.0), math.exp(-1.0), rel_tol=1e-10)
    assert math.isclose(betainc(2.0, 3.0, 0.4), 0.5248, abs_tol=1e-9)    # I_0.4(2,3) = 0.5248
    assert math.isclose(f_sf(4.964602743730711, 1, 10), 0.05, rel_tol=1e-6)
    assert math.isclose(f_sf(3.4928284, 2, 20), 0.05, rel_tol=1e-4)
    assert f_sf(0.0, 3, 30) == 1.0


def test_binomial_sign_test():
    assert math.isclose(binom_two_sided(8, 10), 0.109375)
    assert math.isclose(binom_two_sided(5, 10), 1.0)
    assert math.isclose(binom_two_sided(10, 10), 2 / 1024)


def test_distributed_lag_recovers_the_lag_and_coefficient():
    frames = {}
    rng = np.random.default_rng(1)
    for e in range(5):
        n = 600
        ys = rng.normal(0, 1, n)
        x = 3 * e + rng.normal(0, 1, n)
        x[3:] += 0.6 * ys[:-3]
        frames[f"e{e}"] = pd.DataFrame({"x": x, "ys": ys, "in_window": np.r_[np.zeros(60, bool), np.ones(n - 60, bool)]},
                                       index=pd.date_range(T0, periods=n, freq="1min"))
    fit, st = distributed_lag(frames, "x", "ys", lags=8, hac_lags=8)
    z_ratio = 0.6 * 1.0 / np.sqrt(1 + 0.36)           # z-scaling: x has sd sqrt(1+.36)
    assert abs(fit.beta[2] - z_ratio) < 0.08            # lag 3 sits at index 2
    assert fit.t[2] > 6
    others = np.delete(np.abs(fit.t), 2)
    assert (others < 4).all()
    assert st["wald_p"] < 1e-6 and st["events"] == 5
    est, se, t = cumulative(fit)
    assert est > 0.3 and t > 2


def test_granger_detects_direction_only():
    rng = np.random.default_rng(2)
    frames = {}
    for e in range(5):
        n = 600
        pm = rng.normal(0, 1, n)
        eq = rng.normal(0, 1, n) + 2 * e
        eq[2:] += 0.5 * pm[:-2]          # PM leads equity by 2
        frames[f"e{e}"] = pd.DataFrame({"x": eq, "ys": pm, "in_window": np.r_[np.zeros(60, bool), np.ones(n - 60, bool)]},
                                       index=pd.date_range(T0, periods=n, freq="1min"))
    fwd = granger(frames, "x", "ys", p=5, hac_lags=5)
    rev = granger(frames, "ys", "x", p=5, hac_lags=5)
    assert fwd["F_p"] < 1e-6 and fwd["F"] > 20
    assert rev["F_p"] > 0.01 and rev["F"] < fwd["F"] / 5
    assert fwd["events"] == 5 and fwd["df2"] == fwd["n"] - 10 - 5


def test_no_relationship_gives_unremarkable_p_value():
    rng = np.random.default_rng(3)
    frames = {f"e{e}": pd.DataFrame({"x": rng.normal(size=500), "ys": rng.normal(size=500), "in_window": np.ones(500, bool)},
                                    index=pd.date_range(T0, periods=500, freq="1min")) for e in range(4)}
    g = granger(frames, "x", "ys", p=5, hac_lags=5)
    assert g["F_p"] > 0.01


def test_hac_se_is_larger_than_naive_for_autocorrelated_errors():
    rng = np.random.default_rng(4)
    frames = {}
    for e in range(6):
        n = 1500
        u = np.zeros(n)
        ys = np.zeros(n)
        for t in range(1, n):
            u[t] = 0.8 * u[t - 1] + rng.normal()
            ys[t] = 0.8 * ys[t - 1] + rng.normal()
        frames[f"e{e}"] = pd.DataFrame({"x": u, "ys": ys, "in_window": np.ones(n, bool)}, index=pd.date_range(T0, periods=n, freq="1min"))
    blocks = [build_block(k, f, "x", 0, "ys", 1) for k, f in frames.items()]
    naive = fe_ols(blocks, hac_lags=0)
    robust = fe_ols(blocks, hac_lags=30)
    assert robust.se[0] > naive.se[0] * 1.4


def test_blocks_with_too_few_rows_are_skipped():
    idx = pd.date_range(T0, periods=30, freq="1min")
    f = pd.DataFrame({"x": np.random.default_rng(0).normal(size=30), "ys": np.random.default_rng(1).normal(size=30),
                      "in_window": True}, index=idx)
    assert build_block("short", f, "x", 0, "ys", 5) is None
