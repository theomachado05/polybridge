from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from overshoot import analysis, run
from overshoot.config import COLUMNS, Params

P = Params(draws=300)


def fake_events(n_closures: int = 10, per: int = 5, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_closures):
        for j in range(per):
            s = 1 if (c + j) % 2 == 0 else -1
            pc, oc = 0.5, 0.5
            po = pc + s * 0.10
            oo = oc + s * 0.04
            pe = po - s * 0.025
            oe = oo + s * 0.01
            y = int(rng.random() < oo)
            rows.append(dict(market_id=f"m{c}-{j}", question="q", underlying="SPY", kind="daily", outcome=y,
                             closure=f"2026-0{1 + c % 9}-{10 + c}", status="event", pm_close=pc, pm_open=po,
                             pm_0945=po, pm_eod=pe, prints_in_closure=True, oc_mid=oc, oo_mid=oo, oe_mid=oe))
    rows.append(dict(rows[0], market_id="x", status="f3_move_below_3pt"))
    return pd.DataFrame(rows)[list(COLUMNS)]


def write(tmp_path, df):
    p = tmp_path / "events.csv"
    df.to_csv(p, index=False)
    return p


def test_load_keeps_events_only(tmp_path):
    e = analysis.load(write(tmp_path, fake_events()))
    assert len(e) == 50 and e["prints"].all()


def test_load_stops_on_missing_column(tmp_path):
    with pytest.raises(SystemExit):
        analysis.load(write(tmp_path, fake_events().drop(columns=["pm_eod"])))


def test_decomposition_identity_and_shares(tmp_path):
    e = analysis.load(write(tmp_path, fake_events()))
    p = analysis.decompose(e)
    assert np.allclose(p["G"], 0.06) and np.allclose(p["R"], 0.025) and np.allclose(p["F"], 0.01) and np.allclose(p["L"], 0.025)
    st = analysis.decomp_stats(e, params=P)
    assert st["share_R"]["value"] == pytest.approx(0.025 / 0.06)
    assert st["share_F"]["value"] == pytest.approx(1 / 6)
    assert st["beta_open"]["beta"] == pytest.approx(0.4)
    assert st["beta_perm"]["beta"] == pytest.approx(0.04 / 0.075)
    v = analysis.verdict_a(st, P)
    assert v["overshoot"] and not v["majority"] and v["lag"] and v["persists"]
    assert v["label"] == "OVERSHOOT-PARTIAL / LAG-SHOWN"


def test_majority_rule(tmp_path):
    df = fake_events()
    s = np.sign(df["pm_open"] - df["pm_close"])
    df["pm_eod"] = df["pm_open"] - s * 0.05
    df["oe_mid"] = df["oo_mid"]
    st = analysis.decomp_stats(analysis.load(write(tmp_path, df)), params=P)
    assert st["share_R"]["value"] == pytest.approx(5 / 6)
    assert analysis.verdict_a(st, P)["label"] == "OVERSHOOT-MAJORITY / NO-LAG-SHOWN"


def test_small_sample():
    e = fake_events(n_closures=3)
    e = e[e["status"] == "event"].assign(prints=True)
    assert analysis.verdict_a(analysis.decomp_stats(e, params=P), P)["label"] == "SAMPLE-TOO-SMALL"
    assert analysis.verdict_b(analysis.pair_stats(e, "pm_open", "oo_mid", P), P) == "SAMPLE-TOO-SMALL"


def test_scores():
    assert analysis.brier([0.8], [1])[0] == pytest.approx(0.04)
    assert analysis.log_score([1.0], [0])[0] == pytest.approx(-np.log(0.01))
    assert analysis.log_score([0.25], [1])[0] == pytest.approx(-np.log(0.25))


def test_forecast_verdict_options_better(tmp_path):
    df = fake_events(n_closures=20, per=6)
    rng = np.random.default_rng(3)
    y = rng.integers(0, 2, len(df))
    df["outcome"] = y
    df["oo_mid"] = np.where(y == 1, 0.8, 0.2)
    df["pm_open"] = 0.5 + np.where(df.index % 2 == 0, 0.1, -0.1)
    st = analysis.pair_stats(analysis.load(write(tmp_path, df)), "pm_open", "oo_mid", P)
    assert st["brier"]["d"]["mean"] > 0
    assert analysis.verdict_b(st, P) == "OPTIONS-BETTER"
    df["pm_open"], df["oo_mid"] = df["oo_mid"], df["pm_open"]
    st = analysis.pair_stats(analysis.load(write(tmp_path, df)), "pm_open", "oo_mid", P)
    assert analysis.verdict_b(st, P) == "PM-BETTER"


def test_forecast_verdict_no_difference():
    st = {"n": 100, "clusters": 20, "brier": {"d": {"ci": [-0.01, 0.01]}}, "log": {"d": {"ci": [-0.02, 0.03]}}}
    assert analysis.verdict_b(st, P) == "NO-DIFFERENCE-SHOWN"
    st["brier"]["d"]["ci"] = [0.001, 0.02]
    assert analysis.verdict_b(st, P) == "MIXED"


def test_lpm_recovers_coefficients():
    rng = np.random.default_rng(0)
    n = 400
    X = rng.random((n, 2))
    y = 0.1 + 0.3 * X[:, 0] + 0.5 * X[:, 1]
    r = analysis.Boot(np.repeat(np.arange(40), 10), P).lpm(X, y)
    assert r["coef"] == pytest.approx([0.1, 0.3, 0.5])
    assert r["ci"][1][0] == pytest.approx(0.3, abs=1e-6)


def test_run_writes_outputs_and_refuses_second_run(tmp_path):
    p = write(tmp_path, fake_events())
    out = tmp_path / "out"
    st = run.run(p, out, P)
    assert (out / ".done").exists() and (out / "SUMMARY.md").exists() and (out / "decomposition.png").exists()
    js = json.loads((out / "stats.json").read_text())
    assert js["decomposition"]["n"] == 50 and st["verdict_a"]["label"].startswith("OVERSHOOT")
    assert "re-analysis" in (out / "SUMMARY.md").read_text()
    with pytest.raises(SystemExit):
        run.run(p, out, P)
