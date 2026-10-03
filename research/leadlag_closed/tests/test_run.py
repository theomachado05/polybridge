"""End-to-end with mocked HTTP: no network, no key needed."""
import json

import numpy as np
import pandas as pd
import pytest

import leadlag_closed.run as run
from leadlag_closed.closures import build_closures
from leadlag_closed.config import PANELS, TZ
from leadlag_closed.data import fetch_equity_ohlc, month_chunks


class FakeClient:
    """Minute bars for every trading day: flat RTH, a +1% jump at each open after a news-sized PM move is not modelled here."""

    def __init__(self):
        self.calls = []

    def get_all(self, path, params=None):
        self.calls.append(path)
        parts = path.split("/")
        a, b = int(parts[-2]), int(parts[-1])
        days = pd.bdate_range(pd.Timestamp(a, unit="ms").normalize(), pd.Timestamp(b, unit="ms").normalize())
        rows = []
        for d in days:
            px = 100.0
            for t in pd.date_range(f"{d.date()} 07:00", f"{d.date()} 16:00", freq="1min", inclusive="left"):
                ts = t.tz_localize(TZ).tz_convert("UTC")
                ms = int(ts.timestamp() * 1000)
                if a <= ms <= b:
                    rows.append({"t": ms, "o": px, "c": px, "v": 100})
        return rows


def test_fetch_equity_ohlc_shapes_and_dedupes():
    df = fetch_equity_ohlc(FakeClient(), "SPY", pd.Timestamp("2025-04-01", tz="UTC"), pd.Timestamp("2025-04-04", tz="UTC"))
    assert list(df.columns) == ["open", "close", "volume"] and df.index.is_monotonic_increasing and df.index.tz is not None
    empty = fetch_equity_ohlc(type("C", (), {"get_all": lambda s, p, q=None: []})(), "SPY", pd.Timestamp("2025-04-01", tz="UTC"), pd.Timestamp("2025-04-02", tz="UTC"))
    assert empty.empty


def test_month_chunks_cover_range_with_padding():
    ch = month_chunks("2025-01-10", "2025-03-05")
    assert ch[0][0] <= pd.Timestamp("2025-01-09", tz="UTC") and ch[-1][1] >= pd.Timestamp("2025-03-06", tz="UTC")
    assert len(ch) == 3


def test_plan_has_events_flagged_and_unique():
    markets, events = run.load_events()
    plan = run.plan_closures(markets, events)
    news = [p for p in plan if p["news"]]
    assert len(news) == len(events) == 17
    keys = [p["closure"].key for p in plan]
    assert len(keys) == len(set(keys))
    assert any(p["market"] == "election" and not p["news"] for p in plan)
    assert all(p["sign"] == PANELS[p["market"]]["sign"] for p in plan)
    # the 2024 election-call closure sits outside the placebo panel range but is still planned
    assert any(p["event"] == "e04-2024-11-06-election" for p in plan)


def test_collect_rows_with_mocked_http(monkeypatch):
    markets, events = run.load_events()
    plan = run.plan_closures(markets, events)[:6]

    def fake_pm(token_id, c, pm_session=None, cache_dir=None):
        t0 = int((c.nominal_close - pd.Timedelta(hours=5)).timestamp())
        t1 = int((c.nominal_open + pd.Timedelta(minutes=30)).timestamp())
        return [(t, 0.40 if t < int(c.nominal_close.timestamp()) + 600 else 0.45) for t in range(t0, t1, 60)]

    monkeypatch.setattr(run, "fetch_closure_pm", fake_pm)
    df = run.collect_rows(plan, markets, FakeClient(), None, progress=False)
    assert len(df) == 6
    ok = df[df["reason"] == ""]
    assert len(ok) >= 1
    assert np.allclose(ok["dpm_pp"], 5.0)                                  # 40 -> 45 pp
    assert np.allclose(ok["dpm_o_pp"], ok["sign"] * 5.0)
    assert np.allclose(ok["gap_bp"], 0.0)                                  # flat synthetic prices
    assert set(df.columns) >= {"news", "event", "kind", "market", "gap_qqq_bp", "ret30_bp", "resid_bp"}


def test_collect_rows_records_fetch_failure(monkeypatch):
    markets, events = run.load_events()
    plan = run.plan_closures(markets, events)[:2]

    def boom(*a, **k):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(run, "fetch_closure_pm", boom)
    df = run.collect_rows(plan, markets, FakeClient(), None, progress=False)
    assert all("fetch failed" in r for r in df["reason"])


def test_main_missing_key_exits_2_and_logs(tmp_path, monkeypatch, capsys):
    from polybridge_research import massive

    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(massive, "load_api_key", lambda **k: (_ for _ in ()).throw(massive.MissingApiKey("no key here")))
    assert run.main(["--no-charts"]) == 2
    assert "MASSIVE_API_KEY missing" in capsys.readouterr().err
    log = (tmp_path / "RUN_LOG.md").read_text()
    assert "exit: 2" in log and "no key here" in log


def test_write_all_end_to_end_on_synthetic_rows(tmp_path):
    from leadlag_closed.analysis import analyse
    from leadlag_closed.report import write_all
    from leadlag_closed.tests.test_stats import _rows

    rows = _rows(n_ev=14, n_pl=120, event_slope=10.0, seed=3)
    for col, val in (("name", "Event"), ("family", "f"), ("news_et", "2025-04-02T16:15"), ("precision", "approx"), ("open_day", "2025-04-03"),
                     ("pm_close", 30.0), ("pm_open", 33.0), ("dpm_pp", 3.0), ("gap_qqq_bp", 1.0)):
        rows[col] = val
    rows["event"] = [f"e{i:02d}-x" if n else "" for i, n in enumerate(rows["news"])]
    markets = {"recession": {}, "election": {}}
    res = analyse(rows)
    write_all(rows, res, markets, charts=True, out_dir=tmp_path)
    for f in ("SUMMARY.md", "events.csv", "tests.json", "charts/scatter_gap_vs_pm.png", "charts/events_pm_vs_gap.png", "charts/pairing_placebo.png"):
        assert (tmp_path / f).exists(), f
    text = (tmp_path / "SUMMARY.md").read_text()
    assert "Hindsight selection" in text and "Placebo" in text and res["verdict"] in text
    json.loads((tmp_path / "tests.json").read_text())
    assert "nan" not in (tmp_path / "SUMMARY.md").read_text().lower().replace("nan%", "")
