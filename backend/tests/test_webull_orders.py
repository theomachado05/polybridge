"""Webull paper: order history (bounded windows), reconciliation (broker pass + background task), short-sale
readiness, margin balances, option positions, option orders behind options_supported, and the routes / portfolio that
surface them. Offline: every Webull call is a mocked HTTP response in the documented shape."""
from __future__ import annotations

import asyncio
import datetime as dt
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.broker import OrderRequest, SimBroker, WebullBroker, WebullClient
from app.broker import reconcile as rc
from app.broker.webull import (HISTORY_MAX_PAGES, MARKET_CLOSED_REASON, RateLimiter, _order_rows, map_status,
                               option_strategy, short_verdict)
from app.main import create_app
from tests.test_broker_support import FakeQuotes, run
from tests.test_broker_webull import Sandbox, make
from tests.test_closed_staged import MON_CLOSE, MON_OPEN, SAT_NOON, Clock

NOW = dt.datetime(2026, 10, 3, 12, 0, 0, tzinfo=dt.UTC)  # make()'s client clock


def group(cid, status="FILLED", symbol="AAPL", side="BUY", qty="10", filled="10", px="189.9", **kw):
    """One order group as Webull's open-orders / history / detail endpoints return it."""
    return {"client_order_id": cid, "combo_type": "NORMAL",
            "orders": [{"client_order_id": cid, "order_id": f"WB-{cid}", "symbol": symbol, "side": side,
                        "status": status, "order_type": "LIMIT", "instrument_type": "EQUITY", "total_quantity": qty,
                        "filled_quantity": filled, "filled_price": px, "limit_price": "190",
                        "place_time_at": "2026-10-02T14:31:02.120Z", "filled_time_at": "2026-10-02T14:31:03.000Z",
                        **kw}]}


class Book(Sandbox):
    """Sandbox whose order detail answers per client id from ``detail`` (else the base answer)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.detail: dict[str, dict] = {}

    def handler(self, r):
        if r.url.path == "/trading/orders/get" and r.url.params["client_order_id"] in self.detail:
            self.requests.append(r)
            return httpx.Response(200, json=self.detail[r.url.params["client_order_id"]])
        return super().handler(r)


def paths(sb, path):
    return [r for r in sb.requests if r.url.path == path]


# ------------------------------------------------------------------------------------------------ parsing

def test_order_groups_are_flattened_and_parsed_with_their_real_fields():
    payload = {"data": [group("c1", status="PARTIAL_FILLED", filled="4", px="0"),
                        {"client_order_id": "g2", "combo_type": "NORMAL", "orders": [
                            {"order_id": "WB-g2", "symbol": "TLT", "side": "SHORT", "status": "SUBMITTED",
                             "order_type": "MARKET", "total_quantity": "5", "place_time": 1759415462120}]}]}
    rows = _order_rows(payload)
    assert [r["client_order_id"] for r in rows] == ["c1", "g2"] and rows[0]["_combo_type"] == "NORMAL"
    from app.broker.webull import order_from_webull
    a, b = (order_from_webull(r, origin="webull_open") for r in rows)
    assert (a.symbol, a.status, a.filled_qty, a.fill_px, a.broker_status) == ("AAPL", "open", 4.0, None, "PARTIAL_FILLED")
    assert a.created_at.startswith("2026-10-02T14:31:02.120") and a.origin == "webull_open" and a.type == "limit"
    assert (b.symbol, b.side, b.qty, b.status, b.type) == ("TLT", "sell", 5.0, "open", "market")
    assert b.created_at.startswith("2025-10-02")  # epoch-ms place_time


@pytest.mark.parametrize("raw,ours", [("PENDING", "open"), ("SUBMITTED", "open"), ("PARTIAL_FILLED", "open"),
                                      ("PENDING_CANCEL", "open"), ("FILLED", "filled"), ("CANCELLED", "cancelled"),
                                      ("CANCELED", "cancelled"), ("EXPIRED", "cancelled"), ("FAILED", "rejected"),
                                      ("REJECTED", "rejected"), (None, "open"), ("weird", "open")])
def test_status_mapping(raw, ours):
    assert map_status(raw) == ours


# ------------------------------------------------------------------------------------------------ history

def test_history_reads_bounded_newest_first_windows_in_webull_time_format(tmp_path):
    sb = Sandbox()

    async def go():
        b = make(sb, tmp_path)
        return await b.order_history(20)
    run(go())
    hs = paths(sb, "/trading/orders/historical-orders/list")
    got = [(r.url.params["start_time"], r.url.params["end_time"]) for r in hs]
    assert got == [("2026-09-26T12:00:00.000Z", "2026-10-03T12:00:00.000Z"),
                   ("2026-09-19T12:00:00.000Z", "2026-09-26T12:00:00.000Z"),
                   ("2026-09-13T12:00:00.000Z", "2026-09-19T12:00:00.000Z")]
    assert all(r.headers["x-version"] == "v3" for r in hs)


def test_history_days_are_clamped_and_pages_are_capped_and_flagged(tmp_path):
    pages = [{"data": [group(f"h{i}")], "pagination_key": str(i + 1)} for i in range(HISTORY_MAX_PAGES + 3)]
    sb = Sandbox(history=pages)

    async def go():
        b = make(sb, tmp_path)
        rows = await b.order_history(1)
        again = await b.order_history(1)  # cached: no second read inside HISTORY_CACHE_S
        return b, rows, again
    b, rows, again = run(go())
    hs = paths(sb, "/trading/orders/historical-orders/list")
    assert len(hs) == HISTORY_MAX_PAGES and len(rows) == HISTORY_MAX_PAGES and b.history_truncated is True
    assert [r.url.params.get("pagination_key") for r in hs] == [None, "1", "2", "3", "4"]
    assert {o.client_order_id for o in again} == {o.client_order_id for o in rows}
    sb2 = Sandbox()
    run(make(sb2, tmp_path).order_history(999))
    assert len(paths(sb2, "/trading/orders/historical-orders/list")) == 5  # 30 days max = 5 windows of <= 7 days


def test_orders_merge_history_open_list_and_ours_with_the_freshest_state_winning(tmp_path):
    sb = Book(status="SUBMITTED",
              history=[{"data": [group("app-1", symbol="MSFT"),  # placed in the Webull app, filled
                                 group("ours", status="FILLED", qty="1", filled="1")]}],
              open_groups=[group("app-2", status="SUBMITTED", symbol="XOM", filled="0", px="0")])

    async def go():
        b = make(sb, tmp_path)
        placed = await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=1, type="limit",
                                                  limit_px=1.0, client_order_id="ours", tag="br-1"))
        return placed, await b.orders(), b
    placed, rows, b = run(go())
    assert placed.status == "open"
    by = {o.client_order_id: o for o in rows}
    assert by["ours"].status == "filled" and by["ours"].tag == "br-1" and by["ours"].origin == "polybridge"
    assert b._placed["ours"].status == "filled"  # history settled our open order
    assert (by["app-1"].origin, by["app-1"].symbol, by["app-1"].status) == ("webull_history", "MSFT", "filled")
    assert (by["app-2"].origin, by["app-2"].status) == ("webull_open", "open")
    assert any(t["client_order_id"] == "ours" and t["to"] == "filled" and t["via"] == "history" for t in b.transitions)


def test_get_orders_route_passes_days_and_bounds_it(tmp_path):
    sb = Sandbox()
    app = create_app()
    app.state.broker = make(sb, tmp_path)
    with TestClient(app) as c:
        assert c.get("/orders", params={"days": 14}).status_code == 200
        assert len(paths(sb, "/trading/orders/historical-orders/list")) == 2
        assert c.get("/orders", params={"days": 31}).status_code == 422
        assert c.get("/orders", params={"days": 0}).status_code == 422


# ------------------------------------------------------------------------------------------------ reconcile

def test_reconcile_settles_fills_partials_and_counts_outside_orders(tmp_path):
    sb = Book(status="SUBMITTED")

    async def go():
        b = make(sb, tmp_path)
        for cid in ("a", "b", "c"):
            await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=10, type="limit",
                                             limit_px=1.0, client_order_id=cid))
        sb.open_groups = [group("b", status="PARTIAL_FILLED", filled="4", px="1.0"),
                          group("x", status="SUBMITTED", filled="0", px="0", symbol="NVDA")]
        sb.detail["a"] = {"data": group("a", status="FILLED", filled="10", px="1.0")}
        sb.detail["c"] = {"data": group("c", status="CANCELLED", filled="0", px="0")}
        r1 = await b.reconcile()
        r2 = await b.reconcile()  # nothing changed since
        return b, r1, r2
    b, r1, r2 = run(go())
    assert (r1["checked"], r1["open_at_webull"], r1["updated"], r1["external_open"]) == (3, 2, 3, 1)
    moves = {t["client_order_id"]: (t["from"], t["to"], t["filled_qty"]) for t in r1["transitions"]}
    assert moves == {"a": ("open", "filled", 10.0), "b": ("open", "open", 4.0), "c": ("open", "cancelled", 0.0)}
    assert b._placed["a"].fill_px == 1.0 and b._placed["c"].status == "cancelled"
    assert r2["updated"] == 0 and r2["checked"] == 1  # only "b" is still open


def test_reconcile_spends_a_bounded_detail_budget_and_defers_the_rest(tmp_path):
    sb = Book(status="SUBMITTED")

    async def go():
        b = make(sb, tmp_path)
        for i in range(6):
            await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=1, type="limit",
                                             limit_px=1.0, client_order_id=f"o{i}"))
        n0 = len(paths(sb, "/trading/orders/get"))
        res = await b.reconcile(detail_budget=2)
        return res, len(paths(sb, "/trading/orders/get")) - n0
    res, details = run(go())
    assert details == 2 and res["deferred"] == 4 and res["checked"] == 6


def test_reconcile_raises_a_broker_error_when_the_open_list_cannot_be_read(tmp_path):
    from app.broker import BrokerError

    class Down(Sandbox):
        def handler(self, r):
            if r.url.path == "/trading/orders/open-orders/list":
                return httpx.Response(500, json={"message": "down"})
            return super().handler(r)
    with pytest.raises(BrokerError):
        run(make(Down(), tmp_path).reconcile())


class FakeRecBroker:
    name = "webull-paper"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    async def reconcile(self):
        self.calls += 1
        if self.fail:
            from app.broker import BrokerError
            raise BrokerError("Webull 500: down", 502)
        return {"checked": 1, "open_at_webull": 0, "updated": 1, "external_open": 0, "deferred": 0,
                "transitions": [{"client_order_id": "a", "from": "open", "to": "filled"}]}


def test_reconciler_runs_in_session_idles_when_closed_and_makes_one_closing_pass():
    clock = Clock(MON_OPEN + dt.timedelta(hours=1))
    b = FakeRecBroker()
    r = rc.Reconciler(lambda: b, clock=clock)

    async def go():
        open_res = await r.run_once()
        d_open = r._delay()
        clock.t = MON_CLOSE + dt.timedelta(minutes=1)
        closing = await r.run_once()  # first pass after the close still reads (late fills)
        idle = await r.run_once()
        d_idle = r._delay()
        clock.t = SAT_NOON
        return open_res, d_open, closing, idle, d_idle, r._delay()
    open_res, d_open, closing, idle, d_idle, d_sat = run(go())
    assert open_res["ran"] and open_res["ok"] and d_open == 15.0
    assert closing["ran"] and closing["closing_pass"] is True
    assert idle == {"ran": False, "reason": r.idle_reason} and "market closed" in r.idle_reason
    assert d_idle == rc.RECONCILE_IDLE_S and d_sat == rc.RECONCILE_IDLE_S and b.calls == 2
    assert r.passes == 2 and list(r.recent)[-1]["to"] == "filled"


def test_reconciler_backs_off_on_errors_and_idles_for_a_synchronous_broker():
    clock = Clock(MON_OPEN + dt.timedelta(hours=1))
    r = rc.Reconciler(lambda: FakeRecBroker(fail=True), clock=clock)

    async def go():
        out = []
        for _ in range(5):
            res = await r.run_once()
            out.append((res["ok"], r._delay()))
        return out
    assert run(go()) == [(False, 15.0), (False, 30.0), (False, 60.0), (False, 120.0), (False, 120.0)]
    assert r.errors == 5 and r.last_error == "Webull 500: down"
    sim = rc.Reconciler(lambda: SimBroker(None), clock=clock)
    assert run(sim.run_once()) == {"ran": False, "reason": "broker sim fills synchronously"}


def test_reconciler_loop_starts_stops_and_uses_the_interval():
    clock = Clock(MON_OPEN + dt.timedelta(hours=1))
    b = FakeRecBroker()
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)
        await asyncio.sleep(0)

    r = rc.Reconciler(lambda: b, clock=clock, sleep=fake_sleep)

    async def go():
        assert r.start() is True and r.start() is False
        for _ in range(20):
            await asyncio.sleep(0)
        assert r.running
        stopped = await r.stop()
        return stopped
    assert run(go()) is True
    assert not r.running and b.calls >= 2 and set(slept) == {15.0} and r.status()["state"] == "stopped"


def test_reconcile_routes_start_stop_status_and_run_and_shutdown_stops(tmp_path, monkeypatch):
    sb = Sandbox()
    app = create_app()
    app.state.broker = make(sb, tmp_path)
    app.state.staged_clock = Clock(SAT_NOON)
    with TestClient(app) as c:
        c.get("/account")  # under pytest no auto-start unless WEBULL_RECONCILE=force
        assert c.get("/broker/reconcile").json()["running"] is False
        s = c.post("/broker/reconcile/start").json()
        assert s["started"] is True and s["running"] is True and s["status_map"]["PARTIAL_FILLED"].startswith("open")
        st = c.get("/broker/reconcile").json()
        assert st["market_open"] is False and st["broker"] == "webull-paper" and st["supported"] is True
        run_now = c.post("/broker/reconcile/run").json()  # forced pass, read-only
        assert run_now["ran"] and run_now["ok"] and run_now["open_at_webull"] == 0
        assert c.post("/broker/reconcile/stop").json()["stopped"] is True
        monkeypatch.setenv("WEBULL_RECONCILE", "force")
        c.get("/positions")
        assert c.get("/broker/reconcile").json()["running"] is False  # stopped by the user: no auto-start
        c.post("/broker/reconcile/start")
        rec = app.state.reconciler
        assert rec.running
    assert not rec.running  # the router's shutdown hook stopped it
    assert not [r for r in sb.requests if r.url.path == "/trading/orders/place"]


def test_auto_start_with_force_for_webull_only(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBULL_RECONCILE", "force")
    app = create_app()
    app.state.broker = make(Sandbox(), tmp_path)
    app.state.staged_clock = Clock(SAT_NOON)
    with TestClient(app) as c:
        c.get("/orders")
        assert c.get("/broker/reconcile").json()["running"] is True
    sim_app = create_app()
    with TestClient(sim_app) as c:
        c.get("/orders")
        assert c.get("/broker/reconcile").json()["running"] is False  # the simulator fills synchronously
    monkeypatch.setenv("WEBULL_RECONCILE", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert rc.auto_start_enabled() is False


# ------------------------------------------------------------------------------------------------ shortability

def test_can_short_true_false_none_and_cached(tmp_path):
    sb = Sandbox(profiles={"GME": {"easy_to_borrow": False}, "XYZ": {"shortable": False}, "OLD": {"status": "NT"},
                           "LIQ": {"status": "CO"}})

    async def go():
        b = make(sb, tmp_path)
        out = {s: await b.can_short(s) for s in ("AAPL", "GME", "XYZ", "OLD", "LIQ", "UNLISTED")}
        st = await b.short_status(["GME", "AAPL"])
        await b.can_short("AAPL")
        return out, st
    out, st = run(go())
    assert out == {"AAPL": True, "GME": True, "XYZ": False, "OLD": False, "LIQ": False, "UNLISTED": None}
    assert "hard to borrow" in st["GME"]["reason"] and st["AAPL"]["reason"] == "shortable, easy to borrow"
    prof = paths(sb, "/trading/instruments/stocks/profiles/list")
    assert len(prof) == 6 and prof[0].url.params["category"] == "US_STOCK"  # GME/AAPL/AAPL served from the cache


def test_can_short_is_false_for_a_cash_account_and_none_when_the_lookup_fails(tmp_path):
    from tests.test_webull_market_hours import Hours

    class Down(Sandbox):
        def handler(self, r):
            if r.url.path == "/trading/instruments/stocks/profiles/list":
                return httpx.Response(500, json={"message": "down"})
            return super().handler(r)
    # Hours lists the cash account first: make() picks it
    cash = run(make(Hours(closed=False), tmp_path).short_status(["SPY"]))["SPY"]
    assert cash["can_short"] is False and "cash account" in cash["reason"]
    down = run(make(Down(), tmp_path).short_status(["SPY"]))["SPY"]
    assert down["can_short"] is None and "lookup failed" in down["reason"]
    assert short_verdict(None) is None and short_verdict({"shortable": True, "status": "CO"}) is False


def test_a_short_webull_lists_as_not_shortable_is_refused_before_it_is_sent(tmp_path):
    sb = Sandbox(profiles={"AAPL": {"shortable": False}})

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=5,
                                                                 client_order_id="s1"))
    o = run(go())
    assert o.status == "rejected" and o.reject_reason.startswith("not_shortable: AAPL")
    assert not paths(sb, "/trading/orders/place")


def test_a_split_sell_on_a_not_shortable_name_sells_what_is_held_and_refuses_the_short(tmp_path):
    sb = Sandbox(held=3.0, profiles={"AAPL": {"shortable": False}})

    async def go():
        b = make(sb, tmp_path)
        o = await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=5, client_order_id="p"))
        return o, await b.find_order("p")
    o, again = run(go())
    sent = [json.loads(r.content)["new_orders"][0] for r in paths(sb, "/trading/orders/place")]
    assert [(i["side"], i["quantity"]) for i in sent] == [("SELL", "3")]
    assert o.status == "rejected" and o.filled_qty == 3 and "not_shortable" in o.reject_reason
    assert again.filled_qty == 3


def test_shortable_and_capabilities_routes(tmp_path):
    app = create_app()
    app.state.broker = make(Sandbox(profiles={"XYZ": {"shortable": False}}), tmp_path)
    with TestClient(app) as c:
        cap = c.get("/broker/capabilities", params={"symbols": "spy,XYZ"}).json()
        assert cap["broker"] == "webull-paper" and cap["options_supported"] is False and cap["options_route"] == "sim"
        assert cap["reconcile"] is True and cap["can_short"]["SPY"]["can_short"] is True
        assert cap["can_short"]["XYZ"]["can_short"] is False and "unverified" in cap["note"]
        assert c.get("/broker/shortable/xyz").json()["can_short"] is False
        assert c.get("/broker/capabilities", params={"symbols": "a b"}).status_code == 422
    with TestClient(create_app()) as c:  # the simulator
        cap = c.get("/broker/capabilities", params={"symbols": "SPY"}).json()
        assert cap["options_supported"] is True and cap["can_short"]["SPY"]["can_short"] is True
        assert cap["reconcile"] is False


# ------------------------------------------------------------------------------------------------ balances / positions

REAL_BALANCE = {"total_asset_currency": "USD", "total_net_liquidation_value": "1000000.00", "total_market_value": "0.00",
                "total_cash_balance": "1000000.00", "total_unrealized_profit_loss": "0.00", "day_trades_left": "UNLIMITED",
                "maintenance_margin": "0.00", "open_margin_calls": [],
                "account_currency_assets": [{"currency": "USD", "net_liquidation_value": "1000000.00",
                                             "cash_balance": "1000000.00", "option_buying_power": "1000000.00",
                                             "day_buying_power": "4000000", "overnight_buying_power": "2000000.00",
                                             "settled_cash": "1000000.00"}]}


def test_margin_balance_uses_overnight_buying_power_and_reports_every_margin_figure(tmp_path):
    class Margin(Sandbox):
        def handler(self, r):
            if r.url.path == "/trading/assets/balances/get":
                return httpx.Response(200, json=REAL_BALANCE)  # the sandbox's real shape (2026-10-03), no buying_power
            return super().handler(r)
    a = run(make(Margin(), tmp_path).account())
    assert (a.cash, a.equity, a.buying_power) == (1e6, 1e6, 2e6)
    assert (a.day_buying_power, a.overnight_buying_power, a.option_buying_power) == (4e6, 2e6, 1e6)
    assert a.maintenance_margin == 0 and a.open_margin_calls == [] and a.day_trades_left == "UNLIMITED"
    assert a.options_supported is False and a.options_route == "sim" and "overnight" in a.note


def test_option_and_equity_positions_are_parsed_and_labelled(tmp_path):
    class Held(Sandbox):
        def handler(self, r):
            if r.url.path == "/trading/assets/positions/list":
                return httpx.Response(200, json=[
                    {"symbol": "TLT", "instrument_type": "EQUITY", "quantity": "-376", "cost_price": "90",
                     "last_price": "89", "position_id": "P1"},
                    {"symbol": "SPY", "instrument_type": "OPTION", "option_strategy": "SINGLE", "quantity": "2",
                     "cost_price": "3.1", "last_price": "3.5", "unrealized_profit_loss": "80",
                     "legs": [{"symbol": "SPY", "quantity": "2", "option_type": "PUT", "option_expire_date": "2026-10-16",
                               "option_exercise_price": "560", "option_contract_multiplier": "100"}]}])
            return super().handler(r)
    ps = run(make(Held(), tmp_path).positions())
    by = {p.symbol: p for p in ps}
    assert by["TLT"].qty == -376 and by["TLT"].unrealized_pnl == pytest.approx(376) and by["TLT"].account == "Webull paper account"
    opt = by["O:SPY261016P00560000"]
    assert (opt.asset, opt.qty, opt.multiplier, opt.market_value, opt.strategy) == ("option", 2, 100, 700.0, "SINGLE")


# ------------------------------------------------------------------------------------------------ options at Webull

def opt(cid, sym, side, **kw):
    return OrderRequest(symbol=sym, asset="option", side=side, qty=kw.pop("qty", 1), client_order_id=cid, **kw)


@pytest.mark.parametrize("legs,want", [
    ([("O:SPY261016C00500000", "buy")], "SINGLE"),
    ([("O:SPY261016C00500000", "buy"), ("O:SPY261016C00510000", "sell")], "VERTICAL"),
    ([("O:SPY261016C00500000", "sell"), ("O:SPY261016P00500000", "sell")], "STRADDLE"),
    ([("O:SPY261016C00510000", "buy"), ("O:SPY261016P00490000", "buy")], "STRANGLE"),
    ([("O:SPY261016C00500000", "sell"), ("O:SPY261120C00500000", "buy")], "CALENDAR"),
    ([("O:SPY261016P00480000", "buy"), ("O:SPY261016P00490000", "sell"), ("O:SPY261016C00510000", "sell"),
      ("O:SPY261016C00520000", "buy")], "IRON_CONDOR"),
    ([("O:SPY261016C00500000", "buy"), ("O:QQQ261016C00500000", "sell")], None),
    ([("O:SPY261016C00500000", "buy"), ("O:SPY261120C00510000", "sell")], None),
    ([("SPY", "buy")], None)])
def test_option_strategy_names(legs, want):
    assert option_strategy([opt(f"l{i}", s, side) for i, (s, side) in enumerate(legs)]) == want


def wb_options(sb, tmp_path):
    b = make(sb, tmp_path)
    b.options_supported = True
    return b


def test_options_supported_single_leg_order_is_sent_to_webull_in_the_documented_shape(tmp_path):
    sb = Book(status="FILLED")
    sb.detail["oc1"] = {"client_order_id": "oc1", "combo_type": "NORMAL", "orders": [
        {"client_order_id": "oc1", "order_id": "WB-9", "status": "FILLED", "instrument_type": "OPTION", "side": "BUY",
         "total_quantity": "2", "filled_quantity": "2", "filled_price": "3.40", "symbol": "SPY",
         "legs": [{"symbol": "SPY", "side": "BUY", "quantity": "1", "option_type": "PUT", "strike_price": "560",
                   "option_expire_date": "2026-10-16"}]}]}

    async def go():
        b = wb_options(sb, tmp_path)
        o = await b.place_order(opt("oc1", "O:SPY261016P00560000", "buy", qty=2))
        return b, o, await b.orders()
    b, o, rows = run(go())
    item = json.loads(paths(sb, "/trading/orders/place")[0].content)["new_orders"][0]
    assert item == {"client_order_id": "oc1", "combo_type": "NORMAL", "option_strategy": "SINGLE", "order_type": "MARKET",
                    "quantity": "2", "side": "BUY", "time_in_force": "DAY", "entrust_type": "QTY",
                    "instrument_type": "OPTION", "market": "US", "symbol": "SPY",
                    "legs": [{"side": "BUY", "quantity": "1", "symbol": "SPY", "strike_price": "560",
                              "option_expire_date": "2026-10-16", "instrument_type": "OPTION", "option_type": "PUT",
                              "market": "US"}]}
    assert (o.broker, o.asset, o.status, o.filled_qty, o.fill_px, o.id) == ("webull-paper", "option", "filled", 2, 3.4, "WB-9")
    assert any(r.client_order_id == "oc1" and r.broker == "webull-paper" for r in rows)
    assert not b.sim._orders  # nothing went to the simulator


def test_options_supported_vertical_is_one_net_limit_and_leg_prices_sum_to_webulls_net(tmp_path):
    sb = Book(status="FILLED")
    sb.detail["cv"] = {"data": {"client_order_id": "cv", "combo_type": "NORMAL", "orders": [
        {"client_order_id": "cv", "order_id": "WB-V", "status": "FILLED", "instrument_type": "OPTION", "side": "BUY",
         "option_strategy": "VERTICAL", "total_quantity": "3", "filled_quantity": "3", "filled_price": "2.05"}]}}
    legs = [opt("cv-L0", "O:SPY261016C00500000", "buy", qty=3, ref_px=5.0, ref_half_spread=0.05, combo_id="cv"),
            opt("cv-L1", "O:SPY261016C00510000", "sell", qty=3, ref_px=3.0, ref_half_spread=0.05, combo_id="cv")]

    async def go():
        b = wb_options(sb, tmp_path)
        return await b.place_combo(legs)
    a, c = run(go())
    item = json.loads(paths(sb, "/trading/orders/place")[0].content)["new_orders"][0]
    assert (item["option_strategy"], item["order_type"], item["side"], item["limit_price"], item["quantity"]) == (
        "VERTICAL", "LIMIT", "BUY", "2.1", "3")  # net debit 2.00 + 0.10 half-spreads
    assert [(lg["side"], lg["strike_price"], lg["quantity"]) for lg in item["legs"]] == [("BUY", "500", "1"),
                                                                                       ("SELL", "510", "1")]
    assert a.status == c.status == "filled" and a.combo_id == c.combo_id == "cv"
    assert a.fill_px - c.fill_px == pytest.approx(2.05) and a.price_source == "webull_paper_net_allocated"


def test_options_supported_credit_spread_unknown_structures_and_missing_prices(tmp_path):
    sb = Book()
    credit = [opt("k-L0", "O:SPY261016P00490000", "sell", ref_px=4.0, combo_id="k"),
              opt("k-L1", "O:SPY261016P00480000", "buy", ref_px=2.5, combo_id="k")]
    odd = [opt("u-L0", "O:SPY261016C00500000", "buy", combo_id="u"),
           opt("u-L1", "O:SPY261120C00510000", "sell", combo_id="u")]
    noprice = [opt("n-L0", "O:SPY261016C00500000", "buy", combo_id="n"),
               opt("n-L1", "O:SPY261016C00510000", "sell", combo_id="n")]

    async def go():
        b = wb_options(sb, tmp_path)
        b.sim.quotes = FakeQuotes()
        return await b.place_combo(credit), await b.place_combo(odd), await b.place_combo(noprice)
    cr, un, npx = run(go())
    item = json.loads(paths(sb, "/trading/orders/place")[0].content)["new_orders"][0]
    assert (item["side"], item["limit_price"]) == ("SELL", "1.5")  # net credit, no half-spread given
    assert all(o.broker == "sim" and "no option_strategy" in o.note for o in un)
    assert all(o.status == "rejected" and o.reject_reason.startswith("no_price") for o in npx)
    assert len(paths(sb, "/trading/orders/place")) == 1


def test_options_supported_orders_are_refused_cleanly_while_the_market_is_closed(tmp_path):
    from tests.test_webull_market_hours import Hours

    async def go():
        b = wb_options(Hours(closed=True), tmp_path)
        return await b.place_combo([opt("m-L0", "O:SPY261016C00500000", "buy", ref_px=5.0, combo_id="m"),
                                    opt("m-L1", "O:SPY261016C00510000", "sell", ref_px=3.0, combo_id="m")])
    legs = run(go())
    assert all(o.status == "rejected" and o.reject_reason == MARKET_CLOSED_REASON for o in legs)


def test_cancelling_a_webull_option_order_cancels_the_combo_client_id(tmp_path):
    sb = Book(status="SUBMITTED")

    async def go():
        b = wb_options(sb, tmp_path)
        legs = await b.place_combo([opt("z-L0", "O:SPY261016C00500000", "buy", ref_px=5.0, combo_id="z"),
                                    opt("z-L1", "O:SPY261016C00510000", "sell", ref_px=3.0, combo_id="z")])
        sb.status = "CANCELLED"
        return legs, await b.cancel(legs[1].id)
    legs, out = run(go())
    assert legs[0].status == "open"
    assert json.loads(paths(sb, "/trading/orders/cancel")[0].content)["client_order_id"] == "z"
    assert out.status == "cancelled" and out.client_order_id == "z-L1"


def test_options_stay_in_the_simulator_without_the_flag(tmp_path):
    sb = Sandbox()

    async def go():
        b = make(sb, tmp_path)
        return await b.place_order(opt("s1", "O:X270115C00001000", "buy"))
    o = run(go())
    assert o.broker == "sim" and not paths(sb, "/trading/orders/place")


def test_factory_reads_the_options_flag(monkeypatch):
    import app.broker as broker_mod

    monkeypatch.setattr(broker_mod, "_env", lambda n: {"BROKER": "webull", "WEBULL_APP_KEY": "k",
                                                       "WEBULL_APP_SECRET": "s", "WEBULL_OPTIONS": "1"}.get(n, ""))
    b = broker_mod.build_broker(None)
    assert isinstance(b, WebullBroker) and b.options_supported is True and b.client.limiter is not None


# ------------------------------------------------------------------------------------------------ rate limit

def test_rate_limiter_spaces_calls_to_the_documented_limit():
    now = [0.0]
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)
        now[0] += s

    lim = RateLimiter({"/p": (2, 2.0)}, clock=lambda: now[0], sleep=sleep)

    async def go():
        for _ in range(3):
            await lim.acquire("/p")
        await lim.acquire("/free")
    run(go())
    assert slept == [pytest.approx(2.01)] and lim.waited_s == pytest.approx(2.01)
    mocked = WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    assert mocked.limiter is None  # an injected transport is not paced


# ------------------------------------------------------------------------------------------------ positions / portfolio

def test_positions_route_separates_the_broker_book_from_demo_holdings(tmp_path, monkeypatch):
    from app import portfolio

    pf = tmp_path / "pf.json"
    pf.write_text(json.dumps({"holdings": [{"ticker": "TLT", "shares": 1000}, {"ticker": "IWM", "shares": 400}]}))
    monkeypatch.setattr(portfolio, "PORTFOLIO_PATH", pf)
    app = create_app()
    app.state.broker = make(Sandbox(held=7.0), tmp_path)
    with TestClient(app) as c:
        plain = c.get("/positions").json()
        both = c.get("/positions", params={"include_demo": True}).json()
    assert [(p["symbol"], p["account"]) for p in plain] == [("AAPL", "Webull paper account")]
    assert [(p["symbol"], p["broker"], p["account"], p["qty"]) for p in both[1:]] == [
        ("TLT", "demo", "demo holdings", 1000), ("IWM", "demo", "demo holdings", 400)]


def test_portfolio_shows_the_webull_paper_book_separately_with_short_readiness(tmp_path, monkeypatch):
    from app import mapping, portfolio
    from tests.test_equities import make as make_eq

    pf = tmp_path / "pf.json"
    pf.write_text(json.dumps({"holdings": [{"ticker": "AAPL", "shares": 10}, {"ticker": "XYZ", "shares": 5}]}))
    monkeypatch.setattr(portfolio, "PORTFOLIO_PATH", pf)
    ml = tmp_path / "map.json"
    ml.write_text(json.dumps({"items": {}}))
    monkeypatch.setattr(mapping, "MAP_PATH", ml)
    c = make_eq(None, monkeypatch)
    c.app.state.broker = make(Sandbox(held=7.0, profiles={"XYZ": {"shortable": False}}), tmp_path)
    d = c.get("/portfolio").json()
    assert d["holdings_label"] == "demo holdings"
    book = d["broker_account"]
    assert (book["label"], book["broker"], book["available"]) == ("Webull paper account", "webull-paper", True)
    assert book["account"]["cash"] == 90000.0 and book["account"]["buying_power"] == 180000.0
    assert [(p["symbol"], p["account"]) for p in book["positions"]] == [("AAPL", "Webull paper account")]
    h = {x["ticker"]: x for x in d["holdings"]}
    assert (h["AAPL"]["broker_qty"], h["AAPL"]["can_short"], h["AAPL"]["shares"]) == (7.0, True, 10)
    assert h["XYZ"]["can_short"] is False and h["XYZ"]["broker_qty"] == 0.0
    assert d["total_value"] is None  # demo totals never include the broker book


def test_portfolio_survives_a_broker_that_cannot_be_read(tmp_path, monkeypatch):
    from app import mapping, portfolio
    from tests.test_equities import make as make_eq

    class Down(Sandbox):
        def handler(self, r):
            return httpx.Response(503, json={"message": "maintenance"})
    pf = tmp_path / "pf.json"
    pf.write_text(json.dumps({"holdings": [{"ticker": "AAPL", "shares": 10}]}))
    monkeypatch.setattr(portfolio, "PORTFOLIO_PATH", pf)
    ml = tmp_path / "map.json"
    ml.write_text(json.dumps({"items": {}}))
    monkeypatch.setattr(mapping, "MAP_PATH", ml)
    c = make_eq(None, monkeypatch)
    c.app.state.broker = make(Down(), tmp_path)
    r = c.get("/portfolio")
    assert r.status_code == 200
    book = r.json()["broker_account"]
    assert book["available"] is False and "503" in book["error"]
    assert r.json()["holdings"][0]["broker_qty"] is None and r.json()["holdings"][0]["can_short"] is None
