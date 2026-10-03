"""Bridge -> broker integration with a fake engine (no compiled hedgecore needed)."""
import asyncio
from types import SimpleNamespace

import pytest

from app import bridges
from app.broker import SimBroker
from app.broker.quotes import Quote
from tests.test_bridges import _approved, _body, _events, client, replay_file  # noqa: F401
from tests.test_broker_support import FakeQuotes, run

SCRIPT = {1: 100.0, 5: 50.0, 10: -80.0}  # engine tick number -> order_qty (>0 adds to the short hedge, <0 reduces it)


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


def start(client):
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid)).json()["bridge_id"]
    return bid, _events(client, bid)


def test_engine_orders_reach_the_broker_sell_to_add_and_buy_to_reduce(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "fake_last")})))
    bid, ev = start(client)
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["side"], f["qty"]) for f in fills] == [("sell", 100.0), ("sell", 50.0), ("buy", 80.0)]
    assert all(f["status"] == "filled" and f["broker"] == "sim" and f["symbol"] == "ABNB" for f in fills)
    assert fills[0]["fill_px"] == 149.985  # a sell fills at mid minus the 1 bp half-spread
    assert fills[0]["price_note"]  # replay ticks are historical: the price is labelled as current
    pos = run(b.positions())
    assert [(p.symbol, p.qty) for p in pos] == [("ABNB", -70.0)]  # short 150, covered 80
    orders = run(b.orders())
    assert len(orders) == 3 and {o.tag for o in orders} == {bid}
    assert len({o.client_order_id for o in orders}) == 3
    # the stream order: fill, then position, per order; the engine-side hedge is unchanged by the broker
    kinds = [k for k, _ in ev]
    assert kinds.count("position") == 3 and kinds.count("fill") == 3
    assert [d["hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 70.0]
    assert [d["broker"] for k, d in ev if k == "position"] == ["sim"] * 3
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker"] == "sim" and s["broker_filled"] == 3 and s["broker_rejects"] == 0 and s["broker_errors"] == 0
    assert s["last_fill"]["side"] == "buy" and s["orders"] == 3 and s["status"] == "finished"
    # and the API reads the same account
    assert client.get("/positions").json()[0]["qty"] == -70.0
    assert client.get("/account").json()["cash"] == pytest.approx(run(b.account()).cash)


def test_account_math_after_the_bridge_run(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")})))
    start(client)
    a = run(b.account())
    sell_px, buy_px = 150 - 0.015, 150 + 0.015  # 1 bp half-spread on 150
    realised = (sell_px - buy_px) * 80
    assert a.realized_pnl == pytest.approx(realised)
    assert a.fees_paid == pytest.approx(230 * 0.005)
    assert a.cash == pytest.approx(1_000_000 + 150 * sell_px - 80 * buy_px - 230 * 0.005, abs=1e-3)


def test_no_price_rejects_are_recorded_and_the_loop_keeps_running(client, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes()))  # no Massive price for ABNB, none supplied
    bid, ev = start(client)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["rejected"] * 3 and fills[0]["reject_reason"].startswith("no_price")
    kinds = [k for k, _ in ev]
    assert kinds.count("tick") == 20 and ev[-1][1]["status"] == "finished"
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_rejects"] == 3 and s["broker_filled"] == 0 and s["orders"] == 3


def test_insufficient_buying_power_is_reported_not_raised(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")}), starting_cash=1000.0))
    bid, ev = start(client)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["rejected"] * 3
    assert {f["reject_reason"] for f in fills} == {"insufficient_buying_power"}
    assert run(b.positions()) == [] and run(b.account()).cash == 1000.0
    assert ev[-1][1]["status"] == "finished"


class _Exploding:
    name = "exploding"

    async def place_order(self, req):
        raise RuntimeError("broker is on fire")


def test_a_raising_broker_never_stops_the_bridge(client):
    pin(client, _Exploding())
    bid, ev = start(client)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["error"] * 3 and fills[0]["error"] == "RuntimeError"
    assert "on fire" not in str(fills)  # the exception text is not echoed to the stream
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_errors"] == 3 and s["status"] == "finished" and s["ticks"] == 20
    assert [d["hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 70.0]


class _Hanging(_Exploding):
    name = "hanging"

    async def place_order(self, req):
        await asyncio.sleep(60)


def test_a_hanging_broker_is_cut_off_by_the_timeout(client, monkeypatch):
    monkeypatch.setattr(bridges, "BROKER_TIMEOUT_S", 0.05)
    pin(client, _Hanging())
    bid, ev = start(client)
    assert [d["status"] for k, d in ev if k == "fill"] == ["error"] * 3
    assert ev[-1][1]["status"] == "finished"


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
    bid, ev = start(client)  # nothing pinned: get_broker(app) builds the sim (no market data in tests)
    assert client.get(f"/bridges/{bid}").json()["broker"] == "sim"
    assert [d["status"] for k, d in ev if k == "fill"] == ["rejected"] * 3
