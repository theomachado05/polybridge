"""Link map v2: the trust rule, the version-3 row preferred, the open-only filter, no-instrument items and the keys
ai_map.json consumers read. Offline: CSVs are written to a temp folder and options come from a stub."""
import json

import pandas as pd

from linker import link_map2 as lm

COLS = ["source", "linker", "market", "question", "ticker", "direction", "confidence", "two_models", "days", "gap_bp_per_point", "gap_t",
        "verdict", "theme"]


def row(market="polymarket:1", ticker="USO", direction="up_on_yes", verdict="confirmed", two=1, gap=5.0, t=3.0, **kw):
    return {"source": "S5", "linker": "v1", "market": market, "question": f"Q{market}", "ticker": ticker, "direction": direction, "confidence": 0.6,
            "two_models": two, "days": 120, "gap_bp_per_point": gap, "gap_t": t, "verdict": verdict, "theme": "Other", **kw}


def write(tmp, bench=(), held=(), v3=()):
    pd.DataFrame(list(bench), columns=COLS + ["score_out_of_fold", "score_full_model"]).to_csv(tmp / "benchmark_scored.csv", index=False)
    pd.DataFrame(list(held), columns=COLS + ["score"]).to_csv(tmp / "heldout_links.csv", index=False)
    if v3:
        pd.DataFrame(list(v3)).to_csv(tmp / "heldout2_links.csv", index=False)


ENDS = {f"polymarket:{i}": ("2026-12-31", False) for i in range(1, 10)}


def test_trust_rule():
    df = pd.DataFrame([
        {"two_models": 1, "verdict": "confirmed", "score_used": 0.1},      # prices confirm
        {"two_models": 1, "verdict": "unproven", "score_used": 0.5},       # score at the bar
        {"two_models": 1, "verdict": "unproven", "score_used": 0.49},
        {"two_models": 0, "verdict": "confirmed", "score_used": 0.9},      # one model only
        {"two_models": 1, "verdict": "contradicted", "score_used": 0.9},   # prices contradict
        {"two_models": 1, "verdict": "untestable", "score_used": float("nan")}])
    assert lm.is_trusted(df).tolist() == [True, True, False, False, False, False]


def test_version3_row_preferred_and_score_v2_used(tmp_path):
    write(tmp_path, bench=[{**row(verdict="unproven", t=1.0), "score_out_of_fold": 0.2, "score_full_model": 0.2}],
          v3=[{**row(verdict="unproven", t=1.0), "score_v2": 0.7, "score_v1": 0.2, "score": 0.7, "cluster": "c001",
               "signal": json.dumps([["polymarket:1", 1.0], ["polymarket:2", -0.5]]), "impact_pct": 4.0, "alternative": "no deal"}])
    df = lm.gather(tmp_path)
    assert len(df) == 1 and df.version.iloc[0] == 3 and df.score_used.iloc[0] == 0.7
    m = lm.build(df, ENDS)
    it = m["items"]["polymarket:1"]
    assert it["cluster"] == "c001" and it["signal"][1] == ["polymarket:2", -0.5] and it["alternative"] == "no deal"
    assert it["mappings"][0]["trusted"] and it["mappings"][0]["impact_pct"] == 4.0


def test_missing_v3_files_are_fine_and_score_falls_back_to_v1(tmp_path):
    write(tmp_path, bench=[{**row(), "score_out_of_fold": 0.3, "score_full_model": 0.6}], held=[{**row("polymarket:2"), "score": 0.4}])
    df = lm.gather(tmp_path)
    assert sorted(df.score_used.tolist()) == [0.4, 0.6] and set(df.version) == {1}


def test_open_only_and_no_spy():
    df = pd.DataFrame([row("polymarket:1"), row("polymarket:2"), row("polymarket:3"), row("polymarket:4"), row("polymarket:1", ticker="SPY")])
    ends = {"polymarket:1": ("2026-12-31", False), "polymarket:2": ("2026-10-03", False),       # ended yesterday
            "polymarket:3": ("2026-12-31", True)}                                               # resolved; 4 unknown
    assert lm.open_only(df, ends, "2026-10-04")[["market", "ticker"]].values.tolist() == [["polymarket:1", "USO"]]


def test_ai_map_keys_option_and_fallbacks():
    df = pd.DataFrame([{**row(gap=-3.25, direction="down_on_yes"), "version": 1, "score_used": 0.8},
                       {**row("polymarket:2", verdict="unproven", t=0.5), "version": 1, "score_used": 0.2}])
    calls = []

    def resolve(tk, dr, ends):
        calls.append((tk, dr, ends))
        return {"directional_leg": "O:USO261231P00100000", "expiry": "2026-12-31", "strike": 100.0, "call": "O:USO261231C00100000", "put": "O:USO261231P00100000"}
    m = lm.build(df, ENDS, resolve=resolve)
    mp = m["items"]["polymarket:1"]["mappings"][0]
    assert {"ticker", "direction", "impact_pct", "rationale"} <= set(mp)
    assert mp["impact_pct"] == 3.25 and mp["rationale"].startswith("Prices confirm it")          # measured move per 100 points
    assert mp["option"]["contract"].endswith("P00100000") and calls == [("USO", "down_on_yes", "2026-12-31")]   # untrusted: no call
    assert m["items"]["polymarket:2"]["mappings"][0]["option"] is None
    assert m["summary"]["trusted_links"] == 1 and m["summary"]["trusted_with_an_option_contract"] == 1
    json.dumps(m, allow_nan=False)


def test_labeller_mechanism_used_as_rationale():
    df = pd.DataFrame([{**row(), "version": 1, "score_used": 0.8}])
    notes = {("polymarket:1", "USO", "up_on_yes"): {"mechanism": ["Less Gulf crude."], "impact": [6.0], "alternative": []}}
    mp = lm.build(df, ENDS, notes, {"polymarket:1": {"spot_proxy"}})["items"]["polymarket:1"]
    assert mp["mappings"][0]["rationale"] == "Less Gulf crude." and mp["mappings"][0]["impact_pct"] == 6.0 and mp["kind"] == "price proxy"


def test_no_instrument_items(monkeypatch):
    monkeypatch.setattr(lm, "roster", lambda s: {"polymarket:5": {"question": "Will X happen?"}})
    answers = {"c1": {"P": {"no_instrument": True, "no_instrument_reason": "nothing moves 1%"}, "S": {"no_instrument": True, "no_instrument_reason": ""}},
               "c2": {"P": {"no_instrument": True}, "S": {"no_instrument": False}},                  # only one says so
               "c3": {"P": {"no_instrument": True}, "S": {"no_instrument": True}}}                   # cluster has older links
    cl = {"c1": {"main": "polymarket:5"}, "c2": {"main": "polymarket:6"}, "c3": {"main": "polymarket:1"}}
    assert [x["cluster"] for x in lm.no_instrument(answers, cl)] == ["c1", "c3"]
    df = pd.DataFrame([{**row(), "version": 1, "score_used": 0.8}])
    m = lm.build(df, ENDS, v3={"heldout2": (answers, cl)})
    it = m["items"]["polymarket:5"]
    assert it["no_instrument"] and it["mappings"] == [] and it["no_instrument_reason"] == "nothing moves 1%" and it["question"] == "Will X happen?"
    assert not m["items"]["polymarket:1"]["no_instrument"] and m["items"]["polymarket:1"]["mappings"]
    assert m["summary"]["no_instrument_items"] == 1 and m["summary"]["no_instrument_but_older_links"] == 1
