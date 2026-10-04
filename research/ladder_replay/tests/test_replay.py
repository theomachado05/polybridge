import numpy as np

from ladder_replay import replay as rp


def _p(t, p, s, z):
    return {"t": np.array(t, dtype=np.int64), "p": np.array(p, float), "s": np.array(s, np.int8), "z": np.array(z, float)}


M = {"orderPriceMinTickSize": 0.01, "feesEnabled": False}


def test_candidate_needs_both_prints_within_window():
    a = _p([100, 1000], [0.60, 0.60], [-1, -1], [50, 50])
    b = _p([130, 1100], [0.50, 0.50], [1, 1], [20, 500])
    c = rp.candidates(a, b, M, M, 0, 10_000)
    assert [x[0] for x in c] == [130]
    assert abs(c[0][1] - 0.08) < 1e-9 and c[0][2] == 20


def test_wrong_side_prints_do_not_count():
    a = _p([100], [0.60], [1], [50])
    b = _p([110], [0.50], [-1], [50])
    assert rp.candidates(a, b, M, M, 0, 10_000) == []


def test_edge_must_beat_ticks_and_fees():
    a = _p([100], [0.52], [-1], [50])
    b = _p([110], [0.50], [1], [50])
    assert rp.candidates(a, b, M, M, 0, 10_000) == []
    fm = {"orderPriceMinTickSize": 0.01, "feesEnabled": True, "feeSchedule": {"rate": 0.25, "exponent": 1}}
    a = _p([100], [0.56], [-1], [50])
    assert rp.candidates(a, b, M, M, 0, 10_000) and not rp.candidates(a, b, fm, fm, 0, 10_000)


def test_walk_cooldown_and_cap():
    c = [("p", (t, 0.01, 10, 0.5, 0.4, 0, 0, t, t)) for t in (1_760_000_000, 1_760_000_100, 1_760_004_000)]
    tr = rp.walk(c)
    assert [x["t_entry"] for x in tr] == [1_760_000_000, 1_760_004_000]


def test_nesting_rule_masks_only_own_date():
    b = {"keys": ["2026-01-15", "2026-01-31"], "legs": ["a", "b"]}
    g = {"a": {"description": "Resolves Yes if X happens between December 1, 2025 and January 15, 2026, 11:59 PM ET.", "resolutionSource": ""},
         "b": {"description": "Resolves Yes if X happens between December 1, 2025 and January 31, 2026, 11:59 PM ET.", "resolutionSource": ""}}
    assert rp.nested("date", b, "a", "b", g) == (True, "nested")
    g["b"]["description"] = "Resolves Yes if X happens between December 5, 2025 and January 31, 2026, 11:59 PM ET."
    assert not rp.nested("date", b, "a", "b", g)[0]
    g["b"]["description"] = "Resolves Yes if X happens between December 1, 2025 and January 31, 2026, 11:59 PM UTC."
    assert not rp.nested("date", b, "a", "b", g)[0]


def test_settle_floor_when_unresolved():
    tr = {"t_entry": 1_760_000_000, "fill_rich": 0.6, "fill_cheap": 0.5, "fee_rich": 0, "fee_cheap": 0, "size": 10, "print_size": 10}
    r = rp.settle(tr, {"closed": False}, {"closed": False, "endDate": "2025-12-31T00:00:00Z"})
    assert abs(r["pnl_points"] - 10) < 1e-9 and not r["settled"]
    r = rp.settle(tr, {"closed": True, "outcomePrices": '["0","1"]', "closedTime": "2025-11-01 00:00:00+00"},
                  {"closed": True, "outcomePrices": '["1","0"]', "closedTime": "2025-12-01 00:00:00+00"})
    assert abs(r["pnl_points"] - 110) < 1e-9
