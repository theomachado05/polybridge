import pandas as pd
import pytest

import strategy_backtest.data as data
import strategy_backtest.report as report
import strategy_backtest.run as run
from polybridge_research.calendar import TradingCalendar

from .synth import A, B, bars_from, world


@pytest.fixture
def fake_world(monkeypatch, tmp_path):
    w = world(n=90, seed=11)
    bars = bars_from(w["meas"])
    daily = pd.DataFrame({"open": w["meas"]["open_px"], "close": w["meas"]["rth_close"], "volume": 5e7,
                          "vwap": w["meas"]["rth_close"]}, index=w["meas"].index)
    pa, pb = w["markets"]
    pc = {**pb, "market_slug": "mkt-c", "rank": 11, "source": "candidate"}
    monkeypatch.setattr(data, "fetch_minutes", lambda client, s, e: bars)
    monkeypatch.setattr(data, "fetch_daily", lambda client, s, e: daily)
    monkeypatch.setattr(data, "fetch_dividends", lambda client, s, e: pd.Series({w["days"][30]: 1.5}))
    monkeypatch.setattr(data, "panel_a_markets", lambda session=None: [pa])
    monkeypatch.setattr(data, "replication_markets", lambda ranks=None: [pb] if ranks is not None else [pb, pc])
    pm = dict(w["pm"])
    for (slug, key), pts in w["pm"].items():
        if slug == B:
            pm[("mkt-c", key)] = pts[:1]
    monkeypatch.setattr(data, "fetch_pm_for", lambda m, cl, session=None: {c.key: pm.get((m["market_slug"], c.key), []) for c in cl})
    r1 = pd.DataFrame({"market": "a", "closure": [d.strftime("%Y-%m-%d") for d in w["days"][40:50]],
                       "gap_bp": 0.0, "ret30_bp": 0.0, "dpm_o_pp": 0.0, "f_B": 0.1, "Y_B": 0.0, "Y0_B": 0.0})
    r1p = tmp_path / "r1.csv"
    r1.to_csv(r1p, index=False)
    monkeypatch.setattr(run, "R1_CSV", r1p)
    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path / "out")
    monkeypatch.setattr(report, "RESULTS_DIR", tmp_path / "out")
    monkeypatch.setattr(run, "DONE", tmp_path / "out" / ".done")
    return w, tmp_path / "out"


def test_end_to_end_synthetic(fake_world):
    w, out = fake_world
    log = {}
    res = run.execute(None, None, TradingCalendar(), w["days"][-1], log)
    assert log["last_session"] == w["days"][-1].strftime("%Y-%m-%d")
    assert len(res["segs"]["OOS"]) == 18
    assert set(res["coverage"]["market"]) == {A, B, "mkt-c"}
    assert not res["coverage"].set_index("market").loc["mkt-c", "v4"]
    assert res["metrics"]["book"].nunique() == 6
    assert len(res["metrics"]) == 3 * (1 + 5 * 2)
    assert res["recon"]["n"] == 10
    assert (res["trades"]["variant"] == "primary").sum() > 0
    report.write_all(res, "test")
    for f in ("SUMMARY.md", "metrics.csv", "equity_curve.png", "drawdown.png", "trades.csv", "capacity.md", "daily.csv",
              "records.csv"):
        assert (out / f).exists(), f
    s = (out / "SUMMARY.md").read_text()
    assert s.index("## Verdict") < s.index("## Primary metrics") < s.index("## Variants")
    d = pd.read_csv(out / "daily.csv")
    assert abs(d["bh"].iloc[0] - 1e6) < 1e-6


def test_second_run_refuses(fake_world, monkeypatch):
    _, out = fake_world
    out.mkdir(parents=True, exist_ok=True)
    (out / ".done").write_text("x")
    assert run.main([]) == 3
    assert "refused" in (out / "RUN_LOG.md").read_text()
