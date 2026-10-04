"""S20: the window clock, the two inclusion rules, the observation per market and side, the reach of a window, the scopes and the tests."""
import numpy as np
import pandas as pd
import pytest

from s20_closed_vs_open import config as cfg
from s20_closed_vs_open import pull, run
from s20_closed_vs_open import windows as wn

H = 3600.0


def _calendar():
    """Two weeks of sessions, Monday 2026-03-09 to Friday 2026-03-20, with Wednesday the 18th missing (a holiday) and one early close."""
    days = ["2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-16", "2026-03-17", "2026-03-19", "2026-03-20"]
    opens = np.array([wn.at_et(d, "09:30") for d in days])
    close = opens + 6.5 * H
    close[2] = opens[2] + 3.5 * H + 300          # an early close, as the calendar on disk records it (13:05)
    sess = pd.DataFrame({"day": days, "open": opens, "close": close})
    cal = [{"start": wn.at_et("2026-03-06", "20:00")}, {"start": wn.at_et("2026-03-13", "20:00")}]
    return sess, cal


def test_w2_is_the_next_weekend_and_d1_the_sessions_between():
    sess, cal = _calendar()
    starts, spans = wn.weekend_starts(cal, sess), wn.session_spans(sess)
    assert list(starts) == [wn.at_et("2026-03-06", "20:00"), wn.at_et("2026-03-13", "20:00"), wn.at_et("2026-03-20", "20:00")]   # the last one is added
    entry = wn.at_et("2026-03-06", "20:00")
    w = wn.market_windows(entry, starts, spans)
    assert w["W1"] == [(entry, entry + 48 * H)]
    assert w["W2"] == [(wn.at_et("2026-03-13", "20:00"), wn.at_et("2026-03-13", "20:00") + 48 * H)]
    assert w["W2"][0][0] - entry == 7 * 24 * H - H                    # the clocks moved forward on 8 March: one hour short of a week
    assert [a for a, _ in w["D1"]] == [wn.at_et(d, "09:30") for d in ("2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13")]
    assert w["D1"][0][1] == wn.at_et("2026-03-09", "16:00") and w["D1"][1][1] == wn.at_et("2026-03-10", "13:00")      # the early close ends at 13:00
    four = wn.market_windows(wn.at_et("2026-03-13", "20:00"), starts, spans)
    assert len(four["D1"]) == 4 and four["W2"][0][0] == wn.at_et("2026-03-20", "20:00")                              # a holiday week has four sessions
    last = wn.market_windows(wn.at_et("2026-03-20", "20:00"), starts, spans)
    assert last["D1"] == [] and last["W2"] == []


def test_only_session_hours_are_inside_d1():
    sess, cal = _calendar()
    w = wn.market_windows(wn.at_et("2026-03-06", "20:00"), wn.weekend_starts(cal, sess), wn.session_spans(sess))
    assert wn.inside(wn.at_et("2026-03-09", "09:30"), w["D1"]) and wn.inside(wn.at_et("2026-03-09", "16:00"), w["D1"])
    assert not wn.inside(wn.at_et("2026-03-09", "09:29"), w["D1"]) and not wn.inside(wn.at_et("2026-03-09", "20:00"), w["D1"])
    assert not wn.inside(wn.at_et("2026-03-10", "14:00"), w["D1"])                                                   # after the early close
    assert not wn.inside(wn.at_et("2026-03-14", "12:00"), w["D1"]) and wn.inside(wn.at_et("2026-03-14", "12:00"), w["W2"])


def test_rule_a_needs_the_result_after_the_window_and_rule_b_after_its_start():
    spans, now = [(100.0, 200.0), (300.0, 400.0)], 1000.0
    assert wn.status("A", spans, 401.0, now) == "in" and wn.status("A", spans, 400.0, now) == "resolved before or during the window"
    assert wn.status("A", spans, 350.0, now) == "resolved before or during the window" and wn.status("B", spans, 350.0, now) == "in"
    assert wn.status("B", spans, 100.0, now) == "resolved before the window"
    assert wn.status("B", spans, 350.0, 399.0) == "window not over at the pull" and wn.status("A", [], 350.0, now) == "no window in the calendar"


def test_observation_is_s18s_formula_per_side_with_the_fee_once_and_doubled():
    raw = [{"outcome": "Yes", "side": "BUY", "price": 0.40, "size": 10, "timestamp": 1}, {"outcome": "Yes", "side": "BUY", "price": 0.60, "size": 30, "timestamp": 2},
           {"outcome": "No", "side": "BUY", "price": 0.70, "size": 5, "timestamp": 3},      # buying NO at 0.70 is selling YES at 0.30
           {"outcome": "Yes", "side": "SELL", "price": 0.50, "size": 15, "timestamp": 4}]
    o = run.observe(raw, 0.04, 1.0, 1.0)
    assert o["buy_prints"] == 2 and o["buy_size"] == 40 and o["buy_price"] == pytest.approx(0.55)
    assert o["buy_pnl_points"] == pytest.approx(100 * (1.0 - 0.55 - 0.04 * 0.55 * 0.45))
    assert o["buy_pnl_points_2x_fee"] == pytest.approx(100 * (1.0 - 0.55 - 0.08 * 0.55 * 0.45))
    assert o["sell_prints"] == 2 and o["sell_price"] == pytest.approx(0.45)
    assert o["sell_pnl_points"] == pytest.approx(100 * (0.45 - 0.04 * 0.45 * 0.55 - 1.0))
    none = run.observe([], 0.04, 1.0, 0.0)
    assert none["prints_in_window"] == 0 and np.isnan(none["buy_pnl_points"]) and np.isnan(none["sell_pnl_points"])
    assert run.observe(raw, 0.0, 1.0, 0.0)["sell_pnl_points"] == pytest.approx(45.0)


def test_a_window_beyond_the_prints_the_api_keeps_is_left_out():
    assert run.reach_w1(None, 100.0) == run.NO_FILE and run.reach_w1({"reach_oldest": None, "served": 0}, 100.0) == run.NOT_SERVED
    assert run.reach_w1({"reach_oldest": 150.0, "served": 20000}, 100.0) == run.BEYOND and run.reach_w1({"reach_oldest": 150.0, "served": 19999}, 100.0) == run.OK
    assert run.reach_later({"reach_oldest": 150.0, "served": 20000}, 100.0) == run.BEYOND and run.reach_later({"reach_oldest": 90.0, "served": 20000}, 100.0) == run.OK
    assert run.reach_later({"reach_oldest": 150.0, "served": 10000}, 100.0) == run.BEYOND      # a full page and nothing older: not known to be everything
    assert run.reach_later({"reach_oldest": 150.0, "served": 137}, 100.0) == run.OK             # a short page: every print of the market was served
    assert run.reach_later({"reach_oldest": None, "served": 0}, 100.0) == run.NOT_SERVED


def test_the_pull_keeps_only_prints_inside_d1_and_w2():
    w = {"W1": [(0.0, 10.0)], "D1": [(20.0, 30.0), (40.0, 50.0)], "W2": [(60.0, 70.0)]}
    raw = [{"timestamp": t, "price": 0.5, "side": "BUY", "outcome": "Yes", "size": 1, "name": "dropped"} for t in (5, 20, 35, 45, 65, 80)]
    rec = pull.split(raw, w)
    assert [p["timestamp"] for p in rec["d1"]] == [20, 45] and [p["timestamp"] for p in rec["w2"]] == [65]
    assert rec["reach_oldest"] == 5 and rec["served"] == 6 and set(rec["d1"][0]) == set(pull.KEEP)
    assert pull.split([], w) == {"reach_oldest": None, "served": 0, "d1": [], "w2": []}


def test_scopes_follow_s18s_buckets_and_the_two_asset_groups():
    d = pd.DataFrame({"group": ["stocks and S&P 500", "commodities", "commodities", "stocks and S&P 500"], "segment": ["IS", "IS", "OOS", "OOS"]})
    price = pd.Series([0.01, 0.10, 0.60, 0.98])
    assert list(run.in_scope(d, run.ALL, price)) == [True] * 4
    assert list(run.in_scope(d, run.RANGE, price)) == [False, True, True, False]              # S18's buckets are closed below and open above
    assert list(run.in_scope(d, "traded price 10 to 25%", price)) == [False, True, False, False]
    assert list(run.in_scope(d, "traded price 50 to 75%", price)) == [False, False, True, False]
    assert list(run.in_scope(d, "commodities", price)) == [False, True, True, False]
    assert list(run.in_scope(d, "out-of-sample events", price)) == [False, False, True, True]
    assert run.group_of("sp500") == "stocks and S&P 500" and run.group_of("natgas") == "commodities"
    assert len(run.SCOPES) == 12 and len(run.BUCKET_NAMES) == len(cfg.BUCKETS)


def _frame():
    """Six events, one market each, in W1 and D1 under rule B. Buyers pay 10 points more in W1 than in D1; one market has no D1 buy."""
    rows = []
    for i in range(6):
        out, base = float(i % 2), 0.30 + 0.05 * i
        for w, px in (("W1", base + 0.10), ("D1", base), ("W2", base)):
            has = not (w == "D1" and i == 5)
            rows.append({"rule": "B", "window": w, "status": "in", "market": f"m{i}", "event": i, "segment": "IS" if i < 4 else "OOS", "group": "commodities",
                         "outcome": out, "buy_price": px if has else np.nan, "buy_size": 10.0, "buy_pnl_points": 100 * (out - px) if has else np.nan,
                         "buy_pnl_points_2x_fee": 100 * (out - px) if has else np.nan, "sell_price": px - 0.02, "sell_size": 10.0,
                         "sell_pnl_points": 100 * (px - 0.02 - out), "sell_pnl_points_2x_fee": 100 * (px - 0.02 - out)})
    return pd.DataFrame(rows)


def test_t1_is_the_difference_of_means_and_t3_the_paired_price_difference():
    t = run.tests(_frame(), "B")

    def get(kind, side, windows, scope=run.ALL, fee=1.0):
        return next(r for r in t if r["kind"] == kind and r["side"] == side and r["windows"] == windows and r["scope"] == scope and (kind == "path" or r["fee_mult"] == fee))

    w1, d1 = get("level", "buy", "W1"), get("level", "buy", "D1")
    assert w1["markets"] == 6 and d1["markets"] == 5 and d1["events"] == 5
    t1 = get("difference", "buy", "W1-D1")
    assert t1["test"].startswith("T1 buyers") and t1["estimate"] == pytest.approx(w1["estimate"] - d1["estimate"]) and t1["markets_b"] == 5
    t3 = get("path", "buy", "W1-D1")
    assert t3["markets"] == 5 and t3["estimate"] == pytest.approx(10.0) and t3["ci_lo"] == pytest.approx(10.0)       # only markets with buys in both windows
    assert get("path", "buy", "W2-D1")["estimate"] == pytest.approx(0.0)
    assert get("path", "sell", "W1-D1")["markets"] == 6 and get("path", "sell", "W1-D1")["estimate"] == pytest.approx(10.0)
    oos = get("path", "buy", "W1-D1", "out-of-sample events")
    assert oos["markets"] == 1 and np.isnan(oos["ci_lo"])                                                            # fewer than five events: no interval
    assert get("difference", "buy", "W1-W2")["test"].startswith("T2 buyers") and get("difference", "buy", "W2-D1")["test"].startswith("T2 buyers")


def test_a_market_left_out_of_a_window_never_enters_a_test():
    d = _frame()
    d.loc[(d.window == "D1") & (d.market == "m0"), "status"] = "resolved before or during the window"
    t = run.tests(d, "B")
    lvl = next(r for r in t if r["kind"] == "level" and r["side"] == "buy" and r["windows"] == "D1" and r["scope"] == run.ALL and r["fee_mult"] == 1.0)
    path = next(r for r in t if r["kind"] == "path" and r["side"] == "buy" and r["windows"] == "W1-D1" and r["scope"] == run.ALL)
    assert lvl["markets"] == 4 and path["markets"] == 4
    assert run.tests(d, "A") and all(r["markets"] == 0 for r in run.tests(d, "A") if r["kind"] == "level")          # nothing was observed under rule A


def test_the_book_locks_capital_from_the_window_start_and_caps_the_size():
    d = _frame()
    d["window_start"] = d.window.map({"W1": 0.0, "D1": 3 * 86400.0, "W2": 7 * 86400.0})
    d["result_epoch"] = 1772845200.0 + d.event * 31 * 86400.0
    rows, eq = run.books(d, "B")
    r = next(x for x in rows if x["window"] == "D1" and x["scope"] == run.ALL and x["fee_mult"] == 1.0 and x["segment"] == "ALL")
    s = d[d.window == "D1"]
    assert r["trades"] == 6 and r["pnl"] == pytest.approx(float((10.0 * s.sell_pnl_points / 100).sum()))             # 10 contracts printed: fewer than 100
    assert r["capital_base"] == pytest.approx(float((10.0 * (1 - s.sell_price)).sum()))                               # all six are locked together at the first result
    assert {x["window"] for x in eq} == {"W1", "D1", "W2"} and {x["segment"] for x in rows} == {"IS", "OOS", "ALL"}


def test_cached_prints_lie_inside_their_windows():
    """Integrity of the pull, on the real cache when it is there: every kept print is inside the window it is filed under,
    and D1 prints fall on weekdays between 09:30 and 16:00 New York."""
    import json
    from datetime import datetime

    files = list(pull.CACHE.glob("prints_*.json")) if pull.CACHE.exists() else []
    if not files:
        pytest.skip("no cache on this machine")
    by_market = {m["market"]: m for m in pull.plan()}
    n = 0
    for f in files:
        m, rec = by_market[f.stem.split("_")[1]], json.loads(f.read_text())
        for key, name in (("d1", "D1"), ("w2", "W2")):
            for p in rec[key]:
                ts = float(p["timestamp"])
                assert wn.inside(ts, m["windows"][name])
                if name == "D1":
                    t = datetime.fromtimestamp(ts, wn.ET)
                    assert t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) and (t.hour, t.minute, t.second) <= (16, 0, 0)
                n += 1
    assert n > 0
