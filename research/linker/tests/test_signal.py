"""Version-3 agreement: file faults and hard rules, orientation on the common anchor, the common signal and its
two-thirds rule, event and price-proxy links, off-list tickers, market_wide, and a signal's odds with carried legs."""
import json

import numpy as np
import pytest

from linker import signal as sg
from linker import store


def _m(i, q, vol=1e6, in_test=True):
    return {"id": f"polymarket:{i}", "question": q, "volume": vol, "start": "2026-01-01T00:00:00Z", "end": "2026-12-31 00:00:00+00",
            "closed": False, "token": f"tok{i}", "event": f"ev{i}", "in_test": in_test}


EVENTS = [
    ("c001", "multi_outcome", 1, False, [_m(1, "Will Alice win the election?", 5e6), _m(2, "Will Bob win the election?", 3e6)]),
    ("c002", "single", 3, False, [_m(3, "Will Iran close Hormuz?")]),
    ("c003", "multi_outcome", 601825, True, [_m(601825, "Will Renan Santos win?", 9e6, False), _m(601826, "Will Flavio Bolsonaro win?", 5e6, False)]),
    ("c004", "multi_outcome", 5, False, [_m(5, "Outcome five?", 3e6), _m(6, "Outcome six?", 2e6), _m(7, "Outcome seven?")]),
    ("c005", "single", 8, False, [_m(8, "Will a tariff pass?")]),
    ("c006", "multi_outcome", 9, False, [_m(9, "Cut 25?", 4e6), _m(10, "No change?", 3e6), _m(11, "Hike 25?", 2e6)]),
    ("c007", "single", 12, False, [_m(12, "Will Bitcoin reach $150,000?")]),
    ("c008", "single", 13, False, [_m(13, "Will the Senate pass the bill?")]),
    ("c009", "single", 14, False, [_m(14, "Will Berkshire buy a company?")]),
]


def _ans(c, sig, links, family="event", structure="binary", **kw):
    return {"cluster": c, "family": family, "structure": structure,
            "signal": [{"id": f"polymarket:{i}", "weight": w} for i, w in sig], "signal_meaning": "", "alternative": kw.get("alternative", "the rest"),
            "links": [{"ticker": t, "direction": d, "confidence": kw.get("conf", 0.6), "impact_pct": kw.get("imp", 4),
                       "mechanism_class": "other", "mechanism": "", "off_menu": False} for t, d in links],
            "no_instrument": kw.get("no_instrument", False), "no_instrument_reason": "", "market_wide": kw.get("market_wide"),
            "remembered": kw.get("remembered", False)}


MO = "multi_outcome"
P = [_ans("c001", [(1, 1), (2, -1)], [("XLE", "up_on_yes")], structure=MO, alternative="Bob wins", market_wide="up"),
     _ans("c002", [(3, 1)], [("USO", "up_on_yes"), ("xop", "up_on_yes")], conf=0.7, imp=6),
     _ans("c003", [(601826, 1)], [("EWZ", "up_on_yes")], structure=MO),
     _ans("c004", [(6, 1)], [("GLD", "up_on_yes")], structure=MO),
     _ans("c005", [(8, 1)], [], no_instrument=True),
     _ans("c006", [(9, 1), (10, 0.8), (11, -0.5)], [("GLD", "up_on_yes")], structure=MO),
     _ans("c007", [(12, 1)], [("IBIT", "up_on_yes")], family="spot_proxy"),
     _ans("c008", [(13, 1)], [("SPY", "up_on_yes"), ("XLF", "up_on_yes")]),
     _ans("c009", [(14, 1)], [("BRK-B", "up_on_yes")])]
S = [_ans("c001", [(1, -1), (2, 1)], [("XLE", "down_on_yes"), ("TLT", "up_on_yes")], structure=MO, remembered=True, market_wide="down"),
     _ans("c002", [(3, 1)], [("USO", "up_on_yes"), ("XOP", "down_on_yes")], conf=0.5, imp=4),
     _ans("c003", [(601826, -1), (601825, 0.5)], [("EWZ", "down_on_yes"), ("PBR", "down_on_yes")], structure=MO),
     _ans("c004", [(7, 1)], [("GLD", "up_on_yes")], structure=MO),
     _ans("c005", [(8, 1)], [("XRT", "down_on_yes")]),
     _ans("c006", [(9, 0.5), (10, -1), (11, -0.5)], [("GLD", "up_on_yes")], structure=MO),
     _ans("c007", [(12, 1)], [("IBIT", "up_on_yes")], family="spot_proxy"),
     _ans("c008", [(13, 1)], [("XLF", "up_on_yes")]),
     _ans("c009", [(14, 1)], [("brk.b", "up_on_yes")])]


def make_study(tmp, p=P, s=S, extra=None):
    d = tmp / "study"
    d.mkdir()
    ev = [{"cluster": c, "slugs": [c], "structure": st, "main": f"polymarket:{m}", "seen_ladder": c == "c002", "probe": pr, "markets": ms}
          for c, st, m, pr, ms in EVENTS]
    mk = [{**{k: v for k, v in m.items() if k != "in_test"}, "cluster": e["cluster"]} for e in ev for m in e["markets"] if m["in_test"]]
    (d / "universe.json").write_text(json.dumps({"rule": "synthetic", "counts": {}, "markets": mk, "events": ev}))
    (d / "input_v3_1.json").write_text(json.dumps({"instructions": "", "instruments": {}, "events": [
        {"cluster": e["cluster"], "questions": [{"id": m["id"], "question": m["question"]} for m in e["markets"]]} for e in ev]}))
    (d / "labels_v3_P_1.json").write_text(json.dumps({"labeller": "P", "chunk": 1, "answers": p}))
    (d / "labels_v3_S_1.json").write_text(json.dumps({"labeller": "S", "chunk": 1, "answers": s}))
    for name, body in (extra or {}).items():
        (d / name).write_text(body if isinstance(body, str) else json.dumps(body))
    return d


def _c(links, c):
    return [l for l in links if l["cluster"] == c]


# ---------------------------------------------------------------- validation and hard rules

def test_validate_reports_only_the_rerun_grounds_of_plan_2_2(tmp_path):
    p = json.loads(json.dumps(P))
    p.append(p[0])                                              # c001 twice: a note and a discard, not a rerun
    s = json.loads(json.dumps(S[1:]))                           # c001 missing: a rerun ground
    s.append({**S[0], "cluster": "c999"})                      # not in the input file: a note
    d = make_study(tmp_path, p=p, s=s, extra={"labels_v3_P_2.json": "{not json", "labels_v3_S_2.json": {"answers": 3},
                                              "input_v3_2.json": {"events": []}, "labels_v3_P_3.json": {"labeller": "P", "chunk": 3, "answers": []}})
    (d / "labels_v3_S_1.json").write_text(json.dumps({"labeller": "Q", "chunk": 3, "answers": s}))
    assert sg.validate(d) == ["labels_v3_P_2.json: not JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1))",
                              "labels_v3_S_1.json: cluster c001 missing", "labels_v3_S_2.json: no answers list"]
    notes = "\n".join(sg.notes(d))
    for want in ("labels_v3_P: cluster c001 answered 2 times over its files", "labels_v3_S_1.json: cluster c999 is not in its input file",
                 "labeller 'Q', the file name says 'S'", "chunk 3, the file name says 1", "labels_v3_P_3.json: no input file"):
        assert want in notes, want


def test_validate_control_and_recall_files(tmp_path):
    ctrl_in = {"tickers": ["USO", "XLE"], "events": [{"event": "e", "questions": [{"id": "polymarket:3", "question": "?"}]}]}
    good = {"labeller": "C1", "chunk": 1, "answers": [{"id": "polymarket:3", "family": "event", "role": "carrier", "remembered": False,
                                                        "links": [{"ticker": "USO", "direction": "up_on_yes", "confidence": 0.5}]}]}
    bad = {"labeller": "C2", "chunk": 1, "answers": [{"id": "polymarket:3", "family": "maybe", "links": [{"ticker": "GLD", "direction": "up"}]}]}
    rec = {"labeller": "R", "chunk": 1, "answers": [{"id": "polymarket:3", "resolved": "yes", "confidence": 0.8},
                                                     {"id": "polymarket:777", "resolved": "perhaps", "confidence": 2}]}
    d = make_study(tmp_path, extra={"input_control_1.json": ctrl_in, "labels_control_C1_1.json": good, "labels_control_C2_1.json": bad,
                                    "labels_recall_R_1.json": rec})
    assert sg.validate(d) == []
    notes = "\n".join(sg.notes(d))
    for want in ("labels_recall_R_1.json: question polymarket:777 is not a market of this study", "C2_1.json polymarket:3: missing field role", "bad family 'maybe'", "'GLD' is not on the list", "bad direction 'up'",
                 "resolved 'perhaps'", "confidence 2 outside"):
        assert want in notes, want
    assert "C1_1.json" not in notes


def test_discard_each_hard_rule():
    ev = {"main": "polymarket:1", "markets": [{"id": "polymarket:1"}, {"id": "polymarket:2"}]}
    ok = _ans("c", [(1, 1)], [("USO", "up_on_yes")])
    assert sg.discard(ok, ev) is None
    cases = {
        "missing field remembered": {k: v for k, v in ok.items() if k != "remembered"},
        "a link misses off_menu": {**ok, "links": [{k: v for k, v in ok["links"][0].items() if k != "off_menu"}]},
        "not exactly the main question": _ans("c", [(2, 1)], []),
        "binary: signal is not exactly": _ans("c", [(1, 0.5)], []),
        "ladder: signal": _ans("c", [(1, 1), (2, 1)], [], structure="ladder"),
        "not one of the cluster's questions": _ans("c", [(9, 1)], [], structure=MO),
        "not a number in [-1, 1]": _ans("c", [(1, 1.5)], [], structure=MO),
        "no weight is non-zero": _ans("c", [(1, 0), (2, 0)], [], structure=MO),
        "no_instrument true or family none": _ans("c", [(1, 1)], [("USO", "up_on_yes")], no_instrument=True),
        "5 links": _ans("c", [(1, 1)], [(t, "up_on_yes") for t in ("USO", "XLE", "XOP", "OIH", "BNO")]),
        "a ticker appears twice": _ans("c", [(1, 1)], [("BRK.B", "up_on_yes"), ("brk-b", "down_on_yes")]),
        "SPY named": _ans("c", [(1, 1)], [("spy", "up_on_yes")]),
        "structure 'single'": _ans("c", [(1, 1)], [], structure="single"),
    }
    for want, a in cases.items():
        why = sg.discard(a, ev)
        assert why and want in why, (want, why)
    assert sg.discard(_ans("c", [(1, 1)], [], family="none"), ev) is None
    assert sg.discard({"cluster": "c", "_answered": 2}, ev) == "answered 2 times"
    assert "comes later in the input file" in sg.discard({**ok, "_out_of_order": True}, ev)


def test_a_cluster_answered_twice_gets_no_link_whatever_the_answers_say(tmp_path):
    p = json.loads(json.dumps(P))
    p.append(_ans("c005", [(8, 1)], [("XRT", "down_on_yes")]))    # P first said no instrument; S links XRT down_on_yes
    d = make_study(tmp_path, p=p)
    assert sg.validate(d) == []                                  # not a rerun ground
    links, st = sg.merge(d, off_menu={})
    assert not _c(links, "c005")
    assert {"cluster": "c005", "labeller": "P", "reason": "answered 2 times", "probe": False} in st["discarded_answers"]
    assert any("cluster c005 answered 2 times" in n for n in sg.notes(d))
    (tmp_path / "x").mkdir()                                     # the same across two chunks
    d2 = make_study(tmp_path / "x", extra={"labels_v3_P_2.json": {"labeller": "P", "chunk": 2, "answers": [
        _ans("c002", [(3, 1)], [("USO", "up_on_yes")])]}, "input_v3_2.json": {"events": [{"cluster": "c002", "questions": []}]}})
    links, st = sg.merge(d2, off_menu={})
    assert not _c(links, "c002") and sg.load_v3(d2, "P")["c002"] == {"cluster": "c002", "_answered": 2}


def test_answers_out_of_the_input_order_are_discarded(tmp_path):
    p = json.loads(json.dumps(P))
    p[0], p[1] = p[1], p[0]                                      # c002 then c001: c001 comes after a later cluster
    d = make_study(tmp_path, p=p)
    assert sg.validate(d) == []
    links, st = sg.merge(d, off_menu={})
    assert not _c(links, "c001") and _c(links, "c002")           # one swap costs one answer
    assert any(x["cluster"] == "c001" and "later in the input file" in x["reason"] for x in st["discarded_answers"])
    assert "labels_v3_P_1.json c001: discarded, answered after a cluster that comes later in the input file" in sg.notes(d)


# ---------------------------------------------------------------- orientation and the common signal

def test_orient_turns_each_labeller_on_the_common_highest_volume_question():
    vol = {"polymarket:1": 5e6, "polymarket:2": 3e6, "polymarket:3": 9e6}
    a = _ans("c", [(1, -1), (2, 0.5), (3, 1)], [("XLE", "up_on_yes")], market_wide="up")
    b = _ans("c", [(1, 1), (2, -0.5)], [("XLE", "down_on_yes")], market_wide="down")
    oa, ob, anc = sg.orient(a, b, vol)
    assert anc == "polymarket:1"                                # pm_3 is larger but only a weights it
    assert [s["weight"] for s in oa["signal"]] == [1, -0.5, -1] and oa["links"][0]["direction"] == "down_on_yes" and oa["market_wide"] == "down"
    assert ob is b
    assert sg.orient(_ans("c", [(1, 1)], []), _ans("c", [(2, 1)], []), vol)[2] is None


def test_common_signal_mean_scaled_and_two_thirds_rule():
    a = _ans("c", [(1, 1), (2, -0.5)], [])
    b = _ans("c", [(1, 0.5), (2, -0.5)], [])
    sig, ok = sg.common_signal(a, b)
    assert ok and sig == [("polymarket:1", 1.0), ("polymarket:2", -2 / 3)]
    assert sg.signal_range_points(sig) == pytest.approx(100 * (1 + 2 / 3))
    a = _ans("c", [(1, 1), (2, 1), (3, -1)], [])                # shares 2/3 exactly: valid
    b = _ans("c", [(1, 1), (2, -1), (3, -1)], [])
    assert sg.common_signal(a, b)[1]
    a = _ans("c", [(1, 1), (2, 0.8), (3, -0.5)], [])            # a's share 1.5 / 2.3 < 2/3: invalid
    b = _ans("c", [(1, 0.5), (2, -1), (3, -0.5)], [])
    sig, ok = sg.common_signal(a, b)
    assert not ok and [i for i, _ in sig] == ["polymarket:1", "polymarket:3"]


def test_common_signal_main_leg_first_largest_weight_then_volume():
    a = _ans("c", [(1, 1), (2, 1)], [])
    sig, _ = sg.common_signal(a, a, {"polymarket:1": 1.0, "polymarket:2": 5.0})
    assert sig[0][0] == "polymarket:2"


# ---------------------------------------------------------------- merge

def test_opposite_conventions_merge_to_one_signal_with_agreeing_directions(tmp_path):
    links, st = sg.merge(make_study(tmp_path))
    c1 = _c(links, "c001")
    assert len(c1) == 1 and c1[0]["ticker"] == "XLE" and c1[0]["direction"] == "up_on_yes" and c1[0]["kind"] == "event"
    assert json.loads(c1[0]["signal"]) == [["polymarket:1", 1.0], ["polymarket:2", -1.0]]
    assert c1[0]["market"] == "polymarket:1" and c1[0]["remembered"] and c1[0]["alternative"] == "Bob wins"
    assert c1[0]["signal_range_points"] == 200.0
    assert st["market_wide_agreed_direction"] == 1 and st["market_wide"][0]["direction"] == "up"


def test_merge_normalises_takes_the_smaller_confidence_and_counts(tmp_path):
    links, st = sg.merge(make_study(tmp_path))
    c2 = _c(links, "c002")
    assert [l["ticker"] for l in c2] == ["USO"] and c2[0]["confidence"] == 0.5 and c2[0]["impact_pct"] == 5.0 and c2[0]["seen_ladder"]
    assert st["opposite_direction"] == 1                        # XOP (xop upper-cased); XLE agrees once S is turned
    assert st["named_by_one_only"] == 2 and st["probe"]["named_by_one_only"] == 1   # TLT, XRT; PBR is the probe's


def test_merge_no_common_question_disagreement_and_discard(tmp_path):
    links, st = sg.merge(make_study(tmp_path))
    assert not [l for l in links if l["cluster"] in ("c004", "c005", "c006", "c008")]
    assert st["no_common_question"] == 1 and st["signal_disagreement"] == 1
    assert st["discarded_answers"] == [{"cluster": "c008", "labeller": "P", "reason": "SPY named", "probe": False}]
    assert st["discarded_clusters"] == 1 and st["no_instrument_by_one"] == 1


def test_price_proxy_links_are_kind_price_proxy(tmp_path):
    links, st = sg.merge(make_study(tmp_path))
    c7 = _c(links, "c007")
    assert [(l["ticker"], l["kind"]) for l in c7] == [("IBIT", "price proxy")]
    assert st["price_proxy_links"] == 1 and st["both_spot_proxy"] == 1


def test_probe_orients_on_the_common_question_and_stays_apart(tmp_path):
    links, st = sg.merge(make_study(tmp_path))
    probe = [l for l in links if l["probe"]]
    assert [(l["ticker"], l["direction"]) for l in probe] == [("EWZ", "up_on_yes")]
    assert json.loads(probe[0]["signal"]) == [["polymarket:601826", 1.0]]
    assert st["probe"]["clusters"] == 1 and st["clusters"] == 8


def test_off_list_tickers_need_the_pull_validation(tmp_path):
    d = make_study(tmp_path)
    links, _ = sg.merge(d)
    brk = _c(links, "c009")
    assert [(l["ticker"], l["off_menu"]) for l in brk] == [("BRK.B", True)]   # BRK-B and brk.b are one symbol
    links, st = sg.merge(d, off_menu={})
    assert not _c(links, "c009") and st["off_menu_dropped"][0]["ticker"] == "BRK.B"
    links, st = sg.merge(d, off_menu={"BRK.B": {"keep": True, "note": ""}})
    assert _c(links, "c009") and not st["off_menu_dropped"]
    assert _c(links, "c002")                                    # tickers on the list never need it


def test_market_wide_needs_a_valid_signal(tmp_path):
    p, s = json.loads(json.dumps(P)), json.loads(json.dumps(S))
    p[5]["market_wide"], s[5]["market_wide"] = "up", "up"      # c006: same direction, signal fails two thirds
    _, st = sg.merge(make_study(tmp_path, p=p, s=s))
    assert [m["cluster"] for m in st["market_wide"]] == ["c001"]


# ---------------------------------------------------------------- the signal's odds

@pytest.fixture
def odds_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "READ", (tmp_path,))
    monkeypatch.setattr(store, "NEW", tmp_path)
    t0 = 1_780_000_000 // 60 * 60
    t1 = np.concatenate([t0 + np.arange(0, 3600, 600), t0 + np.arange(3 * 3600, 6 * 3600, 600)])   # main: silent from 0:50 to 3:00
    store.save("pm_1.npz", t=t1, p=np.full(len(t1), 0.6, dtype=np.float32))
    store.save("pm_2.npz", t=np.array([t0 + 1800, t0 + 4 * 3600]), p=np.array([0.3, 0.5], dtype=np.float32))   # a thin leg
    return t0


def test_series_single_question_unchanged(odds_store):
    t, p = sg.series([("polymarket:1", 1.0)])
    assert len(t) == 24 and np.allclose(p, 0.6)
    t, p = sg.series([("polymarket:1", -0.5)])
    assert np.allclose(p, -0.6)


def test_series_carries_a_thin_leg_and_marks_a_stale_main_leg(odds_store):
    t0 = odds_store
    t, p = sg.series([("polymarket:1", 0.5), ("polymarket:2", -0.25)])     # scaled: 1 and -0.5
    assert np.all(t % 60 == 0) and np.all(np.diff(t) == 60)                # every minute, none dropped
    fresh = np.isfinite(p)
    assert np.allclose(p[fresh & (t < t0 + 1800)], 0.6)                     # the thin leg counts 0 before its first price
    assert np.allclose(p[fresh & (t >= t0 + 1800) & (t < t0 + 4 * 3600)], 0.6 - 0.15)   # then carried with no age limit
    assert np.allclose(p[fresh & (t >= t0 + 4 * 3600)], 0.6 - 0.25)
    stale = (t > t0 + 3000 + 1800) & (t < t0 + 3 * 3600)
    assert stale.any() and np.isnan(p[stale]).all()                         # main leg over 30 minutes old: NaN
    assert fresh[(t > t0 + 3000) & (t <= t0 + 3000 + 1800)].all()
    assert np.isnan(p[-1]) and t[-1] - (t0 + 6 * 3600 - 600) > 1800         # ends on a stale minute
    t2, _ = sg.series([("polymarket:2", -0.25), ("polymarket:1", 0.5)])
    assert np.array_equal(t, t2)                                           # the main leg is the largest |weight|
    t3, _ = sg.series([("polymarket:1", 1.0), ("polymarket:2", 1.0)], main="polymarket:2")
    assert t3[0] >= t0 + 1800                                              # the grid follows the main leg
    assert sg.series([("polymarket:1", 1.0), ("polymarket:9", 1.0)])[0].size == 0   # a leg's file absent: the pull failed


def test_a_weighted_lookup_never_reaches_past_30_minutes_of_the_main_leg(odds_store):
    from s1_twin_spread.engine import asof
    t0 = odds_store
    store.save("pm_21.npz", t=np.array([t0, t0 + 3000]), p=np.array([0.4, 0.5]))          # main: T0 and T0+50 min
    store.save("pm_22.npz", t=np.array([t0 + 600]), p=np.array([0.5]))                      # weighted -0.5 from T0+10
    t, p = sg.series([("polymarket:21", 1.0), ("polymarket:22", -0.5)])
    at = np.array([t0, t0 + 600, t0 + 49 * 60, t0 + 3000], dtype=np.int64)
    got = asof(at, t, p, sg.MAX_AGE_S)
    alone = asof(at, np.array([t0, t0 + 3000]), np.array([0.4, 0.5]), sg.MAX_AGE_S)
    assert np.allclose(got[[0, 1, 3]], [0.4, 0.15, 0.25]) and np.isnan(got[2]) and np.isnan(alone[2])
    assert np.isnan(asof(np.array([t0 + 3000 + 1800 + 600]), t, p, sg.MAX_AGE_S)[0])      # past the end: stale too


def test_a_leg_that_never_traded_counts_as_zero_but_an_empty_main_leg_is_untestable(odds_store):
    store.save("pm_13.npz", t=np.array([], dtype=np.int64), p=np.array([], dtype=np.float32))
    t, p = sg.series([("polymarket:1", 1.0), ("polymarket:13", -0.5)])
    assert len(t) and np.allclose(p[np.isfinite(p)], 0.6)
    assert sg.series([("polymarket:13", 1.0), ("polymarket:1", 0.5)])[0].size == 0


def test_a_link_needs_the_confidence_floor_from_both_labellers(tmp_path):
    p = [_ans("c002", [(3, 1)], [("USO", "up_on_yes")], conf=0.6), _ans("c008", [(13, 1)], [("XLF", "up_on_yes")], conf=0.3)]
    s = [_ans("c002", [(3, 1)], [("USO", "up_on_yes")], conf=0.25), _ans("c008", [(13, 1)], [("XLF", "up_on_yes")], conf=0.3)]
    links, stats = sg.merge(make_study(tmp_path, p, s))
    assert [(l["cluster"], l["ticker"]) for l in links] == [("c008", "XLF")]            # exactly at the floor counts
    assert [(x["cluster"], x["ticker"], x["confidence"]) for x in stats["below_confidence_floor"]] == [("c002", "USO", 0.25)]
    assert stats["agreed_links"] == 1 and stats["clusters_with_link"] == 1
