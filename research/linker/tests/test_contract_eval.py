"""Contract eval (linker/contract_eval/PLAN.md): truth from agreement, each measure on a hand-made case, the exact
interval, the file-fault refusal, price fields dropped at parse time, and blind input files. Offline."""
import json

import pytest

from linker import contract_eval as ce


def lab(type_="touch_ticket", underlying="NVDA", level=200, direction="up", date="2026-12-31", **kw):
    return {"type": type_, "underlying": underlying, "level": level, "direction": direction, "date": date, **kw}


def pred(type_="touch_ticket", underlying="NVDA", level=200.0, direction="up", date="2026-12-31", linkable=True, reasons=()):
    return {"type": type_, "linkable": linkable, "reasons": list(reasons), "underlying": underlying, "level": level,
            "direction": direction, "date": date, "year_source": "explicit year"}


def test_truth_from_agreement_drops_the_field_not_the_question():
    t, dis = ce.truth_fields(lab(level=200), lab(level=205, underlying="nvda "))
    assert t == {"type": "touch_ticket", "underlying": "NVDA", "direction": "up", "date": "2026-12-31"} and dis == ["level"]
    t, dis = ce.truth_fields(lab(level=200.0000001), lab(level=200))
    assert "level" in t and not dis
    t, dis = ce.truth_fields(lab(type_="other"), lab())
    assert t == {} and dis == ["type"]
    t, dis = ce.truth_fields(lab(type_="ladder_rung", date="2026-01-31"), lab(type_="ladder_rung", date="2026-01-31", level=9))
    assert t == {"type": "ladder_rung", "date": "2026-01-31"}
    t, dis = ce.truth_pair({"nested": True, "earlier_date": "2026-01-15", "later_date": "2026-01-31"},
                           {"nested": False, "earlier_date": "2026-01-15", "later_date": "2026-01-31"})
    assert dis == ["nested"] and t == {"earlier_date": "2026-01-15", "later_date": "2026-01-31"}


def test_interval_is_the_study_helper():
    from linker.study import binom_ci
    r = ce.rate(19, 20)
    assert r["interval_95_exact"] == list(binom_ci(19, 20)) and abs(r["interval_95_exact"][0] - 0.7513) < 1e-3
    assert ce.bar(19, 20)["result"] == "pass" and ce.bar(18, 20)["result"] == "fail" and ce.bar(0, 0)["result"] == "no data"


def case():
    qs = [{"id": str(i), "question": f"Q{i}"} for i in range(1, 8)]
    preds = {"1": pred(), "2": pred(level=210.0), "3": pred(linkable=False, reasons=["direction unknown"], direction=None),
             "4": pred(type_="ladder_rung", underlying=None, level=None, direction=None, date="2026-03-31"),
             "5": pred(type_="ladder_rung", underlying=None, level=None, direction=None, date="2025-03-31"),
             "6": pred(type_="other", underlying=None, level=None, direction=None, date=None, linkable=False, reasons=["no tested mechanism"]),
             "7": pred()}
    l1 = {"1": lab(), "2": lab(), "3": lab(direction="down"), "4": lab("ladder_rung", "", 0, "none", "2026-03-31"),
          "5": lab("ladder_rung", "", 0, "none", "2026-03-31"), "6": lab(), "7": lab(type_="other")}
    l2 = {**l1, "7": lab()}                                     # 7: the labellers disagree on type
    pairs = [{"pair": "p001", "earlier": {"question": "a"}, "later": {"question": "b"}},
             {"pair": "p002", "earlier": {"question": "c"}, "later": {"question": "d"}}]
    pp = {"p001": {"nested": True, "reasons": [], "rich_date": "2026-01-15", "cheap_date": "2026-01-31"},
          "p002": {"nested": False, "reasons": ["descriptions differ"], "rich_date": "2026-02-15", "cheap_date": "2026-02-28"}}
    lp = {"p001": {"nested": False, "earlier_date": "2026-01-15", "later_date": "2026-01-31"},
          "p002": {"nested": True, "earlier_date": "2026-02-15", "later_date": "2026-02-28"}}
    return ce.measures({"questions": qs, "pairs": pairs}, preds, pp, (l1, l2), (lp, lp))


def test_measures_on_a_hand_made_case():
    out, errors = case()
    b = out["bars"]
    assert (b["exact_ticket_links"]["k"], b["exact_ticket_links"]["n"]) == (1, 2)          # 2 has the wrong level, 7 dropped
    assert b["exact_ticket_links"]["excluded"] == {"type disagreement": 1}
    assert (b["rung_dates"]["k"], b["rung_dates"]["n"], b["rung_dates"]["result"]) == (1, 2, "fail")
    assert (b["nested_pairs"]["k"], b["nested_pairs"]["n"]) == (0, 1)
    t = out["type_table_parser_rows_truth_columns"]
    assert t["touch_ticket"]["touch_ticket"] == 3 and t["other"]["touch_ticket"] == 1 and t["ladder_rung"]["ladder_rung"] == 2
    assert out["precision"]["touch_ticket"]["share"] == 1.0 and out["recall_within_sample"]["touch_ticket"]["k"] == 3 and out["recall_within_sample"]["touch_ticket"]["n"] == 4
    fa = out["ticket_field_accuracy"]["touch_ticket"]
    assert fa["questions"] == 4 and fa["parser_other_type"] == 1 and (fa["level"]["k"], fa["level"]["n"]) == (2, 4)
    assert out["refused_tickets"] == {"tickets": 1, "by_reason": {"direction unknown": 1}, "labellers_read_in_full": 1, "read_in_full_ids": ["3"]}
    assert out["nested_pairs_missed"]["k"] == 1 and out["nested_pairs_missed"]["pairs"][0]["pair"] == "p002"
    assert out["labeller_agreement"]["type"]["k"] == 6 and out["disagreements_dropped"]["questions"] == {"type": 1}
    got = {(e["id"], e["field"]) for e in errors}
    assert {("2", "level"), ("5", "date"), ("6", "type"), ("p001", "nested"), ("p002", "nested")} <= got
    assert ("7", "type") not in got


def test_bar1_counts_a_link_wrong_on_an_agreed_field_even_if_another_field_is_undecided():
    qs = [{"id": str(i), "question": f"Q{i}"} for i in range(1, 5)]
    preds = {"1": pred(), "2": pred(date="2025-12-31"), "3": pred(), "4": pred(type_="close_above_ticket")}
    l1 = {"1": lab(), "2": lab(level=200), "3": lab(level=200), "4": lab(level=200)}
    l2 = {"1": lab(), "2": lab(level=205), "3": lab(level=205), "4": lab(level=205)}  # 2-4: level undecided
    out, errors = ce.measures({"questions": qs, "pairs": []}, preds, {}, (l1, l2), ({}, {}))
    b = out["bars"]["exact_ticket_links"]
    # 2 is wrong on its agreed date, 4 on its agreed type: both stay in the bar as failures; 3 matches all it can and leaves
    assert (b["k"], b["n"]) == (1, 3) and b["excluded"] == {"field disagreement, every agreed field matches": 1}
    got = {(e["id"], e["field"]) for e in errors}
    assert ("2", "date") in got and ("4", "type") in got and not any(e["id"] == "3" for e in errors)


def test_recall_weighted_by_stratum_size():
    # stratum 'other' is 9 times the size of 'touch_ticket' per sampled question; one missed ticket hides in 'other'
    qs = [{"id": "1", "question": "a", "stratum": "touch_ticket", "half": "A"},
          {"id": "2", "question": "b", "stratum": "other", "half": "A"}]
    preds = {"1": pred(), "2": pred(type_="other", underlying=None, level=None, direction=None, date=None, linkable=False)}
    labs = {"1": lab(), "2": lab()}
    counts = {"parser_types_all": {"touch_ticket": 10, "other": 90}, "questions": {"touch_ticket": {"A": 1}, "other": {"A": 1}}}
    out, _ = ce.measures({"questions": qs, "pairs": [], "counts": counts}, preds, {}, (labs, labs), ({}, {}))
    assert out["recall_within_sample"]["touch_ticket"]["share"] == 0.5
    w = out["recall_weighted_by_stratum"]["by_type"]["touch_ticket"]
    assert abs(w["share"] - 0.1) < 1e-12 and w["weighted_truth"] == 100
    out, _ = ce.measures({"questions": qs, "pairs": []}, preds, {}, (labs, labs), ({}, {}))
    assert out["recall_weighted_by_stratum"]["by_type"] is None


def write_half(tmp, half="A", drop=None, bad_json=None, stored=None):
    qs = [{"id": "1", "half": half, "stratum": "touch_ticket", "question": "Will Nvidia (NVDA) reach $200 by December 31, 2026?",
           "description": "", "event_id": "e", "event_title": "", "createdAt": "2026-01-02T00:00:00Z"},
          {"id": "2", "half": half, "stratum": "other", "question": "Who wins?", "description": "", "event_id": "e", "event_title": ""}]
    uni = {"questions": qs, "pairs": []}
    (tmp / "universe.json").write_text(json.dumps(uni))
    (tmp / "predictions.json").write_text(json.dumps({"sha256": {"link_map.py": "old"}, "questions": stored or {}, "pairs": {}}))
    for c, items in (("1", [ce.field_item(qs[0])]), ("2", [ce.field_item(qs[1])])):
        (tmp / f"input_fields_{half}{c}.json").write_text(json.dumps({"instructions": "", "questions": items}))
    for L in ("L1", "L2"):
        for c, i in (("1", "1"), ("2", "2")):
            ans = [] if (L, c) == drop else [{"id": i, **(lab() if i == "1" else lab("other", "", 0, "none", ""))}]
            f = tmp / f"labels_fields_{L}_{half}{c}.json"
            f.write_text("{oops" if (L, c) == bad_json else json.dumps({"labeller": L, "chunk": c, "answers": ans}))
        (tmp / f"labels_pairs_{L}_{half}.json").write_text(json.dumps({"labeller": L, "answers": []}))


def test_file_fault_refuses_the_half(tmp_path, capsys):
    write_half(tmp_path, drop=("L2", "1"))
    assert ce.score("A", root=tmp_path, results=tmp_path / "out") == 2
    out = capsys.readouterr().out
    assert "labels_fields_L2_A1.json: 1 item(s) unanswered" in out and not (tmp_path / "out").exists()
    write_half(tmp_path, bad_json=("L1", "2"))
    assert ce.score("A", root=tmp_path, results=tmp_path / "out") == 2
    assert "labels_fields_L1_A2.json: not valid JSON" in capsys.readouterr().out


def test_score_writes_results(tmp_path):
    write_half(tmp_path)
    assert ce.score("A", tag="t", root=tmp_path, results=tmp_path / "out") == 0
    r = json.loads((tmp_path / "out" / "contract_eval_A_t.json").read_text())
    assert r["questions"] == 2 and set(r["sha256_at_scoring"]) == set(ce.PARSER_FILES)
    assert (tmp_path / "out" / "contract_eval_A_t_errors.csv").read_text().startswith("id,question,field")


def test_stored_scores_the_step_one_answers_too(tmp_path):
    old = {"1": pred(level=999.0), "2": pred(type_="other", underlying=None, level=None, direction=None, date=None, linkable=False)}
    write_half(tmp_path, stored=old)
    assert ce.score("A", root=tmp_path, results=tmp_path / "out", use_stored=True) == 0
    now = json.loads((tmp_path / "out" / "contract_eval_A.json").read_text())
    step1 = json.loads((tmp_path / "out" / "contract_eval_A_stepone.json").read_text())
    assert step1["sha256_of_parser_scored"] == {"link_map.py": "old"} and now["sha256_of_parser_scored"] == ce.sha256s()
    assert step1["bars"]["exact_ticket_links"]["k"] == 0 and step1["bars"]["exact_ticket_links"]["n"] == 1
    assert "999.0" in (tmp_path / "out" / "contract_eval_A_stepone_errors.csv").read_text()
    write_half(tmp_path, stored={"1": old["1"]})                     # an answer missing from predictions.json: refused
    assert ce.score("A", tag="x", root=tmp_path, results=tmp_path / "o2", use_stored=True) == 2


def test_price_fields_dropped_at_parse_time():
    raw = {"id": 5, "title": "T", "slug": "s", "closed": True, "tags": [{"label": "Stocks"}], "markets": [
        {"id": 7, "question": "q", "outcomePrices": "[0.4]", "lastTradePrice": 0.4, "bestBid": 0.3, "bestAsk": 0.5,
         "oneDayPriceChange": 0.1, "spread": 0.2, "volume": "123.5", "closed": True}]}
    s = ce.strip_event(raw, "x")
    text = json.dumps(s)
    for k in ("outcomePrices", "lastTradePrice", "bestBid", "bestAsk", "oneDayPriceChange", "spread"):
        assert k not in text
    assert s["markets"][0]["volume"] == 123.5 and s["tags"] == ["Stocks"]


def test_no_input_file_holds_a_parser_field():
    q = {"id": "1", "question": "Q", "event_title": "E", "description": "x" * 2000, "createdAt": "2026-01-02T03:00:00Z",
         "stratum": "touch_ticket", "half": "A", "type": "touch_ticket"}
    side = {"question": "a", "description": "r", "resolutionSource": "", "createdAt": "2026-01-01", "nested": True}
    uni = {"questions": [q, {**q, "id": "2", "half": "B"}],
           "pairs": [{"pair": "p001", "half": "A", "event_resolutionSource": "src", "earlier": side, "later": side}]}
    ins = ce.build_inputs(uni)
    assert set(ins) == {f"input_fields_{h}{c}.json" for h in "AB" for c in "12"} | {"input_pairs_A.json", "input_pairs_B.json"}
    for inp in ins.values():
        assert ce.leaks(inp) == []
    item = ins["input_fields_A1.json"]["questions"][0]
    assert set(item) == {"id", "question", "event_title", "rules", "created"} and len(item["rules"]) == 900 and item["created"] == "2026-01-02"
    assert ins["input_pairs_A.json"]["pairs"][0]["earlier"]["resolution_source"] == "src"
    assert ce.leaks({"questions": [{"id": "1", "stratum": "x"}]}) == ["stratum"]


@pytest.mark.skipif(not (ce.OUT_DIR / "input_pairs_A.json").exists(), reason="sample not built")
def test_written_input_files_are_blind():
    for f in ce.OUT_DIR.glob("input_*.json"):
        assert ce.leaks(json.loads(f.read_text())) == [], f.name
