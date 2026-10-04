"""Selection walk, rows, the key gate and the .done marker with fake PM and equity data (no network, no key)."""
import json

import pandas as pd

import macro_panel.run as run
from macro_panel.closures import calendar_close, fresh_date, market_closures, panel_row, window_closures
from macro_panel.config import TZ


def _bars(days, jump_bp):
    rows = {}
    for d, j in zip(days, jump_bp):
        for t in pd.date_range(f"{d} 09:30", f"{d} 16:00", freq="1min", inclusive="left"):
            ts = t.tz_localize(TZ).tz_convert("UTC")
            rows[ts] = (100 * (1 + j / 1e4),) * 2 if t.hour == 9 and t.minute == 30 else (100.0, 100.0)
    idx = pd.DatetimeIndex(sorted(rows))
    return pd.DataFrame({"open": [rows[i][0] for i in idx], "close": [rows[i][1] for i in idx], "volume": 1.0}, index=idx)


def test_window_and_closures():
    cl = window_closures()
    assert cl[0].key == "2023-01-03" and cl[-1].key == "2025-12-30"
    assert all(c.open_day <= pd.Timestamp("2025-12-31") for c in cl)
    c = [c for c in cl if c.key == "2023-11-24"][0]
    assert calendar_close(c).tz_convert(TZ).hour == 13
    assert fresh_date("2023-06-01") and not fresh_date("2024-06-03")
    m = market_closures("2023-03-01T00:00:00Z", "2023-03-31T00:00:00Z", cl)
    assert m[0].key == "2023-03-01" and m[-1].open_day <= pd.Timestamp("2023-03-31")


def test_panel_row_orients_and_ignores_post_open_points():
    c = [c for c in window_closures() if c.key == "2023-03-07"][0]
    bars = _bars(["2023-03-07", "2023-03-08"], [0, -40])
    tc, to = int(pd.Timestamp("2023-03-07 16:00", tz=TZ).timestamp()), int(pd.Timestamp("2023-03-08 09:30", tz=TZ).timestamp())
    pts = [(tc - 60, 0.30), (to - 120, 0.34), (to + 60, 0.90)]
    r = panel_row(c, {"market_slug": "x", "rank": 1, "sign": 1, "cls": "fed"}, pts, bars)
    assert abs(r["x_pp"] - 4.0) < 1e-9 and abs(r["gap_spy_bp"] + 40) < 1e-6 and r["reason"] == "" and r["fresh_date"]
    assert run.trim(pts, c) == pts[:2]


def _cands():
    out = []
    for i in range(1, 15):
        cls = "fed" if i <= 12 else "recession"
        out.append({"rank": i, "market_slug": f"m{i}", "token_id": f"t{i}", "sign": 1, "cls": cls, "sign_reason": "",
                    "start": "2023-02-01T00:00:00Z", "end": "2023-04-28T00:00:00Z"})
    return out


def _fake_pm(token, closures, session=None):
    if token == "t2":
        return {c.key: [] for c in closures}
    out = {}
    for c in closures:
        a, b = int(calendar_close(c).timestamp()), int(c.nominal_open.timestamp())
        out[c.key] = [(a - 60, 0.2), (b - 60, 0.2 + 0.01 * (hash(c.key) % 3 - 1)), (b + 600, 0.5)]
    return out


def test_select_markets_class_cap_and_coverage():
    sel, cov = run.select_markets(_cands(), None, fetch_pm=_fake_pm, progress=False)
    names = [s["market"]["market_slug"] for s in sel]
    assert "m2" not in names and sum(s["market"]["cls"] == "fed" for s in sel) == 10
    assert names[-2:] == ["m13", "m14"] and "m12" not in names
    assert list(cov["market"]).count("m12") == 0


def test_main_gates_key_and_done(tmp_path):
    mp = tmp_path / "markets.json"
    mp.write_text(json.dumps({"snapshot_utc": "x", "n_pool_events": 1, "candidates": _cands()}))
    out = tmp_path / "res"
    assert run.main([], load_key=lambda: None, fetch_pm=_fake_pm, markets_path=mp, results_dir=out) == 2
    assert (out / "coverage.csv").exists() and not (out / ".done").exists()
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2023-01-30", "2023-05-02")]
    bars = _bars(days, [5] * len(days))
    rc = run.main([], load_key=lambda: "k", fetch_pm=_fake_pm, fetch_bars=lambda a, b: bars, markets_path=mp, results_dir=out)
    assert rc == 0 and (out / ".done").exists() and (out / "SUMMARY.md").exists() and (out / "chart.png").exists()
    assert run.main([], load_key=lambda: "k", fetch_pm=_fake_pm, fetch_bars=lambda a, b: bars, markets_path=mp, results_dir=out) == 3
    assert run.main(["--reuse-csv"], markets_path=mp, results_dir=out) == 0
    assert "stage reached: equity" in (out / "RUN_LOG.md").read_text()
