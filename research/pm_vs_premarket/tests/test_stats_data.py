import numpy as np
import pandas as pd

from leadlag_closed.closures import Closure
from pm_vs_premarket.config import TZ
from pm_vs_premarket.data import (arm_k_rows, at_or_before, closure_measures, front_contract, parse_futures_rows,
                                  probe_futures)
from pm_vs_premarket.stats import benchmark_test, ols_cluster, verdict


def _panel(n, extra, seed=1):
    rng = np.random.default_rng(seed)
    b = rng.normal(0, 40, n)
    x = 0.03 * b + rng.normal(0, 1.5, n)
    g = b + extra * x + rng.normal(0, 8, n)
    days = pd.bdate_range("2024-04-01", periods=n)
    return g, b, x, days.strftime("%Y-%m-%d"), days.strftime("%Y-%m")


def test_null_when_pm_only_mirrors_benchmark():
    g, b, x, d, m = _panel(300, 0.0)
    r = benchmark_test(g, b, x, d, m, n_perm=199, n_boot=99, seed=3)
    assert abs(r["c"]) < 1.5 and r["d"] > abs(r["c"])
    assert verdict(r) .startswith("no evidence")


def test_pass_when_pm_carries_extra_information():
    g, b, x, d, m = _panel(300, 6.0)
    r = benchmark_test(g, b, x, d, m, n_perm=199, n_boot=99, seed=3)
    assert r["c"] > 4 and r["c_t"] > 1.96 and r["p_perm"] < 0.05 and r["dr2"] > 0
    assert verdict(r) == "adds information beyond the benchmark"


def test_cluster_se_matches_hc1_with_one_row_per_cluster():
    rng = np.random.default_rng(0)
    X = np.column_stack([np.ones(50), rng.normal(size=50)])
    y = X @ [1, 2] + rng.normal(size=50)
    r = ols_cluster(y, X, np.arange(50))
    e = y - X @ r["beta"]
    inv = np.linalg.inv(X.T @ X)
    hc1 = 50 / 48 * inv @ (X.T * e ** 2) @ X @ inv
    np.testing.assert_allclose(r["se"], np.sqrt(np.diag(hc1)) , rtol=1e-8)


def test_not_computable_on_tiny_sample():
    r = benchmark_test([1, 2], [1, 2], [0, 1], ["a", "b"], ["m", "m"], 9, 9, 1)
    assert verdict(r) == "not computable"


def test_front_contract_roll():
    assert front_contract("ES", pd.Timestamp("2024-06-03")) == "ESM4"
    assert front_contract("ES", pd.Timestamp("2024-06-12")) == "ESM4"
    assert front_contract("ES", pd.Timestamp("2024-06-13")) == "ESU4"
    assert front_contract("ES", pd.Timestamp("2024-12-20")) == "ESH5"
    assert front_contract("NQ", pd.Timestamp("2025-01-02"), "y2") == "NQH25"


def test_parse_futures_rows_ns_and_ms():
    t = pd.Timestamp("2024-06-03 12:00", tz="UTC")
    df = parse_futures_rows([{"window_start": t.value, "close": 5300.0}, {"t": t.value // 10**6 + 60000, "c": 5301.0}])
    assert list(df["close"]) == [5300.0, 5301.0] and df.index[0] == t


def test_at_or_before_tolerance():
    idx = pd.DatetimeIndex([pd.Timestamp("2024-06-03 09:05", tz=TZ).tz_convert("UTC")])
    bars = pd.DataFrame({"close": [1.0]}, index=idx)
    t = pd.Timestamp("2024-06-03 09:25", tz=TZ).tz_convert("UTC")
    assert np.isnan(at_or_before(bars, t))
    assert at_or_before(bars, t, tol_min=25) == 1.0


class _Probe:
    def __init__(self, n=None):
        self.n = n

    def get_all(self, path, params=None):
        if self.n is None:
            raise RuntimeError("403 not entitled")
        s = int(params["window_start.gte"])
        return [{"window_start": s + i * 60 * 10**9, "close": 1.0} for i in range(self.n)]


def test_probe_rule():
    assert probe_futures(_Probe())["benchmark"] == "SPY"
    assert probe_futures(_Probe(10))["benchmark"] == "SPY"
    p = probe_futures(_Probe(90))
    assert p["benchmark"] == "ES" and p["spelling"] == "y1"


def test_arm_k_bench_identity():
    df = pd.DataFrame({"closure": ["2024-04-01", "2024-04-02"], "open_day": ["2024-04-02", "2024-04-03"],
                       "market": "election", "kind": "overnight", "news": [False, True], "reason": ["", ""],
                       "gap_bp": [100.0, 5.0], "resid_bp": [20.0, 1.0], "dpm_early_o_pp": [1.0, 0.0], "dpm_o_pp": [2.0, 0.0]})
    r = arm_k_rows(df)
    assert len(r) == 1
    assert abs((1 + r["b_0800"][0] / 1e4) * (1.002) - 1.01) < 1e-12


def _bars():
    rows = {}
    for t in pd.date_range("2024-04-01 09:30", "2024-04-01 15:59", freq="1min"):
        rows[pd.Timestamp(t, tz=TZ)] = 100.0
    rows[pd.Timestamp("2024-04-02 07:59", tz=TZ)] = 100.5
    rows[pd.Timestamp("2024-04-02 09:24", tz=TZ)] = 100.8
    rows[pd.Timestamp("2024-04-02 09:30", tz=TZ)] = 101.0
    idx = pd.DatetimeIndex(list(rows)).tz_convert("UTC")
    v = list(rows.values())
    return pd.DataFrame({"open": v, "close": v, "volume": 1.0}, index=idx)


def test_closure_measures_spy_benchmark():
    c = Closure(pd.Timestamp("2024-04-01"), pd.Timestamp("2024-04-02"), "overnight")
    ts = lambda s: int(pd.Timestamp(s, tz=TZ).timestamp())
    pts = [(ts("2024-04-01 15:50"), 0.40), (ts("2024-04-02 07:50"), 0.42), (ts("2024-04-02 09:20"), 0.45)]
    r = closure_measures(c, _bars(), pts, -1)
    assert abs(r["g"] - 100.0) < 1e-9 and abs(r["b_0800"] - 50.0) < 1e-9 and abs(r["b_0925"] - 80.0) < 1e-9
    assert abs(r["x_0800"] + 2.0) < 1e-9 and abs(r["x_0925"] + 5.0) < 1e-9 and abs(r["x_full"] + 5.0) < 1e-9
