"""Synthetic tests for the R1 hedge study. No network, no key."""
import json

import numpy as np
import pandas as pd
import pytest

import closed_hedge.run as run
from closed_hedge import analysis as A
from closed_hedge import hedge as H
from closed_hedge.books import half_spread_pp, pick_markets, summarise


def panel(n=120, slope=10.0, noise=20.0, market="m1", start="2025-01-02", seed=0, x_scale=2.0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n + 1)
    x = np.round(rng.normal(0, x_scale, n), 1)
    gap = slope * x + rng.normal(0, noise, n)
    return pd.DataFrame({
        "closure": days[:-1].strftime("%Y-%m-%d"), "open_day": days[1:].strftime("%Y-%m-%d"), "kind": "overnight",
        "market": market, "sign": -1, "pm_close": 30.0, "pm_open": 30.0 - x, "dpm_pp": -x, "dpm_o_pp": x,
        "dpm_early_o_pp": x / 2, "gap_bp": gap, "ret30_bp": rng.normal(0, 25, n), "resid_bp": rng.normal(0, 20, n),
        "gap_qqq_bp": gap, "reason": np.nan, "news": False,
    })


def test_rate_has_no_look_ahead():
    d = H.sort_panel(panel())
    r1 = H.expanding_rates(d)
    d2 = d.copy()
    d2.loc[60:, "gap_bp"] = d2.loc[60:, "gap_bp"] * -50 + 1e4  # change the future and the row itself
    r2 = H.expanding_rates(d2)
    pd.testing.assert_series_equal(r1["rate"].iloc[:61], r2["rate"].iloc[:61])
    assert not np.allclose(r1["rate"].iloc[62:].fillna(0), r2["rate"].iloc[62:].fillna(0))


def test_rate_burn_in_and_recovery():
    d = H.sort_panel(panel(n=300, slope=10.0, noise=5.0))
    r = H.expanding_rates(d)
    assert r["rate"].iloc[:20].isna().all()          # fewer than 20 earlier closures
    assert np.isfinite(r["rate"].iloc[20])
    assert r["n_prior"].iloc[20] == 20
    assert abs(r["rate"].iloc[-1] - 10.0) < 0.5
    assert (r["rate_src"].iloc[20:] == "market").all()


def test_pooled_fallback_then_own_market_and_clip():
    a = panel(n=60, slope=10.0, noise=1.0, market="a", start="2024-01-02", seed=1)
    b = panel(n=60, slope=-5.0, noise=1.0, market="b", start="2025-01-02", seed=2)
    d = H.sort_panel(pd.concat([a, b]))
    r = pd.concat([d, H.expanding_rates(d)], axis=1)
    rb = r[r["market"] == "b"]
    assert (rb["rate_src"].iloc[:20] == "pooled").all()
    assert rb["rate"].iloc[0] == pytest.approx(10.0, abs=0.5)    # market a's slope
    assert (rb["rate_src"].iloc[25:] == "market").all()
    assert (rb["rate"].iloc[25:] == 0).all()                    # negative own slope clipped to 0
    assert (rb["rate_raw"].iloc[25:] < 0).all()


def test_requires_nonzero_moves():
    d = panel(n=60)
    d.loc[:, "dpm_o_pp"] = 0.0
    d.loc[[3, 7], "dpm_o_pp"] = 1.0
    r = H.expanding_rates(H.sort_panel(d))
    assert r["rate"].isna().all()


def test_hedge_a_removes_explained_variance_and_charges_cost():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 2, 5000)
    gap = 10 * x + rng.normal(0, 10, 5000)
    y = H.hedge_a(gap, x, np.full(5000, 10.0), hs_pp=0.0)
    assert np.allclose(y, gap - 10 * x)
    vr = 1 - y.var() / gap.var()
    assert vr == pytest.approx(0.8, abs=0.03)                  # R2 = 400/500
    yc = H.hedge_a(gap, x, np.full(5000, 10.0), hs_pp=0.5)
    assert np.allclose(y - yc, 10.0)                           # 2 * 0.5 pp * 10 bp/pp


def test_frac_b_and_hedge_b():
    assert np.allclose(H.frac_b([-200, -50, 0, 30], 100), [1, 0.5, 0, 0])
    y = H.hedge_b([10.0, 10.0], [0.5, 0.0], 2.0)
    assert np.allclose(y, [5.0 - 2.0, 10.0])
    assert H.compound_bp(100, 100) == pytest.approx(201.0)


def test_variance_test_and_verdict():
    rng = np.random.default_rng(4)
    y0 = rng.normal(0, 10, 400)
    idx = H.iid_indices(400, 2000, 1)
    same = H.variance_test(y0, y0, y0, idx)
    assert same["VR0"] == pytest.approx(0) and same["VRS"] == pytest.approx(0)
    assert H.verdict(same) == "no evidence"
    good = H.variance_test(y0, 0.5 * y0, 0.9 * y0, idx)
    assert good["VR0"] == pytest.approx(0.75) and good["VRS"] == pytest.approx(0.81 - 0.25)
    assert H.verdict(good) == "reduces the loss variance"
    half = H.variance_test(y0, 0.5 * y0, 0.4 * y0, idx)
    assert H.verdict(half) == "partial"
    worse = H.variance_test(y0, 2 * y0, 2 * y0, idx)
    assert H.verdict(worse) == "increases variance"


def test_bootstrap_indices():
    b = H.block_indices(95, 50, 10, 0)
    assert b.shape == (50, 95) and b.min() >= 0 and b.max() < 95
    assert np.all(np.diff(b[:, :10], axis=1) == 1)             # first block is consecutive
    groups = np.array(["d1", "d1", "d2", "d3", "d3", "d3"])
    for rows in H.cluster_indices(groups, 20, 0):
        g = groups[rows]
        for k in ("d1", "d3"):
            assert (g == k).sum() % (groups == k).sum() == 0     # whole dates only


def test_static_control_has_same_average_size():
    d = A.prepare(panel(n=150))
    ev = d[d["excluded"] == ""]
    st = H.strategies(ev, 0.5)
    assert st.attrs["rbar"] == pytest.approx(ev["rate"].mean())
    assert st.attrs["fbar"] == pytest.approx(st["f_B"].mean())


def test_books_helpers():
    book = {"bids": [{"price": "0.40", "size": "5"}, {"price": "0.44", "size": "1"}],
            "asks": [{"price": "0.47", "size": "2"}, {"price": "0.45", "size": "3"}]}
    assert half_spread_pp(book) == pytest.approx(0.5)
    assert half_spread_pp({"bids": [{"price": "0.005"}], "asks": [{"price": "0.009"}]}) is None   # mid < 2%
    assert half_spread_pp({"bids": [], "asks": [{"price": "0.5"}]}) is None
    assert summarise([0.5] * 3)["fallback"] is True
    assert summarise([0.1, 0.5, 0.9] * 4) == {"hs_pp": 0.5, "n": 12, "fallback": False}
    ms = [{"enableOrderBook": True, "clobTokenIds": '["1","2"]', "active": True, "closed": False},
          {"enableOrderBook": False, "clobTokenIds": '["3"]', "active": True, "closed": False}]
    assert len(pick_markets(ms, 5)) == 1


def test_end_to_end_offline(tmp_path, monkeypatch):
    p = pd.concat([panel(n=150, market="election", start="2024-04-01", seed=5),
                   panel(n=150, market="recession", start="2025-01-10", seed=6)])
    ev = p.iloc[[40, 200]].copy()
    ev["news"] = True
    p = pd.concat([p, ev.assign(closure=ev["closure"] + "x")])
    csv = tmp_path / "closures_all.csv"
    p.to_csv(csv, index=False)
    monkeypatch.setattr(run, "PANEL_CSV", csv)
    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path / "out")
    monkeypatch.setattr(run, "replication_panel", lambda: (None, "not available (test)"))
    assert run.main(["--offline-books"]) == 0
    out = tmp_path / "out"
    res = json.loads((out / "results.json").read_text())
    assert res["n_panel"] == 300 and res["n_eval"] == 280
    assert res["hs"]["fallback"] is True
    assert {"A", "B", "B08"} <= set(res["primary"]["tests"])
    assert res["primary"]["tests"]["A"]["VR0"] > 0.2          # slope 10, x sd 2, noise 20 -> R2 = 0.5
    s = (out / "SUMMARY.md").read_text()
    assert "Headline" in s and "not available (test)" in s
    assert (out / "chart.png").stat().st_size > 1000
    h = pd.read_csv(out / "closures_hedged.csv")
    assert len(h) == 300 and (h["excluded"].fillna("") == "no rate yet").sum() == 20
