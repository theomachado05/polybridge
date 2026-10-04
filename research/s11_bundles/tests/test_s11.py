import math

import numpy as np

from s11_bundles import engine as en
from s11_bundles import universe as uni

NOFEE = (0.0, 1.0)


def mk(i, q, vol=1e6, end="2026-12-31T00:00:00Z"):
    return {"id": str(i), "question": q, "volume": vol, "endDate": end}


def test_date_ladder_orders_by_date_and_needs_by():
    ms = [mk(1, "Ceasefire by May 31?"), mk(2, "Ceasefire by April 30?"), mk(3, "Ceasefire by end of June?"),
          mk(4, "Ceasefire on April 30?"), mk(5, "Ceasefire on May 31?")]
    out = uni.date_ladders("e", ms)
    assert len(out) == 1
    assert out[0]["legs"] == ["2", "1", "3"]
    assert out[0]["pairs"] == [["2", "1"], ["1", "3"]]


def test_date_ladder_drops_duplicate_dates():
    assert uni.date_ladders("e", [mk(1, "X by May 31?"), mk(2, "X by May 31, 2026?")]) == []


def test_parse_date():
    assert str(uni.parse_date("end of June", 2026)) == "2026-06-30"
    assert str(uni.parse_date("February", 2028)) == "2028-02-29"
    assert str(uni.parse_date("August 31, 2026", 2025)) == "2026-08-31"
    assert str(uni.parse_date("Dec 31st", 2025)) == "2025-12-31"


def test_strike_ladder_orientation():
    up = [mk(1, "Will WTI hit (HIGH) $100 by end of March?"), mk(2, "Will WTI hit (HIGH) $105 by end of March?"),
          mk(3, "Will WTI hit (HIGH) $95 by end of March?")]
    out = uni.strike_ladders("e", up)
    assert out[0]["legs"] == ["3", "1", "2"] and out[0]["orient"] == 1
    assert out[0]["pairs"] == [["1", "3"], ["2", "1"]]
    dn = [mk(1, "Will WTI hit (LOW) $40 by end of March?"), mk(2, "Will WTI hit (LOW) $45 by end of March?")]
    out = uni.strike_ladders("e", dn)
    assert out[0]["orient"] == -1 and out[0]["pairs"] == [["1", "2"]]


def test_strike_levels_and_unsigned_wording_left_out():
    assert uni.strike_template("Lighter market cap (FDV) >$1B one day after launch?")[1:] == (1e9, 1)
    assert uni.strike_template("Will Bitcoin dip to $80,000 by December 31?")[1:] == (80000.0, -1)
    assert uni.strike_template("Will Bitcoin be above $100k in 2026?")[1:] == (100000.0, 1)
    assert uni.strike_template("Will 7 Fed rate cuts happen in 2025?")[2] == 0
    assert uni.strike_template("Will the 10-year yield be above 4.5% on Dec 31?")[1] is None


def test_negrisk_bounds():
    ms = [mk(i, f"Will {i} win?") for i in range(3)]
    assert uni.negrisk_set("e", ms, True)[0]["legs"] == ["0", "1", "2"]
    assert uni.negrisk_set("e", ms, False) == []
    assert uni.negrisk_set("e", [mk(i, "q") for i in range(31)], True) == []


def test_pair_arb_walks_depth_and_charges_fees():
    r = en.pair_arb([(0.60, 10), (0.55, 50)], [(0.50, 20), (0.58, 100)], NOFEE, NOFEE)
    assert r["size"] == 20 and math.isclose(r["locked"], 10 * 0.10 + 10 * 0.05)
    r = en.pair_arb([(0.60, 10)], [(0.50, 20)], (0.25, 1.0), (0.25, 1.0))
    assert r["size"] == 0 and r["edge"] < 0
    assert en.pair_arb([], [(0.5, 1)], NOFEE, NOFEE)["size"] == 0


def test_basket_arb_both_sides():
    asks = [[(0.30, 10)], [(0.30, 5), (0.35, 10)], [(0.30, 10)]]
    r = en.basket_arb(asks, [NOFEE] * 3, "buy_yes")
    assert r["size"] == 10 and math.isclose(r["locked"], 5 * 0.10 + 5 * 0.05)
    bids = [[(0.40, 10)], [(0.40, 10)], [(0.40, 3)]]
    r = en.basket_arb(bids, [NOFEE] * 3, "buy_no")
    assert r["size"] == 3 and math.isclose(r["locked"], 3 * 0.20)
    assert en.basket_arb([[(0.3, 1)], []], [NOFEE] * 2, "buy_yes")["size"] == 0


def test_pair_edge_and_costs_scale():
    e1 = en.pair_edge(0.60, 0.50, 0.01, NOFEE, NOFEE, 1.0)
    e2 = en.pair_edge(0.60, 0.50, 0.01, NOFEE, NOFEE, 2.0)
    assert math.isclose(float(e1), 0.08) and math.isclose(float(e2), 0.06)
    assert np.isnan(en.pair_edge(np.nan, 0.5, 0.01, NOFEE, NOFEE))


def test_basket_edge():
    mids = np.array([[0.30, 0.40], [0.30, 0.40], [0.30, 0.40]])
    y, n = en.basket_edge(mids, 0.01, [NOFEE] * 3)
    assert np.allclose(y, [1 - 0.93, 1 - 1.23]) and np.allclose(n, [0.87 - 1, 1.17 - 1])


def test_episodes_join_short_gaps():
    t = np.arange(0, 600 * 60, 60.0)
    f = np.zeros(len(t), bool)
    f[[10, 11, 40, 200]] = True
    assert en.episodes(f, t) == [(10, 40), (200, 200)]


def test_jumps_threshold_and_cooldown():
    t = np.arange(0, 200 * 60, 60.0)
    p = np.full(len(t), 0.50)
    p[10:] = 0.53
    p[30:] = 0.60
    p[100:] = 0.50
    j = en.jumps(t, p)
    assert [i for i, _ in j] == [10, 100] and math.isclose(j[0][1], 3.0, abs_tol=1e-6) and j[1][1] < 0
    q = p.copy()
    q[5:12] = np.nan
    assert 10 not in [i for i, _ in en.jumps(t, q)]


def test_taker_trade():
    e, pnl = en.taker_trade(0.50, 0.55, True, 0.01, NOFEE, 1.0)
    assert math.isclose(e, 0.51) and math.isclose(pnl, 0.03)
    e, pnl = en.taker_trade(0.50, 0.55, False, 0.01, NOFEE, 2.0)
    assert math.isclose(e, 0.48) and math.isclose(pnl, 0.48 - 0.57)


def test_year_from_an_end_date_just_past_new_year_utc():
    ms = [mk(1, "Change by December 31?", end="2027-01-01T04:59:00Z"), mk(2, "Change by June 30, 2027?", end="2027-07-01T03:59:00Z"),
          mk(3, "Change by November 30?", end="2026-12-01T04:59:00Z")]
    assert uni.date_ladders("e", ms)[0]["legs"] == ["3", "1", "2"]


def _fake(monkeypatch, data):
    from s11_bundles import run as R
    monkeypatch.setattr(R, "series", lambda mid, src: data.get(mid))
    return R


def test_pair_episode_trade_closes_at_gap_close(monkeypatch):
    t = np.arange(1_780_000_020, 1_780_000_020 + 300 * 60, 60, dtype=np.int64)
    a = np.full(len(t), 0.40)
    b = np.full(len(t), 0.45)
    a[100:120] = 0.60
    R = _fake(monkeypatch, {"A": (t, a), "B": (t, b)})
    M = {"A": {"question": "x by May?", "fee_rate": 0.0, "fee_exponent": 1.0}, "B": {"question": "x by June?", "fee_rate": 0.0, "fee_exponent": 1.0}}
    recs, x = R.pair_episodes({"kind": "date", "source": "s5", "event": "e", "template": "x"}, "A", "B", M, {"A": 0.0, "B": 1.0}, 0.01)
    r = [r for r in recs if r["cost_mult"] == 1.0][0]
    assert math.isclose(r["edge"], 0.59 - 0.46) and r["minutes_beyond_cost"] == 20 and r["minutes_to_gap_close"] == 20
    assert math.isclose(r["pnl_close"], 0.13 + (0.45 - 0.01) - (0.40 + 0.01))
    assert math.isclose(r["pnl_hold"], 0.13 + 1.0 - 0.0) and r["settled_by"] == "result" and not r["broken"]


def test_cap_one_open_trade_per_bundle_and_daily_limit():
    import pandas as pd
    from s11_bundles import run as R
    df = pd.DataFrame({"date": ["d"] * 12 + ["e"], "bundle": ["x"] * 2 + [f"b{i}" for i in range(10)] + ["x"],
                       "t_entry": list(range(12)) + [100], "edge": [5, 4] + [1] * 10 + [1], "t_exit": [50, 60] + [None] * 10 + [None]})
    k = R.cap(df, "edge", "t_exit")
    assert len(k[k.date == "d"]) == 10 and (k[k.date == "d"].bundle == "x").sum() == 1 and (k.date == "e").sum() == 1


def test_cap_without_bundle_limit_for_propagation():
    import pandas as pd
    from s11_bundles import run as R
    df = pd.DataFrame({"date": ["d"] * 3 + ["e"] * 3, "bundle": ["x"] * 6, "t_entry": [1, 2, 3, 100, 101, 102], "abs_jump": [3, 4, 5, 3, 4, 5]})
    assert len(R.cap(df, "abs_jump", per_bundle=False)) == 6
