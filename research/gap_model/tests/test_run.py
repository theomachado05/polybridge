"""End-to-end run on synthetic closure tables (no network, no real data)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from gap_model import run


def _write_inputs(tmp_path, with_b: bool):
    rng = np.random.default_rng(11)
    rows = []
    for market, start, n, sign in (("election", "2024-04-01", 150, 1), ("recession", "2025-01-10", 230, -1)):
        days = pd.bdate_range(start, periods=n + 1)
        x = rng.choice([-2, -1, -0.5, 0, 0, 0.5, 1, 2], size=n).astype(float)
        g = 7 * x + rng.normal(0, 30, n)
        for i in range(n):
            rows.append({"closure": days[i].strftime("%Y-%m-%d"), "open_day": days[i + 1].strftime("%Y-%m-%d"),
                         "kind": "overnight", "market": market, "sign": sign, "dpm_o_pp": x[i], "gap_bp": g[i],
                         "gap_qqq_bp": 1.2 * g[i], "reason": "", "news": i in (40, 41)})
    a = tmp_path / "closures_all.csv"
    pd.DataFrame(rows).to_csv(a, index=False)
    ev = tmp_path / "events.yaml"
    ev.write_text("markets:\n  election: {market_slug: slug-e, token_id: '1', sign: 1}\n"
                  "  recession: {market_slug: slug-r, token_id: '2', sign: -1}\n")
    b = tmp_path / "results.csv"
    mk = tmp_path / "markets.json"
    if with_b:
        brows = []
        days = pd.bdate_range("2025-02-03", periods=80)
        for m in ("b1", "b2"):
            x = rng.choice([-1, 0, 1], size=79).astype(float)
            for i in range(79):
                brows.append({"market": m, "closure": days[i].strftime("%Y-%m-%d"),
                              "open_day": days[i + 1].strftime("%Y-%m-%d"), "kind": "overnight", "x_pp": x[i],
                              "gap_spy_bp": float(i), "gap_qqq_bp": float(i), "reason": ""})
        pd.DataFrame(brows).to_csv(b, index=False)
        mk.write_text(json.dumps({"candidates": [{"market_slug": "b1", "token_id": "9", "sign": 1, "question": "B1?"},
                                                 {"market_slug": "b2", "token_id": "8", "sign": -1, "question": "B2?"}]}))
    return a, ev, b, mk


def _patch(monkeypatch, tmp_path, with_b):
    a, ev, b, mk = _write_inputs(tmp_path, with_b)
    monkeypatch.setattr(run, "PANEL_A_CSV", a)
    monkeypatch.setattr(run, "PANEL_A_EVENTS", ev)
    monkeypatch.setattr(run, "PANEL_B_CSV", b)
    monkeypatch.setattr(run, "PANEL_B_MARKETS", mk)
    exp = tmp_path / "gap_rates.json"
    monkeypatch.setattr(run, "EXPORT_PATH", exp)
    return exp


def test_run_without_panel_b(tmp_path, monkeypatch):
    exp = _patch(monkeypatch, tmp_path, with_b=False)
    out = tmp_path / "out"
    assert run.main(["--out-dir", str(out)]) == 0
    for f in ("SUMMARY.md", "predictions.csv", "tests.json", "chart.png", "RUN_LOG.md"):
        assert (out / f).exists(), f
    res = json.loads((out / "tests.json").read_text())
    assert res["panel_b_available"] is False
    assert res["primary"]["SPY"]["n_test"] > 300
    assert "not available at run time" in (out / "SUMMARY.md").read_text()
    e = json.loads(exp.read_text())
    assert set(e["markets"]) == {"slug-e", "slug-r"}
    assert e["pooled"]["n"] == 376  # 380 rows minus 4 news closures
    assert e["markets"]["slug-r"]["rate_raw_bp_per_pp"] == -e["markets"]["slug-r"]["rate_bp_per_pp"]
    assert e["oos"]["verdict"] == res["primary"]["SPY"]["verdict"]
    # the primary predictions never include news closures
    pr = pd.read_csv(out / "predictions.csv")
    assert (pr["set"] == "A_placebo").sum() == 2 * res["primary"]["SPY"]["n_test"]


def test_run_with_panel_b(tmp_path, monkeypatch):
    exp = _patch(monkeypatch, tmp_path, with_b=True)
    out = tmp_path / "out"
    assert run.main(["--out-dir", str(out)]) == 0
    res = json.loads((out / "tests.json").read_text())
    assert res["panel_b_available"] is True
    pb = res["panel_b"]
    assert pb["n_markets"] == 2 and pb["n_test"] > 0
    e = json.loads(exp.read_text())
    assert {"b1", "b2"} <= set(e["markets"])
    assert e["markets"]["b2"]["sign"] == -1
