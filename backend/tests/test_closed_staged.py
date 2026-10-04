import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app.broker import BrokerError, Order, OrderRequest, SimBroker
from app.broker.models import now_iso
from app.broker.quotes import Quote
from app.closed import gap as gapsvc
from app.closed import staged
from app.closed.tracker import market_key, tracker_for
from app.main import create_app
from app.models import MarketRef
from tests.test_broker_support import FakeQuotes, run

UTC = dt.timezone.utc
FRI_CLOSE = dt.datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
SAT_NOON = dt.datetime(2026, 10, 3, 16, 0, tzinfo=UTC)
MON_PRE = dt.datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
MON_OPEN = dt.datetime(2026, 10, 5, 13, 30, tzinfo=UTC)
MON_CLOSE = dt.datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
KEY = market_key("polymarket", "m1")
POOLED = gapsvc.POOLED_RATE


@pytest.fixture(autouse=True)
def _pooled_rates(monkeypatch):
    monkeypatch.setattr(gapsvc, "load_rates", lambda path=None: gapsvc.GapRates())


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class NoExtSim(SimBroker):
    extended_hours = False


class RestingBroker:
    name = "fake"
    extended_hours = True

    def __init__(self):
        self.placed: list[OrderRequest] = []
        self.cancelled: list[str] = []
        self._orders: list[Order] = []

    async def place_order(self, req):
        self.placed.append(req)
        o = Order(id=f"f-{len(self.placed)}", client_order_id=req.client_order_id, broker=self.name, symbol=req.symbol,
                  asset=req.asset, side=req.side, qty=req.qty, type=req.type, limit_px=req.limit_px, status="open",
                  created_at=now_iso(), tag=req.tag)
        self._orders.append(o)
        return o.model_copy()

    async def orders(self, status=None):
        return [o.model_copy() for o in self._orders if status is None or o.status == status]

    async def cancel(self, oid):
        o = next(o for o in self._orders if oid in (o.id, o.client_order_id))
        o.status = "cancelled"
        self.cancelled.append(oid)
        return o.model_copy()

    async def account(self): ...
    async def positions(self): return []


class StubBridge:
    def __init__(self, prop, broker, source="live", ts=None, bid="br1"):
        self.id, self.proposal_id, self.proposal = bid, prop.id, prop
        self.direction, self.market = prop.direction, prop.market
        self.effective_source, self.last_replay_ts_ns = source, ts
        self.broker_hedge = self.account_hedge = 0.0
        self.resting = None
        self.pm = None
        self._broker = broker

    def order_broker(self):
        return self._broker

    def _sandboxed(self):
        return self.effective_source == "replay"

    def summary(self):
        return {} if self.pm is None else {"hedge_a": {"equity_equiv_shares": self.pm}}


def make_app(tmp_path, broker=None, t=SAT_NOON):
    app = create_app()
    app.state.broker = broker or SimBroker(tmp_path / "a.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "fake")}))
    app.state.staged_autorun = False
    app.state.staged_clock = Clock(t)
    return app


def approved_proposal(app, shares=1000, cov=0.5, direction="down_on_yes", ticker="SPY", override=True):
    p = app.state.store.propose(ticker=ticker, family="hedge", strategy="s", shares_held=shares, target_coverage=cov,
                                basis="market_event", market=MarketRef(source="polymarket", id="m1"),
                                direction=direction, act_on_unvalidated=override)
    return app.state.store.approve(p.id, ack_unvalidated=True)


def track(app, *points):
    tr = tracker_for(app)
    for t, p in points:
        tr.observe(KEY, t, p)


def test_gap_estimate_uses_the_gap_service_sign_rate_band_and_n():
    r, sign, codes = staged.choose("polymarket", "m1", "SPY", "down_on_yes")
    e = staged.gap_estimate(5.0, r, sign, "SPY", codes)
    assert sign == -1 and e["rate_source"] == "pooled" and e["n_closures"] == 380
    assert e["gap_bp"] == pytest.approx(-5 * POOLED)
    lo, hi = e["band_bp"]
    assert lo < e["gap_bp"] < hi and e["band_level"] == 0.8
    assert "GAP_POOLED_RATE" in e["reasons"] and "BAND_INCLUDES_ZERO" in e["reasons"]
    up = staged.gap_estimate(5.0, *staged.choose("polymarket", "m1", "SPY", "up_on_yes")[:2])
    assert up["gap_bp"] == pytest.approx(5 * POOLED)


def test_size_hedge_scales_with_the_gap_and_counts_equity_and_pm_legs_against_the_cap():
    q, codes, d = staged.size_hedge(-37.6, 1000, 0.5, 0, 0, 0, 50, 10)
    assert (q, codes, d["target_hedge"], d["cap_total"]) == (376, ["SIZED_TO_EXPECTED_GAP"], 376, 500)
    q, _, d = staged.size_hedge(-37.6, 1000, 0.5, 100, 50, 0, 50, 10)
    assert q == 226 and d["coverage_room"] == 350
    assert staged.size_hedge(-80, 1000, 0.5, 0, 0, 0, 50, 10)[0] == 500
    assert staged.size_hedge(-37.6, 1000, 0.5, 300, 100, 0, 50, 10)[:2] == (0, ["ALREADY_HEDGED"])
    assert staged.size_hedge(-5, 1000, 0.5, 0, 0, 0, 50, 10)[:2] == (0, ["GAP_BELOW_THRESHOLD"])
    assert staged.size_hedge(20, 1000, 0.5, 0, 0, 0, 50, 10)[:2] == (0, ["GAP_NOT_ADVERSE"])


def test_schedule_pre_market_with_extended_hours_else_the_open():
    t, at, day, codes = staged.schedule(SAT_NOON, True)
    assert (t, at, day.isoformat(), codes) == ("pre_market", MON_PRE, "2026-10-05", ["NEXT_PRE_MARKET"])
    t, at, _, codes = staged.schedule(SAT_NOON, False)
    assert (t, at, codes) == ("regular_open", MON_OPEN, ["NO_EXTENDED_HOURS_WAIT_OPEN"])
    t, at, _, _ = staged.schedule(MON_PRE + dt.timedelta(minutes=30), True)
    assert t == "pre_market" and at == MON_PRE + dt.timedelta(minutes=30)


def test_plan_approve_and_execute_pre_market_through_the_sim(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app)
    with TestClient(app) as c:
        r = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0})
        assert r.status_code == 201, r.text
        o = r.json()
        assert o["status"] == "staged" and o["qty"] == 376 and o["side"] == "sell"
        assert o["session_target"] == "pre_market" and o["execute_at"] == "2026-10-05T08:00:00Z"
        assert o["extended_hours"] and o["order_type"] == "limit" and o["broker"] == "sim"
        assert o["estimate"]["n_closures"] == 380 and len(o["estimate"]["band_bp"]) == 2
        assert [d["code"] for d in o["decisions"]] == ["NEXT_PRE_MARKET", "EXPECTED_GAP", "EVIDENCE_OVERRIDE",
                                                       "SIZED_TO_EXPECTED_GAP", "AWAITING_APPROVAL"]
        assert o["evidence_gate"] == "override" and o["evidence"]["validated"] is False
        listed = c.get("/staged").json()
        assert listed["broker"] == {"name": "sim", "extended_hours": True} and listed["orders"][0]["id"] == o["id"]

        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=5)
        assert c.post("/staged/run").json()["changed"] == []
        assert c.get("/orders").json() == []
        app.state.staged_clock.t = SAT_NOON

        a = c.post(f"/staged/{o['id']}/approve").json()
        assert a["status"] == "approved" and a["approved_qty"] == 376
        assert c.post(f"/staged/{o['id']}/approve").status_code == 409
        assert c.post("/staged/run").json()["changed"] == []

        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=5)
        changed = c.post("/staged/run").json()["changed"]
        assert len(changed) == 1 and changed[0]["status"] == "filled" and changed[0]["filled_qty"] == 376
        bo = changed[0]["broker_order"]
        assert bo["type"] == "limit" and bo["limit_px"] == 495.0 and bo["side"] == "sell"
        assert bo["client_order_id"] == f"stg-{o['id']}" and bo["fill_px"] == pytest.approx(499.95)
        assert "evidence: override" in bo["note"]
        assert c.get("/positions").json()[0]["qty"] == -376
        assert c.delete(f"/staged/{o['id']}").status_code == 409


def test_broker_without_extended_hours_waits_for_the_open_with_a_market_order(tmp_path):
    app = make_app(tmp_path, NoExtSim(tmp_path / "b.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "f")})))
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0}).json()
        assert o["session_target"] == "regular_open" and o["execute_at"] == "2026-10-05T13:30:00Z"
        assert not o["extended_hours"] and o["order_type"] == "market"
        c.post(f"/staged/{o['id']}/approve")
        app.state.staged_clock.t = MON_PRE + dt.timedelta(hours=1)
        assert c.post("/staged/run").json()["changed"] == []
        app.state.staged_clock.t = MON_OPEN + dt.timedelta(seconds=5)
        done = c.post("/staged/run").json()["changed"][0]
        assert done["status"] == "filled" and done["broker_order"]["type"] == "market"


def test_revert_cancels_and_partial_revert_resizes_never_above_approval(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app)
    track(app, (FRI_CLOSE - dt.timedelta(minutes=1), 0.40), (SAT_NOON, 0.45))
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id}).json()
        assert o["estimate"]["pm_move_pp"] == pytest.approx(5.0) and o["qty"] == 376
        c.post(f"/staged/{o['id']}/approve")

        t1 = SAT_NOON + dt.timedelta(hours=2)
        app.state.staged_clock.t = t1
        track(app, (t1, 0.43))
        got = c.post("/staged/run").json()["changed"][0]
        assert got["qty"] == 225 and got["reason"] == "PM_PARTIAL_REVERT_RESIZE"

        t2 = t1 + dt.timedelta(hours=1)
        app.state.staged_clock.t = t2
        track(app, (t2, 0.46))
        got = c.post("/staged/run").json()["changed"][0]
        assert got["qty"] == 376 and got["reason"] == "PM_RESIZE_UP"
        got = c.post("/staged/run").json()["changed"][0]
        assert got["qty"] == 376 and got["reason"] == "RESIZE_UP_NEEDS_APPROVAL"
        assert c.post("/staged/run").json()["changed"] == []

        t3 = t2 + dt.timedelta(hours=1)
        app.state.staged_clock.t = t3
        track(app, (t3, 0.41))
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "cancelled" and got["reason"] == "PM_REVERTED"
        assert c.get("/orders").json() == []


def test_working_order_is_cancelled_at_the_broker_when_the_pm_reverts(tmp_path):
    fake = RestingBroker()
    app = make_app(tmp_path, fake, t=MON_PRE + dt.timedelta(minutes=1))
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        assert o["session_target"] == "pre_market"
        a = c.post(f"/staged/{o['id']}/approve").json()
        assert a["status"] == "working" and fake.placed[0].extended_hours and fake.placed[0].type == "limit"
        assert fake.placed[0].limit_px == pytest.approx(round(500 * (1 - 5 * POOLED / 1e4) * 0.99, 2))
        t = MON_PRE + dt.timedelta(minutes=10)
        app.state.staged_clock.t = t
        track(app, (FRI_CLOSE - dt.timedelta(minutes=1), 0.40), (t, 0.40))
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "cancelled" and got["reason"] == "PM_REVERTED" and fake.cancelled == ["f-1"]


def test_coverage_is_rechecked_at_execution_and_the_fill_feeds_the_bridge_hedge(tmp_path):
    app = make_app(tmp_path)
    app.state.capital_limits = {"max_event_pct": 0.5}
    prop = approved_proposal(app)
    bridge = StubBridge(prop, app.state.broker)
    app.state.bridges = {prop.id: bridge}
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"bridge_id": "br1", "pm_move_pp": 8.0, "pm_leg_equiv_shares": 40}).json()
        assert o["qty"] == 460 and o["bridge_id"] == "br1" and o["sizing"]["pm_leg_equiv_shares"] == 40
        c.post(f"/staged/{o['id']}/approve")
        bridge.broker_hedge = 420.0
        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=1)
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "filled" and got["filled_qty"] == 40
        assert "COVERAGE_CAP_AT_EXECUTION" in [d["code"] for d in got["decisions"]]
        assert bridge.broker_hedge == 460.0 and bridge.account_hedge == 40.0


def test_replay_order_moves_only_on_replayed_ticks_priced_from_the_tick_in_the_sandbox(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app)
    sandbox = SimBroker(None, FakeQuotes(equity={"SPY": Quote(500.0, None, "f")}))
    bridge = StubBridge(prop, sandbox, source="replay", ts=int(SAT_NOON.timestamp() * 1e9))
    app.state.bridges = {prop.id: bridge}
    with TestClient(app) as c:
        app.state.staged_clock.t = dt.datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
        o = c.post("/staged/plan", json={"bridge_id": "br1", "pm_move_pp": 5.0}).json()
        assert o["clock"] == "replay" and o["planned_at"] == "2026-10-03T16:00:00Z"
        assert c.post("/staged/plan", json={"bridge_id": "br1"}).status_code == 422
        a = c.post(f"/staged/{o['id']}/approve").json()
        assert a["status"] == "approved" and a["approved_at"] == "2026-10-03T16:00:00Z"
        bridge.last_replay_ts_ns = int((MON_PRE + dt.timedelta(minutes=2)).timestamp() * 1e9)
        assert c.post("/staged/run").json()["changed"] == []
    tick = MON_PRE + dt.timedelta(minutes=2)
    run(staged.on_tick(app, bridge, tick, 5.0))
    got = app.state.staged_book.get(o["id"])
    assert got.status == "approved" and got.reason == "REPLAY_NEEDS_TICK_PRICE" and run(sandbox.orders()) == []
    run(staged.on_tick(app, bridge, tick, 5.0))
    assert [d.code for d in got.decisions].count("REPLAY_NEEDS_TICK_PRICE") == 1
    run(staged.on_tick(app, bridge, tick, 5.0, 480.0))
    assert got.status == "filled" and got.ref_source == "recorded"
    assert got.broker_order["price_source"] == "recorded" and "recorded price" in got.broker_order["note"]
    assert got.fill_px == pytest.approx(480 - 480 * 1e-4, rel=1e-3)
    assert run(sandbox.positions())[0].qty == -376 and run(app.state.broker.positions()) == []
    assert bridge.broker_hedge == 376 and bridge.account_hedge == 0.0


def test_real_replay_bridge_without_tick_time_or_sandbox_never_falls_back_to_the_wall_clock(tmp_path):
    from app.bridges import Bridge

    app = make_app(tmp_path)
    prop = approved_proposal(app)
    b = Bridge(prop, "replay", prop.market, 0.0, direction=prop.direction)
    app.state.bridges = {prop.id: b}
    with TestClient(app) as c:
        r = c.post("/staged/plan", json={"bridge_id": b.id, "pm_move_pp": 5.0})
        assert r.status_code == 409 and r.json()["detail"].startswith("REPLAY_NO_TICK_TIME")
        b.last_replay_ts_ns = int(SAT_NOON.timestamp() * 1e9)
        r = c.post("/staged/plan", json={"bridge_id": b.id, "pm_move_pp": 5.0})
        assert r.status_code == 409 and r.json()["detail"].startswith("REPLAY_SANDBOX_NOT_READY")
        b.broker = app.state.broker
        o = c.post("/staged/plan", json={"bridge_id": b.id, "pm_move_pp": 5.0}).json()
        assert o["clock"] == "replay" and o["broker"] == b.order_broker().name != "sim"
        w = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0}).json()
        assert w["clock"] == "wall" and w["bridge_id"] is None and w["broker"] == "sim"
        assert c.get("/staged", params={"status": "staged"}).json()["orders"].__len__() == 2
        c.post(f"/staged/{o['id']}/approve")
        b.broker = None
        b.replay_broker = None
        run(staged.on_tick(app, b, MON_PRE + dt.timedelta(minutes=1), 5.0, 500.0))
        got = app.state.staged_book.get(o["id"])
        assert got.status == "approved" and got.reason == "REPLAY_SANDBOX_NOT_READY"
        assert c.get("/orders").json() == []


def test_coverage_counts_resting_staged_orders_bridge_resting_sells_and_the_current_pm_leg(tmp_path):
    fake = RestingBroker()
    app = make_app(tmp_path, fake, t=MON_PRE + dt.timedelta(minutes=1))
    prop = approved_proposal(app)
    bridge = StubBridge(prop, fake)
    app.state.bridges = {prop.id: bridge}
    with TestClient(app) as c:
        a = c.post("/staged/plan", json={"bridge_id": "br1", "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        assert c.post(f"/staged/{a['id']}/approve").json()["status"] == "working"
        assert staged.reserved_sell_qty(app, prop.id) == 376
        bridge.broker_hedge = 60.0
        bridge.resting = {"side": "sell", "qty": 50, "hedged": 10, "instrument": "equity"}
        b = c.post("/staged/plan", json={"bridge_id": "br1", "pm_move_pp": 8.0, "ref_px": 500.0}).json()
        assert b["sizing"]["staged_working"] == 376 and b["sizing"]["bridge_resting_sell"] == 40
        assert b["qty"] == 24
        bridge.broker_hedge = 80.0
        bridge.pm = 2.0
        got = c.post(f"/staged/{b['id']}/approve").json()
        assert got["status"] == "working" and fake.placed[-1].qty == 2
        assert "COVERAGE_CAP_AT_EXECUTION" in [d["code"] for d in got["decisions"]]
        assert 376 + 2 + 80 + 40 + 2 == 500


def test_a_restarted_bridge_gets_the_fill_and_its_coverage_is_checked(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app)
    old = StubBridge(prop, app.state.broker)
    app.state.bridges = {prop.id: old}
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"bridge_id": "br1", "pm_move_pp": 5.0}).json()
        c.post(f"/staged/{o['id']}/approve")
        new = StubBridge(prop, app.state.broker, bid="br2")
        new.broker_hedge = new.account_hedge = 450.0
        app.state.bridge_history, app.state.bridges = {"br1": old}, {prop.id: new}
        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=1)
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "filled" and got["filled_qty"] == 50
        assert new.broker_hedge == 500.0 and old.broker_hedge == 0.0


def test_guards_unapproved_proposal_market_open_cancel_and_missed_session(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app)
    pending = app.state.store.propose(ticker="SPY", family="hedge", strategy="s", shares_held=10, target_coverage=0.5)
    with TestClient(app) as c:
        assert c.post("/staged/plan", json={"proposal_id": pending.id, "pm_move_pp": 5}).status_code == 409
        assert c.post("/staged/plan", json={}).status_code == 422
        assert c.post("/staged/plan", json={"bridge_id": "nope"}).status_code == 404
        assert c.post("/staged/plan", json={"proposal_id": prop.id}).status_code == 422
        skip = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": -5}).json()
        assert skip["status"] == "skipped" and skip["reason"] == "GAP_NOT_ADVERSE"
        assert c.post(f"/staged/{skip['id']}/approve").status_code == 409

        a = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5}).json()
        b = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 6}).json()
        assert c.get("/staged", params={"status": "cancelled"}).json()["orders"][0]["id"] == a["id"]
        d = c.delete(f"/staged/{b['id']}").json()
        assert d["status"] == "cancelled" and d["reason"] == "USER_CANCELLED"
        assert c.delete(f"/staged/{b['id']}").status_code == 409 and c.delete("/staged/zzz").status_code == 404

        late = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5}).json()
        c.post(f"/staged/{late['id']}/approve")
        app.state.staged_clock.t = MON_CLOSE + dt.timedelta(minutes=1)
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "cancelled" and got["reason"] == "SESSION_MISSED"

        app.state.staged_clock.t = MON_OPEN + dt.timedelta(hours=1)
        assert c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5}).status_code == 409


def test_webull_extended_hours_sends_session_all_and_refuses_extended_market_orders(tmp_path):
    from tests.test_broker_webull import Sandbox, make

    sb = Sandbox(status="SUBMITTED")
    wb = make(sb, tmp_path)
    assert wb.extended_hours is False and wb.regular_session_only and SimBroker.extended_hours is True
    wb.extended_hours = True

    async def go():
        lim = await wb.place_order(OrderRequest(symbol="SPY", asset="equity", side="buy", qty=3, type="limit",
                                                limit_px=500.0, client_order_id="x1", extended_hours=True))
        mkt = await wb.place_order(OrderRequest(symbol="SPY", asset="equity", side="buy", qty=3,
                                                client_order_id="x2", extended_hours=True))
        return lim, mkt
    lim, mkt = run(go())
    items = [json.loads(r.content)["new_orders"][0] for r in sb.requests if r.url.path == "/trading/orders/place"]
    assert [i["support_trading_session"] for i in items] == ["ALL"] and items[0]["order_type"] == "LIMIT"
    assert lim.status == "open"
    assert mkt.status == "rejected" and mkt.reject_reason.startswith("extended_hours_needs_limit")

    off = make(Sandbox(), tmp_path)
    o = run(off.place_order(OrderRequest(symbol="SPY", asset="equity", side="buy", qty=1, type="limit", limit_px=1.0,
                                         client_order_id="x3", extended_hours=True)))
    assert o.status == "rejected" and o.reject_reason.startswith("extended_hours_disabled")


def test_build_broker_reads_webull_extended_hours_switch(monkeypatch, tmp_path):
    import app.broker as broker_mod

    monkeypatch.setenv("BROKER", "webull")
    monkeypatch.setenv("WEBULL_APP_KEY", "k")
    monkeypatch.setenv("WEBULL_APP_SECRET", "s")
    monkeypatch.delenv("WEBULL_EXTENDED_HOURS", raising=False)
    monkeypatch.chdir(tmp_path)
    assert broker_mod.build_broker(None).extended_hours is False
    monkeypatch.setenv("WEBULL_EXTENDED_HOURS", "1")
    assert broker_mod.build_broker(None).extended_hours is True
    monkeypatch.setenv("WEBULL_EXTENDED_HOURS", "0")
    assert broker_mod.build_broker(None).extended_hours is False


def test_background_runner_executes_on_the_wall_clock_and_stops_when_idle(tmp_path):
    import time

    app = make_app(tmp_path)
    app.state.staged_autorun, app.state.staged_poll_s = True, 0.01
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0}).json()
        c.post(f"/staged/{o['id']}/approve")
        runner = app.state.staged_book.runner
        assert runner is not None and not runner.done()
        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=1)
        for _ in range(200):
            if c.get("/staged").json()["orders"][0]["status"] == "filled":
                break
            time.sleep(0.01)
        assert c.get("/staged").json()["orders"][0]["status"] == "filled"
        for _ in range(200):
            if runner.done():
                break
            time.sleep(0.01)
        assert runner.done()


def test_the_model_estimate_is_never_a_fill_price(tmp_path):
    app = make_app(tmp_path)
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        c.post(f"/staged/{o['id']}/approve")
        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=1)
        got = c.post("/staged/run").json()["changed"][0]
        est = 500 * (1 - 5 * POOLED / 1e4)
        assert got["limit_anchor"] == "expected_open_estimate" and got["ref_source"] == "quote"
        assert got["broker_order"]["limit_px"] == pytest.approx(round(est * 0.99, 2))
        assert got["fill_px"] == pytest.approx(499.95)

    noq = make_app(tmp_path, SimBroker(tmp_path / "n.json", FakeQuotes(equity={})))
    prop = approved_proposal(noq)
    with TestClient(noq) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        c.post(f"/staged/{o['id']}/approve")
        for t in (MON_PRE + dt.timedelta(minutes=1), MON_OPEN + dt.timedelta(minutes=1),
                  MON_OPEN + dt.timedelta(minutes=2)):
            noq.state.staged_clock.t = t
            c.post("/staged/run")
        got = c.get("/staged").json()["orders"][0]
        assert got["status"] == "approved" and got["reason"] == "NO_QUOTE_WAIT" and c.get("/orders").json() == []
        assert [d["code"] for d in got["decisions"]].count("NO_QUOTE_WAIT") == 1
        noq.state.staged_clock.t = MON_CLOSE + dt.timedelta(minutes=1)
        assert c.post("/staged/run").json()["changed"][0]["reason"] == "SESSION_MISSED"


def test_an_unfilled_pre_market_limit_is_replaced_by_a_market_order_at_the_open(tmp_path):
    fake = RestingBroker()
    app = make_app(tmp_path, fake, t=MON_PRE + dt.timedelta(minutes=1))
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        c.post(f"/staged/{o['id']}/approve")
        app.state.staged_clock.t = MON_PRE + dt.timedelta(hours=2)
        assert c.post("/staged/run").json()["changed"] == []
        app.state.staged_clock.t = MON_OPEN + dt.timedelta(seconds=5)
        got = c.post("/staged/run").json()["changed"][0]
        assert fake.cancelled == ["f-1"] and len(fake.placed) == 2
        r = fake.placed[1]
        assert (r.type, r.extended_hours, r.qty, r.client_order_id) == ("market", False, 376, f"stg-{o['id']}-r1")
        assert got["status"] == "working" and got["session_target"] == "regular_open" and got["replacements"] == 1
        assert "PRE_MARKET_UNFILLED_REPLACED" in [d["code"] for d in got["decisions"]]


def test_a_failed_cancel_after_a_revert_is_logged_once(tmp_path):
    class StuckBroker(RestingBroker):
        async def cancel(self, oid):
            raise BrokerError("cannot cancel now", 500)

    fake = StuckBroker()
    app = make_app(tmp_path, fake, t=MON_PRE + dt.timedelta(minutes=1))
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        c.post(f"/staged/{o['id']}/approve")
        t = MON_PRE + dt.timedelta(minutes=10)
        app.state.staged_clock.t = t
        track(app, (FRI_CLOSE - dt.timedelta(minutes=1), 0.40), (t, 0.40))
        for _ in range(3):
            c.post("/staged/run")
        codes = [d["code"] for d in c.get("/staged").json()["orders"][0]["decisions"]]
        assert codes.count("PM_REVERTED") == 1 and codes.count("CANCEL_FAILED") == 1


def test_webull_split_sell_and_unconfirmed_fill_are_reconciled_by_client_id(tmp_path, roomy_capital):
    from tests.test_broker_webull import Sandbox, make

    sb = Sandbox(status="SUBMITTED", held=50.0)
    wb = make(sb, tmp_path)
    wb.extended_hours = True
    app = make_app(tmp_path, wb, t=MON_PRE + dt.timedelta(minutes=1))
    prop = approved_proposal(app, ticker="AAPL")
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 190.0}).json()
        a = c.post(f"/staged/{o['id']}/approve").json()
        assert a["status"] == "working"
        legs = [json.loads(r.content)["new_orders"][0] for r in sb.requests if r.url.path == "/trading/orders/place"]
        assert [(i["side"], i["quantity"], i["support_trading_session"]) for i in legs] == [
            ("SELL", "50", "ALL"), ("SHORT", "326", "ALL")]
        sb.status = "FILLED"
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "filled" and got["filled_qty"] == 376

    sb2 = Sandbox(status="FILLED")
    wb2 = make(sb2, tmp_path)
    wb2.extended_hours = True
    real = wb2.place_order

    async def accepted_then_timeout(req):
        await real(req)
        wb2._placed.pop(req.client_order_id, None)
        raise TimeoutError

    wb2.place_order = accepted_then_timeout
    app2 = make_app(tmp_path, wb2, t=MON_PRE + dt.timedelta(minutes=1))
    prop = approved_proposal(app2, ticker="AAPL")
    with TestClient(app2) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 190.0}).json()
        a = c.post(f"/staged/{o['id']}/approve").json()
        assert a["status"] == "working" and a["reason"] == "BROKER_UNCONFIRMED"
        got = c.post("/staged/run").json()["changed"][0]
        assert got["status"] == "filled" and got["filled_qty"] == 376
        assert sum(r.url.path == "/trading/orders/place" for r in sb2.requests) == 1
