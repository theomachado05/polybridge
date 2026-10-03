"""Capital controls (app/capital): the budget and margin math, GET /capital, and the pre-trade check on every order
path (bridge equity orders, staged hedge B approval and execution), failing closed when the account cannot be read."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.capital import budget as b
from tests.test_bridges import _events
from tests.test_liquidity import live_algo_app


# ------------------------------------------------------------------------------------------------------ the math


def test_reg_t_margin_for_shorts_and_options():
    assert b.short_equity_margin(100_000.0) == {"initial": 50_000.0, "maintenance": 30_000.0}
    # Reg T naked put: max(20% S - OTM, 10% K) + premium, x100. S 100, K 90 (10 OTM), premium 1: max(10, 9) + 1
    assert b.naked_put_margin(100.0, 90.0, 1.0) == pytest.approx(1_100.0)
    assert b.naked_put_margin(100.0, 50.0, 0.1) == pytest.approx((5.0 + 0.1) * 100)  # the 10%-of-strike floor
    assert b.option_requirement("call_spread", +1, 2, 3.0, 0.1) == pytest.approx(3.1 * 100 * 2)  # long: premium
    assert b.option_requirement("put_spread", -1, 1, 2.0, 0.1, width=5.0) == pytest.approx((5.0 - 1.9) * 100)
    assert b.option_requirement("cash_secured_put", -1, 1, 2.0, 0.0, strike=90.0) == pytest.approx(8_800.0)
    assert b.option_requirement("cash_secured_put", -1, 1, 2.0, 0.0, strike=90.0, spot=100.0,
                                mode="margin") == pytest.approx(b.naked_put_margin(100.0, 90.0, 2.0))
    assert b.option_requirement("straddle", -1, 1, None, None) is None


def test_evaluate_flags_each_budget_and_fails_closed_without_an_account():
    lim = {**b.limits(), "max_gross_hedge_pct": 0.5, "max_event_pct": 0.2}
    ok = b.evaluate(equity=1e6, buying_power=1e6, gross_now=0, event_now=0, add_notional=150_000,
                    add_margin=75_000, bp_basis="margin", lim=lim, event="polymarket:x")
    assert ok["ok"] and ok["event"]["limit_usd"] == 200_000
    bad = b.evaluate(equity=1e6, buying_power=50_000, gross_now=400_000, event_now=150_000, add_notional=150_000,
                     add_margin=75_000, bp_basis="margin", lim=lim, event="polymarket:x")
    assert {x["kind"] for x in bad["breaches"]} == {"gross_hedge_notional", "event_exposure", "buying_power"}
    webull = b.evaluate(equity=1e6, buying_power=120_000, gross_now=0, event_now=0, add_notional=150_000,
                        add_margin=75_000, bp_basis="notional", lim=lim)
    assert [x["kind"] for x in webull["breaches"]] == ["buying_power"]  # notional vs Webull's notional BP
    closed = b.evaluate(equity=None, buying_power=None, gross_now=0, event_now=0, add_notional=1, add_margin=1,
                        bp_basis="margin", lim=lim)
    assert not closed["ok"] and closed["breaches"][0]["kind"] == "account_unreadable"


def test_limits_come_from_env_then_app_state(monkeypatch):
    monkeypatch.setenv("CAPITAL_MAX_EVENT_PCT", "0.1")
    assert b.limits()["max_event_pct"] == 0.1 and b.limits()["max_gross_hedge_pct"] == 0.5
    app = type("A", (), {"state": type("S", (), {"capital_limits": {"max_gross_hedge_pct": 0.3}})()})()
    assert b.limits(app)["max_gross_hedge_pct"] == 0.3 and b.limits(app)["max_event_pct"] == 0.1
    monkeypatch.setenv("CAPITAL_MAX_EVENT_PCT", "nonsense")
    assert b.limits()["max_event_pct"] == 0.2


# ----------------------------------------------------------------------------------------------- bridges + route


def test_a_sell_that_would_breach_the_event_budget_is_refused_and_get_capital_shows_it(tmp_path, monkeypatch):
    """$1M sim account, per-event budget 20% ($200k): a 300-share SPY short ($150k) fits; another 200 ($100k more)
    would take the event to $250k and is refused with reason capital_budget; GET /capital reports the exposure."""
    from tests.test_bridges_algo import FakeAlgo, proposal

    app = live_algo_app(tmp_path, monkeypatch, {2: {"side": -1, "qty": 300.0}, 3: {"side": -1, "qty": 200.0}},
                        open5=1e6, adv=1e9)
    with TestClient(app) as c:
        p = proposal(c, {"family": "macro_fed_hedge"})
        bid = c.post("/bridges", json={"proposal_id": p["id"], "source": "live"}).json()["bridge_id"]
        ev = _events(c, bid)
        fills = [d for k, d in ev if k == "fill"]
        assert [(f["status"], f["qty"]) for f in fills] == [("filled", 300.0), ("held", 200.0)]
        refused = fills[1]
        assert refused["reject_reason"].startswith("capital_budget:")
        assert refused["gates"] == [{"reason": "capital_budget", "enforced": True, "breaches": ["event_exposure"]}]
        assert fills[0]["capital"]["ok"] is True and fills[0]["capital"]["scope"] == "account"
        assert FakeAlgo.instances[0].rejects == ["equity"]
        s = c.get(f"/bridges/{bid}").json()
        assert s["capital_refused"] == 1 and s["reasons"]["capital_budget"] == 1 and s["broker_hedge"] == 300.0

        cap = c.get("/capital").json()
        assert cap["account_read"] and cap["broker"] == "sim" and cap["buying_power_basis"] == "margin"
        assert cap["equity"] == pytest.approx(1e6, rel=1e-3)
        assert cap["gross_hedge_notional"] == pytest.approx(150_000, rel=1e-3)
        assert cap["gross_limit_usd"] == pytest.approx(0.5 * cap["equity"])
        ev0 = cap["events"][0]
        assert ev0["event"] == "polymarket:2589813" and ev0["equity_hedge_shares"] == 300.0
        assert ev0["use_pct"] == pytest.approx(150_000 / (0.2 * cap["equity"]), rel=1e-3)
        assert cap["margin"]["initial_required"] == pytest.approx(75_000, rel=1e-3)
        assert cap["margin"]["maintenance_required"] == pytest.approx(45_000, rel=1e-3)
        assert cap["breaches"] == [] and cap["limits"]["reg_t_initial"] == 0.5


def test_an_unreadable_account_refuses_exposure_increasing_orders(tmp_path, monkeypatch):
    from app.broker import BrokerError

    app = live_algo_app(tmp_path, monkeypatch, {2: {"side": -1, "qty": 100.0}}, open5=1e6, adv=1e9)

    async def down():
        raise BrokerError("account endpoint down", 502)
    monkeypatch.setattr(app.state.broker, "account", down)
    from tests.test_bridges_algo import proposal
    with TestClient(app) as c:
        p = proposal(c, {"family": "macro_fed_hedge"})
        bid = c.post("/bridges", json={"proposal_id": p["id"], "source": "live"}).json()["bridge_id"]
        f = next(d for k, d in _events(c, bid) if k == "fill")
        assert f["status"] == "held" and f["gates"][0]["breaches"] == ["account_unreadable"]
        cap = c.get("/capital").json()
        assert cap["account_read"] is False and "account endpoint down" in cap["account_error"]
        assert {x["kind"] for x in cap["breaches"]} == {"account_unreadable"}


def test_staged_approval_and_execution_check_the_budget(tmp_path):
    from tests.test_closed_staged import MON_PRE, approved_proposal, make_app
    import datetime as dt

    app = make_app(tmp_path)
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "rate_bp_per_pp": 7.523237932200106,
                                         "ref_px": 500.0}).json()
        assert o["qty"] == 376
        app.state.capital_limits = {"max_event_pct": 0.1}  # $100k per event < 376 x $500
        r = c.post(f"/staged/{o['id']}/approve")
        assert r.status_code == 409 and r.json()["detail"].startswith("CAPITAL_BUDGET")
        got = c.get("/staged").json()["orders"][0]
        assert got["status"] == "staged" and got["capital"]["breaches"][0]["kind"] == "event_exposure"
        app.state.capital_limits = {}
        assert c.post(f"/staged/{o['id']}/approve").json()["status"] == "approved"
        # the budget tightens before the session: the execution check refuses it
        app.state.capital_limits = {"max_event_pct": 0.1}
        app.state.capital_accounts = {}
        app.state.staged_clock.t = MON_PRE + dt.timedelta(minutes=5)
        done = c.post("/staged/run").json()["changed"][0]
        assert done["status"] == "rejected" and done["reason"] == "CAPITAL_BUDGET"
        assert c.get("/orders").json() == []


def test_a_replay_sandbox_is_evaluated_but_not_enforced(tmp_path, monkeypatch):
    """A replay trades a throwaway simulator: the budget is evaluated and shown, never enforced there."""
    from app.broker import SimBroker
    from app.broker.quotes import Quote
    from tests.test_bridges_algo import FakeAlgo, proposal, start
    from tests.test_broker_support import FakeQuotes
    from tests.test_liquidity import pinned_app
    from app import bridges
    from tests.test_bridges_algo import CATALOG
    from types import SimpleNamespace
    import json

    app = pinned_app(open5=1e6, adv=1e9)
    rp = tmp_path / "r.jsonl"
    rp.write_text("".join(json.dumps({"ts_ns": 1_000_000_000 * (i + 1), "p": 0.4, "under_px": 500.0}) + "\n"
                          for i in range(4)))
    app.state.replay_path, app.state.replay_speed = str(rp), 0
    app.state.broker = SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")}))
    app.state.capital_limits = {"max_event_pct": 0.01}
    FakeAlgo.script, FakeAlgo.instances = {2: {"side": -1, "qty": 100.0}}, []
    monkeypatch.setattr(bridges, "_load_engine", lambda: SimpleNamespace(catalog=lambda: CATALOG, Algo=FakeAlgo))
    with TestClient(app) as c:
        p = proposal(c, {"family": "macro_fed_hedge"})
        bid = start(c, p["id"]).json()["bridge_id"]
        f = next(d for k, d in _events(c, bid) if k == "fill")
        assert f["status"] == "filled" and f["scope"] == "replay_sandbox"
        assert f["capital"]["enforced"] is False and f["capital"]["ok"] is False and "not enforced" in f["capital"]["note"]
        assert c.get("/capital").json()["gross_hedge_notional"] == 0.0  # the account holds nothing from a sandbox


def test_get_capital_tells_not_checked_and_stale_apart_from_a_failed_read():
    """A broker with no account read is not checked (no fail-closed breach, nothing enforced); a failed read right after
    a good one is served from the last good read and labelled stale; a failed read with nothing cached is a breach."""
    import asyncio
    from types import SimpleNamespace

    from app.broker import BrokerError
    from app.capital import service

    class NoAccount:
        name = "fake"

    class Flaky:
        name = "flaky"
        up = True

        async def account(self):
            if not self.up:
                raise BrokerError("account endpoint down", 502)
            return SimpleNamespace(equity=1e6, cash=1e6, buying_power=2e6, broker="flaky")

        async def positions(self):
            return []

    async def run():
        app = SimpleNamespace(state=SimpleNamespace())
        nc = await service.snapshot(app, NoAccount())
        assert nc["account_checked"] is False and nc["account_read"] is False and nc["account_stale"] is False
        assert nc["breaches"] == []
        fl = Flaky()
        ok = await service.snapshot(app, fl)
        assert ok["account_checked"] and ok["account_read"] and not ok["account_stale"]
        fl.up = False
        st = await service.snapshot(app, fl)
        assert st["account_read"] and st["account_stale"] is True and "account endpoint down" in st["account_error"]
        cold = await service.snapshot(SimpleNamespace(state=SimpleNamespace()), fl)
        assert cold["account_checked"] and not cold["account_read"] and not cold["account_stale"]
        assert {x["kind"] for x in cold["breaches"]} == {"account_unreadable"}

    asyncio.run(run())


def test_an_unpriced_exposure_increasing_order_fails_closed_at_the_account():
    """No price anywhere (no tick, no cached Massive price, no broker mark or quote): at an account the broker can read
    the order is refused (breach no_price); a replay sandbox passes it labelled unchecked; a broker with no account
    read (a test fake) stays unchecked. A broker's own position mark prices the order before giving up."""
    import asyncio
    from types import SimpleNamespace

    from app.broker.models import Position
    from app.capital import service

    class Readable:
        name = "webull-paper"
        held: list = []

        async def account(self):
            return SimpleNamespace(equity=1e6, cash=1e6, buying_power=2e6, broker=self.name)

        async def broker_positions(self):
            return list(self.held)

        async def positions(self):
            return list(self.held)

    class NoAccount:
        name = "fake"

    async def run():
        app = SimpleNamespace(state=SimpleNamespace())
        acct = Readable()
        assert await service.order_price(app, acct, "SPY") == (None, None)
        chk = await service.check(app, broker=acct, event="polymarket:m1", add_notional=None, add_margin=None)
        assert service.refused(chk) and chk["breaches"][0]["kind"] == service.NO_PRICE
        assert service.refusal_text(chk).startswith("capital_budget: no price to size the budget")
        sb = await service.check(app, broker=acct, event="polymarket:m1", add_notional=None, add_margin=None,
                                 scope="replay_sandbox")
        assert not service.refused(sb) and sb["checked"] is False and "replay sandbox" in sb["note"]
        na = await service.check(app, broker=NoAccount(), event=None, add_notional=None, add_margin=None)
        assert not service.refused(na) and na["checked"] is False
        acct.held = [Position(symbol="SPY", asset="equity", qty=-10, avg_px=480.0, mark_px=500.0,
                              broker=acct.name)]
        assert await service.order_price(app, acct, "spy") == (500.0, "broker_position")
        assert await service.order_price(app, acct, "SPY", None, 0.0, 499.0) == (499.0, "order")
    asyncio.run(run())


def test_a_staged_order_at_a_broker_that_prices_itself_is_refused_without_a_price(tmp_path):
    """Webull prices its own fills, so a staged sell there was sent with no price and labelled "not checked". With no
    price from the plan, Massive or the broker, the capital budget now refuses it at execution (fail closed)."""
    import datetime as dt
    from types import SimpleNamespace

    from tests.test_closed_staged import MON_OPEN, RestingBroker, approved_proposal, make_app

    class PricelessWebull(RestingBroker):
        name = "webull-paper"

        async def account(self):
            return SimpleNamespace(equity=1e6, cash=1e6, buying_power=2e6, broker=self.name)

    fake = PricelessWebull()
    app = make_app(tmp_path, broker=fake)
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0, "rate_bp_per_pp": 7.5}).json()
        assert o["status"] == "staged" and o["ref_px"] is None
        r = c.post(f"/staged/{o['id']}/approve")
        assert r.status_code == 409 and "no price to size the budget" in r.json()["detail"]
        got = c.get("/staged").json()["orders"][0]
        assert got["status"] == "staged" and got["capital"]["breaches"][0]["kind"] == "no_price"
        # an order approved earlier (e.g. while a price was cached) is re-checked at execution: still no price at the
        # open, so it is refused and nothing reaches the broker
        from app.closed import staged
        st = staged.book_for(app).get(o["id"])
        st.status, st.approved_qty = "approved", st.qty
        app.state.staged_clock.t = MON_OPEN + dt.timedelta(minutes=1)
        done = c.post("/staged/run").json()["changed"][0]
        assert done["status"] == "rejected" and done["reason"] == "CAPITAL_BUDGET"
        assert done["capital"]["breaches"][0]["kind"] == "no_price"
    assert fake.placed == []
