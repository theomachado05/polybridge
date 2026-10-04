from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.broker as broker_mod
from app import bridges
from app.broker import OrderRequest, SimBroker
from app.broker.webull import MARKET_CLOSED_REASON, WebullBroker, WebullClient, is_market_closed
from app.closed import bridge_mode
from tests.test_broker_support import run
from tests.test_broker_webull import NONCE, Sandbox, make
from tests.test_closed_bridge import approved, fake_engine, make_client, research_rate, write_rows  # noqa: F401
from tests.test_closed_staged import MON_OPEN, SAT_NOON, Clock, approved_proposal, make_app
from tests.test_bridges import _events

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import webull_check  # noqa: E402

CLOSED_MSG = ("Orders cannot be placed at this time. Please try again during normal market hours "
              "9:30 a.m. - 4:00 p.m. ET")
TUE_OPEN = dt.datetime(2026, 10, 6, 13, 30, tzinfo=dt.timezone.utc)


class Hours(Sandbox):

    def __init__(self, closed=True, **kw):
        super().__init__(**kw)
        self.closed = closed
        self.known: set[str] = set()

    def handler(self, r: httpx.Request) -> httpx.Response:
        p = r.url.path
        if p == "/trading/accounts/list":
            self.requests.append(r)
            return httpx.Response(200, json=[
                {"account_id": "ACC-CASH-0001", "account_type": "CASH", "account_label": "Individual Cash",
                 "account_class": "INDIVIDUAL_CASH"},
                {"account_id": "ACC-MARGIN-0042", "account_type": "MARGIN", "account_label": "Individual Margin",
                 "account_class": "INDIVIDUAL_MARGIN"}])
        if p == "/trading/orders/place":
            if self.closed:
                self.requests.append(r)
                return httpx.Response(417, json={"error_code": "ORDER_TIME_NOT_ALLOWED", "message": CLOSED_MSG})
            self.known.add(json.loads(r.content)["new_orders"][0]["client_order_id"])
        if p == "/trading/orders/cancel" and json.loads(r.content)["client_order_id"] not in self.known:
            self.requests.append(r)
            return httpx.Response(417, json={"error_code": "ORDER_NOT_EXIST", "message": "Order not present"})
        if p == "/trading/orders/get" and r.url.params["client_order_id"] not in self.known:
            self.requests.append(r)
            return httpx.Response(417, json={"message": "Order not present"})
        if p == "/trading/assets/balances/get":
            self.requests.append(r)
            return httpx.Response(200, json={
                "total_asset_currency": "USD", "total_net_liquidation_value": "1000000.00",
                "total_cash_balance": "1000000.00", "maintenance_margin": "0.00", "open_margin_calls": [],
                "account_currency_assets": [{"currency": "USD", "cash_balance": "1000000.00",
                                             "net_liquidation_value": "1000000.00",
                                             "day_buying_power": "4000000", "overnight_buying_power": "2000000.00",
                                             "option_buying_power": "1000000.00"}]})
        return super().handler(r)


def margin(sb, tmp_path, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(sb.handler))
    client = WebullClient("APPKEY", "SECRET", http=http, nonce=lambda: NONCE)
    return WebullBroker(client, SimBroker(tmp_path / "s.json"), account_id="ACC-MARGIN-0042", **kw)


def placed(sb):
    return [json.loads(r.content)["new_orders"][0] for r in sb.requests if r.url.path == "/trading/orders/place"]


def test_extended_hours_are_off_by_default_for_the_sandbox(monkeypatch, tmp_path):
    wb = margin(Hours(), tmp_path)
    assert wb.extended_hours is False and wb.regular_session_only is True
    env = {"BROKER": "webull", "WEBULL_API_KEY": "k", "WEBULL_APP_SECRET": "s", "WEBULL_ACCOUNT_ID": "A"}
    monkeypatch.setattr(broker_mod, "_env", lambda n: env.get(n, ""))
    b = broker_mod.build_broker()
    assert b.name == "webull-paper" and b.extended_hours is False and b.regular_session_only
    env["WEBULL_EXTENDED_HOURS"] = "1"
    assert broker_mod.build_broker().extended_hours is True and not broker_mod.build_broker().regular_session_only


def test_a_417_outside_market_hours_is_a_rejected_market_closed_order_not_an_exception(tmp_path):
    sb = Hours(closed=True)
    wb = margin(sb, tmp_path)

    async def go():
        first = await wb.place_order(OrderRequest(symbol="SPY", asset="equity", side="buy", qty=1, type="limit",
                                                  limit_px=1.0, client_order_id="c1"))
        sb.closed = False
        again = await wb.place_order(OrderRequest(symbol="SPY", asset="equity", side="buy", qty=1, type="limit",
                                                  limit_px=1.0, client_order_id="c1"))
        return first, again
    first, again = run(go())
    assert first.status == "rejected" and first.reject_reason == MARKET_CLOSED_REASON
    assert first.reject_reason == "market_closed: Webull paper accepts orders 09:30-16:00 ET"
    assert is_market_closed(first) and first.broker == "webull-paper"
    assert [i["support_trading_session"] for i in placed(sb)] == ["CORE", "CORE"]
    assert again.status == "filled" and not is_market_closed(again)


def test_a_split_sell_refused_for_market_hours_is_market_closed_and_retried(tmp_path):
    sb = Hours(closed=True, held=4.0)
    wb = margin(sb, tmp_path)

    async def go():
        o = await wb.place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=10, client_order_id="s"))
        sb.closed = False
        return o, await wb.place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=10,
                                                    client_order_id="s"))
    o, again = run(go())
    assert is_market_closed(o) and o.filled_qty == 0
    assert again.status == "filled" and again.filled_qty == 10
    assert [(i["side"], i["quantity"]) for i in placed(sb)][-2:] == [("SELL", "4"), ("SHORT", "6")]


def test_cancel_of_an_order_webull_reports_not_present_is_a_clean_not_found_order(tmp_path):
    sb = Hours(closed=False, status="SUBMITTED")
    wb = margin(sb, tmp_path)

    async def go():
        gone = await wb.cancel("never-placed")
        o = await wb.place_order(OrderRequest(symbol="SPY", asset="equity", side="buy", qty=1, type="limit",
                                              limit_px=1.0, client_order_id="mine"))
        sb.status = "FILLED"
        sb.known.discard("mine")

        def get_filled(r, inner=sb.handler):
            if r.url.path == "/trading/orders/get":
                return httpx.Response(200, json={"data": {"order_id": "WB-1", "status": "FILLED",
                                                          "filled_quantity": "1", "filled_price": "1.0",
                                                          "client_order_id": "mine"}})
            return inner(r)
        wb.client._http = httpx.AsyncClient(transport=httpx.MockTransport(get_filled))
        return gone, o, await wb.cancel(o.id)
    gone, o, done = run(go())
    assert gone.status == "rejected" and gone.reject_reason.startswith("not_found:") and gone.broker == "webull-paper"
    assert o.status == "open"
    assert done.status == "filled" and done.filled_qty == 1


def test_get_account_reports_webull_paper_margin_class_and_market_open(tmp_path):
    sb = Hours()
    app = make_app(tmp_path, margin(sb, tmp_path), t=SAT_NOON)
    with TestClient(app) as c:
        a = c.get("/account").json()
        assert (a["broker"], a["account_type"], a["account_class"], a["account_label"]) == (
            "webull-paper", "margin", "INDIVIDUAL_MARGIN", "Individual Margin")
        assert a["market_open"] is False and a["extended_hours"] is False and a["simulated"] is True
        assert a["session"].startswith("Market closed") and a["next_open"] == "2026-10-05T13:30:00Z"
        assert "09:30-16:00 ET only" in a["note"]
        app.state.staged_clock.t = MON_OPEN + dt.timedelta(hours=1)
        assert c.get("/account").json()["market_open"] is True
    assert not placed(sb)


def test_staged_orders_for_webull_execute_only_in_the_regular_session_and_a_417_is_held(tmp_path, roomy_capital):
    sb = Hours(closed=True)
    app = make_app(tmp_path, margin(sb, tmp_path), t=SAT_NOON)
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "ref_px": 500.0}).json()
        assert o["broker"] == "webull-paper" and o["session_target"] == "regular_open"
        assert o["execute_at"] == "2026-10-05T13:30:00Z" and o["order_type"] == "market" and not o["extended_hours"]
        r = c.post(f"/staged/{o['id']}/approve")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved" and not placed(sb)

        app.state.staged_clock.t = dt.datetime(2026, 10, 5, 8, 30, tzinfo=dt.timezone.utc)
        assert c.post("/staged/run").json()["changed"] == [] and not placed(sb)

        app.state.staged_clock.t = MON_OPEN + dt.timedelta(seconds=5)
        held = c.post("/staged/run").json()["changed"][0]
        assert held["status"] == "approved" and held["reason"] == "HELD_FOR_NEXT_SESSION" and held["holds"] == 1
        assert held["execute_at"] == TUE_OPEN.isoformat().replace("+00:00", "Z")
        assert held["session_date"] == "2026-10-06" and held["filled_qty"] == 0
        assert held["broker_order"]["reject_reason"] == MARKET_CLOSED_REASON
        assert "BROKER_REJECTED" not in [d["code"] for d in held["decisions"]]
        assert c.post("/staged/run").json()["changed"] == []

        sb.closed = False
        app.state.staged_clock.t = TUE_OPEN + dt.timedelta(seconds=5)
        done = c.post("/staged/run").json()["changed"][0]
        assert done["status"] == "filled" and done["filled_qty"] == 376
        assert done["client_order_id"] == f"stg-{o['id']}-h1"
    sent = placed(sb)
    assert [(i["client_order_id"], i["order_type"], i["support_trading_session"]) for i in sent] == [
        (f"stg-{o['id']}", "MARKET", "CORE"), (f"stg-{o['id']}-h1", "MARKET", "CORE")]


def test_closed_mode_forces_the_hold_only_for_a_regular_session_only_order_broker(tmp_path):
    wb = margin(Hours(), tmp_path)

    class B:
        def __init__(self, broker):
            self.b = broker

        def order_broker(self):
            return self.b

    class CM:
        hedging, hold_enabled = True, False
        sess = bridge_mode.session_at(SAT_NOON)
        broker_hold = bridge_mode.ClosedMode.broker_hold
        hold = bridge_mode.ClosedMode.hold

    cm = CM()
    cm.bridge = B(wb)
    assert cm.broker_hold and cm.hold
    cm.bridge = B(SimBroker(None))
    assert not cm.broker_hold and not cm.hold
    wb.extended_hours = True
    cm.bridge = B(wb)
    assert not cm.broker_hold
    cm.bridge, cm.sess = B(margin(Hours(), tmp_path)), bridge_mode.session_at(MON_OPEN + dt.timedelta(hours=1))
    assert cm.broker_hold and not cm.hold


def test_replay_scope_keeps_the_sandbox_while_webull_is_closed(tmp_path):
    app = make_app(tmp_path, margin(Hours(), tmp_path), t=SAT_NOON)
    rep = bridges.BridgeIn(proposal_id="p", source="replay", replay_to_account=True)
    live = bridges.BridgeIn(proposal_id="p", source="live")
    to_acct, note = bridges._replay_scope(app, rep)
    assert to_acct is False and "in-memory sandbox" in note and "replay_to_account ignored" in note
    to_acct, note = bridges._replay_scope(app, live)
    assert to_acct is False and "staged orders go to Webull" in note and "09:30" in note
    app.state.staged_clock.t = MON_OPEN + dt.timedelta(hours=1)
    assert bridges._replay_scope(app, rep) == (True, None)
    sim = make_app(tmp_path, SimBroker(tmp_path / "x.json"), t=SAT_NOON)
    assert bridges._replay_scope(sim, rep) == (True, None)


def test_a_live_bridge_at_webull_on_a_weekend_sends_nothing_even_with_session_hold_off(
        tmp_path, fake_engine, research_rate):
    sat = SAT_NOON
    close_s = int(dt.datetime(2026, 10, 2, 20, 0, tzinfo=dt.timezone.utc).timestamp())

    class Live:
        def __init__(self, mid, **kw):
            pass

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            from app.ticks import Tick
            for i in range(6):
                yield Tick(1_790_000_000_000_000_000 + i, 0.40)

    async def fetcher(source, token, start, end):
        return [(close_s - 600, 0.30), (close_s - 60, 0.31)]

    sb = Hours(closed=True)
    with make_client(tmp_path, None) as c:
        c.app.state.broker = margin(sb, tmp_path)
        c.app.state.live_source_factory = Live
        c.app.state.staged_clock = lambda: sat
        c.app.state.closed_history_fetcher = fetcher
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "live", "session_hold": False}).json()[
            "bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
    ticks = [d for k, d in ev if k == "tick"]
    assert ticks and all(d["closed"]["hold"] for d in ticks)
    assert [x for k, x in ev if k == "fill"] == [] and not placed(sb)
    assert s["closed_mode"]["broker_hold"] is True and s["closed_mode"]["session_hold"] is False
    assert s["broker"] == "webull-paper" and "staged orders go to Webull" in s["broker_note"]


def test_a_replay_bridge_at_webull_while_closed_keeps_its_in_memory_sandbox(tmp_path, fake_engine, research_rate):
    f = write_rows(tmp_path / "wk.jsonl")
    sb = Hours(closed=True)
    with make_client(tmp_path, f) as c:
        c.app.state.broker = margin(sb, tmp_path)
        c.app.state.staged_clock = lambda: SAT_NOON
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay", "replay_to_account": True}).json()[
            "bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
    fills = [x for k, x in ev if k == "fill"]
    assert fills and all(x["broker"] == bridges.REPLAY_BROKER_NAME for x in fills)
    assert s["account_scope"] == "replay_sandbox" and "replay_to_account ignored" in s["broker_note"]
    assert not placed(sb)


def test_recorded_prices_switch_makes_a_replay_sandbox_fill_at_the_replayed_price(monkeypatch):
    from types import SimpleNamespace

    from app.broker.quotes import Quote
    from tests.test_broker_support import FakeQuotes

    sim = SimBroker(None, FakeQuotes(equity={"SPY": Quote(600.0, None, "today")}))
    br = SimpleNamespace(quote_check=None, proposal=SimpleNamespace(ticker="SPY"))
    monkeypatch.delenv("POLYBRIDGE_REPLAY_PRICES", raising=False)
    assert asyncio.run(bridges._broker_can_price(br, sim)) is True
    br.quote_check = None
    monkeypatch.setenv("POLYBRIDGE_REPLAY_PRICES", "recorded")
    assert asyncio.run(bridges._broker_can_price(br, sim)) is False


def test_an_indexed_recording_plays_at_its_sidecar_speed_the_configured_file_at_the_configured_speed(
        tmp_path, monkeypatch):
    from types import SimpleNamespace

    rec = tmp_path / "r.jsonl"
    rec.write_text("")
    rec.with_name("r.jsonl.meta.json").write_text(json.dumps({"source": "polymarket", "id": "1", "replay_speed": 3600}))
    other = tmp_path / "o.jsonl"
    other.write_text("")
    app = SimpleNamespace(state=SimpleNamespace(replay_speed=None, replay_path=str(other)))
    monkeypatch.setenv("POLYBRIDGE_REPLAY_SPEED", "21600")
    assert bridges._replay_speed(app, rec) == 3600.0
    assert bridges._replay_speed(app, other) == 21600.0
    app.state.replay_path = str(rec)
    assert bridges._replay_speed(app, rec) == 21600.0
    app.state.replay_speed = 0
    assert bridges._replay_speed(app, rec) == 0
    root = Path(bridges.__file__).resolve().parents[1] / "replays"
    speeds = {p.name: json.loads(p.read_text()).get("replay_speed") for p in root.glob("*.meta.json")}
    assert speeds["us-recession-in-2025-weekend-2025-04-04.jsonl.meta.json"] == 3600
    assert speeds["another-fed-hike-2026-history.jsonl.meta.json"] == 21600


def test_webull_check_is_read_only_while_the_market_is_closed_even_with_the_smoke_switch(tmp_path):
    sb = Hours(closed=True)
    lines: list[str] = []
    res = run(webull_check.check(margin(sb, tmp_path), SAT_NOON, smoke=True, out=lines.append))
    text = "\n".join(lines)
    assert res["market_open"] is False and res["order_test"] == "skipped: market closed"
    assert res["account"] == "***042" and "ACC-MARGIN-0042" not in text and "INDIVIDUAL_MARGIN" in text
    assert res["extended_hours"] is False and "RESULT          OK (read-only)" in text
    assert not placed(sb) and not any(r.url.path == "/trading/orders/cancel" for r in sb.requests)


def test_webull_check_needs_the_switch_to_place_an_order_during_market_hours(tmp_path):
    sb = Hours(closed=False, status="SUBMITTED")
    open_t = MON_OPEN + dt.timedelta(hours=1)
    res = run(webull_check.check(margin(sb, tmp_path), open_t, smoke=False, out=lambda s: None))
    assert res["market_open"] is True and res["order_test"].startswith("skipped") and not placed(sb)

    sb.status = "SUBMITTED"
    lines: list[str] = []
    res = run(webull_check.check(margin(sb, tmp_path), open_t, smoke=True, out=lines.append))
    sent = placed(sb)
    assert len(sent) == 1 and (sent[0]["symbol"], sent[0]["order_type"], sent[0]["limit_price"], sent[0]["quantity"],
                               sent[0]["side"], sent[0]["support_trading_session"]) == (
        "SPY", "LIMIT", "1", "1", "BUY", "CORE")
    cancel = [json.loads(r.content) for r in sb.requests if r.url.path == "/trading/orders/cancel"]
    assert [x["client_order_id"] for x in cancel] == [sent[0]["client_order_id"]]
    assert res["order_test"] == "placed and cancelled" and res["placed"]["status"] == "open"
    assert "WB-1" not in "\n".join(lines)


def test_webull_check_smoke_switch_parsing():
    assert webull_check.smoke_enabled({"WEBULL_SMOKE_ORDER": "1"}) and not webull_check.smoke_enabled({})
    assert not webull_check.smoke_enabled({"WEBULL_SMOKE_ORDER": "0"}) and webull_check.mask("abcdef") == "***def"
    assert webull_check.mask(None) == "***"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    from app.closed import gap as gapsvc

    monkeypatch.delenv("WEBULL_EXTENDED_HOURS", raising=False)
    monkeypatch.setattr(gapsvc, "load_rates", lambda path=None: gapsvc.GapRates())
