"""The mechanism registry (backend/app/closed/evidence.py): one entry per mechanism, statuses as the brief sets them,
and every number with its range, its sample and a result file it was copied from (checked against that file)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.closed import evidence as ev
from app.main import create_app

REPO = Path(__file__).resolve().parents[2]


def _all_numbers():
    for m in ev.mechanisms():
        for n in m["numbers"]:
            yield m["id"], n
    for n in ev.system_numbers():
        yield "system", n


def _floats(text: str) -> list[float]:
    text = text.replace("−", "-")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 7,111 -> 7111
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", text)]


def _decimals(v: float) -> int:
    s = repr(float(v))
    return 0 if float(v).is_integer() else len(s.split(".")[1])


def _appears(v: float, found: list[float]) -> bool:
    dp = _decimals(v)
    tol = 0.5 * 10 ** -dp + 1e-12
    return any(abs(f - v) <= tol for f in found) or any(abs(-f - v) <= tol for f in found if v < 0)


def test_one_entry_per_mechanism_with_the_statuses_of_the_brief():
    by = {m["id"]: m for m in ev.mechanisms()}
    assert len(by) == len(ev.MECHANISMS)
    assert by["foundation"]["status"] == ev.CONFIRMED_FOUNDATION
    assert by["ladders"]["status"] == ev.LEAD
    assert by["touch"]["status"] == ev.OPEN_LEAD
    assert by["btc_15min"]["status"] == ev.WATCH_ONLY
    assert by["other"]["status"] == ev.NO_TESTED_MECHANISM
    # the generic fit stays available, labelled unvalidated; FAILED is kept for what is never offered (S25)
    assert by["generic_ai_fit"]["status"] == ev.UNVALIDATED_AVAILABLE == "UNVALIDATED"
    assert by["generic_ai_fit"]["status_label"] == "Unvalidated: walk-forward test failed"
    assert by["ticket_option_hedge"]["status"] == ev.FAILED
    assert [m["id"] for m in by.values() if m["status"] == ev.FAILED] == ["ticket_option_hedge"]
    for m in by.values():
        assert m["status"] in ev.STATUSES and m["status_label"] == ev.STATUS_LABELS[m["status"]]
        assert m["name"] and m["claim"] and isinstance(m["caveats"], list)
        for k in ("mode", "trade", "proposals", "requires_approval", "requires_acknowledgement", "text"):
            assert k in m["actions_allowed"], (m["id"], k)


def test_actions_allowed_follow_the_brief():
    by = {m["id"]: m["actions_allowed"] for m in ev.mechanisms()}
    assert by["ladders"]["mode"] == "proposals_with_approval" and by["ladders"]["requires_approval"]
    assert by["touch"]["mode"] == "proposals_behind_acknowledgement"
    assert by["touch"]["requires_acknowledgement"] and by["touch"]["requires_approval"]
    assert "hedge" in by["touch"]["text"]  # says the option-spread hedge is not offered
    assert by["btc_15min"] == {**by["btc_15min"], "mode": "watch_only", "trade": False, "proposals": False}
    assert by["other"]["mode"] == "none" and not by["other"]["trade"] and not by["other"]["proposals"]
    assert by["generic_ai_fit"]["mode"] == "available_unvalidated" and by["generic_ai_fit"]["requires_acknowledgement"]
    assert by["ticket_option_hedge"]["mode"] == "none" and not by["ticket_option_hedge"]["proposals"]
    assert by["foundation"]["mode"] == "reference_only" and not by["foundation"]["trade"]


@pytest.mark.parametrize("mid,n", list(_all_numbers()), ids=lambda x: x if isinstance(x, str) else x["label"][:40])
def test_every_number_has_a_range_a_sample_and_a_result_file(mid, n):
    assert n["label"]
    assert n["ci_low"] is not None and n["ci_high"] is not None and n["range_kind"]
    assert n["ci_low"] <= n["value"] <= n["ci_high"]
    assert n["range_kind"] in {"ci95", "ci90", "census", "percentiles", "none"} and n["range_desc"]
    if n["range_kind"] in ("census", "none"):
        assert n["ci_low"] == n["value"] == n["ci_high"] and n.get("note") or n["range_kind"] == "census"
    assert isinstance(n["sample"]["n"], int) and n["sample"]["n"] > 0 and n["sample"]["units"]
    assert isinstance(n["confirmatory"], bool)
    rf = n["result_file"]
    assert rf.startswith("research/results/")
    on_disk = (REPO / rf).is_file()
    assert n["result_file_on_disk"] is on_disk
    if not on_disk:  # only two files live off main; both name the branch and commit that hold them
        assert n.get("source_branch") and n.get("source_commit"), rf
        assert rf in (ev.S25, ev.LATENCY)


@pytest.mark.parametrize("mid,n", [(m, n) for m, n in _all_numbers() if (REPO / n["result_file"]).is_file()],
                         ids=lambda x: x if isinstance(x, str) else x["label"][:40])
def test_every_number_is_copied_from_its_result_file(mid, n):
    p = REPO / n["result_file"]
    raw = p.read_text()
    if p.suffix == ".json":
        found: list[float] = []

        def walk(o):
            if isinstance(o, bool):
                return
            if isinstance(o, (int, float)):
                found.append(float(o))
            elif isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(json.loads(raw))
    else:
        found = _floats(raw)
    for k in ("value", "ci_low", "ci_high"):
        assert _appears(n[k], found), (n["label"], k, n[k], n["result_file"])
    assert _appears(n["sample"]["n"], found), (n["label"], n["sample"])


def test_headline_numbers_match_the_note():
    by = {m["id"]: m for m in ev.mechanisms()}

    def num(mid, label_start):
        return next(n for n in by[mid]["numbers"] if n["label"].startswith(label_start))

    b = num("foundation", "Brier")
    assert (b["value"], b["ci_low"], b["ci_high"]) == (0.0108, 0.0064, 0.0158) and b["confirmatory"]
    assert b["sample"]["n"] == 7111 and [a["n"] for a in b["sample"]["also"]] == [4561, 89]
    reg = num("ladders", "Fresh ladders, rule as registered")
    assert (reg["value"], reg["ci_low"], reg["ci_high"], reg["sample"]["n"]) == (2.47, -1.14, 6.26, 650)
    assert reg["confirmatory"] and reg["sample"]["also"][0]["n"] == 221 and "NULL" in reg["note"]
    yf = num("ladders", "Fresh ladders, year parsed")
    assert (yf["value"], yf["ci_low"], yf["ci_high"], yf["sample"]["n"]) == (8.82, 6.73, 11.13, 562)
    assert yf["confirmatory"] is False and "Post hoc" in yf["note"]
    live = num("ladders", "Live sweep")
    assert live["value"] == 0 and live["sample"]["n"] == 34
    assert all(n["confirmatory"] is False for n in by["touch"]["numbers"] if n["label"].startswith("Seen data"))
    assert "INSUFFICIENT" in num("touch", "Fresh test")["note"]
    better, worse = num("generic_ai_fit", "Test window: markets where the chosen preset beat"), \
        num("generic_ai_fit", "Test window: markets where the chosen preset did worse")
    assert (better["value"], worse["value"], better["sample"]["n"]) == (19, 72, 122)
    hedge = by["ticket_option_hedge"]["numbers"][0]
    assert hedge["value"] > 1 and hedge["source_branch"] == "r/weekend-options"
    lat = {n["unit"]: n for n in ev.system_numbers()}
    assert (lat["microseconds"]["value"], lat["microseconds"]["ci_high"]) == (39.0, 3875.9)
    assert lat["microseconds"]["sample"]["n"] == 58610 and lat["nanoseconds per call"]["value"] == 158
    note = (REPO / "note" / "NOTE.md").read_text().replace("−", "-")
    for s in ("+0.0108", "+0.0064", "+0.0158", "+2.47", "-1.14", "+6.26", "+8.82", "+6.73", "+11.13", "650", "562",
              "7,111", "4,561", "89 resolution dates", "34 live date ladders", "39 µs", "3.9 ms", "58,610", "158 ns"):
        assert s in note, s


def test_forward_tests_start_monday_5_october_and_name_existing_files():
    by = {m["id"]: m for m in ev.mechanisms()}
    for mid, f in (("ladders", "research/ladder_replay/live.py"), ("touch", "research/touch_fresh/FORWARD.md")):
        ft = by[mid]["forward_test"]
        assert ft["starts"] == "2026-10-05" and ft["file"] == f and (REPO / f).is_file()


def test_mechanism_for_each_contract_type():
    assert ev.mechanism_for("ladder_rung")["id"] == "ladders"
    assert ev.mechanism_for("ladder_rung")["trade_mechanism"] is True
    assert ev.mechanism_for("touch_ticket")["id"] == "touch"
    assert ev.mechanism_for("touch_ticket")["actions_allowed"]["requires_acknowledgement"] is True
    # close-above tickets are not one of the brief's mechanisms: no tested mechanism, never the foundation's tag
    ca = ev.mechanism_for("close_above_ticket")
    assert ca["id"] == "other" and ca["status"] == ev.NO_TESTED_MECHANISM and ca["trade_mechanism"] is False
    assert ev.REFERENCE_FOR["close_above_ticket"] == "foundation"
    # the classifier's BTC watch mechanism reaches the watch-only entry
    for k in ("btc_15m_watch", "btc_15min"):
        b = ev.mechanism_for(k)
        assert b["id"] == "btc_15min" and b["status"] == ev.WATCH_ONLY and b["trade_mechanism"] is False
    assert ev.contract_key({"type": "other", "mechanism": "btc_15m_watch"}) == "btc_15min"
    assert ev.contract_key({"type": "touch_ticket"}) == "touch_ticket"
    for t in ("other", None, "", "something_new"):
        m = ev.mechanism_for(t)
        assert m["id"] == "other" and m["status"] == ev.NO_TESTED_MECHANISM and m["trade_mechanism"] is False


def test_route_serves_the_registry_and_the_old_evidence_route_still_works():
    with TestClient(create_app()) as c:
        r = c.get("/evidence/mechanisms")
        assert r.status_code == 200
        body = r.json()
        assert body["source_of_truth"] == "note/NOTE.md"
        assert {m["id"] for m in body["mechanisms"]} == {m["id"] for m in ev.MECHANISMS}
        assert body["contract_types"]["touch_ticket"] == "touch" and body["system"]
        old = c.get("/closed/evidence")
        assert old.status_code == 200 and "hedge_a" in old.json() and "validated_markets" in old.json()


def test_touch_sell_threshold_matches_the_frozen_forward_rule():
    text = (REPO / "research/touch_fresh/forward_config.py").read_text()
    m = re.search(r"^THRESHOLD = ([\d.]+)", text, re.M)
    assert m and float(m.group(1)) == ev.TOUCH_SELL_THRESHOLD_POINTS
    assert ev.registry()["touch_sell_threshold_points"] == ev.TOUCH_SELL_THRESHOLD_POINTS


def test_touch_entry_carries_the_sell_threshold_behind_the_ack_gate_and_no_hedge():
    t = ev.mechanism("touch")
    a = t["actions_allowed"]
    assert a["sell_threshold_points"] == ev.TOUCH_SELL_THRESHOLD_POINTS == 5.0
    assert a["side"] == "sell_yes" and a["hedge_offered"] is False
    assert a["proposals"] and a["requires_acknowledgement"] and a["requires_approval"]
    hedge = ev.mechanism("ticket_option_hedge")
    assert hedge["actions_allowed"]["proposals"] is False and hedge["actions_allowed"]["trade"] is False


def test_latency_is_marked_percentiles_not_a_confidence_interval():
    lat = next(n for n in ev.SYSTEM_NUMBERS if "Receive to decision" in n["label"])
    assert lat["range_kind"] == "percentiles" and lat["value"] == lat["ci_low"] == 39.0 and lat["ci_high"] == 3875.9
    assert "not a confidence interval" in lat["range_desc"]
    kinds = {n["range_kind"] for m in ev.MECHANISMS for n in m["numbers"]}
    assert "percentiles" not in kinds and "ci95" in kinds
