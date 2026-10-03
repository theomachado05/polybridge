"""Review fixes: a restarted proposal starts from what earlier runs left at the account (one approval is one
target_coverage budget, however often it is re-POSTed), and a replay bridge finds the requested market's own recording
(replay index / ``<id>-history.jsonl``) instead of failing on a configured file of another market."""
from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace

import pytest

from app import bridges
from app.broker import SimBroker
from app.broker.quotes import Quote
from app.models import MarketRef
from tests.test_bridges import _approved, _body, _events, client, replay_file, write_meta  # noqa: F401
from tests.test_bridges_algo import pin
from tests.test_bridges_review_fixes import ScriptedEngine, _order, legacy  # noqa: F401
from tests.test_broker_support import FakeQuotes

CAP = 600.0  # floor(0.5 default coverage * 1200 shares held)


def _acct(client):
    rows = [p for p in client.get("/positions").json() if p["symbol"] == "ABNB"]
    return rows[0]["qty"] if rows else 0.0


def _run(client, pid, **kw):
    r = client.post("/bridges", json=_body(pid, **kw))
    assert r.status_code == 201, r.text
    bid = r.json()["bridge_id"]
    assert _events(client, bid)[-1][1]["status"] == "finished"
    return client.get(f"/bridges/{bid}").json()


# ---------------------------------------------------------------- restarts keep the approved cap at the account


needs_engine = pytest.mark.skipif(importlib.util.find_spec("hedgecore") is None, reason="engine not installed (uv sync --group engine)")

def test_restarts_never_grow_the_account_short_past_the_approved_coverage(client, legacy, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")})))
    ScriptedEngine.script = {1: 180.0}  # every run sells 180 (the reviewer's scenario: -180, -360, -540, -720, ...)
    pid = _approved(client)
    shorts, seen = [], []
    for _ in range(5):
        s = _run(client, pid, replay_to_account=True)
        shorts.append(-_acct(client))
        seen.append((s["broker_hedge"], s["account_hedge"]))
        assert -_acct(client) <= CAP  # never past the approved coverage, whatever the number of restarts
    assert shorts == [180.0, 360.0, 540.0, 600.0, 600.0]
    assert seen[-1] == (600.0, 600.0)  # the restart was seeded with the earlier runs' account short
    assert len(client.app.state.bridge_history) == 4  # every earlier run stays readable by its id


def test_a_sandbox_restart_starts_from_an_empty_sim_but_carries_the_account_total(client, legacy, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"ABNB": Quote(150.0, None, "q")})))
    ScriptedEngine.script = {1: 400.0}
    pid = _approved(client)
    first = _run(client, pid, replay_to_account=True)
    assert (first["broker_hedge"], _acct(client)) == (400.0, -400.0)
    sandbox = _run(client, pid)  # replay sandbox: its own empty sim, the account is never touched
    assert sandbox["account_scope"] == "replay_sandbox"
    assert sandbox["broker_hedge"] == 400.0 and sandbox["account_hedge"] == 400.0 and _acct(client) == -400.0
    third = _run(client, pid, replay_to_account=True)  # back at the account: only 200 of room left
    assert third["broker_hedge"] == CAP and third["account_hedge"] == CAP and _acct(client) == -CAP


class StuckThenFilled:
    """The order rests (market closed) and the cancel never takes; it fills after the bridge has ended."""
    name = "acct"

    def __init__(self):
        self.placed, self.filled = [], False

    async def place_order(self, req):
        self.placed.append(req)
        return _order(req, f"o{len(self.placed)}", "open", 0.0)

    async def orders(self):
        return [_order(r, f"o{i + 1}", "filled" if self.filled else "open", r.qty if self.filled else 0.0)
                for i, r in enumerate(self.placed)]

    async def cancel(self, oid):
        raise RuntimeError("cancel did not take")


def test_an_order_an_earlier_run_left_resting_is_reconciled_by_the_restart(client, legacy):
    br = pin(client, StuckThenFilled())
    ScriptedEngine.script = {1: 250.0}
    pid = _approved(client)
    first = _run(client, pid, replay_to_account=True)
    assert first["resting_order"]["order_id"] == "o1" and first["broker_hedge"] == 0.0
    br.filled = True  # it filled at the account after the first run ended
    ScriptedEngine.script = {}
    second = _run(client, pid, replay_to_account=True)
    assert len(br.placed) == 1  # nothing sent on top of it
    assert second["resting_order"] is None
    assert second["broker_hedge"] == 250.0 and second["account_hedge"] == 250.0


def test_carried_resting_order_never_reaches_the_new_runs_algo():
    prop = SimpleNamespace(id="p", ticker="SPY", shares_held=1000, target_coverage=0.5, family="hedge")
    m = MarketRef(source="polymarket", id="m1", token_id="t1")
    acct = SimpleNamespace(name="acct")
    old = bridges.Bridge(prop, "live", m, 1.0, algo={"family": "f"})
    old.account_hedge = 120.0
    old.resting = {"order_id": "o9", "client_order_id": "o9", "instrument": "equity", "side": "sell", "qty": 80.0,
                   "applied": 0.0, "hedged": 0.0}
    old.resting_broker = acct
    new = bridges.Bridge(prop, "replay", m, 1.0, replay_to_account=True, algo={"family": "f"})
    bridges._carry_account_exposure(old, new)
    assert new.broker_hedge == new.hedge == new.account_hedge == 120.0
    assert new.resting["inherited"] is True and new.resting_broker is acct
    sandboxed = bridges.Bridge(prop, "replay", m, 1.0, algo={"family": "f"})
    bridges._carry_account_exposure(old, sandboxed)
    assert sandboxed.broker_hedge == 0.0 and sandboxed.account_hedge == 120.0

    class Algo:
        def __init__(self):
            self.calls = []

        def on_fill(self, *a):
            self.calls.append(("fill", a))

        def on_reject(self, *a):
            self.calls.append(("reject", a))

    class Filled:
        name = "acct"

        async def orders(self):
            return [SimpleNamespace(id="o9", client_order_id="o9", status="filled", filled_qty=80.0, fill_px=10.0,
                                    limit_px=None, qty=80.0)]

    import asyncio

    algo = Algo()
    sandboxed.resting_broker = Filled()
    assert asyncio.run(bridges._settle_resting(sandboxed, algo, None, "replace")) is True
    assert algo.calls == []  # this run never sent it
    assert sandboxed.account_hedge == 200.0  # the account total sees it ...
    assert sandboxed.broker_hedge == 0.0  # ... the sandbox does not hold it


# ---------------------------------------------------------------- replay lookup: the requested market's own file

def _req(path):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(replay_path=str(path) if path else None)))


def test_a_configured_replay_of_another_market_falls_back_to_the_requested_markets_indexed_recording():
    # `make dev`: REPLAY=another-fed-hike-2026-history.jsonl, then a Russia/EU -> ITA bridge (polymarket:4713962)
    conf = bridges.REPLAYS_DIR / "another-fed-hike-2026-history.jsonl"
    russia = MarketRef(source="polymarket", id="4713962")
    assert bridges._replay_path(_req(conf), russia).name == "russia-eu-military-2026-history.jsonl"
    fed = MarketRef(source="polymarket", id="4620900")
    assert bridges._replay_path(_req(conf), fed) == conf  # the configured file still wins for its own market


def test_without_a_configured_replay_the_index_and_history_naming_are_used(monkeypatch):
    monkeypatch.delenv("POLYBRIDGE_REPLAY_PATH", raising=False)
    # `make dev-live`: nothing configured, 4620900.jsonl does not exist but the indexed -history file does
    fed = MarketRef(source="polymarket", id="4620900")
    assert bridges._replay_path(_req(None), fed).name == "another-fed-hike-2026-history.jsonl"


@pytest.fixture
def replays(tmp_path, monkeypatch):
    d = tmp_path / "replays"
    d.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(bridges, "REPLAYS_DIR", d)
    from app.pipeline import ticks
    monkeypatch.setattr(ticks, "DATA", data)
    monkeypatch.delenv("POLYBRIDGE_REPLAY_PATH", raising=False)
    return d, data


@needs_engine
def test_a_replay_bridge_starts_on_its_own_recording_when_the_configured_file_is_another_market(client, replay_file,
                                                                                                 replays):
    d, data = replays
    write_meta(replay_file, {"source": "polymarket", "id": "other"})  # the configured file records another market
    own = d / "recorded-m1.jsonl"
    own.write_text(replay_file.read_text())
    write_meta(own, {"source": "polymarket", "id": "m1", "token_id": "t1"})
    (data / "replay_index.json").write_text(json.dumps({"polymarket:m1": "recorded-m1.jsonl"}))
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid, replay_file=None))
    assert r.status_code == 201, r.text
    assert _events(client, r.json()["bridge_id"])[-1][1]["status"] == "finished"
    s = client.get(f"/bridges/{r.json()['bridge_id']}").json()
    assert s["replay_file"] == "recorded-m1.jsonl" and s["replay_market"]["id"] == "m1"


@needs_engine
def test_the_mismatch_422_stands_when_the_requested_market_has_no_recording(client, replay_file, replays):
    d, _ = replays
    write_meta(replay_file, {"source": "polymarket", "id": "other"})
    wrong = d / "m1-history.jsonl"  # named like m1's, but its sidecar says it records another market
    wrong.write_text(replay_file.read_text())
    write_meta(wrong, {"source": "polymarket", "id": "nope"})
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid, replay_file=None))
    assert r.status_code == 422 and "records polymarket:other" in r.json()["detail"]


@needs_engine
def test_with_nothing_configured_a_history_named_recording_is_found(client, replay_file, replays):
    d, _ = replays
    client.app.state.replay_path = None
    (d / "m1-history.jsonl").write_text(replay_file.read_text())
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid, replay_file=None))
    assert r.status_code == 201, r.text
    assert client.get(f"/bridges/{r.json()['bridge_id']}").json()["replay_file"] == "m1-history.jsonl"
