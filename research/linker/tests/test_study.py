"""The study evaluator: always the link's own signal, HC3 and the robust verdict, the cutoff masks, the exact binomial
interval, recall by cluster, the control arm on malformed answers, off-list types, a synthetic end-to-end run with
every block of PLAN section 5, the frozen-set gate as study.py applies it, and the check against the first held-out
test (h1check)."""
import json

import numpy as np
import pandas as pd
import pytest

from linker import freeze, store
from linker import study as su
from linker.tests.test_freeze import frozen_root
from linker.tests.test_signal import P, S, make_study

DAYS = pd.bdate_range("2026-05-01", periods=90)
CUTOFF = "2026-07-01"


def _world(tmp, short_days=10, k_bp=10.0):
    """SPY flat; XLE's opening gap is k_bp per point of the overnight move in pm_1 (plus noise). pm_2 lives only on the
    last `short_days` sessions."""
    rng = np.random.default_rng(1)
    opens = np.array([pd.Timestamp(f"{d:%Y-%m-%d} 09:30", tz="America/New_York").tz_convert("UTC").timestamp() for d in DAYS], dtype=np.int64)
    closes = opens + 390 * 60
    v = np.clip(0.5 + np.cumsum(rng.normal(0, 0.02, len(DAYS))), 0.05, 0.95)
    px = 100.0 * np.cumprod(1 + np.concatenate([[0.0], k_bp * 1e-4 * 100 * np.diff(v)]) + rng.normal(0, 2e-4, len(DAYS)))
    bt, bo = [], []
    for i, o in enumerate(opens):
        bt.append(o + 300 * np.arange(78))
        bo.append(np.full(78, px[i]))
    t, o = np.concatenate(bt), np.concatenate(bo)
    ones = np.ones_like(o)
    store.save("eq_SPY.npz", t=t, o=500 * ones, c=500 * ones, v=ones, vw=500 * ones)
    store.save("eq_XLE.npz", t=t, o=o, c=o, v=ones, vw=o)
    day = np.array([f"{d:%Y-%m-%d}" for d in DAYS])
    store.save("day_SPY.npz", day=day, c=np.full(len(DAYS), 500.0), o=np.full(len(DAYS), 500.0))
    store.save("day_XLE.npz", day=day, c=px, o=px)
    pt, pp = [], []
    for i in range(len(DAYS)):
        a = closes[i - 1] + 60 if i else opens[0] - 6 * 3600
        ts = np.arange(a, closes[i] + 1, 900)
        pt.append(ts)
        pp.append(np.full(len(ts), v[i]))
    pt, pp = np.concatenate(pt), np.concatenate(pp).astype(np.float32)
    for n in (1, 3, 12, 601826):
        store.save(f"pm_{n}.npz", t=pt, p=pp)
    late = pt >= opens[-short_days] - 6 * 3600
    store.save("pm_2.npz", t=pt[late], p=(1 - pp[late]))
    return opens


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "READ", (tmp_path / "cache",))
    monkeypatch.setattr(store, "NEW", tmp_path / "cache")
    _world(tmp_path)
    return su.Prices()


LINK = {"source": "t", "linker": su.V3, "kind": "event", "cluster": "c001", "market": "polymarket:1", "question": "Will Alice win the election?",
        "ticker": "XLE", "direction": "up_on_yes", "confidence": 0.5, "two_models": 1, "links_on_question": 1, "main_market": "polymarket:1"}


def test_a_weighted_signal_is_always_scored_on_itself(world):
    r = su.score_link({**LINK, "signal": json.dumps([["polymarket:1", 1.0], ["polymarket:2", -1.0]])}, world, {})
    alone = su.score_link({**LINK, "signal": json.dumps([["polymarket:1", 1.0]])}, world, {})
    assert r["scored_on"] == alone["scored_on"] == "signal"
    assert r["days"] == alone["days"] >= 30                    # pm_2 is carried, 0 before its first price
    assert not np.isclose(r["gap_t"], alone["gap_t"])          # but it is in the signal
    r = su.score_link({**LINK, "signal": json.dumps([["polymarket:2", 1.0]])}, world, {})
    assert r["scored_on"] == "signal" and r["verdict"] == "untestable"


def test_direction_flips_the_verdict_and_the_robust_verdict(world):
    up = su.score_link({**LINK, "signal": json.dumps([["polymarket:1", 1.0]])}, world, {})
    dn = su.score_link({**LINK, "direction": "down_on_yes", "signal": json.dumps([["polymarket:1", 1.0]])}, world, {})
    assert up["verdict"] == "confirmed" and dn["verdict"] == "contradicted"
    assert up["nights_1pt"] >= 10 and up["verdict_robust"] == "confirmed" and dn["verdict_robust"] == "contradicted"
    assert np.isclose(up["gap_t_hc3"], -dn["gap_t_hc3"])


def test_hc3_against_a_hand_computation():
    r = su.hc3_slope(np.array([1.0, 2.0, 3.0]), np.array([1.0, 3.0, 2.0]))
    # b = 13/14; residuals 1/14, 16/14, -11/14; 1 - h = 13/14, 10/14, 5/14
    se = np.sqrt((1 / 169 + 1024 / 100 + 1089 / 25) / 196)
    assert np.isclose(r["slope"], 13 / 14) and np.isclose(r["se"], se) and np.isclose(r["t"], (13 / 14) / se)
    assert np.isnan(su.hc3_slope(np.array([2.0]), np.array([1.0]))["t"])     # one date: leverage 1


def test_robust_verdict_thresholds():
    base = {"ticker": "XLE", "days": 40, "nights_1pt": 10, "gap_t_hc3": 2.1}
    assert su.robust_verdict(base) == "confirmed"
    assert su.robust_verdict({**base, "nights_1pt": 9}) == "untestable"
    assert su.robust_verdict({**base, "days": 29}) == "untestable"
    assert su.robust_verdict({**base, "gap_t_hc3": -2.0}) == "contradicted"
    assert su.robust_verdict({**base, "gap_t_hc3": 1.0}) == "unproven"


def test_cutoff_masks_split_the_sessions_exactly(world):
    t, p = su.sg.series([("polymarket:1", 1.0)])
    x, g, d = su._days({"t": t, "p": p}, 1, world, world.asset("XLE"))
    b, s = su.period(x, g, d, "before", CUTOFF), su.period(x, g, d, "since", CUTOFF)
    assert b["days_before_cutoff"] + s["days_since_cutoff"] == len(d) == len(DAYS) - 1
    assert s["days_since_cutoff"] == int((DAYS >= CUTOFF).sum())             # July 1's night (from June 30's close) is "since"
    assert b["days_before_cutoff"] == int((DAYS < CUTOFF).sum()) - 1         # the first session has no previous close
    assert min(d[d >= CUTOFF]) == "2026-07-01" and max(d[d < CUTOFF]) == "2026-06-30"
    r = su.since_cutoff({"t": t, "p": p}, 1, world, world.asset("XLE"), CUTOFF)
    assert r == s and r["gap_t_since_cutoff"] > 2


def test_exact_binomial_interval_against_known_values():
    assert su.binom_ci(0, 10) == (0.0, pytest.approx(0.308497, abs=1e-5))
    lo, hi = su.binom_ci(5, 10)
    assert lo == pytest.approx(0.187086, abs=1e-5) and hi == pytest.approx(0.812914, abs=1e-5)
    lo, hi = su.binom_ci(1, 20)
    assert lo == pytest.approx(0.001265, abs=1e-5) and hi == pytest.approx(0.248732, abs=1e-4)
    assert su.binom_ci(10, 10)[1] == 1.0 and np.isnan(su.binom_ci(0, 0)[0])


def test_resolution_and_recall(world, tmp_path):
    store.save("pm_77.npz", t=np.array([1, 2, 3]), p=np.array([0.5, 0.2, 0.95]))
    store.save("pm_78.npz", t=np.array([1, 2]), p=np.array([0.5, 0.05]))
    store.save("pm_79.npz", t=np.array([1, 2]), p=np.array([0.5, 0.5]))
    assert su.resolution({"id": "polymarket:77", "closed": True}) == "yes"
    assert su.resolution({"id": "polymarket:78", "closed": True}) == "no"
    assert su.resolution({"id": "polymarket:79", "closed": True}) is None
    assert su.resolution({"id": "polymarket:77", "closed": False}) is None
    d = make_study(tmp_path, extra={"labels_recall_R_1.json": {"labeller": "R", "chunk": 1, "answers": [
        {"id": "polymarket:1", "resolved": "yes", "confidence": 0.9}, {"id": "polymarket:3", "resolved": "no", "confidence": 0.9}]}})
    u = json.loads((d / "universe.json").read_text())
    for m in u["markets"] + [m for e in u["events"] for m in e["markets"]]:
        m["closed"] = m["id"] in ("polymarket:1", "polymarket:3")
    (d / "universe.json").write_text(json.dumps(u))
    store.save("pm_1.npz", t=np.array([1, 2]), p=np.array([0.5, 0.97]))       # resolved yes: recalled right
    store.save("pm_3.npz", t=np.array([1, 2]), p=np.array([0.5, 0.97]))       # resolved yes, answered no: not recalled
    assert su.recalled_markets(d, {"polymarket:1", "polymarket:3", "polymarket:8"}) == {"polymarket:1"}


def test_a_cluster_is_recalled_on_its_main_question_and_the_pull_fetches_every_main(world, tmp_path):
    d = make_study(tmp_path, extra={"labels_recall_R_1.json": {"labeller": "R", "chunk": 1, "answers": [
        {"id": "polymarket:2", "resolved": "yes", "confidence": 0.9}]}})
    u = json.loads((d / "universe.json").read_text())
    u["events"][0]["main"] = "polymarket:2"                    # the code's main of c001 is not the common signal's top leg (pm_1)
    for m in u["markets"] + [m for e in u["events"] for m in e["markets"]]:
        m["closed"] = m["id"] == "polymarket:2"
    (d / "universe.json").write_text(json.dumps(u))
    pm = store.npz("pm_1.npz")
    store.save("pm_2.npz", t=np.append(pm["t"], pm["t"][-1] + 60), p=np.append(1 - pm["p"], 0.99))
    assert su.recalled_clusters(d) == {"c001"}
    out, df = su.evaluate(d, px=world, write=False)
    v3 = df[(df.linker == su.V3) & (df.kind == "event") & ~df.probe.astype(bool)]
    assert v3.set_index("ticker").recalled.to_dict() == {"XLE": True, "USO": False}
    assert v3[v3.ticker == "XLE"].main_market.iloc[0] == "polymarket:2" and v3[v3.ticker == "XLE"].market.iloc[0] == "polymarket:1"
    assert out["hindsight"]["v3 without recalled clusters"]["links"] == 1
    links, stats = su.sg.merge(d)
    assert {"polymarket:2", "polymarket:5", "polymarket:9", "polymarket:13"} <= su.pull_ids(d, links, stats, [])


def test_a_recall_answer_given_twice_counts_for_nothing(tmp_path):
    d = make_study(tmp_path, extra={"labels_recall_R_1.json": {"labeller": "R", "chunk": 1, "answers": [
        {"id": "polymarket:1", "resolved": "yes"}, {"id": "polymarket:1", "resolved": "no"}, {"id": "polymarket:3", "resolved": "no"}]}})
    assert su.recall_answers(d) == {"polymarket:3": {"no"}}


def test_a_leg_that_never_traded_leaves_the_link_testable(world):
    store.save("pm_13.npz", t=np.array([], dtype=np.int64), p=np.array([], dtype=np.float32))
    r = su.score_link({**LINK, "signal": json.dumps([["polymarket:1", 1.0], ["polymarket:13", -0.5]])}, world, {})
    assert r["days"] >= 30 and r["verdict"] == "confirmed"


def test_how_alive_the_odds_are_is_read_from_the_main_leg(world):
    pm = store.npz("pm_1.npz")
    store.save("pm_4.npz", t=pm["t"], p=np.clip(pm["p"] - 0.05, 0, 1))   # A - B sits near 0.05 although A is alive
    r = su.score_link({**LINK, "signal": json.dumps([["polymarket:1", 1.0], ["polymarket:4", -1.0]])}, world, {})
    alone = su.score_link({**LINK, "signal": json.dumps([["polymarket:1", 1.0]])}, world, {})
    assert alone["odds_share_between_10_and_90"] > 0.5
    assert r["odds_share_between_10_and_90"] == alone["odds_share_between_10_and_90"]


def test_control_links_survive_malformed_answers(tmp_path):
    ctrl_in = {"tickers": ["XLE", "USO"], "events": [{"event": "e", "questions": [{"id": f"polymarket:{i}", "question": "?"} for i in (1, 3, 8)]}]}

    def lab(who, extra):
        return {"labeller": who, "chunk": 1, "answers": [
            {"id": "polymarket:1", "family": "event", "role": "carrier", "remembered": False,
             "links": [{"ticker": "XLE", "direction": "up_on_yes", "confidence": None if who == "C1" else 0.5},
                       {"ticker": "USO"}, {"direction": "up_on_yes"}, "junk", {"ticker": ["USO"], "direction": "up_on_yes"}]},
            {"id": "polymarket:3", "family": "event", "role": "carrier", "remembered": False, "links": [{"ticker": "USO", "direction": "up_on_yes"}]},
            *extra]}
    twice = [{"id": "polymarket:3", "family": "none", "role": "none", "remembered": False, "links": []}]
    d = make_study(tmp_path, extra={"input_control_1.json": ctrl_in, "labels_control_C1_1.json": lab("C1", twice),
                                    "labels_control_C2_1.json": lab("C2", [])})
    links, st = su.control_links(d)
    assert [(l["market"], l["ticker"]) for l in links] == [("polymarket:1", "XLE")]   # pm_3 dropped: C1 answered it twice
    assert np.isnan(links[0]["confidence"]) and st["links_without_a_direction_skipped"] == 2 and st["questions_answered_twice_dropped"] == 1


def test_off_list_tickers_must_be_a_stock_adr_etf_or_etv():
    ref = {"ticker": "ABC", "name": "ABC Corp", "type": "CS", "primary_exchange": "XNYS", "recent_listing": False, "list_date": "2001-01-01"}
    assert su.off_menu_verdict(ref)["keep"]
    for t in ("WARRANT", "RIGHT", "UNIT", "ETN", "PFD", "", None):
        v = su.off_menu_verdict({**ref, "type": t})
        assert not v["keep"] and "not a stock, ADR, ETF or ETV" in v["note"], t
    assert su.off_menu_verdict({**ref, "type": "ETV"})["keep"] and not su.off_menu_verdict({**ref, "recent_listing": True})["keep"]
    df = pd.DataFrame([{"ticker": "ABC", "cluster": "c009"}])
    assert su.off_menu_kept({"ABC": {**ref, "keep": True}, "XYZ": {"keep": False}}, df) == [
        {"ticker": "ABC", "name": "ABC Corp", "type": "CS", "primary_exchange": "XNYS", "list_date": "2001-01-01", "clusters": ["c009"]}]


def _with_control(tmp_path, name="study"):
    ctrl_in = {"tickers": ["XLE", "USO"], "events": [{"event": "e", "questions": [{"id": "polymarket:1", "question": "?"},
                                                                                {"id": "polymarket:3", "question": "?"}]}]}

    def lab(who, xle):
        return {"labeller": who, "chunk": 1, "answers": [
            {"id": "polymarket:1", "family": "event", "role": "carrier", "remembered": False,
             "links": [{"ticker": "XLE", "direction": xle, "confidence": 0.5, "impact_pct": 3}]},
            {"id": "polymarket:3", "family": "event", "role": "carrier", "remembered": False, "links": []}]}
    d = make_study(tmp_path, extra={"input_control_1.json": ctrl_in, "labels_control_C1_1.json": lab("C1", "up_on_yes"),
                                    "labels_control_C2_1.json": lab("C2", "up_on_yes")})
    return d.rename(d.parent / name) if name != "study" else d


def test_evaluate_on_a_synthetic_study(world, tmp_path):
    pm = store.npz("pm_1.npz")
    store.save("pm_2.npz", t=pm["t"], p=1 - pm["p"])           # Bob lives as long as Alice here: the signal is 2p - 1
    out, df = su.evaluate(_with_control(tmp_path), px=world, write=False, amended=["signal.py"])
    v3 = df[(df.linker == su.V3) & (df.kind == "event") & ~df.probe.astype(bool)]
    assert set(v3.ticker) == {"XLE", "USO"}                    # BRK.B dropped: off the list, no pull validation
    assert out["merge_stats"][su.V3]["off_menu_dropped"][0]["ticker"] == "BRK.B"
    assert (df.scored_on == "signal").all() and not (df.ticker == "SPY").any()
    xle = v3[v3.ticker == "XLE"].iloc[0]
    assert xle.verdict == "confirmed" and xle.signal_range_points == 200.0
    bar = out["brief_bar"]
    assert set(bar) >= {"confirmed_share", "confirmed", "contradicted", "auc_v2_v3_testable", "all_four_pass", "verdict"}
    assert bar["verdict"] == "inconclusive" and bar["testable"] == 1
    assert out["amended"] == ["signal.py"]
    assert out["against_control"][su.V3]["links"] == 2 and out["against_control"][su.CONTROL]["links"] == 1
    pc = out["against_control"]["paired_by_cluster"]
    assert pc["clusters"] == 1 and pc["any_confirmed"]["both"] == 1 and pc["rows"][0]["cluster"] == "c001"
    assert out["without_seen_ladder"]["testable"] == 1
    assert out["by_cluster"]["top_theme"] == xle.theme and out["by_cluster"][f"{su.V3} without the top theme"]["linked"] == 1   # c002 (Hormuz) stays
    assert out["contradicted_share"][su.V3]["interval_95_exact"][0] == 0.0
    assert out["robust"][su.V3]["confirmed"] == 1
    assert out["v3_on_s5_ticker_list"]["links"] == 2
    assert out["hindsight"][su.V3]["links"] == 1 and out["hindsight"]["v3 without remembered clusters"]["links"] == 1   # c001 is remembered
    assert set(out["scorer"]) == {"v1", "v2", "odds_only"} and "v3_testable (the bar)" in out["scorer"]["v2"]
    pp = out["price_proxy_links"]
    assert pp["links"] == 1 and pp["rows"][0]["ticker"] == "IBIT" and not (v3.ticker == "IBIT").any()
    assert out["brazil_check"]["c003"]["passes"] and out["brazil_check"]["c003"]["weight_on_601826"] == 1.0
    assert out["no_instrument"]["clusters_by_one"] == 1
    assert "control_reconstruction" not in out
    assert set(su.COLUMNS) <= set(df.columns)


def test_dev_scores_the_control_reconstruction_next_to_arm_b(world, tmp_path):
    out, _ = su.evaluate(_with_control(tmp_path, "dev"), px=world, write=False)
    rc = out["control_reconstruction"]
    assert rc["reconstruction"]["links"] == 1 and rc["original_arm_B"]["links"] == 42


def test_market_wide_answers_are_scored_on_spy_outside_the_tables(world, tmp_path):
    p, s = json.loads(json.dumps(P)), json.loads(json.dumps(S))
    p[0]["market_wide"], s[0]["market_wide"] = "up", "down"   # S is turned on the anchor, so both say up
    out, df = su.evaluate(make_study(tmp_path, p=p, s=s), px=world, write=False)
    mw = out["market_wide_on_spy_raw_gap"]
    assert out["merge_stats"][su.V3]["market_wide_agreed_direction"] == 1
    assert [a["cluster"] for a in mw["answers"]] == ["c001"] and mw["answers"][0]["direction"] == "up_on_yes"
    assert mw["answers"][0]["days"] > 30 and not (df.ticker == "SPY").any()


# ---------------------------------------------------------------- the frozen set

def test_study_refuses_heldout2_when_frozen_files_changed(tmp_path, monkeypatch, capsys):
    root, fz = frozen_root(tmp_path)
    monkeypatch.setattr(freeze, "ROOT", root)
    monkeypatch.setattr(freeze, "FROZEN", fz)
    assert su.main(["--study", "heldout2"]) == 2 and "does not exist" in capsys.readouterr().out
    assert su.main(["pull", "--study", "heldout2"]) == 2
    freeze.write()
    (root / "linker/study.py").write_text("changed")
    assert su.main(["--study", "heldout2", "--amended", "signal.py"]) == 2 and "linker/study.py" in capsys.readouterr().out
    assert "in no amendment" in su.frozen_gate("heldout2", ["study.py"])
    (root / freeze.PLAN).write_text((root / freeze.PLAN).read_text() + "\n### 2026-10-04: study.py fixed for a crash.\n")
    assert su.frozen_gate("heldout2", ["study.py"]) is None
    assert su.frozen_gate("dev", []) is None and su.frozen_gate("h1check", []) is None


def test_h1check_matches_the_first_held_out_test():
    if store.find("eq_SPY.npz") is None or store.find("pm_1169205.npz") is None:
        pytest.skip("S5 cache absent")
    r = su.h1check()
    assert r["match"], r
    assert {k: r["new"][k] for k in su.H1_OLD} == su.H1_OLD
    assert r["robust"]["links"] == 42 and r["robust"]["testable"] <= 21
