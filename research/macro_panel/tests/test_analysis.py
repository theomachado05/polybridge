"""Clustered OLS, the contrast, the verdict and the full analysis on synthetic panels."""
import numpy as np
import pandas as pd

from leadlag_replication.stats import cluster_t
from macro_panel.analysis import analyse, cluster_ols, contrast, verdict

CLS = ("recession", "fed", "inflation", "unemployment", "gdp")


def _panel(beta, n_dates=300, n_markets=5, seed=1, noise=40.0, start="2023-01-03"):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n_dates).strftime("%Y-%m-%d")
    common = rng.normal(0, 2, n_dates)
    gap = beta * common + rng.normal(0, noise, n_dates)
    rows = []
    for k in range(n_markets):
        x = common + rng.normal(0, 1, n_dates)
        for d, xi, g in zip(dates, x, gap):
            rows.append({"market": f"m{k}", "rank": k + 1, "sign": 1, "cls": CLS[k % 5], "closure": d,
                         "kind": "overnight" if k % 2 else "weekend", "fresh_date": d < "2024-01-01", "pm_close": 10.0,
                         "x_pp": xi, "gap_spy_bp": g, "reason": ""})
    return pd.DataFrame(rows)


def test_cluster_ols_matches_cluster_t():
    df = _panel(8.0)
    f = cluster_ols(df["gap_spy_bp"], np.column_stack([np.ones(len(df)), df["x_pp"]]), df["closure"])
    c = cluster_t(df["x_pp"], df["gap_spy_bp"], df["closure"])
    assert abs(f["beta"][1] - c["b"]) < 1e-9 and abs(f["se"][1] - c["se"]) < 1e-9


def test_contrast_detects_planted_difference_and_null():
    macro, geo = _panel(25.0, seed=2), _panel(0.0, seed=3, start="2024-01-02")
    c = contrast(macro, geo)
    assert c["label"] == "macro slope larger" and c["ci"][0] > 0 and abs(c["b_macro"] - c["b_geo"] - c["d"]) < 1e-9
    c0 = contrast(_panel(5.0, seed=4), _panel(5.0, seed=5, start="2024-01-02"))
    assert c0["label"] == "no difference shown"


def test_verdict_rule():
    assert verdict({"b": 5.0, "p_perm": 0.01, "cluster_t": 2.5})[0] == "holds"
    assert verdict({"b": 5.0, "p_perm": 0.01, "cluster_t": 1.5})[0] == "partial"
    assert verdict({"b": 5.0, "p_perm": 0.20, "cluster_t": 2.5})[0] == "partial"
    assert verdict({"b": 5.0, "p_perm": 0.20, "cluster_t": 1.0})[0] == "does not hold"
    assert verdict({"b": -5.0, "p_perm": 0.001, "cluster_t": -4.0})[0] == "does not hold"
    assert verdict({"b": float("nan"), "p_perm": float("nan"), "cluster_t": float("nan")})[0] == "does not hold"


def test_analyse_planted_and_null():
    res = analyse(_panel(25.0), _panel(0.0, seed=9, start="2024-01-02"), n_perm_secondary=100)
    assert res["verdict"] == "holds" and res["primary"]["ci"][0] > 0 and set(res["by_class"]) == set(CLS)
    assert res["fresh"]["n_dates"] > 0 and res["contrast"]["label"] == "macro slope larger"
    null = analyse(_panel(0.0, seed=11), None, n_perm_secondary=100)
    assert null["verdict"] == "does not hold" and null["contrast"] is None
