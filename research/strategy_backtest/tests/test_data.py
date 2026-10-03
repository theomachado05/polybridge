import pandas as pd

from strategy_backtest import data


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def get_all(self, path, params=None):
        return self.rows(path, params)


def _ms(s):
    return int(pd.Timestamp(s, tz="America/New_York").timestamp() * 1000)


def test_fetch_daily_indexes_by_et_date():
    rows = [{"t": _ms("2024-01-02 00:00"), "o": 1.0, "c": 2.0, "v": 10.0, "vw": 1.5},
            {"t": _ms("2024-01-03 00:00"), "o": 2.0, "c": 3.0, "v": 11.0, "vw": 2.5}]
    d = data.fetch_daily(FakeClient(lambda p, q: rows), "2024-01-02", "2024-01-03")
    assert list(d.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert list(d["close"]) == [2.0, 3.0] and list(d["vwap"]) == [1.5, 2.5]


def test_fetch_minutes_dedups_chunks():
    rows = [{"t": _ms("2024-01-31 10:00"), "o": 1.0, "c": 2.0, "v": 3.0}]
    m = data.fetch_minutes(FakeClient(lambda p, q: rows), "2024-01-02", "2024-02-10")
    assert len(m) == 1 and m.index.tz is not None
    assert list(m.columns) == ["open", "close", "volume"]


def test_fetch_dividends_cash_only():
    rows = [{"ex_dividend_date": "2024-03-15", "cash_amount": 1.6, "dividend_type": "CD"},
            {"ex_dividend_date": "2024-06-21", "cash_amount": 9.0, "dividend_type": "SC"}]
    s = data.fetch_dividends(FakeClient(lambda p, q: rows), "2024-01-02", "2024-12-31")
    assert s.to_dict() == {pd.Timestamp("2024-03-15"): 1.6}


def test_panel_a_markets_from_cached_metadata(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    (tmp_path / "gamma").mkdir()
    for slug in ("will-donald-trump-win-the-2024-us-presidential-election", "us-recession-in-2025"):
        (tmp_path / "gamma" / f"{slug}.json").write_text(json.dumps(
            {"startDate": "2024-01-04T22:58:00Z", "closedTime": "2024-11-07 15:38:41+00", "endDate": "2024-11-05T12:00:00Z",
             "closed": True}))
    ms = data.panel_a_markets()
    assert {m["label"] for m in ms} == {"election", "recession"}
    assert all(m["end"].startswith("2024-11-07T15:38:41") for m in ms)
