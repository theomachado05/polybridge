import asyncio
from types import SimpleNamespace

import pytest

from app import bridges
from app.broker import SimBroker
from app.broker.quotes import Quote
from tests.test_bridges import _approved, _body, _events, client, replay_file  # noqa: F401
from tests.test_broker_support import FakeQuotes, run

SCRIPT = {1: 100.0, 5: 50.0, 10: -80.0}


class FakeEngine:
    def __init__(self, spec):
        self.spec, self.n, self.current_hedge = spec, 0, 0.0

    def on_tick(self, *, ts_ns, p, now_ns):
        self.n += 1
        q = SCRIPT.get(self.n)
        return SimpleNamespace(action="order" if q else "hold", reason="rebalance" if q else "in_band",
                               order_qty=q or 0.0, target_hedge=0.0, current_hedge=self.current_hedge, latency_ns=100)

    def on_fill(self, qty):
        self.current_hedge += qty


@pytest.fixture(autouse=True)
def fake_engine(monkeypatch):
    monkeypatch.setattr(bridges, "_load_engine", lambda: SimpleNamespace(HedgeSpec=lambda **kw: SimpleNamespace(**kw),
                                                                         Engine=FakeEngine))


def pin(client, broker):
    client.app.state.broker = broker
    return broker


def start(client, **kw):
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, **kw)).json()["bridge_id"]
    return bid, _events(client, bid)


def test_engine_orders_reach_the_broker_sell_to_add_and_buy_to_reduce(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "fake_last")})))
    bid, ev = start(client, replay_to_account=True)
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["side"], f["qty"]) for f in fills] == [("sell", 100.0), ("sell", 50.0), ("buy", 80.0)]
    assert all(f["status"] == "filled" and f["broker"] == "sim" and f["symbol"] == "ABNB" for f in fills)
    assert fills[0]["fill_px"] == 149.985
    assert fills[0]["price_note"] and fills[0]["scope"] == "account"
    assert all(o.note == bridges.REPLAY_NOTE for o in run(b.orders()))
    pos = run(b.positions())
    assert [(p.symbol, p.qty) for p in pos] == [("ABNB", -70.0)]
    orders = run(b.orders())
    assert len(orders) == 3 and {o.tag for o in orders} == {bid}
    assert len({o.client_order_id for o in orders}) == 3
    kinds = [k for k, _ in ev]
    assert kinds.count("position") == 3 and kinds.count("fill") == 3
    assert [d["hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 70.0]
    assert [d["broker"] for k, d in ev if k == "position"] == ["sim"] * 3
    assert [d["broker_hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 70.0]
    assert [d["broker_coverage"] for k, d in ev if k == "position"] == pytest.approx([100 / 1200, 150 / 1200, 70 / 1200])
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker"] == "sim" and s["account_scope"] == "account" and s["broker_hedge"] == 70.0 and s["broker_filled"] == 3 and s["broker_rejects"] == 0 and s["broker_errors"] == 0
    assert s["last_fill"]["side"] == "buy" and s["orders"] == 3 and s["status"] == "finished"
    assert client.get("/positions").json()[0]["qty"] == -70.0
    assert client.get("/account").json()["cash"] == pytest.approx(run(b.account()).cash)


def test_account_math_after_the_bridge_run(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")})))
    start(client, replay_to_account=True)
    a = run(b.account())
    sell_px, buy_px = 150 - 0.015, 150 + 0.015
    realised = (sell_px - buy_px) * 80
    assert a.realized_pnl == pytest.approx(realised)
    assert a.fees_paid == pytest.approx(230 * 0.005)
    assert a.cash == pytest.approx(1_000_000 + 150 * sell_px - 80 * buy_px - 230 * 0.005, abs=1e-3)


def test_no_price_rejects_are_recorded_and_the_loop_keeps_running(client, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes()))
    bid, ev = start(client, replay_to_account=True)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["held", "held", "held"]
    assert all(f["reject_reason"].startswith("capital_budget: no price") for f in fills[:2])
    assert fills[2]["reject_reason"].startswith("no short filled") and fills[2]["capped_from"] == 80.0
    kinds = [k for k, _ in ev]
    assert kinds.count("tick") == 20 and ev[-1][1]["status"] == "finished"
    s = client.get(f"/bridges/{bid}").json()
    assert s["capital_refused"] == 2 and s["broker_rejects"] == 0 and s["broker_filled"] == 0 and s["orders"] == 3
    assert s["broker_hedge"] == 0.0


def test_insufficient_buying_power_is_reported_not_raised(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")}), starting_cash=1000.0))
    bid, ev = start(client, replay_to_account=True)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["held", "held", "held"]
    assert all(f["reject_reason"].startswith("capital_budget: ") for f in fills[:2])
    assert all(f["capital_price_source"] == "quote" for f in fills[:2])
    assert run(b.positions()) == [] and run(b.account()).cash == 1000.0
    assert [d["broker_hedge"] for k, d in ev if k == "position"] == [0.0, 0.0, 0.0]
    assert [d["hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 70.0]
    assert ev[-1][1]["status"] == "finished"


class _Exploding:
    name = "exploding"

    async def place_order(self, req):
        raise RuntimeError("broker is on fire")


def test_a_raising_broker_never_stops_the_bridge(client):
    pin(client, _Exploding())
    bid, ev = start(client, replay_to_account=True)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["error", "held", "held"] and fills[0]["error"] == "RuntimeError"
    assert fills[0]["kept_resting"] is True and fills[0]["order_id"] == f"{bid}-1"
    assert "on fire" not in str(fills)
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_errors"] >= 3 and s["status"] == "finished" and s["ticks"] == 20
    assert s["resting_order"]["unconfirmed"] is True
    assert [d["hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 70.0]
    assert [d["broker_hedge"] for k, d in ev if k == "position"] == [0.0, 0.0, 0.0]


class _Hanging(_Exploding):
    name = "hanging"

    async def place_order(self, req):
        await asyncio.sleep(60)


def test_a_hanging_broker_is_cut_off_by_the_timeout(client, monkeypatch):
    monkeypatch.setattr(bridges, "BROKER_TIMEOUT_S", 0.05)
    pin(client, _Hanging())
    bid, ev = start(client, replay_to_account=True)
    assert [d["status"] for k, d in ev if k == "fill"] == ["error", "held", "held"]
    assert ev[-1][1]["status"] == "finished"


def test_lookup_chain_shares_one_deadline(monkeypatch):
    class Slow:
        name = "slow"

        async def orders(self):
            await asyncio.sleep(0.04)
            return []

        async def find_order(self, cid):
            await asyncio.sleep(0.04)
            return None

    monkeypatch.setattr(bridges, "BROKER_TIMEOUT_S", 0.06)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(bridges._lookup(Slow(), "o1", "c1"))
    monkeypatch.setattr(bridges, "BROKER_TIMEOUT_S", 1.0)
    assert asyncio.run(bridges._lookup(Slow(), "o1", "c1")) is None


def test_broker_construction_failure_leaves_the_bridge_running(client, monkeypatch):
    def broken(app):
        raise RuntimeError("no broker")
    monkeypatch.setattr(bridges, "get_broker", broken)
    bid, ev = start(client)
    kinds = [k for k, _ in ev]
    assert kinds[0] == "error" and ev[0][1]["source"] == "broker"
    assert "fill" not in kinds and kinds.count("position") == 3 and ev[-1][1]["status"] == "finished"
    assert client.get(f"/bridges/{bid}").json()["broker"] is None


def test_default_broker_comes_from_the_environment_and_is_the_sim(client):
    bid, ev = start(client)
    s = client.get(f"/bridges/{bid}").json()
    assert s["account_scope"] == "replay_sandbox" and s["broker"] == "sim-replay"
    assert [d["status"] for k, d in ev if k == "fill"] == ["rejected", "rejected", "held"]
    assert s["broker_hedge"] == 0.0 and s["hedge"] == 70.0 and s["hedge_basis"] == "engine_intent"
    assert [d["broker_hedge"] for k, d in ev if k == "position"] == [0.0] * 3
    live = start(client, replay_to_account=True)
    assert client.get(f"/bridges/{live[0]}").json()["broker"] == "sim"


def test_replay_bridges_use_an_isolated_sandbox_by_default(client, tmp_path):
    acct = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")})))
    bid, ev = start(client)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["filled"] * 3
    assert {f["broker"] for f in fills} == {"sim-replay"} and {f["scope"] for f in fills} == {"replay_sandbox"}
    assert all(f["note"] == bridges.REPLAY_NOTE for f in fills)
    assert run(acct.positions()) == [] and run(acct.orders()) == []
    assert not (tmp_path / "s.json").exists()
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker"] == "sim-replay" and s["account_scope"] == "replay_sandbox" and s["broker_hedge"] == 70.0


def test_replay_never_reaches_webull_unless_opted_in(client, tmp_path):
    import httpx
    from app.broker import WebullBroker, WebullClient
    seen = []

    def h(r):
        seen.append(r.url.path)
        return httpx.Response(200, json={"data": {"holdings": []}})
    sim = SimBroker(tmp_path / "w.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")}))
    pin(client, WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(h))), sim, account_id="A"))
    bid, ev = start(client)
    assert [d["broker"] for k, d in ev if k == "fill"] == ["sim-replay"] * 3
    assert seen == [] and run(sim.positions()) == []
