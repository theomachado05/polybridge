"""Closure windows, rows and the selection walk with fake PM and equity data (no network, no key)."""
import pandas as pd

import leadlag_replication.run as run
from leadlag_replication.closures import calendar_close, in_original_panels, market_class, market_closures, replication_row
from leadlag_replication.config import TZ
from leadlag_replication.report import write_all


def test_market_closures_respect_market_life_and_window():
    cl = market_closures("2025-12-01T00:00:00Z", "2026-03-01T00:00:00Z")
    assert cl[0].key == "2025-12-01" and cl[-1].key == "2025-12-30"           # nothing opening in 2026
    assert all(c.open_day <= pd.Timestamp("2025-12-31") for c in cl)
    cl2 = market_closures("2024-09-13T15:43:00Z", "2024-12-21T00:31:00Z")
    assert cl2[0].key == "2024-09-13" and cl2[-1].open_day == pd.Timestamp("2024-12-20")
    assert {c.kind for c in cl2} >= {"overnight", "weekend", "holiday"}


def test_calendar_close_early_days_and_panels():
    c = [c for c in market_closures("2024-11-01", "2024-12-31") if c.key == "2024-11-29"][0]
    assert calendar_close(c).tz_convert(TZ).hour == 13
    assert in_original_panels("2024-05-01") and not in_original_panels("2024-12-02") and not in_original_panels("2024-02-01")
    assert market_class({"sign_reason": "risk-off: shutdown"}) == "US macro/policy"
    assert market_class({"sign_reason": "risk-on: cease-?fire"}) == "geopolitics"


def _bars(days, jump_bp):
    """Flat 100 every RTH minute; the open of each listed day jumps by jump_bp."""
    rows = {}
    for d, j in zip(days, jump_bp):
        px = 100.0
        for t in pd.date_range(f"{d} 09:30", f"{d} 16:00", freq="1min", inclusive="left"):
            ts = t.tz_localize(TZ).tz_convert("UTC")
            rows[ts] = (px * (1 + j / 1e4), px * (1 + j / 1e4)) if t.hour == 9 and t.minute == 30 else (px, px)
    idx = pd.DatetimeIndex(sorted(rows))
    return pd.DataFrame({"open": [rows[i][0] for i in idx], "close": [rows[i][1] for i in idx], "volume": 1.0}, index=idx)


def test_replication_row_orients_and_uses_asof_quotes():
    c = [c for c in market_closures("2025-03-01", "2025-04-30") if c.key == "2025-03-04"][0]
    bars = _bars(["2025-03-04", "2025-03-05"], [0, -50])
    t_close = int(pd.Timestamp("2025-03-04 16:00", tz=TZ).timestamp())
    t_open = int(pd.Timestamp("2025-03-05 09:30", tz=TZ).timestamp())
    pts = [(t_close - 60, 0.10), (t_open - 120, 0.13), (t_open + 60, 0.50)]   # the post-open point must be ignored
    m = {"market_slug": "x", "rank": 1, "sign": -1, "sign_reason": "risk-off: invade"}
    r = replication_row(c, m, pts, {"SPY": bars, "QQQ": bars})
    assert abs(r["dpm_pp"] - 3.0) < 1e-9 and abs(r["x_pp"] + 3.0) < 1e-9
    assert abs(r["gap_spy_bp"] + 50) < 1e-6 and r["reason"] == ""
    stale = replication_row(c, m, [(t_close - 3 * 3600, 0.1)], {"SPY": bars})
    assert stale["reason"] == "no PM quote"


def test_select_markets_walks_ranking_until_n_qualify(tmp_path):
    cands = [{"rank": i, "market_slug": f"m{i}", "token_id": f"t{i}", "sign": 1, "sign_reason": "risk-on: truce",
              "start": "2025-01-01T00:00:00Z", "end": "2025-06-30T00:00:00Z"} for i in (1, 2, 3, 4)]

    def fake_pm(token, closures, session=None):
        if token == "t2":                       # no quotes -> fails coverage
            return {c.key: [] for c in closures}
        out = {}
        for c in closures:
            a, b = int(calendar_close(c).timestamp()), int(c.nominal_open.timestamp())
            out[c.key] = [(a - 60, 0.2), (b - 60, 0.21)]
        return out

    sel, cov = run.select_markets(cands, None, n=2, fetch_pm=fake_pm, progress=False)
    assert [s["market"]["market_slug"] for s in sel] == ["m1", "m3"]
    assert list(cov["qualifies"]) == [True, False, True]       # m4 never examined

    days = sorted({d for s in sel for c in s["closures"] for d in (c.close_day, c.open_day)})
    bars = _bars([d.strftime("%Y-%m-%d") for d in days], [10] * len(days))
    rows = run.collect_rows(sel, {"SPY": bars, "QQQ": bars, "IWM": bars})
    assert len(rows) == sum(len(s["closures"]) for s in sel) and (rows["reason"] == "").all()
    from leadlag_replication.analysis import analyse
    res = analyse(rows, n_perm_secondary=50)
    write_all(rows, res, cov, out_dir=tmp_path)
    assert (tmp_path / "SUMMARY.md").exists() and (tmp_path / "chart.png").exists() and (tmp_path / "tests.json").exists()
