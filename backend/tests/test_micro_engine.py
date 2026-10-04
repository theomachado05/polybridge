import pytest

from app.closed import evidence as ev
from app.contracts import engine, live

HAS_ENGINE = engine.available()
needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason="hedgecore micro families not compiled")
NOW = 1_800_000_000 * 10**9


def leg(bid=None, ask=None, rate=0.0, tick=0.01):
    return {"tick": tick, "fee_rate": rate, "fee_exponent": 1.0, "best_bid": bid, "best_ask": ask,
            "bid_size": 50.0, "ask_size": 70.0}


def python_actionable(bid, ask, a, b, nested=True):
    e = live.pair_edge(bid, ask, a, b)
    return bool(e is not None and e > 0 and nested)


def test_registry_names_the_presets_and_the_threshold_agrees():
    lp = ev.mechanism("ladders")["engine_preset"]
    tp = ev.mechanism("touch")["engine_preset"]
    assert lp["family"] == "ladder_pair" and lp["index"] == 4
    assert lp["params"] == {"min_edge": 1.0, "max_age_s": 60.0, "cap": 100.0}
    assert tp["family"] == "touch_ticket_reference" and tp["index"] == 0
    assert tp["params"]["threshold"] == ev.TOUCH_SELL_THRESHOLD_POINTS == \
        ev.mechanism("touch")["actions_allowed"]["sell_threshold_points"]


@needs_engine
def test_preset_index_4_is_the_registry_params_in_the_compiled_grid():
    import hedgecore

    from app.pipeline.engine_adapter import preset_grid
    fam = {f["id"]: f for f in hedgecore.catalog()["micro_families"]}["ladder_pair"]
    g = preset_grid({"params": fam["params"]})
    assert len(g) == fam["preset_count"] == 18
    assert {k: g[4][k] for k in ("min_edge", "max_age_s", "cap")} == ev.mechanism("ladders")["engine_preset"]["params"]


@needs_engine
def test_ladder_parity_with_python_rule_on_a_cent_grid():
    diffs = []
    for rate in (0.0, 0.02, 0.0625):
        for bid in [x / 100 for x in range(2, 99, 3)]:
            for ask in [x / 100 for x in range(2, 99, 3)]:
                a, b = leg(bid=bid, rate=rate), leg(ask=ask, rate=rate)
                c = engine.decide_ladder(engine.ladder_tick({}, a, b, True, NOW), NOW)
                assert c["source"] == "engine" and c["family"] == "ladder_pair" and c["preset"] == 4
                if (c["action"] == "order") != python_actionable(bid, ask, a, b):
                    diffs.append((rate, bid, ask, live.pair_edge(bid, ask, a, b)))
    assert all(r == 0.0 and abs(e) < 1e-9 for r, _, _, e in diffs), diffs


@needs_engine
def test_ladder_engine_refuses_unnested_stale_and_reports_legs():
    a, b = leg(bid=0.40), leg(ask=0.35)
    o = engine.decide_ladder(engine.ladder_tick({}, a, b, True, NOW), NOW)
    assert o["action"] == "order" and o["reason"] == "entry" and o["latency_ns"] >= 0
    assert o["sizes"] == {"rich": 50.0, "cheap": 50.0} and o["limit_prices"] == {"rich": 0.40, "cheap": 0.35}
    for nested in (False, None):
        assert engine.decide_ladder(engine.ladder_tick({}, a, b, nested, NOW), NOW)["reason"] == "not_nested"
    old = dict(a, book_ts_ns=NOW - 61 * 10**9)
    assert engine.decide_ladder(engine.ladder_tick({}, old, b, True, NOW), NOW)["reason"] == "stale"


@needs_engine
def test_ticket_parity_and_proposals_only():
    ref = lambda c: {"available": True, "ok": True, "central": {"kind": "touch", "mid": c}, "lower_bound": c / 2}
    for bid in [x / 100 for x in range(5, 95, 2)]:
        for central in [x / 100 for x in range(5, 95, 4)]:
            row = {"best_bid": bid, "best_ask": min(0.99, bid + 0.02), "bid_size": 25.0}
            c = engine.decide_ticket(engine.ticket_tick(row, ref(central), NOW), NOW)
            py = 100 * (bid - central) >= ev.TOUCH_SELL_THRESHOLD_POINTS - 1e-9
            assert c["action"] == ("propose" if py else "hold"), (bid, central, c)
            assert c["action"] != "order"
    crossed = {"best_bid": 0.40, "best_ask": 0.38, "bid_size": 5.0}
    assert engine.decide_ticket(engine.ticket_tick(crossed, ref(0.2), NOW), NOW)["action"] == "hold"


def _fixture_ladder():
    rich = {"id": "2", "token": "t2", "tick": 0.01, "fee_rate": 0.0, "fee_exponent": 1.0}
    cheap = {"id": "1", "token": "t1", "tick": 0.01, "fee_rate": 0.0, "fee_exponent": 1.0}
    lad = {"valid": True, "rungs": [rich, cheap], "pairs": [{"rich": "2", "cheap": "1", "nested": True}]}
    bk = {"t2": {"bids": [{"price": "0.40", "size": "30"}], "asks": [{"price": "0.42", "size": "30"}]},
          "t1": {"bids": [{"price": "0.30", "size": "80"}], "asks": [{"price": "0.35", "size": "80"}]}}
    return lad, bk


@needs_engine
def test_price_ladders_uses_the_engine():
    lad, bk = _fixture_ladder()
    live.price_ladders([lad], bk, NOW)
    p = lad["pairs"][0]
    assert p["engine"]["source"] == "engine" and p["engine"]["family"] == "ladder_pair" and p["engine"]["preset"] == 4
    assert p["actionable"] and p["engine"]["action"] == "order" and p["engine"]["sizes"] == {"rich": 30.0, "cheap": 30.0}


def test_price_ladders_falls_back_to_python_when_no_engine(monkeypatch):
    monkeypatch.setattr(engine, "_module", lambda: None)
    lad, bk = _fixture_ladder()
    live.price_ladders([lad], bk, NOW)
    p = lad["pairs"][0]
    assert p["engine"] == {"family": "ladder_pair", "source": "python_fallback", "action": "order",
                           "reason": "python: edge after fees and a tick per leg > 0, nested"}
    assert p["actionable"] and "latency_ns" not in p["engine"]
    lad["pairs"][0]["nested"] = False
    live.price_ladders([lad], bk, NOW)
    assert not lad["pairs"][0]["actionable"] and lad["pairs"][0]["engine"]["action"] == "hold"


def _ticket(bid, central):
    return {"type": "touch_ticket", "linkable": True, "best_bid": bid, "best_ask": bid + 0.02, "bid_size": 10.0,
            "reference": {"available": True, "ok": True, "central": {"kind": "touch", "mid": central}}}


def test_decide_ticket_fallback_labels_python(monkeypatch):
    monkeypatch.setattr(engine, "_module", lambda: None)
    hi, lo = _ticket(0.40, 0.30), _ticket(0.33, 0.30)
    live.decide_ticket(hi, 5.0, NOW)
    live.decide_ticket(lo, 5.0, NOW)
    assert hi["engine"]["source"] == "python_fallback" and hi["engine"]["action"] == "propose" and hi["propose"]
    assert lo["engine"]["action"] == "hold" and not lo["propose"]


@needs_engine
def test_decide_ticket_engine():
    hi, lo = _ticket(0.40, 0.30), _ticket(0.33, 0.30)
    live.decide_ticket(hi, 5.0, NOW)
    live.decide_ticket(lo, 5.0, NOW)
    assert hi["engine"]["source"] == "engine" and hi["engine"]["action"] == "propose" and hi["propose"]
    assert hi["engine"]["reason"] == "proposal" and lo["engine"]["action"] == "hold" and not lo["propose"]


def test_no_engine_block_without_reference():
    t = _ticket(0.4, 0.3)
    t["reference"] = {"available": False, "ok": False}
    live.decide_ticket(t, 5.0, NOW)
    assert "engine" not in t


def test_registry_serves_micro_bench_with_sample_and_tape():
    mb = ev.registry()["micro_bench"]
    assert [b["family"] for b in mb] == ["ladder_pair", "touch_ticket_reference"]
    assert all(b["sample"] and "LCG seed 42" in b["tape"] and b["result_file"] == "engine/hedgecore/BENCH.md" for b in mb)
    assert (mb[0]["mean_ns"], mb[1]["mean_ns"]) == (26.5, 26.3)
