import datetime as dt
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cache import TTLCache
from app.closed import opportunity as opp
from app.closed import session as sc
from app.main import create_app
from app.options import chain as ch
from app.options.match import match_question

EXPIRY = "2026-12-18"
Q = "Will NVDA close above $150 on December 18, 2026?"
SAT = dt.datetime(2026, 10, 3, 16, 0, tzinfo=dt.timezone.utc)
MON_OPEN = dt.datetime(2026, 10, 5, 13, 30, tzinfo=dt.timezone.utc)
FRI_NS = int(dt.datetime(2026, 10, 2, 19, 59, tzinfo=dt.timezone.utc).timestamp() * 1e9)
MON_NS = int((MON_OPEN + dt.timedelta(minutes=2)).timestamp() * 1e9)


def row(kind, strike, bid, ask, upd=FRI_NS):
    return {"details": {"contract_type": kind, "strike_price": strike, "expiration_date": EXPIRY,
                        "ticker": f"O:NVDA261218{kind[0].upper()}{int(strike * 1000):08d}"},
            "greeks": {"delta": 0.5 if kind == "call" else -0.5}, "implied_volatility": 0.4,
            "last_quote": {"bid": bid, "ask": ask, "last_updated": upd},
            "underlying_asset": {"price": 150.0, "timeframe": "DELAYED"}}


def book_rows(c_lo=(7.9, 8.1), c_hi=(2.9, 3.1), p_lo=(1.95, 2.05), p_hi=(6.5, 6.7), upd=FRI_NS):
    return [row("call", 145.0, *c_lo, upd=upd), row("call", 155.0, *c_hi, upd=upd),
            row("put", 145.0, *p_lo, upd=upd), row("put", 155.0, *p_hi, upd=upd)]


class _Resp:
    def __init__(self, p):
        self.p, self.status_code = p, 200

    def json(self):
        return self.p

    def raise_for_status(self):
        pass


class FakeMassive:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0
        self.session = self

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return _Resp({"results": self.rows})


def _snap(pm_yes=0.50, rows=None):
    m = match_question(Q, EXPIRY, as_of=dt.date(2026, 10, 2))
    chain = ch.parse_snapshot("NVDA", [{"results": rows or book_rows()}])
    s = opp.build_snapshot({"source": "polymarket", "id": "t1", "question": Q, "end_date": EXPIRY}, m, chain,
                           now=SAT, pm_yes=pm_yes)
    s["id"] = "snap-test"
    return s


def test_snapshot_records_close_estimate_and_both_spreads():
    s = _snap()
    assert s["available"] and s["close_day"] == "2026-10-02" and s["taken_phase"] == "weekend"
    assert s["next_open"] == "2026-10-05T13:30:00Z"
    o = s["option"]
    DF = math.exp(-0.04 * (77 / 365))
    assert o["method"] == "call_spread" and (o["k_lo"], o["k_hi"]) == (145.0, 155.0) and o["expiry"] == EXPIRY
    assert o["prob"] == pytest.approx(0.5 / DF) and o["hi"] == pytest.approx(0.52 / DF)
    assert {(lg["kind"], lg["strike"]) for lg in s["legs"]} == {("call", 145.0), ("call", 155.0),
                                                                 ("put", 145.0), ("put", 155.0)}
    assert "not a measured edge" in s["label"]
    assert any("after the close" in n for n in s["notes"])


def test_evaluate_stages_yes_spread_when_options_have_not_caught_up():
    d = opp.evaluate(_snap(), 0.62)
    assert d["supported"] and d["decision"] == "stage" and d["reason_code"] == "stage_yes_spread"
    assert d["side"] == "yes" and d["structure"] == "call_spread" and d["opt_ref_source"] == "friday_close"
    assert d["pm_move"] == pytest.approx(0.12) and d["opt_move"] == 0 and d["residual"] == pytest.approx(0.12)
    assert "not a measured edge" in d["label"]


def test_evaluate_stages_no_spread_on_a_down_move():
    d = opp.evaluate(_snap(), 0.38)
    assert d["decision"] == "stage" and d["side"] == "no" and d["structure"] == "put_spread"


@pytest.mark.parametrize("pm_now, code", [
    (0.52, "pm_move_small"),
    (0.515, "pm_move_small"),
    (None, "pm_unavailable"),
])
def test_evaluate_small_or_missing_moves_do_nothing(pm_now, code):
    d = opp.evaluate(_snap(), pm_now)
    assert d["decision"] == "none" and d["reason_code"] == code


def test_evaluate_refuses_when_options_already_past_pm_or_inside_spread():
    assert opp.evaluate(_snap(pm_yes=0.40), 0.48)["reason_code"] == "options_already_past_pm"
    assert opp.evaluate(_snap(pm_yes=0.48), 0.52)["reason_code"] == "gap_within_spread"


def test_evaluate_at_the_open_cancels_when_options_caught_up():
    s = _snap()
    mon = ch.parse_snapshot("NVDA", [{"results": book_rows(c_lo=(10.4, 10.6), c_hi=(4.4, 4.6), upd=MON_NS)}])
    now_est = opp.implied_now(s, mon, now=MON_OPEN + dt.timedelta(minutes=3))
    assert now_est["available"] and now_est["since_open"] and now_est["same_expiry"]
    d = opp.evaluate(s, 0.62, now_est)
    assert d["reason_code"] == "options_caught_up" and d["opt_ref_source"] == "open"
    assert d["catch_up"] == pytest.approx(d["opt_move"] / d["pm_move"], rel=1e-3) and d["catch_up"] > 0.8


def test_unavailable_snapshot_is_not_supported():
    m = match_question(Q, EXPIRY, as_of=dt.date(2026, 10, 2))
    s = opp.build_snapshot({"question": Q, "end_date": EXPIRY}, m, None, now=SAT, pm_yes=0.5,
                           reason_code="no_options_key")
    d = opp.evaluate(s, 0.7)
    assert not s["available"] and not d["supported"] and d["reason_code"] == "no_options_key"


def test_price_structure_and_caps():
    s = _snap()
    c = opp.close_chain(s)
    yes = opp.price_structure(c, "call_spread", EXPIRY, 145.0, 155.0)
    assert yes["quote"]["mid"] == pytest.approx(5.0) and yes["debit"] == pytest.approx(5.2)
    assert yes["unit_risk"] == pytest.approx(520.0) and yes["max_payoff"] == pytest.approx(1000.0)
    assert [(lg["sign"], lg["kind"], lg["strike"]) for lg in yes["legs"]] == [(1, "call", 145.0), (-1, "call", 155.0)]
    no = opp.price_structure(c, "put_spread", EXPIRY, 145.0, 155.0)
    assert no["debit"] == pytest.approx(4.6 + 0.1 + 0.05)
    assert opp.size(5, 10, 10_000, 520.0) == (5, None)
    assert opp.size(5, 3, 10_000, 520.0) == (3, "max_contracts")
    assert opp.size(5, 10, 1_000, 520.0) == (1, "max_notional")
    assert opp.size(5, 10, 500, 520.0) == (0, "max_notional")
    assert opp.size(5, 10, 10_000, 520.0, book_room=1100.0) == (2, "book_notional")
    assert opp.size(5, 10, 10_000, 520.0, book_room=0.0) == (0, "book_notional")
    assert yes["unit_cost"] == pytest.approx(520.0 + 2 * 0.65)
    assert opp.size(10, 10, 10_000, 1000.0 + 2 * 0.65) == (9, "max_notional")
    missing = opp.price_structure(c, "call_spread", EXPIRY, 145.0, 160.0)
    assert missing["reason_code"] == "legs_not_listed"


def test_stage_trade_refuses_without_a_stage_decision_or_room():
    s = _snap()
    with pytest.raises(ValueError, match="pm_move_small"):
        opp.stage_trade(s, opp.evaluate(s, 0.51), now=SAT)
    with pytest.raises(ValueError, match="cap_used_up"):
        opp.stage_trade(s, opp.evaluate(s, 0.62), now=SAT, max_notional=100)
    t = opp.stage_trade(s, opp.evaluate(s, 0.62), now=SAT, contracts=3)
    assert t["status"] == "staged" and t["approval_required"] and t["simulated"]
    assert t["not_before"] == "2026-10-05T13:30:00Z" and t["window_end"] == "2026-10-05T14:00:00Z"
    assert t["qty_estimate"] == 3 and t["events"][-1]["reason_code"] == "awaiting_approval"


def test_review_cancels_when_the_pm_reverts():
    s = _snap()
    t = opp.stage_trade(s, opp.evaluate(s, 0.62), now=SAT)
    opp.review_trade(t, s, 0.505, now=SAT + dt.timedelta(hours=20))
    assert t["status"] == "cancelled" and t["events"][-1]["reason_code"] == "pm_reverted"
    assert t["events"][-1]["detail"] == "pm_move_small"


def test_research_status_pending_until_a_result_says_supported(tmp_path):
    assert opp.research_status(tmp_path)["status"] == "pending"
    d = tmp_path / "research/results/options_catchup"
    d.mkdir(parents=True)
    (d / "tests.json").write_text(json.dumps({"supported": False, "verdict": "null"}))
    r = opp.research_status(tmp_path)
    assert r["status"] == "null" and not r["supports_claim"]
    (d / "tests.json").write_text(json.dumps({"supported": True}))
    assert opp.research_status(tmp_path)["supports_claim"]


@pytest.mark.parametrize("verdict, status, claim", [
    ("PASS", "supported", True), ("NULL", "null", False), ("SAMPLE TOO SMALL", "insufficient", False),
])
def test_research_status_reads_the_r3_study_stats_file(tmp_path, verdict, status, claim):
    d = tmp_path / "research/results/open_options"
    d.mkdir(parents=True)
    (d / "events.csv").write_text("x\n")
    (d / "stats.json").write_text(json.dumps({"verdict": verdict, "primary": {"n": 40, "clusters": 9},
                                              "subsets": {}, "follow_through": {}, "brier": {}}))
    r = opp.research_status(tmp_path)
    assert r["status"] == status and r["supports_claim"] is claim and r["verdict"] == verdict
    assert r["path"] == "research/results/open_options/stats.json"


def test_book_refuses_to_replace_a_snapshot_in_use_and_keeps_the_close_price(tmp_path):
    b = opp.OpportunityBook(tmp_path / "b.json")
    s = b.put_snapshot(_snap(pm_yes=0.50))
    later = {**_snap(pm_yes=0.62), "taken_at": "2026-10-04T18:00:00Z"}
    r = b.put_snapshot(later)
    assert r["id"] == s["id"] and r["pm_yes"] == 0.50 and r["revision"] == 2
    assert any("PM close price kept" in n for n in r["notes"])
    assert b.put_snapshot(_snap(pm_yes=0.48), pm_explicit=True)["pm_yes"] == 0.48
    b.put_trade(opp.stage_trade(b.snapshots[s["id"]], opp.evaluate(b.snapshots[s["id"]], 0.62), now=SAT))
    with pytest.raises(ValueError, match="snapshot_in_use"):
        b.put_snapshot(_snap(pm_yes=0.62), pm_explicit=True)
    assert b.snapshots[s["id"]]["pm_yes"] == 0.48


def test_book_exposure_totals_open_opportunity_trades(tmp_path):
    b = opp.OpportunityBook(tmp_path / "b.json")
    s = b.put_snapshot(_snap())
    t = b.put_trade(opp.stage_trade(s, opp.evaluate(s, 0.62), now=SAT, contracts=3))
    assert b.exposure(SAT) == pytest.approx(3 * (520 + 1.3))
    assert b.book_room(SAT) == pytest.approx(opp.BOOK_MAX_NOTIONAL - 3 * 521.3)
    assert b.exposure(SAT, exclude=t["id"]) == 0
    t["status"], t["execution"] = "executed", {"cost": 1500.0}
    assert b.exposure(SAT) == 1500.0
    assert b.exposure(dt.datetime(2026, 12, 21, 15, tzinfo=dt.timezone.utc)) == 0
    with pytest.raises(ValueError, match="book_cap_used_up"):
        opp.stage_trade(s, opp.evaluate(s, 0.62), now=SAT, book_room=100.0)


def test_book_persists_snapshots_and_trades(tmp_path):
    b = opp.OpportunityBook(tmp_path / "b.json")
    s = b.put_snapshot(_snap())
    assert s["id"].startswith("snap-") and b.latest_for("polymarket:t1")["id"] == s["id"]
    b.put_trade(opp.stage_trade(s, opp.evaluate(s, 0.62), now=SAT))
    b2 = opp.OpportunityBook(tmp_path / "b.json")
    assert set(b2.snapshots) == {s["id"]} and len(b2.trades) == 1 and b2.active_trade(s["id"])


@pytest.fixture
def env(monkeypatch, tmp_path):
    state = {"now": SAT, "yes": 0.50, "massive": FakeMassive(book_rows()), "gamma_down": False}

    def reset_chain_cache():
        monkeypatch.setattr(ch, "_CACHE", TTLCache(60))
        monkeypatch.setattr(ch, "_LAST", {})
        monkeypatch.setattr(ch, "_FOR", {})

    reset_chain_cache()
    monkeypatch.setenv("CLOSED_OPPORTUNITY_PATH", str(tmp_path / "opp.json"))
    monkeypatch.setattr(opp, "make_client", lambda: state["massive"])
    monkeypatch.setattr(opp, "REPO", tmp_path)

    def gamma(req: httpx.Request):
        if "gamma-api" in str(req.url):
            if state["gamma_down"]:
                return httpx.Response(503, json={})
            return httpx.Response(200, json={"question": Q, "endDate": "2026-12-18T21:00:00Z",
                                             "outcomePrices": json.dumps([str(state["yes"]), str(1 - state["yes"])])})
        return httpx.Response(404, json={})

    app = create_app()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(gamma))
    app.state.closed_clock = lambda: state["now"]
    state["client"], state["app"], state["reset"] = TestClient(app), app, reset_chain_cache
    return state


def _snapshot(env):
    r = env["client"].post("/closed/opportunity/snapshot", json={"market_source": "polymarket",
                                                                 "market_id": "pm-test-1", "pm_yes": 0.50})
    assert r.status_code == 200, r.text
    return r.json()


def _to_monday(env, rows):
    env["now"] = MON_OPEN + dt.timedelta(minutes=5)
    env["massive"] = FakeMassive(rows)
    env["reset"]()


def test_route_full_weekend_flow_executes_a_simulated_combo(env, monkeypatch, tmp_path):
    monkeypatch.setattr(opp, "REPO", tmp_path)
    c = env["client"]
    s = _snapshot(env)
    assert s["stored"] and s["supported"] and s["pm_yes"] == 0.50 and s["pm_source"] == "supplied"
    st = c.get("/closed/opportunity").json()
    assert st["supported"] and st["display"] == "estimate" and st["research"]["status"] == "pending"
    assert st["session"]["phase"] == "weekend"

    env["yes"] = 0.62
    cmp_ = c.get("/closed/opportunity/compare", params={"snapshot_id": s["id"]}).json()
    assert cmp_["supported"] and cmp_["comparison"]["reason_code"] == "stage_yes_spread"
    assert cmp_["pm_source"] == "live"

    r = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True, "contracts": 2})
    assert r.status_code == 201, r.text
    tr = r.json()
    assert tr["status"] == "staged" and tr["structure"]["kind"] == "call_spread" and tr["qty_estimate"] == 2
    assert c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).status_code == 409

    r = c.post(f"/closed/opportunity/trades/{tr['id']}/execute")
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "awaiting_approval"
    assert c.post(f"/closed/opportunity/trades/{tr['id']}/approve").json()["status"] == "approved"
    r = c.post(f"/closed/opportunity/trades/{tr['id']}/execute")
    assert r.json()["outcome"] == "held" and r.json()["reason_code"] == "before_open"

    _to_monday(env, book_rows(upd=MON_NS))
    r = c.post("/closed/opportunity/execute-due")
    res = r.json()["results"]
    assert len(res) == 1 and res[0]["outcome"] == "executed", res
    ex = c.get(f"/closed/opportunity/trades/{tr['id']}").json()
    assert ex["status"] == "executed" and ex["execution"]["simulated"] and ex["execution"]["qty"] == 2
    assert ex["execution"]["net_debit"] == pytest.approx(8.1 - 2.9)
    assert ex["events"][-1]["reason_code"] == "filled"
    orders = c.get("/orders").json()
    legs = [o for o in orders if o["combo_id"] == tr["id"]]
    assert len(legs) == 2 and all(o["status"] == "filled" and o["broker"] == "sim" for o in legs)
    assert all("simulated" in o["note"] for o in legs) and {o["side"] for o in legs} == {"buy", "sell"}
    pos = {p["symbol"]: p["qty"] for p in c.get("/positions").json()}
    assert pos == {legs[0]["symbol"]: (2 if legs[0]["side"] == "buy" else -2),
                   legs[1]["symbol"]: (2 if legs[1]["side"] == "buy" else -2)}


def test_route_cancels_at_the_open_when_options_caught_up(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    _to_monday(env, book_rows(c_lo=(10.4, 10.6), c_hi=(4.4, 4.6), upd=MON_NS))
    cmp_ = c.get("/closed/opportunity/compare", params={"snapshot_id": s["id"], "refresh_options": True}).json()
    assert cmp_["comparison"]["reason_code"] == "options_caught_up" and cmp_["opt_now"]["since_open"]
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "cancelled" and r["reason_code"] == "options_caught_up"
    assert [o for o in c.get("/orders").json() if o["combo_id"] == tid] == []


def test_route_holds_on_stale_quotes_then_expires(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    _to_monday(env, book_rows(upd=FRI_NS))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "held" and r["reason_code"] == "quotes_not_updated_since_open"
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert c.get(f"/closed/opportunity/trades/{tid}").json()["events"][-1].get("count") == 2
    env["now"] = MON_OPEN + dt.timedelta(minutes=31)
    res = c.post("/closed/opportunity/execute-due").json()["results"]
    assert res[0]["outcome"] == "expired" and res[0]["reason_code"] == "missed_open_window"


def test_route_caps_bind_at_execution(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True, "contracts": 5,
                                                     "max_notional": 1200}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    _to_monday(env, book_rows(upd=MON_NS))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "executed" and r["execution"]["qty"] == 2 and r["execution"]["cap"] == "max_notional"
    assert c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True, "max_notional": 20_000}).status_code == 422


def test_route_stage_refused_with_reason_code_when_nothing_to_do(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.51
    r = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "pm_move_small"


def test_route_review_cancels_reverted_trades(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    env["yes"] = 0.50
    res = c.post("/closed/opportunity/review").json()["results"]
    assert res[0]["status"] == "cancelled"
    assert c.get(f"/closed/opportunity/trades/{tid}").json()["events"][-1]["reason_code"] == "pm_reverted"


def test_route_unsupported_no_key_and_market_open(env, monkeypatch):
    c = env["client"]
    r = c.post("/closed/opportunity/snapshot", json={"question": "Will Bitcoin hit $200k in 2026?"}).json()
    assert not r["stored"] and not r["supported"] and r["reason_code"] == "unsupported_question"
    monkeypatch.setattr(opp, "make_client", lambda: None)
    r = c.post("/closed/opportunity/snapshot", json={"question": Q, "end_date": EXPIRY, "pm_yes": 0.5}).json()
    assert r["stored"] and not r["supported"] and r["reason_code"] == "no_options_key"
    assert not c.get("/closed/opportunity").json()["supported"]
    env["now"] = MON_OPEN + dt.timedelta(hours=1)
    r = c.post("/closed/opportunity/snapshot", json={"question": Q, "end_date": EXPIRY}).json()
    assert r["reason_code"] == "market_open" and not r["stored"]
    assert c.get("/closed/opportunity/compare", params={"snapshot_id": "nope"}).status_code == 404


def test_remote_caller_cannot_supply_the_pm_price(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.50
    r = c.get("/closed/opportunity/compare", params={"snapshot_id": s["id"], "pm_yes": 0.9},
              headers={"X-Forwarded-For": "1.2.3.4"}).json()
    assert r["pm_source"] == "live" and r["comparison"]["pm_now"] == 0.50
    assert sc.to_utc(s["next_open"]) == MON_OPEN


def test_route_universe_fallback_price_never_feeds_a_decision(env, monkeypatch):
    from app.options import router as orouter
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    monkeypatch.setattr(orouter, "_universe", lambda source, mid, data_dir=None: {
        "question": Q, "end_date": EXPIRY, "yes_price": 0.80})
    env["gamma_down"] = True
    cmp_ = c.get("/closed/opportunity/compare", params={"snapshot_id": s["id"]}).json()
    assert cmp_["pm_source"] == "universe" and cmp_["comparison"]["pm_now"] is None
    assert cmp_["comparison"]["reason_code"] == "pm_unavailable" and cmp_["comparison"]["decision"] == "none"
    assert c.post(f"/closed/opportunity/trades/{tid}/cancel").status_code == 200
    r = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "pm_unavailable"
    env["gamma_down"] = False
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    env["gamma_down"] = True
    res = c.post("/closed/opportunity/review").json()["results"]
    assert res[0]["status"] == "approved" and res[0]["comparison"]["reason_code"] == "pm_unavailable"
    _to_monday(env, book_rows(upd=MON_NS))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "held" and r["reason_code"] == "pm_unavailable"
    assert [o for o in c.get("/orders").json() if o["combo_id"] == tid] == []
    env["now"] = SAT
    r = c.post("/closed/opportunity/snapshot", json={"market_source": "polymarket", "market_id": "pm-other"}).json()
    assert r["stored"] and r["pm_yes"] is None and r["pm_source"] is None and not r["supported"]
    assert any("fell back to universe" in n for n in r["notes"])


def test_route_resnapshot_refused_while_a_trade_uses_it(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    env["now"] = SAT + dt.timedelta(days=1)
    r = c.post("/closed/opportunity/snapshot", json={"market_source": "polymarket", "market_id": "pm-test-1"})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "snapshot_in_use"
    assert r.json()["detail"]["trade_id"] == tid
    assert c.get("/closed/opportunity/compare", params={"snapshot_id": s["id"]}).json()["snapshot"]["pm_yes"] == 0.50
    _to_monday(env, book_rows(upd=MON_NS))
    assert c.post(f"/closed/opportunity/trades/{tid}/execute").json()["outcome"] == "executed"


def test_route_resnapshot_without_trade_keeps_the_friday_price(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    env["now"] = SAT + dt.timedelta(days=1)
    r = c.post("/closed/opportunity/snapshot", json={"market_source": "polymarket", "market_id": "pm-test-1"}).json()
    assert r["id"] == s["id"] and r["pm_yes"] == 0.50 and r["pm_source"] == "supplied" and r["revision"] == 2
    cmp_ = c.get("/closed/opportunity/compare", params={"snapshot_id": s["id"]}).json()
    assert cmp_["comparison"]["reason_code"] == "stage_yes_spread"


def test_route_pm_source_reflects_the_price_origin_not_the_question(env):
    c = env["client"]
    r = c.post("/closed/opportunity/snapshot", json={"market_source": "polymarket", "market_id": "pm-test-1",
                                                     "question": Q, "end_date": EXPIRY}).json()
    assert r["stored"] and r["market"]["origin"] == "request" and r["pm_source"] == "live"


def test_route_book_cap_spans_trades(env, monkeypatch):
    c = env["client"]
    monkeypatch.setattr(opp, "BOOK_MAX_NOTIONAL", 1200.0)
    s = _snapshot(env)
    env["yes"] = 0.62
    r = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True, "contracts": 5})
    assert r.status_code == 201 and r.json()["qty_estimate"] == 2 and r.json()["cap_estimate"] == "book_notional"
    s2 = c.post("/closed/opportunity/snapshot", json={"market_source": "polymarket", "market_id": "pm-test-2",
                                                      "pm_yes": 0.50}).json()
    r2 = c.post("/closed/opportunity/trades", json={"snapshot_id": s2["id"], "ack_unvalidated": True})
    assert r2.status_code == 409 and r2.json()["detail"]["reason_code"] == "book_cap_used_up"
    st = c.get("/closed/opportunity").json()["book"]
    assert st["max_notional"] == 1200.0 and st["exposure"] == pytest.approx(2 * 521.3)


def test_route_simulated_orders_carry_the_decision_time(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()["id"]
    c.post(f"/closed/opportunity/trades/{tid}/approve")
    _to_monday(env, book_rows(upd=MON_NS))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    at = r["execution"]["at"]
    assert at == "2026-10-05T13:35:00Z" and r["execution"]["broker_filled_at"]
    legs = [o for o in c.get("/orders").json() if o["combo_id"] == tid]
    assert legs and all(f"decided at {at}" in o["note"] for o in legs)


def test_committed_r3_result_is_null_and_supports_no_claim():
    st = opp.research_status(opp.REPO)
    assert st["status"] == "null" and st["supports_claim"] is False


def _with_liquidity(rows, volume, oi):
    return [{**r, "day": {"volume": volume}, "open_interest": oi} for r in rows]


def _staged_and_approved(env, contracts=5):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    tid = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "contracts": contracts,
                                                     "ack_unvalidated": True}).json()["id"]
    assert c.post(f"/closed/opportunity/trades/{tid}/approve").json()["status"] == "approved"
    return tid


def test_staging_on_an_unvalidated_signal_needs_the_acknowledgement(env):
    c = env["client"]
    s = _snapshot(env)
    env["yes"] = 0.62
    r = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"]})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "evidence_unvalidated"
    assert c.get("/closed/opportunity/trades").json() == []
    tr = c.post("/closed/opportunity/trades", json={"snapshot_id": s["id"], "ack_unvalidated": True}).json()
    assert tr["ack_unvalidated"] is True and tr["evidence"] == "unvalidated (acknowledged)"


def test_execution_cuts_the_combo_to_the_option_participation_cap(env):
    c = env["client"]
    tid = _staged_and_approved(env, contracts=5)
    _to_monday(env, _with_liquidity(book_rows(upd=MON_NS), volume=30, oi=1_000))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "executed", r
    ex = r["trade"]["execution"]
    assert ex["qty"] == 3 and ex["cap"] == "liquidity_capped" and ex["gates"]["liquidity"]["status"] == "capped"
    assert ex["gates"]["capital"]["ok"] is True and ex["gates"]["capital"]["risk_usd"] > 0


def test_execution_refuses_when_the_participation_cap_allows_nothing(env):
    c = env["client"]
    tid = _staged_and_approved(env)
    _to_monday(env, _with_liquidity(book_rows(upd=MON_NS), volume=5, oi=1_000))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "rejected" and r["reason_code"] == "liquidity_capped"
    assert [o for o in c.get("/orders").json() if o["combo_id"] == tid] == []


def test_execution_refuses_a_trade_the_capital_budget_does_not_allow(env):
    c = env["client"]
    tid = _staged_and_approved(env)
    env["app"].state.capital_limits = {"max_gross_hedge_pct": 0.0001, "max_event_pct": 0.0001}
    _to_monday(env, book_rows(upd=MON_NS))
    r = c.post(f"/closed/opportunity/trades/{tid}/execute").json()
    assert r["outcome"] == "rejected" and r["reason_code"] == "capital_budget", r
    assert [o for o in c.get("/orders").json() if o["combo_id"] == tid] == []
