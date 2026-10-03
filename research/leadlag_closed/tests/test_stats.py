import numpy as np
import pandas as pd
import pytest

from leadlag_closed.analysis import analyse
from leadlag_closed.stats import binom_two_sided, interaction, ols_hc3, pairing_placebo, sign_agreement, slope_test


def test_binomial_exact():
    assert binom_two_sided(5, 10) == 1.0
    assert binom_two_sided(10, 12) == pytest.approx(2 * (66 + 12 + 1) / 4096)   # 0.0386
    assert binom_two_sided(2, 12) == binom_two_sided(10, 12)                   # two-sided symmetry
    assert binom_two_sided(10, 10) == pytest.approx(2 / 1024)
    assert np.isnan(binom_two_sided(0, 0))


def test_sign_agreement_threshold_and_zero_gap():
    x = [5, -3, 0.4, 2, -2, 1.0]
    y = [10, -1, 100, -5, 0, 7]
    r = sign_agreement(x, y, 1.0)
    # |x|>=1 and y!=0: (5,10) agree, (-3,-1) agree, (2,-5) disagree, (1,7) agree; (-2,0) dropped; (0.4,..) below threshold
    assert (r["n"], r["k"]) == (4, 3)
    assert sign_agreement(x, y, 0.3)["n"] == 5
    assert sign_agreement([np.nan, 3], [1, np.nan], 1.0)["n"] == 0


def test_ols_hc3_matches_closed_form():
    rng = np.random.default_rng(0)
    x = rng.normal(size=60)
    y = 2.0 + 3.0 * x + rng.normal(size=60)
    f = ols_hc3(y, np.column_stack([np.ones(60), x]))
    b = np.polyfit(x, y, 1)
    assert f["beta"][1] == pytest.approx(b[0]) and f["beta"][0] == pytest.approx(b[1])
    assert f["t"][1] > 10 and 0.8 < f["r2"] < 1


def test_slope_test_detects_and_rejects():
    rng = np.random.default_rng(1)
    x = rng.normal(size=40) * 5
    s = slope_test(x, 4 * x + rng.normal(size=40), 2000, 1)
    assert s["b"] == pytest.approx(4, abs=0.3) and s["p_perm"] < 0.01 and s["p_rho"] < 0.01
    s0 = slope_test(x, rng.normal(size=40), 2000, 1)
    assert s0["p_perm"] > 0.05
    assert np.isnan(slope_test([1, 2], [1, 2], 100, 1)["b"])                    # too few points
    assert np.isnan(slope_test([1.0] * 10, list(range(10)), 100, 1)["b"])         # no variation in x


def test_slope_test_reproducible():
    x = np.arange(12.0)
    y = np.array([1, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10, 12.0])
    assert slope_test(x, y, 500, 7) == slope_test(x, y, 500, 7)


def test_pairing_placebo_signal_vs_noise():
    rng = np.random.default_rng(2)
    pool = {"a": rng.normal(0, 100, 300)}
    x = np.array([5, -6, 7, -8, 9, -5, 6, -7.0, 8, -9])
    strong = pairing_placebo(x, ["a"] * 10, 100 * x, pool, 1.0, 2000, 3)
    assert strong["k_obs"] == 10 and strong["p_k"] < 0.01 and strong["p_slope"] < 0.01
    weak = pairing_placebo(x, ["a"] * 10, rng.normal(0, 100, 10) * np.sign(rng.normal(size=10)), pool, 1.0, 2000, 3)
    assert weak["p_k"] > 0.01
    few = pairing_placebo([5.0, 6.0], ["a", "a"], [1.0, 2.0], pool, 1.0, 100, 3)
    assert few["k_obs"] is None


def test_interaction_recovers_event_only_effect():
    rng = np.random.default_rng(4)
    x = rng.normal(0, 5, 300)
    news = np.zeros(300)
    news[:20] = 1
    y = 8 * x * news + rng.normal(0, 20, 300)
    r = interaction(x, y, news)
    assert r["d"] == pytest.approx(8, abs=2) and r["d_t"] > 3 and abs(r["b_t"]) < 3


def _rows(n_ev=14, n_pl=200, event_slope=0.0, placebo_slope=0.0, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_ev + n_pl):
        news = i < n_ev
        x = float(rng.normal(0, 6 if news else 1.5))
        slope = event_slope if news else placebo_slope
        out.append(dict(closure=f"c{i}", kind=["overnight", "weekend", "holiday"][i % 3], market="recession" if i % 2 else "election",
                        news=news, dpm_o_pp=x, dpm_early_o_pp=x * 0.5, gap_bp=slope * x + float(rng.normal(0, 25)),
                        ret30_bp=float(rng.normal(0, 15)), resid_bp=float(rng.normal(0, 10)), reason="", event=f"e{i}" if news else ""))
    return pd.DataFrame(out)


def test_analyse_supports_when_events_have_strong_relation():
    res = analyse(_rows(n_ev=16, event_slope=25.0, placebo_slope=0.0, seed=5))
    assert res["verdict"] == "supports the closed-market claim", res["verdict_detail"]
    assert res["t1_events"][1.0]["rate"] > 0.8
    assert res["p3"]["d"] > 10


def test_analyse_no_evidence_on_pure_noise():
    verdicts = [analyse(_rows(event_slope=0.0, seed=s))["verdict"] for s in range(6, 14)]
    assert verdicts.count("supports the closed-market claim") == 0
    assert verdicts.count("no evidence") >= 5


def test_analyse_flags_general_comovement_in_placebo():
    # PM relation present everywhere (events and placebo alike): the claim 'only on news' is not supported by P3
    res = analyse(_rows(n_ev=16, n_pl=300, event_slope=12.0, placebo_slope=12.0, seed=20))
    assert res["p1_t2"]["b"] == pytest.approx(12, abs=4) and res["p1_t2"]["p_perm"] < 0.01
    assert abs(res["p3"]["d_t"]) < 3
    assert res["p3"]["b_t"] > 5


def test_analyse_handles_empty_or_tiny_event_set():
    rows = _rows(n_ev=2, n_pl=50, seed=9)
    res = analyse(rows)
    assert res["verdict"] in ("no evidence", "mixed")
    assert res["n_events_usable"] == 2
