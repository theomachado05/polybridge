"""Pooled test of the mechanism: stacking, standardisation, the clustered slope, the per-instrument collapse, the median
split, the difference t, and the sign of the options stack on a put link. Synthetic, offline."""
import numpy as np
import pandas as pd
import pytest

from linker import pooled as pl


def _l(market, ticker, direction="up_on_yes", linker="v3, by event"):
    return {"linker": linker, "market": market, "cluster": "c", "ticker": ticker, "direction": direction}


def test_stack_one_row_per_finite_day_and_standardised():
    x = np.array([1.0, -2.0, 3.0, np.nan, 0.5])
    g = np.array([10.0, 20.0, np.nan, 5.0, -40.0])
    d = np.array(["2026-01-0%d" % i for i in range(1, 6)])
    five = (np.array([1.0, 2, 3, 4, 5]), np.array([1.0, 1, 1, 1, 1]), d)
    days = {"A": (x, g, d), "B": five}
    links = [_l("m1", "AAA"), _l("m2", "BBB"), _l("m3", "NOV")]
    df, c = pl.stack(links, lambda l: days["A" if l["market"] == "m1" else "B"], {"AAA": 0.01, "BBB": 0.02, "NOV": float("nan")}.get)
    assert (df.key == pl.link_key(links[1])).sum() == 5                 # a link with 5 days gives 5 rows
    a = df[df.key == pl.link_key(links[0])]
    assert list(a.date) == ["2026-01-01", "2026-01-02", "2026-01-05"]   # non-finite x or y dropped
    assert np.allclose(a.y, [10 / 100, 20 / 100, -40 / 100])             # bp / (1e4 x 0.01) = bp / 100
    assert c["left_out_no_vol"] == 1 and c["left_out_no_vol_keys"] == [pl.link_key(links[2])]


def test_slope_matches_hand_computation_and_dates_cluster():
    df = pd.DataFrame({"key": ["a", "b", "a", "b"], "ticker": ["T", "U", "T", "U"],
                       "date": ["d1", "d1", "d2", "d2"], "x": [1.0, 2.0, -1.0, 3.0], "y": [1.0, 1.0, 0.0, 2.0]})
    r = pl.fit(df)
    b = (1 + 2 + 0 + 6) / (1 + 4 + 1 + 9)
    e = df.y - b * df.x
    s1, s2 = 1 * e[0] + 2 * e[1], -1 * e[2] + 3 * e[3]                  # two links on the same date: one cluster
    assert r["slope"] == pytest.approx(b)
    assert r["se"] == pytest.approx(np.sqrt(s1 ** 2 + s2 ** 2) / 15)
    assert (r["date_clusters"], r["dates"], r["links"], r["link_days"]) == (2, 2, 2, 4)
    assert r["holds"] == (r["t"] >= 2)


def test_same_sign_share_on_one_point_nights():
    df = pd.DataFrame({"key": "a", "date": ["1", "2", "3", "4"], "x": [2.0, -3.0, 0.5, 1.0], "y": [1.0, 1.0, -1.0, 0.0]})
    r = pl.fit(df)
    assert r["nights_1pt"] == 3 and r["same_sign_share_1pt"] == pytest.approx(1 / 3)


def test_per_instrument_collapse():
    df = pd.DataFrame({"key": ["a", "b", "c", "a"], "ticker": ["T", "T", "U", "T"], "date": ["d1", "d1", "d1", "d2"],
                       "x": [2.0, 4.0, 1.0, -1.0], "y": [0.5, 0.5, 0.2, 0.1]})
    p = pl.per_instrument(df).set_index(["ticker", "date"])
    assert len(p) == 3 and p.loc[("T", "d1"), "x"] == 3.0 and p.loc[("T", "d1"), "y"] == 0.5 and p.loc[("T", "d1"), "links"] == 2
    r = pl.fit_per_instrument(df)
    assert (r["instrument_days"], r["instruments"], r["links"], r["dates"]) == (3, 2, 3, 2)


def test_median_split_ties_to_quiet():
    s = pd.Series({"a": 0.1, "b": 0.3, "c": 0.3, "d": 0.5, "e": np.nan})
    act, med = pl.active_mask(s)
    assert med == 0.3
    assert act.to_dict() == {"a": False, "b": False, "c": False, "d": True, "e": False}


def test_difference_t():
    assert pl.diff_t({"slope": 0.5, "se": 0.3}, {"slope": 0.1, "se": 0.4}) == pytest.approx(0.4 / 0.5)
    assert np.isnan(pl.diff_t({"slope": 1, "se": 0}, {"slope": 0, "se": 0}))


def _bars(days, o, c):
    return {"day": np.array(days), "open": np.array(o, float), "close": np.array(c, float)}


def test_options_stack_put_link_positive_on_a_rising_signal():
    days = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
    op = np.array([1772460000 + 86400 * i for i in range(4)])          # session open instants
    sess = pd.DataFrame({"day": days, "open": op, "close": op + 23400})
    p = [0.20, 0.30, 0.25, 0.40]                                         # yes odds at 09:29 and at the close of each day
    pm = {"t": np.sort(np.concatenate([op - 60, op + 23400])), "p": np.repeat(p, 2).astype(float)}
    put = _bars(days, [0, 11.0, 9.0, 12.0], [10.0, 10.0, 10.0, 10.0])  # a working down link: the put gains when yes rises
    call = _bars(days, [0, 9.0, 11.0, 8.0], [10.0, 10.0, 10.0, 10.0])

    def fetch(kind, *a):
        if kind == "splits":
            return None
        if kind == "pair":
            return {"month": a[1], "expiry": "2026-04-17", "strike": 100.0, "spot": a[2], "call": "C", "put": "P"}
        return call if a[0] == "C" else put

    dayb = {"day": np.array(["2026-02-27"]), "c": np.array([100.0])}
    o = pl.option_days({"ticker": "XLE", "direction": "down_on_yes"}, sess, pm, dayb, fetch)
    assert len(o) == 3
    assert np.allclose(o.xp, [10.0, -5.0, 15.0])                         # the plain move of the signal, not -x_night
    assert np.allclose(o.r_dir, [1000.0, -1000.0, 2000.0])               # the put's overnight return, bp
    assert pl.options_fit(o.assign(key="k"))["directional"]["slope"] > 0  # positive: the link holding, for a put too
    o2 = pl.option_days({"ticker": "XLE", "direction": "up_on_yes"}, sess, pm, dayb, fetch)
    assert np.allclose(o2.xp, o.xp) and np.allclose(o2.r_dir, [-1000.0, 1000.0, -2000.0])   # same move, the call's return


def test_event_clusters_counted_apart_from_date_clusters():
    df = pd.DataFrame({"key": ["a", "b", "c", "a"], "cluster": ["c1", "c1", "c2", "c1"], "ticker": ["T", "U", "T", "T"],
                       "date": ["d1", "d1", "d1", "d2"], "x": [1.0, 2.0, -1.0, 3.0], "y": [1.0, 1.0, 0.0, 2.0]})
    r = pl.fit(df)
    assert (r["event_clusters"], r["date_clusters"], r["dates"], r["links"]) == (2, 2, 2, 3)
    assert "clusters" not in r
    assert pl.fit_per_instrument(df)["event_clusters"] == 2
    assert pl.fit(df.iloc[:0])["event_clusters"] == 0
    o = pd.DataFrame({"date": ["d1", "d2", "d3"], "xp": [1.0, -2.0, 3.0], "r_dir": [5.0, -3.0, 9.0], "r_str": [1.0, 2.0, 4.0],
                      "key": ["a", "a", "b"], "cluster": ["c1", "c1", "c2"]})
    f = pl.options_fit(o)
    assert f["directional"]["event_clusters"] == 2 and f["straddle"]["date_clusters"] == 3


def _two_month_setup():
    days = ["2026-03-02", "2026-03-03", "2026-04-01", "2026-04-02"]
    op = np.array([1772460000 + 86400 * i for i in range(4)])
    sess = pd.DataFrame({"day": days, "open": op, "close": op + 23400})
    pm = {"t": np.sort(np.concatenate([op - 60, op + 23400])), "p": np.repeat([0.2, 0.3, 0.25, 0.4], 2).astype(float)}
    bars = _bars(days, [0, 11.0, 9.0, 12.0], [10.0, 10.0, 10.0, 10.0])
    dayb = {"day": np.array(["2026-02-27"]), "c": np.array([100.0])}
    return sess, pm, bars, dayb


def test_options_tally_separates_absent_from_cache_and_no_contract():
    sess, pm, bars, dayb = _two_month_setup()

    def fetch(kind, *a):                                                  # March: not in the cache; April: no contract
        if kind == "splits":
            return None
        if kind == "pair":
            return pl.ABSENT if a[1] == "2026-03" else None
        return bars

    links = [{"linker": "v3", "market": "m", "cluster": "c", "ticker": "XLE", "direction": "up_on_yes"}]
    opt, pop = pl.options_stack(links, sess, fetch, lambda l: pm, lambda tk: dayb)
    assert len(opt) == 0 and pop["links_with_no_option_day"] == 1
    assert (pop["link_months"], pop["link_months_absent_from_cache"], pop["link_months_no_contract"]) == (2, 1, 1)
    assert pop["absent_from_cache_keys"] == ["XLE|m|2026-03"]


def test_options_population_is_the_section_7_rule_not_the_cache(tmp_path, monkeypatch):
    rows = pd.DataFrame({"linker": ["v3, by event"] * 3 + ["control"], "kind": ["event"] * 4, "probe": [False] * 4,
                         "market": ["m1", "m2", "m3", "m4"], "ticker": ["USO"] * 4, "direction": ["up_on_yes"] * 4,
                         "cluster": ["c"] * 4, "verdict": ["confirmed", "untestable", "unproven", "unproven"]})
    rows.to_csv(tmp_path / "dev_v3_links.csv", index=False)
    monkeypatch.setattr(pl.oe, "OUT", tmp_path)
    sess, pm, bars, dayb = _two_month_setup()

    def fetch(kind, *a):                                                  # every month is cached for every link
        if kind == "splits":
            return None
        if kind == "pair":
            return {"month": a[1], "expiry": "2026-05-15", "strike": 100.0, "spot": a[2], "call": "C", "put": "P"}
        return bars

    opt, pop = pl.options_stack(pl.oe.load_links("dev"), sess, fetch, lambda l: pm, lambda tk: dayb)
    assert sorted(opt.key.unique()) == sorted(f"v3, by event|{m}|USO|up_on_yes" for m in ("m1", "m3"))  # the untestable link stays out
    assert pop["links"] == 2 and pop["links_with_an_option_day"] == 2
