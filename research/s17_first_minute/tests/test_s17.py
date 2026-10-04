import numpy as np
import pandas as pd

from s17_first_minute import config as cfg
from s17_first_minute.run import at_et, day_prices, events, trade_return, valid, window_returns


def _sess():
    return pd.DataFrame({"day": ["2026-03-02", "2026-03-03"],
                         "open": [at_et("2026-03-02", "09:30"), at_et("2026-03-03", "09:30")],
                         "close": [at_et("2026-03-02", "16:00"), at_et("2026-03-03", "16:00")]})


def _bar(day, hhmm, o, c):
    return {"t": at_et(day, hhmm) * 1000, "o": o, "c": c}


def test_day_prices_regular_session_only():
    raw = [_bar("2026-03-02", "15:59", 99, 100), _bar("2026-03-02", "16:05", 100, 150),   # after hours: ignored
           _bar("2026-03-03", "09:00", 100, 140),                                          # pre-market: ignored
           _bar("2026-03-03", "09:30", 102, 103), _bar("2026-03-03", "09:34", 104, 105),
           _bar("2026-03-03", "09:59", 106, 107), _bar("2026-03-03", "15:54", 108, 109), _bar("2026-03-03", "15:59", 110, 111)]
    p = day_prices(raw, "2026-03-02", "2026-03-03", _sess())
    assert p["prev_close"] == 100 and p["open"] == 102
    assert p["09:31"] == 103            # close of the 09:30 bar
    assert p["09:35"] == 105            # close of the 09:34 bar
    assert p["10:00"] == 107 and p["15:55"] == 109 and p["close"] == 111


def test_day_prices_drops_late_first_bar():
    raw = [_bar("2026-03-02", "15:59", 99, 100), _bar("2026-03-03", "09:33", 102, 103)]
    assert day_prices(raw, "2026-03-02", "2026-03-03", _sess()) is None


def test_window_returns_signed_excess():
    px = {"prev_close": 100, "open": 102, "09:31": 103, "09:35": 103, "10:00": 103, "close": 103}
    sp = {"prev_close": 100, "open": 101, "09:31": 101, "09:35": 101, "10:00": 101, "close": 101}
    w = window_returns(px, sp, beta=2.0, d=-1)
    assert np.isclose(w["gap"], -1e4 * (0.02 - 2 * 0.01))
    assert np.isclose(w["open_0931"], -1e4 * (103 / 102 - 1))
    assert np.isclose(w["gap_raw"], -200)


def test_trade_return_costs_and_side():
    qi, qo = {"bid": 99.9, "ask": 100.1}, {"bid": 100.9, "ask": 101.1}
    r = trade_return(qi, qo, 1, 1.0)
    assert np.isclose(r["net_bp"], 1e4 * (100.9 - 100.1) / 100.1)
    assert np.isclose(r["gross_bp"], 100.0)
    s = trade_return(qi, qo, -1, 2.0)        # short at bid - extra half, cover at ask + extra half
    assert np.isclose(s["net_bp"], -1e4 * (101.2 - 99.8) / 99.8)


def test_quote_validity():
    at = at_et("2026-03-03", "09:31")
    ok = {"bid": 100.0, "ask": 100.05, "ts": at - 5}
    assert valid(ok, at, "2026-03-03")
    assert not valid({**ok, "ts": at - 200}, at, "2026-03-03")                  # stale
    assert not valid({**ok, "ts": at_et("2026-03-03", "09:29")}, at, "2026-03-03")  # before the open
    assert not valid({**ok, "ask": 102.0}, at, "2026-03-03")                    # spread above 100 bp
    assert not valid(None, at, "2026-03-03")


def test_events_match_s16_counts():
    e = events(cfg.MAIN_THRESHOLD)
    assert len(e) == 300 and e.day.nunique() == 109 and (e.segment == "OOS").sum() == 54
    assert not e.duplicated(["day", "ticker"]).any()
    assert set(e.d.unique()) <= {-1, 1}
