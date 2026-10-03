"""Bridges running a fitted hedgecore.Algo (offline: a fake hedgecore module and mocked HTTP; the real engine is
exercised in test_bridges_algo_engine.py under the engine group)."""
from __future__ import annotations

import asyncio
import json
import math
from types import SimpleNamespace

import httpx
import pytest

from app import bridges
from app.broker import SimBroker
from app.broker.models import Order
from app.broker.quotes import Quote
from app.pipeline.engine_adapter import ENGINE_MANIFEST, cap_coverage, normalize_manifest, preset_grid
from app.ticks import LiveSource, ReplaySource, SourceError, Tick, kalshi_book, polymarket_book
from tests.test_bridges import PS, _events, client, replay_file  # noqa: F401
from tests.test_broker_support import FakeQuotes, run

CATALOG = json.loads(ENGINE_MANIFEST.read_text())
FAMS = {f["id"]: f for f in normalize_manifest(CATALOG)["families"]}
FED = {"source": "polymarket", "id": "2589813", "token_id": "tokYES"}


class FakeAlgo:
    """Scripted intents by tick number; records everything the bridge tells it."""
    script: dict[int, dict] = {}
    instances: list["FakeAlgo"] = []

    def __init__(self, family, params, position, direction="down_on_yes"):
        self.family, self.params, self.position, self.direction = family, params, position, direction
        self.ticks, self.fills, self.rejects, self.n = [], [], [], 0
        FakeAlgo.instances.append(self)

    def on_tick(self, tick, now_ns=None):
        self.n += 1
        self.ticks.append(dict(tick))
        s = FakeAlgo.script.get(self.n)
        base = {"action": "hold", "instrument": "equity", "side": 0, "qty": 0.0, "limit_px": None,
                "reason": "inside_band", "reason_code": 0x0401, "reason_block": "execution",
                "signal": tick["yes_bid"], "latency_ns": 150, "venue": "poly"}
        if s:
            base.update({"action": "order", "reason": "rebalance", "reason_code": 0x0301, "reason_block": "sizers",
                         **s})
        return base

    def on_fill(self, instrument, qty, px):
        self.fills.append((instrument, qty, px))

    def on_reject(self, instrument):
        self.rejects.append(instrument)


class FakeEngine:  # legacy Engine, to prove which path ran
    def __init__(self, spec):
        self.current_hedge = 0.0

    def on_tick(self, *, ts_ns, p, now_ns):
        return SimpleNamespace(action="hold", reason="inside_band", order_qty=0.0, target_hedge=0.0,
                               current_hedge=0.0, latency_ns=1)

    def on_fill(self, qty):
        pass


@pytest.fixture(autouse=True)
def fake_hc(monkeypatch):
    FakeAlgo.script, FakeAlgo.instances = {}, []
    hc = SimpleNamespace(catalog=lambda: CATALOG, Algo=FakeAlgo, HedgeSpec=lambda **kw: SimpleNamespace(**kw),
                         Engine=FakeEngine)
    monkeypatch.setattr(bridges, "_load_engine", lambda: hc)
    return hc


def proposal(client, algo=None, direction="down_on_yes", approve=True, **kw):
    body = {"ticker": "SPY", "market": FED, "direction": direction, "shares_held": 1000, "target_coverage": 0.5, **kw}
    if algo is not None:
        body["algo"] = algo
    r = client.post("/proposals", json=body)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    if approve:
        client.post(f"/proposals/{pid}/approve")
    return r.json()


def start(client, pid, **kw):
    return client.post("/bridges", json={"proposal_id": pid, "source": "replay", **kw})


# ---------------------------------------------------------------- choosing the algo

def test_proposal_algo_is_validated_and_pinned(client):
    p = proposal(client, {"family": "macro_fed_hedge", "preset_index": 5}, approve=False)
    grid5 = preset_grid(FAMS["macro_fed_hedge"])[5]
    run5, lowered = cap_coverage(grid5, 0.5)
    assert p["algo"] == {"family": "macro_fed_hedge", "preset_index": 5, "params": None, "source": "ai_fit",
                         "resolved_params": run5, "coverage_cap": 0.5, "capped": lowered}
    for bad, msg in [({"family": "nope"}, "unknown algo family"),
                     ({"family": "no_bid_seller"}, "hedge-division families only"),
                     ({"family": "poly_kalshi_spread"}, "hedge-division families only"),
                     ({"family": "macro_fed_hedge", "preset_index": 81}, "presets 0..80"),
                     ({"family": "macro_fed_hedge", "params": {"coverage": 7.0}}, "outside"),
                     ({"family": "macro_fed_hedge", "params": {"bogus": 1.0}}, "no param"),
                     ({"family": "macro_fed_hedge", "preset_index": 1, "params": {"coverage": 0.5}}, "not both")]:
        r = client.post("/proposals", json={"ticker": "SPY", "market": FED, "direction": "down_on_yes",
                                            "shares_held": 10, "algo": bad})
        assert r.status_code == 422 and msg in json.dumps(r.json()), (bad, r.text)
    r = client.post("/proposals", json={"ticker": "ABNB", "tags": ["workforce_reduction"], "shares_held": 10,
                                        "algo": {"family": "macro_fed_hedge"}})
    assert r.status_code == 422 and "opportunity" in r.json()["detail"]
    # explicit params: missing ones take the catalog defaults, so the approved proposal says exactly what runs
    p = proposal(client, {"family": "macro_fed_hedge", "params": {"coverage": 1.0}, "source": "user"}, approve=False)
    assert p["algo"]["params"]["coverage"] == 1.0 and p["algo"]["params"]["mom_alpha"] == 0.3
    assert p["algo"]["preset_index"] is None and p["algo"]["source"] == "user"
    # ... and the approved record shows the coverage that will run: capped at the proposal's target_coverage
    assert p["algo"]["resolved_params"]["coverage"] == 0.5 and p["algo"]["capped"] == {"coverage": 1.0}
    # server-only fields in a request are ignored, never trusted
    p = proposal(client, {"family": "macro_fed_hedge", "params": {"coverage": 0.25},
                          "resolved_params": {"coverage": 1.0}, "capped": None}, approve=False)
    assert p["algo"]["resolved_params"]["coverage"] == 0.25 and p["algo"]["capped"] is None


def test_bridge_runs_the_approved_algo_with_its_preset(client):
    p = proposal(client, {"family": "macro_fed_hedge", "preset_index": 5})
    r = start(client, p["id"])
    assert r.status_code == 201
    bid = r.json()["bridge_id"]
    ev = _events(client, bid)
    a = FakeAlgo.instances[0]
    assert a.family == "macro_fed_hedge" and a.params == cap_coverage(preset_grid(FAMS["macro_fed_hedge"])[5], 0.5)[0]
    assert a.position == {"shares_held": 1000.0} and a.direction == "down_on_yes"  # direction never reaches hedgecore
    decisions = [d for k, d in ev if k == "decision"]
    assert len(decisions) == 20
    assert all(d["family"] == "macro_fed_hedge" and d["preset"] == 5 and d["engine"] == "algo" for d in decisions)
    assert decisions[0]["reason"] == "inside_band" and decisions[0]["signal"] == PS[0]  # reason string + signal
    s = client.get(f"/bridges/{bid}").json()
    assert s["engine"] == "algo" and s["algo"]["family"] == "macro_fed_hedge" and s["algo"]["preset_index"] == 5
    assert s["reasons"] == {"inside_band": 20} and s["hedge_basis"] == "broker_fill"
    # approval gate unchanged: one bridge per proposal, idempotent; a different algo in the body is refused
    assert start(client, p["id"]).status_code == 200
    assert start(client, p["id"], family="macro_fed_hedge", preset_index=5).status_code == 200  # same algo: fine
    r = start(client, p["id"], family="housing_rates")  # the caller is never told a different algo is running
    assert r.status_code == 409 and "already runs algo macro_fed_hedge preset 5" in r.json()["detail"]
    assert len(client.app.state.bridges) == 1


def test_body_algo_when_the_proposal_has_none_and_conflicts(client):
    p = proposal(client)
    r = start(client, p["id"], family="crypto_reg_hedge", preset_index=3)
    assert r.status_code == 201
    _events(client, r.json()["bridge_id"])
    assert FakeAlgo.instances[0].params == cap_coverage(preset_grid(FAMS["crypto_reg_hedge"])[3], 0.5)[0]

    q = proposal(client, {"family": "macro_fed_hedge", "preset_index": 5})
    r = start(client, q["id"], family="macro_fed_hedge", preset_index=6)
    assert r.status_code == 409 and "approved with algo macro_fed_hedge preset 5" in r.json()["detail"]
    assert q["id"] not in client.app.state.bridges
    assert start(client, q["id"], family="macro_fed_hedge", preset_index=5).status_code == 201  # same: fine


@pytest.mark.parametrize("kw,code", [({"family": "nope"}, 422), ({"family": "vol_vs_pm_move"}, 422),
                                     ({"family": "macro_fed_hedge", "preset_index": 999}, 422),
                                     ({"preset_index": 2}, 422),
                                     ({"family": "macro_fed_hedge", "preset_index": 1, "params": {"coverage": 1}}, 422)])
def test_bad_body_algo_is_422_and_starts_nothing(client, kw, code):
    p = proposal(client)
    r = start(client, p["id"], **kw)
    assert r.status_code == code
    assert p["id"] not in getattr(client.app.state, "bridges", {})


def test_an_engine_that_refuses_the_algo_stops_the_stream_cleanly(client, fake_hc, monkeypatch):
    def refuse(*a, **k):
        raise KeyError("family macro_fed_hedge has no param 'coverage'")
    monkeypatch.setattr(fake_hc, "Algo", refuse)
    p = proposal(client, {"family": "macro_fed_hedge"})
    ev = _events(client, start(client, p["id"]).json()["bridge_id"])
    assert [k for k, _ in ev] == ["error", "status"]
    assert ev[0][1]["source"] == "engine" and ev[1][1] == {"status": "stopped", "reason": "engine_error"}


def test_no_fit_keeps_the_legacy_engine(client):
    p = proposal(client)
    bid = start(client, p["id"]).json()["bridge_id"]
    ev = _events(client, bid)
    assert not FakeAlgo.instances
    assert {d["engine"] for k, d in ev if k == "decision"} == {"legacy"}
    assert client.get(f"/bridges/{bid}").json()["engine"] == "legacy"


def test_unapproved_and_unknown_still_gate(client):
    p = proposal(client, {"family": "macro_fed_hedge"}, approve=False)
    assert start(client, p["id"]).status_code == 409
    assert start(client, "nope", family="macro_fed_hedge").status_code == 404


# ---------------------------------------------------------------- orientation (one place)

def test_up_on_yes_is_oriented_once_before_the_algo(client):
    p = proposal(client, {"family": "macro_fed_hedge"}, direction="up_on_yes")
    ev = _events(client, start(client, p["id"]).json()["bridge_id"])
    a = FakeAlgo.instances[0]
    assert a.direction == "down_on_yes"  # hedgecore's own flip is never used
    assert a.ticks[0]["yes_bid"] == pytest.approx(1 - PS[0]) and a.ticks[0]["no_bid"] == pytest.approx(PS[0])
    assert [d["p"] for k, d in ev if k == "tick"][0] == PS[0]  # the UI keeps the raw market


# ---------------------------------------------------------------- execution: fills, rejects, cancel/replace

def pin(client, broker):
    client.app.state.broker = broker
    return broker


def test_fills_feed_on_fill_and_the_hedge_is_what_filled(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")})))
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0}, 6: {"side": -1, "qty": 50.0}, 9: {"side": 1, "qty": 30.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    a = FakeAlgo.instances[0]
    assert [(i, q) for i, q, _ in a.fills] == [("equity", -100.0), ("equity", -50.0), ("equity", 30.0)]
    assert all(px == pytest.approx(500.0, abs=0.1) for _, _, px in a.fills) and a.rejects == []
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["side"], f["qty"], f["status"]) for f in fills] == [("sell", 100.0, "filled"), ("sell", 50.0, "filled"),
                                                                   ("buy", 30.0, "filled")]
    assert all(f["family"] == "macro_fed_hedge" and f["reason"] == "rebalance" for f in fills)
    assert [d["hedge"] for k, d in ev if k == "position"] == [100.0, 150.0, 120.0]
    decisions = [d for k, d in ev if k == "decision"]
    assert decisions[1]["order_qty"] == 100.0 and decisions[8]["order_qty"] == -30.0
    assert [(x.symbol, x.qty) for x in run(b.positions())] == [("SPY", -120.0)]
    s = client.get(f"/bridges/{bid}").json()
    assert s["hedge"] == s["broker_hedge"] == 120.0 and s["broker_filled"] == 3 and s["orders"] == 3


def test_rejects_and_errors_feed_on_reject(client, tmp_path, monkeypatch):
    pin(client, SimBroker(tmp_path / "s.json"))  # no quotes and no ref price: every order is rejected (no_price)
    FakeAlgo.script = {1: {"side": -1, "qty": 10.0}, 3: {"side": -1, "qty": 10.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    ev = _events(client, start(client, p["id"], replay_to_account=True).json()["bridge_id"])
    a = FakeAlgo.instances[0]
    assert a.rejects == ["equity", "equity"] and a.fills == []
    assert [d["status"] for k, d in ev if k == "fill"] == ["rejected", "rejected"]

    class Boom(SimBroker):
        async def place_order(self, req):
            raise RuntimeError("down")
    pin(client, Boom(None))
    q = proposal(client, {"family": "macro_fed_hedge"})
    ev = _events(client, start(client, q["id"], replay_to_account=True).json()["bridge_id"])
    assert FakeAlgo.instances[1].rejects == ["equity", "equity"]
    assert [d["status"] for k, d in ev if k == "fill"] == ["error", "error"] and ev[-1][1]["status"] == "finished"


def test_resting_order_is_cancelled_before_the_next_and_at_the_end(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")})))
    # passive limits far from the market rest; the second replaces the first; the last is cancelled at the end
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 600.0},
                       5: {"side": -1, "qty": 100.0, "limit_px": 601.0},
                       8: {"side": -1, "qty": 40.0}}
    p = proposal(client, {"family": "stress_lead_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    a = FakeAlgo.instances[0]
    cancels = [d for k, d in ev if k == "cancel"]
    assert [c["status"] for c in cancels] == ["cancelled", "cancelled"]
    assert [c["reason"] for c in cancels] == ["replace", "replace"]
    assert a.rejects == ["equity", "equity"]  # each expired resting order is an on_reject
    assert [(q, round(px)) for _, q, px in a.fills] == [(-40.0, 500)]
    orders = run(b.orders())
    assert sorted(o.status for o in orders) == ["cancelled", "cancelled", "filled"]
    assert not [o for o in orders if o.status == "open"]
    kinds = [k for k, _ in ev]
    assert kinds.index("cancel") < [i for i, k in enumerate(kinds) if k == "fill"][1]  # cancel precedes the replace

    FakeAlgo.script = {3: {"side": -1, "qty": 10.0, "limit_px": 650.0}}
    q = proposal(client, {"family": "stress_lead_hedge"})
    ev = _events(client, start(client, q["id"], replay_to_account=True).json()["bridge_id"])
    last = [d for k, d in ev if k == "cancel"]
    assert last and last[-1]["reason"] == "bridge_end" and last[-1]["status"] == "cancelled"
    assert not [o for o in run(b.orders()) if o.status == "open"]


def test_a_resting_order_that_filled_meanwhile_goes_to_on_fill(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")})))
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 499.0},  # sell limit below the bid -> fills at once
                       4: {"side": -1, "qty": 10.0, "limit_px": 600.0}}
    p = proposal(client, {"family": "stress_lead_hedge"})
    bridge_id = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    _events(client, bridge_id)
    a = FakeAlgo.instances[0]
    assert a.fills[0][1] == -100.0
    assert a.rejects == ["equity"]  # the 600 limit rested and was cancelled at bridge end


# ---------------------------------------------------------------- live MarketTicks

POLY_BOOK = {"bids": [{"price": "0.40", "size": "100"}, {"price": "0.44", "size": "50"}, {"price": "0.43", "size": "10"},
                      {"price": "0.30", "size": "1"}, {"price": "0.20", "size": "1"}, {"price": "0.10", "size": "1"}],
             "asks": [{"price": "0.50", "size": "20"}, {"price": "0.46", "size": "70"}, {"price": "bad", "size": "1"}]}
KALSHI_BOOK = {"orderbook": {"yes": [[38, 10], [41, 25]], "no": [[55, 30], [57, 5]]}}


def mock_http(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def venues(poly=POLY_BOOK, kalshi=KALSHI_BOOK, midpoint=None):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.host == "clob.polymarket.com" and req.url.path == "/book":
            return httpx.Response(200, json=poly) if poly is not None else httpx.Response(503)
        if req.url.host == "clob.polymarket.com" and req.url.path == "/midpoint":
            return httpx.Response(200, json={"mid": midpoint}) if midpoint is not None else httpx.Response(503)
        if req.url.host == "api.elections.kalshi.com" and req.url.path.endswith("/orderbook"):
            return httpx.Response(200, json=kalshi) if kalshi is not None else httpx.Response(503)
        return httpx.Response(404)
    return handler, calls


def test_polymarket_book_sorted_top5_and_kalshi_book_from_no_bids():
    h, _ = venues()
    bids, asks = run(polymarket_book(mock_http(h), "tok"))
    assert bids == [(0.44, 50.0), (0.43, 10.0), (0.40, 100.0), (0.30, 1.0), (0.20, 1.0)]
    assert asks == [(0.46, 70.0), (0.50, 20.0)]
    kb, ka = run(kalshi_book(mock_http(h), "KX-1"))
    assert kb == [(0.41, 25.0), (0.38, 10.0)]
    assert ka == [(pytest.approx(0.43), 5.0), (pytest.approx(0.45), 30.0)]  # NO bid 57c = YES ask 43c
    dollars = {"orderbook": {"yes_dollars": [["0.4100", 25]], "no_dollars": [["0.5700", 5]]}}
    h2, _ = venues(kalshi=dollars)
    assert run(kalshi_book(mock_http(h2), "KX-1")) == ([(0.41, 25.0)], [(pytest.approx(0.43), 5.0)])


def test_live_tick_has_book_twin_and_equity_fields():
    h, _ = venues()
    quote = Quote(500.0, 0.05, "massive")

    async def eq():
        return quote
    src = LiveSource("tok", http=mock_http(h), twin=("kalshi", "KX-1"), equity=eq)
    t = run(src.poll(mock_http(h)))
    f = t.fields
    assert t.p == pytest.approx(0.45) and t.venue == 0
    assert (f["yes_bid"], f["yes_ask"]) == (0.44, 0.46) and f["no_bid"] == pytest.approx(0.54)
    assert f["bid_px_0"] == 0.44 and f["bid_qty_4"] == 1.0 and f["ask_px_1"] == 0.50 and math.isnan(f["ask_px_2"])
    assert f["p_other_venue"] == pytest.approx((0.41 + 0.43) / 2)
    assert (f["under_px"], f["under_bid"], f["under_ask"]) == (500.0, pytest.approx(499.95), pytest.approx(500.05))
    assert math.isnan(f["opt_mid"]) and f["eightk_score"] == 0.0


def test_live_tick_degrades_field_by_field():
    h, _ = venues(kalshi=None)  # twin down
    t = run(LiveSource("tok", twin=("kalshi", "KX-1")).poll(mock_http(h)))
    assert math.isnan(t.fields["p_other_venue"]) and math.isnan(t.fields["under_px"])  # no twin, no equity source

    async def last_trade():
        return Quote(500.0, None, "massive_last_trade")
    t = run(LiveSource("tok", equity=last_trade).poll(mock_http(h)))
    assert t.fields["under_px"] == 500.0 and math.isnan(t.fields["under_bid"])  # no spread: bid/ask unknown

    h, _ = venues(poly={"bids": [], "asks": []}, midpoint="0.31")  # empty book -> CLOB midpoint, mid-only fields
    t = run(LiveSource("tok").poll(mock_http(h)))
    assert t.p == 0.31 and t.fields["yes_bid"] == t.fields["yes_ask"] == 0.31 and math.isnan(t.fields["bid_px_0"])

    h, _ = venues()
    t = run(LiveSource("KX-1", primary="kalshi").poll(mock_http(h)))
    assert t.venue == 1 and (t.fields["yes_bid"], t.fields["yes_ask"]) == (0.41, pytest.approx(0.43))


def test_live_source_fails_after_consecutive_primary_failures():
    h, _ = venues(poly=None, midpoint=None)

    async def go():
        async for _ in LiveSource("tok", interval_s=0, max_failures=2, http=mock_http(h)):
            pass
    with pytest.raises(SourceError):
        run(go())


def test_live_bridge_feeds_book_fields_to_the_algo_and_prices_at_the_live_quote(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, 0.02, "fake")})))
    seen = {}

    class ScriptedLive:
        def __init__(self, market_id, *, primary, twin, equity):
            seen.update(market_id=market_id, primary=primary, twin=twin)
            self.equity = equity

        async def __aiter__(self):
            q = await self.equity()  # the bridge hands the broker's quote source to the live feed
            for i in range(4):
                f = {"yes_bid": 0.30 + i / 100, "yes_ask": 0.32 + i / 100, "no_bid": 0.68 - i / 100,
                     "no_ask": 0.70 - i / 100, "p_other_venue": 0.33, "under_px": q.mid,
                     "under_bid": q.mid - q.half_spread, "under_ask": q.mid + q.half_spread, "bid_px_0": 0.30}
                yield Tick(__import__("time").time_ns(), 0.31 + i / 100, f)

    client.app.state.live_source_factory = ScriptedLive
    FakeAlgo.script = {2: {"side": -1, "qty": 25.0}}
    p = proposal(client, {"family": "energy_geo_hedge"})
    r = client.post("/bridges", json={"proposal_id": p["id"], "source": "live",
                                      "twin": {"source": "kalshi", "id": "KXFED-26OCT"}})
    assert r.status_code == 201, r.text
    ev = _events(client, r.json()["bridge_id"])
    assert seen == {"market_id": "tokYES", "primary": "polymarket", "twin": ("kalshi", "KXFED-26OCT")}
    t0 = FakeAlgo.instances[0].ticks[0]
    assert t0["under_px"] == 500.0 and t0["p_other_venue"] == 0.33 and t0["bid_px_0"] == 0.30
    assert math.isnan(t0["opt_iv"]) and t0["venue"] == 0
    fill = next(d for k, d in ev if k == "fill")
    assert fill["status"] == "filled" and fill["price_source"] == "supplied"  # live: priced at the tick's quote
    ticks = [d for k, d in ev if k == "tick"]
    assert ticks[0]["p_other_venue"] == 0.33 and ticks[0]["under_px"] == 500.0 and ticks[0]["depth"] == 1


def test_live_bridge_twin_must_be_the_other_venue(client):
    p = proposal(client, {"family": "macro_fed_hedge"})
    body = {"proposal_id": p["id"], "source": "live"}
    assert client.post("/bridges", json={**body, "twin": {"source": "polymarket", "id": "x", "token_id": "t"}}).status_code == 422
    q = proposal(client, {"family": "macro_fed_hedge"})
    assert client.post("/bridges", json={"proposal_id": q["id"], "source": "live",
                                         "twin": {"source": "nyse", "id": "x"}}).status_code == 422


# ---------------------------------------------------------------- replay MarketTicks

def test_replay_fills_only_what_it_has(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text('{"ts_ns": 1000000000000000, "p": 0.2}\n{"ts_ns": 1000003600000000000, "p": 0.3, "yes_bid": 0.29, '
                 '"yes_ask": 0.31, "under_px": 99.0}\n')
    bars = [(999_000, 410.0), (1_000_000_100, 420.0)]  # (known_at_s, close)

    async def go():
        return [t async for t in ReplaySource(f, speed=0, bars=bars)]
    a, b = run(go())
    assert (a.p, a.fields["yes_bid"], a.fields["yes_ask"], a.fields["no_bid"]) == (0.2, 0.2, 0.2, 0.8)
    assert a.fields["under_px"] == 410.0  # the bar known at the ORIGINAL time of the row, not at replay time
    assert math.isnan(a.fields["bid_px_0"]) and math.isnan(a.fields["p_other_venue"])
    assert (b.fields["yes_bid"], b.fields["yes_ask"], b.fields["under_px"]) == (0.29, 0.31, 99.0)  # recorded wins
    ts, p = a  # still a (ts_ns, p) pair for older callers
    assert p == 0.2


# ---------------------------------------------------------------- the approved coverage is a hard cap

def test_a_coverage_1_preset_on_a_half_proposal_never_hedges_more_than_half(client, tmp_path):
    b = pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")})))
    fam = FAMS["macro_fed_hedge"]
    idx = next(i for i, g in enumerate(preset_grid(fam)) if g["coverage"] == 1.0)
    # the (fake) algo asks for 400 + 300 + 50 short on 1000 shares: 75%, above the approved 50%
    FakeAlgo.script = {2: {"side": -1, "qty": 400.0}, 4: {"side": -1, "qty": 300.0}, 6: {"side": -1, "qty": 50.0},
                       8: {"side": 1, "qty": 20.0}, 10: {"side": -1, "qty": 40.0}}
    p = proposal(client, {"family": "macro_fed_hedge", "preset_index": idx})
    assert p["algo"]["resolved_params"]["coverage"] == 0.5 and p["algo"]["capped"] == {"coverage": 1.0}
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    a = FakeAlgo.instances[0]
    assert a.params["coverage"] == 0.5  # the algo itself aims within the approval
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["side"], f["qty"], f["status"]) for f in fills] == [
        ("sell", 400.0, "filled"), ("sell", 100.0, "filled"), ("sell", 0.0, "held"), ("buy", 20.0, "filled"),
        ("sell", 20.0, "filled")]
    assert fills[1]["capped_from"] == 300.0 and "coverage cap" in fills[2]["reject_reason"]
    assert [q for _, q, _ in a.fills] == [-400.0, -100.0, 20.0, -20.0] and a.rejects == ["equity"]
    assert max(d["broker_coverage"] for k, d in ev if k == "position") == 0.5
    assert [(x.symbol, x.qty) for x in run(b.positions())] == [("SPY", -500.0)]
    s = client.get(f"/bridges/{bid}").json()
    assert s["coverage_cap"] == 0.5 and s["algo"]["capped"] == {"coverage": 1.0} and s["cap_holds"] == 1
    assert s["algo"]["params"]["coverage"] == 0.5 and s["broker_coverage"] == 0.5


def test_the_cap_holds_a_family_without_a_coverage_param(client, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")})))
    FakeAlgo.script = {1: {"side": -1, "qty": 900.0}}
    p = proposal(client, {"family": "election_hedge"}, target_coverage=0.25)
    assert p["algo"]["capped"] is None  # beta * (p - p_neutral): nothing to lower, the bridge clips instead
    ev = _events(client, start(client, p["id"], replay_to_account=True).json()["bridge_id"])
    f = next(d for k, d in ev if k == "fill")
    assert (f["qty"], f["capped_from"], f["status"]) == (250.0, 900.0, "filled")


# ---------------------------------------------------------------- partial fills, unreadable broker

class ScriptedBroker:
    """A broker whose answers are scripted: place -> open with a partial fill; orders()/cancel() per test."""
    name = "scripted"

    def __init__(self, partial=30.0, final="cancelled", final_filled=30.0, lookup_fails=0):
        self.partial, self.final, self.final_filled, self.lookup_fails = partial, final, final_filled, lookup_fails
        self.placed: list = []
        self.cancelled: list = []
        self.lookups = 0

    def _order(self, req, i, status, filled):
        return Order(id=f"o{i}", client_order_id=req.client_order_id, broker=self.name, symbol=req.symbol,
                     asset="equity", side=req.side, qty=req.qty, type=req.type, limit_px=req.limit_px, status=status,
                     filled_qty=filled, fill_px=500.0 if filled else None, created_at="t")

    async def place_order(self, req):
        self.placed.append(req)
        return self._order(req, len(self.placed), "open", self.partial)

    async def orders(self):
        self.lookups += 1
        if self.lookups <= self.lookup_fails:
            raise RuntimeError("broker unreachable")
        return [self._order(r, i + 1, "open", self.partial) for i, r in enumerate(self.placed)
                if f"o{i + 1}" not in self.cancelled]

    async def cancel(self, oid):
        self.cancelled.append(oid)
        i = int(oid[1:])
        return self._order(self.placed[i - 1], i, self.final, self.final_filled)


def test_a_partial_fill_is_fed_back_once(client):
    br = pin(client, ScriptedBroker(partial=30.0, final="cancelled", final_filled=30.0))
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 600.0}}
    p = proposal(client, {"family": "stress_lead_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    _events(client, bid)
    a = FakeAlgo.instances[0]
    assert a.fills == [("equity", -30.0, 500.0)]  # once, at placement; the cancel (same cumulative 30) adds nothing
    assert a.rejects == ["equity"]  # the unfilled rest expired at bridge end
    assert br.cancelled == ["o1"]
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_hedge"] == 30.0 and s["hedge"] == 30.0 and s["resting_order"] is None


def test_a_partial_fill_that_grows_before_the_cancel_feeds_only_the_difference(client):
    pin(client, ScriptedBroker(partial=30.0, final="cancelled", final_filled=70.0))
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 600.0}, 5: {"side": -1, "qty": 100.0, "limit_px": 600.0}}
    p = proposal(client, {"family": "stress_lead_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    _events(client, bid)
    a = FakeAlgo.instances[0]
    # each order: 30 filled at placement, 70 cumulative when cancelled (replace / bridge end) -> +40, never +70
    assert [q for _, q, _ in a.fills] == [-30.0, -40.0, -30.0, -40.0]
    assert client.get(f"/bridges/{bid}").json()["broker_hedge"] == 140.0


def test_an_unreadable_broker_keeps_the_resting_order_and_sends_nothing_on_top(client):
    br = pin(client, ScriptedBroker(partial=0.0, lookup_fails=1))
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0, "limit_px": 600.0}, 4: {"side": -1, "qty": 100.0}}
    p = proposal(client, {"family": "stress_lead_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    assert len(br.placed) == 1  # the second intent was held, not stacked on the possibly-working first order
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["open", "held"] and "still resting" in fills[1]["reject_reason"]
    cancels = [d for k, d in ev if k == "cancel"]
    assert cancels[0]["status"] == "error" and cancels[0]["kept_resting"] is True
    assert cancels[-1]["reason"] == "bridge_end" and cancels[-1]["status"] == "cancelled"  # retried at the end
    assert br.cancelled == ["o1"]
    assert FakeAlgo.instances[0].rejects == ["equity", "equity"]  # the held intent, then the expired order


# ---------------------------------------------------------------- equity quotes: algo only, cached, never stale

def test_legacy_live_bridges_never_poll_the_equity_quote(client):
    seen = []

    class Live:
        def __init__(self, market_id, *, primary, twin, equity):
            seen.append(equity)

        async def __aiter__(self):
            if False:
                yield
    client.app.state.live_source_factory = Live
    p = proposal(client)
    _events(client, client.post("/bridges", json={"proposal_id": p["id"], "source": "live"}).json()["bridge_id"])
    q = proposal(client, {"family": "macro_fed_hedge"})
    _events(client, client.post("/bridges", json={"proposal_id": q["id"], "source": "live"}).json()["bridge_id"])
    assert seen[0] is None and callable(seen[1])


def test_equity_quote_is_shared_and_a_previous_close_is_not_a_current_price(client, tmp_path):
    calls = []

    class Q:
        def __init__(self, source):
            self.source = source

        async def equity(self, sym):
            calls.append(sym)
            return Quote(500.0, None, self.source)
    app = client.app
    prop = SimpleNamespace(ticker="SPY", shares_held=10.0, target_coverage=0.5, id="x")
    b1, b2 = SimpleNamespace(proposal=prop, equity_source=None), SimpleNamespace(proposal=prop, equity_source=None)
    b1.broker = b2.broker = SimpleNamespace(quotes=Q("massive_last_trade"))
    q1, q2 = bridges._equity_quote(b1, app), bridges._equity_quote(b2, app)
    assert run(q1()).mid == 500.0 and run(q2()).mid == 500.0 and calls == ["SPY"]  # one call for both bridges
    assert b2.equity_source == "massive_last_trade"
    app.state.equity_quotes.clear()
    b1.broker = SimpleNamespace(quotes=Q("massive_prev_close"))
    assert run(q1()) is None and b1.equity_source == "massive_prev_close (stale: not used)"


def test_replay_reports_whether_the_algo_can_see_an_equity_price(client, tmp_path, monkeypatch):
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"]).json()["bridge_id"]
    _events(client, bid)
    s = client.get(f"/bridges/{bid}").json()
    assert s["equity_price"] == "none"  # the fixture replay is from 2001: no recorded SPY bar is known by then
    monkeypatch.setattr(bridges, "_bars", lambda t: [(1, 400.0)])
    q = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, q["id"]).json()["bridge_id"]
    _events(client, bid)
    assert client.get(f"/bridges/{bid}").json()["equity_price"] == "recorded"
    assert client.get(f"/bridges/{start(client, proposal(client)['id']).json()['bridge_id']}").json()["equity_price"] is None


# ---------------------------------------------------------------- replay with no current quote: recorded price

def _replay_with_under(client, tmp_path, px=lambda i: 400.0 + i):
    f = tmp_path / "under.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_000_000_000 * (i + 1), "p": p, "under_px": px(i)}) + "\n"
                         for i, p in enumerate(PS)))
    client.app.state.replay_path = str(f)
    return f


def test_replay_without_a_quote_fills_at_the_recorded_price_labelled(client, tmp_path):
    """Wi-Fi off: the sim has no Massive quote, so a replay fills at the replayed under_px, labelled recorded."""
    quotes = FakeQuotes()  # nothing: offline / no key
    b = pin(client, SimBroker(tmp_path / "s.json", quotes))
    _replay_with_under(client, tmp_path)
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0}, 6: {"side": -1, "qty": 50.0}, 9: {"side": 1, "qty": 30.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"], replay_to_account=True).json()["bridge_id"]
    ev = _events(client, bid)
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["filled"] * 3
    assert all(f["price_source"] == "recorded" and "recorded price" in f["price_note"] for f in fills)
    assert all("recorded price" in f["note"] for f in fills)
    # tick 2 replayed under_px 401, 1 bp half-spread: a sell fills just under it, a buy (tick 9, 408) just over
    assert fills[0]["fill_px"] == pytest.approx(401.0 * (1 - 1e-4), abs=1e-4)
    assert fills[2]["fill_px"] == pytest.approx(408.0 * (1 + 1e-4), abs=1e-4)
    assert [(i, q) for i, q, _ in FakeAlgo.instances[0].fills] == [("equity", -100.0), ("equity", -50.0), ("equity", 30.0)]
    assert all(o.price_source == "recorded" and "recorded price" in o.note for o in run(b.orders()))
    s = client.get(f"/bridges/{bid}").json()
    assert s["broker_filled"] == 3 and s["broker_rejects"] == 0 and s["broker_hedge"] == 120.0
    assert s["recorded_price_fills"] == 3
    # they went into the persistent account: the summary says their cost bases are historical
    assert s["account_scope"] == "account" and "3 fill(s)" in s["account_note"] and "historical" in s["account_note"]
    # the quote check is cached per bridge, not repeated per order (the sim itself never needed a quote)
    assert quotes.calls == [("equity", "SPY")]


def test_replay_with_a_quote_keeps_the_current_market_price(client, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")})))
    _replay_with_under(client, tmp_path)
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"]).json()["bridge_id"]
    (f,) = [d for k, d in _events(client, bid) if k == "fill"]
    assert f["status"] == "filled" and f["price_source"] == "q" and f["fill_px"] == pytest.approx(499.95)
    assert f["price_note"] == "priced at the current market, not the replayed time" and f["scope"] == "replay_sandbox"
    s = client.get(f"/bridges/{bid}").json()
    assert s["recorded_price_fills"] == 0 and s["account_note"] is None


def test_sandboxed_recorded_price_replay_has_no_account_note(client, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes()))
    _replay_with_under(client, tmp_path)
    FakeAlgo.script = {2: {"side": -1, "qty": 100.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    bid = start(client, p["id"]).json()["bridge_id"]
    (f,) = [d for k, d in _events(client, bid) if k == "fill"]
    assert f["price_source"] == "recorded" and f["scope"] == "replay_sandbox"
    s = client.get(f"/bridges/{bid}").json()
    assert s["recorded_price_fills"] == 1 and s["account_note"] is None  # a throwaway sim: no account to mislead


def test_replay_without_quote_or_recorded_price_is_still_refused(client, tmp_path):
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes()))  # the default fixture replay has no under_px
    FakeAlgo.script = {2: {"side": -1, "qty": 10.0}}
    p = proposal(client, {"family": "macro_fed_hedge"})
    (f,) = [d for k, d in _events(client, start(client, p["id"], replay_to_account=True).json()["bridge_id"]) if k == "fill"]
    assert f["status"] == "rejected" and f["reject_reason"].startswith("no_price")


def test_live_bridge_never_uses_the_recorded_price_path(client, tmp_path, monkeypatch):
    called = []

    async def spy(bridge, broker):
        called.append(bridge.effective_source)
        return False
    monkeypatch.setattr(bridges, "_broker_can_price", spy)
    pin(client, SimBroker(tmp_path / "s.json", FakeQuotes()))
    bridge = bridges.Bridge(SimpleNamespace(id="p", family="hedge", ticker="SPY", shares_held=1000,
                                            target_coverage=0.5), "live", bridges.MarketRef(**FED), 0.0,
                            algo={"family": "macro_fed_hedge", "preset_index": 0})
    bridge.broker = client.app.state.broker
    a = FakeAlgo("macro_fed_hedge", {}, {})
    t = Tick(1, 0.3, {"under_px": 400.0})
    rec = run(bridges._send_intent(bridge, a, {"action": "order", "instrument": "equity", "side": -1, "qty": 5.0}, t))
    assert called == [] and rec["status"] == "filled" and rec["price_source"] == "supplied"  # the live tick quote
