"""Link map v2: the trust rule, the version-3 row preferred, the open-only filter, no-instrument items and the keys
ai_map.json consumers read. Offline: CSVs are written to a temp folder and options come from a stub."""
import json

import pandas as pd
import pytest

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


# ---------------------------------------------------------------- the four-type frame (final decision)

META = {"startDate": "2026-09-01T00:00:00Z", "endDate": "2026-11-01", "event_slug": "ev"}
QS = {"polymarket:1": "Will the Fed cut rates?",                                       # other
      "polymarket:2": "Will NVIDIA (NVDA) reach $200 by October 31, 2026?",            # touch ticket
      "polymarket:3": "Strait of Hormuz traffic returns to normal by December 31?"}    # ladder rung


def typed_map(exact=None, meta=True):
    df = pd.DataFrame([{**row(m), "question": q, "version": 1, "score_used": 0.8} for m, q in QS.items()])
    calls = {"resolve": [], "exact": []}

    def resolve(tk, dr, ends):
        calls["resolve"].append(tk)
        return {"directional_leg": "O:USO261231C00100000", "expiry": "2026-12-31", "strike": 100.0, "call": "c", "put": "p"}
    m = lm.build(df, ENDS, resolve=resolve, meta={k: META for k in QS} if meta else None, exact=exact)
    return m, calls


def test_every_item_carries_its_contract_type_and_contract():
    seen = []

    def exact(tk, lv, dr, end):
        seen.append((tk, lv, dr, end))
        return {"ok": True, "reason": "", "expiry": "2026-10-30", "lower_strike": 195.0, "upper_strike": 205.0, "long_leg": "L", "short_leg": "S",
                "headers": "never copied"}
    m, _ = typed_map(exact)
    it = m["items"]
    assert [it[k]["contract_type"] for k in QS] == ["other", "touch_ticket", "ladder_rung"]
    assert it["polymarket:1"]["contract"] is None
    t = it["polymarket:2"]["contract"]
    assert t["linkable"] and (t["underlying"], t["level"], t["direction"], t["window_end"]) == ("NVDA", 200.0, "up", "2026-10-31")
    assert t["exact"] == {"ok": True, "reason": "", "expiry": "2026-10-30", "lower_strike": 195.0, "upper_strike": 205.0, "long_leg": "L", "short_leg": "S"}
    assert seen == [("NVDA", 200.0, "up", "2026-10-31")]
    r = it["polymarket:3"]["contract"]
    assert r["ladder_id"].startswith("ev::") and r["date"] == "2026-12-31" and r["linkable"]
    s = m["summary"]
    assert s["by_contract_type"] == {"ladder_rung": 1, "touch_ticket": 1, "close_above_ticket": 0, "other": 1}
    assert s["items_with_an_exact_contract"] == 2 and s["tickets_with_an_exact_contract"] == 1          # the ticket and the rung
    assert s["linkable_tickets"] == 1 and s["linkable_rungs"] == 1
    json.dumps(m, allow_nan=False)


def test_mappings_are_unvalidated_and_the_atm_option_stays_only_on_type_other():
    m, calls = typed_map()
    for it in m["items"].values():
        for mp in it["mappings"]:
            assert mp["evidence"] == "unvalidated estimate" and mp["mechanism"] == "event_link" and mp["trusted"]
            assert {"ticker", "direction", "impact_pct", "rationale"} <= set(mp)            # ai_map-compatible keys kept
    assert m["items"]["polymarket:1"]["mappings"][0]["option"]["expiry"] == "2026-12-31"
    assert m["items"]["polymarket:2"]["mappings"][0]["option"] is None and m["items"]["polymarket:3"]["mappings"][0]["option"] is None
    assert calls["resolve"] == ["USO"]                                                      # one ATM lookup: the "other" item
    s = m["summary"]
    assert "trusted is not validated" in s["note"] and "held-out bar" in s["note"]
    assert s["trusted_with_an_option_contract"] == 1 and s["trusted_links_on_type_other"] == 1


def test_no_options_keeps_the_parser_fields_and_failures_are_scrubbed():
    m, _ = typed_map(None)
    t = m["items"]["polymarket:2"]["contract"]
    assert t["exact"] is None and t["underlying"] == "NVDA" and m["summary"]["tickets_with_an_exact_contract"] == 0
    assert m["summary"]["items_with_an_exact_contract"] == 1                                    # only the rung's ladder

    def boom(*a):
        raise RuntimeError("GET https://x/?apiKey=SECRET failed")
    t = typed_map(boom)[0]["items"]["polymarket:2"]["contract"]["exact"]
    assert t == {"ok": False, "reason": "contract listing failed: RuntimeError"}


def test_without_a_creation_date_a_ticket_is_not_linkable_and_no_contract_is_asked():
    df = pd.DataFrame([{**row("polymarket:2"), "question": "Will NVIDIA (NVDA) reach $200 by October 31?", "version": 1, "score_used": 0.8}])
    t = lm.build(df, ENDS, exact=lambda *a: pytest.fail("exact link asked for an unlinkable ticket"))["items"]["polymarket:2"]
    assert t["contract_type"] == "touch_ticket" and not t["contract"]["linkable"] and t["contract"]["exact"] is None
    m, _ = typed_map(None, meta=False)
    r = m["items"]["polymarket:3"]
    assert r["contract_type"] == "ladder_rung" and not r["contract"]["linkable"]


def test_no_instrument_items_are_typed_too(monkeypatch):
    monkeypatch.setattr(lm, "roster", lambda s: {"polymarket:5": {"question": "Will X happen?"}})
    answers = {"c1": {"P": {"no_instrument": True}, "S": {"no_instrument": True}}}
    m = lm.build(pd.DataFrame([{**row(), "version": 1, "score_used": 0.8}]), ENDS, v3={"heldout2": (answers, {"c1": {"main": "polymarket:5"}})})
    assert m["items"]["polymarket:5"]["contract_type"] == "other" and m["items"]["polymarket:5"]["contract"] is None


def test_market_meta_reads_the_rosters():
    meta = lm.market_meta()
    assert meta and all(set(v) <= {"startDate", "endDate", "event_slug"} for v in meta.values())
    u = json.loads((lm.HERE / "heldout2" / "universe.json").read_text())
    e = u["events"][0]
    mk = e["markets"][0]
    assert meta[lm._pm(mk["id"])]["event_slug"] == mk["event"] and meta[lm._pm(mk["id"])]["startDate"] == mk["start"]


def test_has_exact_contract_needs_the_link_itself_not_only_the_type():
    hx = lm.has_exact_contract
    assert hx("ladder_rung", {"linkable": True, "ladder_id": "ev::q @D@"})
    assert not hx("ladder_rung", {"linkable": False, "ladder_id": None, "reasons": ["no event id, slug or title"]})
    assert not hx("ladder_rung", None) and not hx("other", None) and not hx("other", {"linkable": True, "ladder_id": "x"})
    assert hx("touch_ticket", {"linkable": True, "exact": {"ok": True}})
    for c in ({"linkable": True, "exact": None}, {"linkable": True, "exact": {"ok": False, "reason": "no listing"}}, {}, None):
        assert not hx("close_above_ticket", c)
    m, _ = typed_map(None, meta=False)                      # no event slug: the rung is classified but has no exact link
    assert m["items"]["polymarket:3"]["contract_type"] == "ladder_rung" and m["summary"]["items_with_an_exact_contract"] == 0
