import numpy as np
import pandas as pd
import pytest

from leadlag_closed.closures import (Closure, build_closures, closure_for_news, closure_kind, closure_row, equity_measures,
                                     load_events, pm_at, rth_bars)
from leadlag_closed.config import PANELS, TZ


def _bars(day_close: str, day_open: str, close_px=100.0, open_px=101.0, early=False, with_open=True, with_0959=True, with_0800=True):
    """Synthetic minute bars: RTH of close_day (09:30-16:00 or -13:00), pre-market of open_day, RTH start of open_day."""
    rows = {}

    def put(ts_et, o, c):
        rows[pd.Timestamp(ts_et, tz=TZ).tz_convert("UTC")] = (o, c, 1000.0)

    end = "13:00" if early else "16:00"
    for t in pd.date_range(f"{day_close} 09:30", f"{day_close} {end}", freq="1min", inclusive="left"):
        put(t, close_px, close_px)
    if with_0800:
        put(f"{day_open} 07:59", 100.5, 100.5)  # bar ending 08:00
    if with_open:
        for t in pd.date_range(f"{day_open} 09:30", f"{day_open} 10:05", freq="1min"):
            if t.strftime("%H:%M") == "09:59" and not with_0959:
                continue
            put(t, open_px, open_px + 0.5 if t.strftime("%H:%M") >= "09:59" else open_px)
    df = pd.DataFrame.from_dict(rows, orient="index", columns=["open", "close", "volume"]).sort_index()
    df.index = pd.DatetimeIndex(df.index)
    return df


def test_kinds_and_calendar():
    cl = {c.key: c for c in build_closures("2025-04-01", "2025-04-30")}
    assert cl["2025-04-02"].kind == "overnight"
    assert cl["2025-04-04"].kind == "weekend"
    assert cl["2025-04-17"].kind == "holiday"   # Thursday before Good Friday
    cl2 = {c.key: c for c in build_closures("2025-05-20", "2025-05-31")}
    assert cl2["2025-05-23"].kind == "holiday"  # Friday before Memorial Day
    assert closure_kind(pd.Timestamp("2025-03-07"), pd.Timestamp("2025-03-10")) == "weekend"


def test_closure_for_news_boundaries():
    cl = build_closures("2025-04-01", "2025-04-10")
    assert closure_for_news("2025-04-02T16:15", cl).key == "2025-04-02"    # just after the close
    assert closure_for_news("2025-04-02T16:00", cl).key == "2025-04-02"    # exactly at the close counts
    assert closure_for_news("2025-04-06T18:00", cl).key == "2025-04-04"    # Sunday belongs to the Friday closure
    assert closure_for_news("2025-04-03T11:00", cl) is None                # RTH is not a closure
    assert closure_for_news("2025-04-03T09:30", cl) is None                # the open instant is RTH


def test_event_list_is_consistent():
    markets, events = load_events()
    pool = build_closures("2024-03-01", "2025-12-31")
    keys = []
    for e in events:
        c = closure_for_news(e["news_et"], pool)
        assert c is not None, e["id"]
        keys.append(c.key)
        assert e["market"] in markets
        assert e["precision"]
    assert len(set(keys)) == len(keys), "two events share a closure"
    assert len(events) == 17
    for m in markets.values():
        assert m["sign"] in (-1, 1) and m["token_id"] and m["volume_usd"] > 1e7
    assert {m: markets[m]["sign"] for m in markets} == {k: v["sign"] for k, v in PANELS.items()}


def test_equity_measures_normal_and_missing():
    c = Closure(pd.Timestamp("2025-04-02"), pd.Timestamp("2025-04-03"), "overnight")
    m = equity_measures(_bars("2025-04-02", "2025-04-03"), c)
    assert m["gap_bp"] == pytest.approx(100.0)                      # 101 / 100 - 1 = 1% = 100 bp
    assert m["ret30_bp"] == pytest.approx(1e4 * (101.5 / 101 - 1))  # close of the 09:59 bar
    assert m["px_0800"] == pytest.approx(100.5)
    assert m["resid_bp"] == pytest.approx(1e4 * (101 / 100.5 - 1))
    assert m["t_close"] == pd.Timestamp("2025-04-02 16:00", tz=TZ).tz_convert("UTC")
    m2 = equity_measures(_bars("2025-04-02", "2025-04-03", with_open=False), c)
    assert np.isnan(m2["gap_bp"]) and np.isnan(m2["ret30_bp"])
    m3 = equity_measures(_bars("2025-04-02", "2025-04-03", with_0959=False, with_0800=False), c)
    assert m3["gap_bp"] == pytest.approx(100.0) and np.isnan(m3["ret30_bp"]) and np.isnan(m3["resid_bp"])


def test_early_close_uses_last_bar_present():
    c = Closure(pd.Timestamp("2025-11-26"), pd.Timestamp("2025-11-28"), "holiday")  # illustrative: 13:00 close
    b = _bars("2025-11-26", "2025-11-28", early=True)
    m = equity_measures(b, c)
    assert m["t_close"] == pd.Timestamp("2025-11-26 13:00", tz=TZ).tz_convert("UTC")


def test_late_open_bar_rejected():
    c = Closure(pd.Timestamp("2025-04-02"), pd.Timestamp("2025-04-03"), "overnight")
    b = _bars("2025-04-02", "2025-04-03")
    b = b[b.index >= pd.Timestamp("2025-04-03 09:36", tz=TZ).tz_convert("UTC")].combine_first(b[b.index < pd.Timestamp("2025-04-03 09:30", tz=TZ).tz_convert("UTC")])
    assert np.isnan(equity_measures(b, c)["gap_bp"])               # first RTH bar starts 6 min after 09:30


def test_rth_bars_ignores_extended_hours():
    b = _bars("2025-04-02", "2025-04-03")
    day = pd.Timestamp("2025-04-03")
    r = rth_bars(b, day)
    assert r.index[0] == pd.Timestamp("2025-04-03 09:30", tz=TZ).tz_convert("UTC")
    assert len(rth_bars(b, pd.Timestamp("2025-04-02"))) == 390


def test_pm_at_staleness_and_no_lookahead():
    t = pd.Timestamp("2025-04-02 20:00", tz="UTC")
    ts = int(t.timestamp())
    pts = [(ts - 3600, 0.50), (ts - 120, 0.40), (ts + 60, 0.99)]
    assert pm_at(pts, t) == pytest.approx(40.0)                      # last point at or before t; the future point is ignored
    assert np.isnan(pm_at([(ts - 3600, 0.5)], t))                    # older than 30 min: no quote
    assert pm_at([(ts - 3600, 0.5)], t, stale_min=90) == pytest.approx(50.0)
    assert np.isnan(pm_at([], t))


def test_closure_row_orientation_and_reasons():
    c = Closure(pd.Timestamp("2025-04-02"), pd.Timestamp("2025-04-03"), "overnight")
    b = _bars("2025-04-02", "2025-04-03")
    t_close, t_open = c.nominal_close, c.nominal_open
    pts = [(int(t_close.timestamp()) - 10, 0.30), (int(t_open.timestamp()) - 10, 0.40)]
    r = closure_row(c, b, b, pts, -1, "recession")
    assert r["dpm_pp"] == pytest.approx(10.0) and r["dpm_o_pp"] == pytest.approx(-10.0)
    assert r["gap_bp"] > 0 and r["reason"] == ""
    r2 = closure_row(c, b, None, [], -1, "recession")
    assert r2["reason"] == "no PM quote"
    r3 = closure_row(c, b.iloc[0:0], None, pts, -1, "recession")
    assert r3["reason"] == "no equity bar"
