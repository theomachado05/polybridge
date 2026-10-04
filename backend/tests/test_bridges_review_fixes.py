from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app import bridges
from app.broker.models import Order
from app.ticks import SourceError, Tick
from tests.test_bridges import _approved, _body, _events, client, replay_file  # noqa: F401
from tests.test_bridges_algo import FakeAlgo, ScriptedBroker, fake_hc, pin, proposal, start  # noqa: F401


def _order(req, oid, status, filled, px=500.0, limit=None):
    return Order(id=oid, client_order_id=req.client_order_id, broker="acct", symbol=req.symbol, asset="equity",
                 side=req.side, qty=req.qty, type=req.type, limit_px=limit if limit is not None else req.limit_px,
                 status=status, filled_qty=filled, fill_px=px if filled else None, created_at="t")


class AcceptsThenTimesOut:
    name = "acct"

    def __init__(self):
        self.placed = []

    async def place_order(self, req):
        self.placed.append(req)
        raise TimeoutError()

    async def orders(self):
        return [_order(r, f"B{i}", "filled", r.qty) for i, r in enumerate(self.placed)]

    async def cancel(self, oid):  # pragma: no cover - nothing is open
        raise AssertionError("nothing to cancel")


def test_an_accepted_order_whose_place_call_timed_out_is_reconciled_not_resent(client):
    br = pin(client, AcceptsThenTimesOut())
    FakeAlgo.script = {2: {"side": -1, "qty": 400.0}, 5: {"side": -1, "qty": 400.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    fills = [d for k, d in ev if k == "fill"]
    assert fills[0]["status"] == "error" and fills[0]["kept_resting"] is True
    a = FakeAlgo.instances[0]
    assert a.fills[0] == ("equity", -400.0, 500.0)
    assert [r.qty for r in br.placed] == [400.0, 100.0]
    assert fills[1]["capped_from"] == 400.0
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_hedge"] == 500.0 and s["broker_coverage"] == 0.5


class FilledWithoutPrice(ScriptedBroker):

    def __init__(self, limit=None):
        super().__init__()
        self.limit = limit

    async def place_order(self, req):
        self.placed.append(req)
        return _order(req, f"o{len(self.placed)}", "filled", req.qty, px=None, limit=self.limit)

    async def orders(self):
        return [_order(r, f"o{i + 1}", "filled", r.qty, px=None, limit=self.limit) for i, r in enumerate(self.placed)]


def test_a_fill_without_a_price_still_counts_toward_the_coverage_cap(client):
    br = pin(client, FilledWithoutPrice())
    FakeAlgo.script = {2: {"side": -1, "qty": 300.0}, 5: {"side": -1, "qty": 300.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_hedge"] == 300.0
    assert len(br.placed) == 1
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["filled", "held"]
    assert s["resting_order"]["unpriced"] is True
    assert any(k == "error" and "no fill price" in d["message"] for k, d in ev)


def test_a_fill_without_a_price_falls_back_to_the_limit_price(client):
    pin(client, FilledWithoutPrice(limit=499.0))
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 499.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    _events(client, bid)
    assert FakeAlgo.instances[0].fills == [("equity", -100.0, 499.0)]
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_hedge"] == 100.0 and s["resting_order"] is None


def _live_then_fail(n_ticks):
    class Live:
        def __init__(self, *_, **__):
            pass

        async def __aiter__(self):
            for i in range(n_ticks):
                yield Tick(time.time_ns(), 0.3, {"yes_bid": 0.29, "yes_ask": 0.31, "under_px": 500.0})
            raise SourceError("wifi down")
    return Live


def test_live_to_replay_fallback_settles_the_account_order_first(client, replay_file):
    br = pin(client, ScriptedBroker(partial=0.0, final="cancelled", final_filled=0.0))
    own = replay_file.with_name("2589813.jsonl")
    own.write_text(replay_file.read_text())
    client.app.state.replay_path = str(own)
    client.app.state.live_source_factory = _live_then_fail(3)
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 600.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = client.post("/bridges", json={"proposal_id": p["id"], "source": "live"}).json()["bridge_id"]
    ev = _events(client, bid)
    kinds = [k for k, _ in ev]
    switch = next(i for i, (k, d) in enumerate(ev) if k == "status" and d.get("note") == "live failed; replaying")
    cancel = next(i for i, (k, d) in enumerate(ev) if k == "cancel")
    assert cancel < switch and ev[cancel][1]["broker"] == "scripted" and ev[cancel][1]["status"] == "cancelled"
    assert br.cancelled == ["o1"]
    assert kinds.count("tick") == 3 + 20 and ev[-1][1]["status"] == "finished"


def test_a_resting_order_stays_with_its_broker_after_the_source_switch(client):
    acct = ScriptedBroker(partial=0.0, final="cancelled", final_filled=0.0)
    p = proposal(client, {"family": "macro_fed_hedge"})
    b = bridges.Bridge(SimpleNamespace(**{**p, "family": "hedge", "algo": None, "max_contracts": None,
                                          "max_notional": None}), "live",
                       bridges.MarketRef(**p["market"]), 0.0)
    b.broker = acct
    b.resting = {"order_id": "o1", "client_order_id": "x", "instrument": "equity", "side": "sell", "qty": 1.0,
                 "applied": 0.0, "hedged": 0.0}
    b.resting_broker = acct
    acct.placed.append(SimpleNamespace(client_order_id="x", symbol="SPY", side="sell", qty=1.0, type="limit",
                                       limit_px=600.0))
    b.effective_source = "replay"
    import asyncio
    algo = FakeAlgo("f", {}, {})
    assert asyncio.run(bridges._settle_resting(b, algo, b.order_broker(), "replace")) is True
    assert acct.cancelled == ["o1"] and b.resting is None and algo.rejects == ["equity"]


class ScriptedEngine:
    script: dict[int, float] = {}

    def __init__(self, spec):
        self.n, self.current_hedge = 0, 0.0

    def on_tick(self, *, ts_ns, p, now_ns):
        self.n += 1
        q = ScriptedEngine.script.get(self.n)
        return SimpleNamespace(action="order" if q else "hold", reason="rebalance" if q else "in_band",
                               order_qty=q or 0.0, target_hedge=0.0, current_hedge=self.current_hedge, latency_ns=1)

    def on_fill(self, qty):
        self.current_hedge += qty


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.setattr(bridges, "_load_engine", lambda: SimpleNamespace(HedgeSpec=lambda **kw: SimpleNamespace(**kw),
                                                                         Engine=ScriptedEngine))


class OpenOrders(ScriptedBroker):

    async def place_order(self, req):
        self.placed.append(req)
        return self._order(req, len(self.placed), "open", 0.0)


def test_legacy_open_orders_are_replaced_and_cancelled_at_bridge_end(client, legacy):
    br = pin(client, OpenOrders(partial=0.0, final="cancelled", final_filled=0.0))
    ScriptedEngine.script = {1: 100.0, 5: 50.0}
    pid = _approved(client)
    bid = client.post("/bridges", json=_body(pid, replay_to_account=True)).json()["bridge_id"]
    ev = _events(client, bid)
    cancels = [d for k, d in ev if k == "cancel"]
    assert [c["reason"] for c in cancels] == ["replace", "bridge_end"]
    assert br.cancelled == ["o1", "o2"]
    s = client.get(f"/bridges/{bid}").json()
    assert s["resting_order"] is None and s["broker_hedge"] == 0.0


def test_legacy_sells_are_clipped_to_the_approved_coverage(client, legacy, tmp_path):
    from app.broker import SimBroker
    from app.broker.quotes import Quote
    from tests.test_broker_support import FakeQuotes
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")})))
    ScriptedEngine.script = {1: 500.0, 3: 400.0, 5: 100.0}
    pid = _approved(client)
    ev = _events(client, client.post("/bridges", json=_body(pid, replay_to_account=True)).json()["bridge_id"])
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["qty"], f["status"]) for f in fills] == [(500.0, "filled"), (100.0, "filled"), (0.0, "held")]
    assert fills[1]["capped_from"] == 400.0 and "coverage cap" in fills[2]["reject_reason"]
    assert client.get("/positions").json()[0]["qty"] == -600.0
