"""Opportunity division end to end (offline): option fields on ticks, listed_options eligibility in the fit,
opportunity proposals and bridges (approval gate, multi-leg option orders through the SimBroker, risk caps)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import time

import httpx
import numpy as np
import pytest

from app import bridges
from app.broker import SimBroker, WebullBroker
from app.broker.models import BrokerError, OrderRequest
from app.options import chain as ch
from app.options import enrich as en
from app.pipeline import service
from app.pipeline.engine_adapter import ENGINE_MANIFEST, EngineAdapter
from app.pipeline.options_join import join_options, spread_series
from app.pipeline.ticks import TickSet, assemble, available_requirements
from app.ticks import LiveSource, OptionsEnricher
from tests.test_bridges import PS, _events  # noqa: F401
from tests.test_bridges_algo import FakeAlgo, fake_hc  # noqa: F401  (autouse fixture: fake hedgecore)
from tests.test_pipeline import fake_hedgecore

NAN = math.nan
EXP = "2026-12-18"
Q_ABOVE = "Will Nvidia (NVDA) close above $150 on December 18, 2026?"
MKT = {"source": "polymarket", "id": "nvda-150-dec", "token_id": "tokNVDA"}
CATALOG = json.loads(ENGINE_MANIFEST.read_text())


def run(coro):
    return asyncio.run(coro)


def ts_of(date: str) -> int:
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp() * 1e9)


def nvda_chain(underlying="NVDA", strikes=(145.0, 150.0, 155.0)) -> ch.Chain:
    c = ch.Chain(underlying=underlying, fetched_at=time.time())
    calls = {strikes[0]: 8.0, strikes[1]: 5.0, strikes[2]: 3.0}
    puts = {strikes[0]: 2.0, strikes[1]: 4.0, strikes[2]: 6.5}
    for k in strikes:
        tag = f"{int(k * 1000):08d}"
        c.quotes.append(ch.OptionQuote(f"O:{underlying}261218C{tag}", "call", k, EXP, bid=calls[k] - 0.1,
                                       ask=calls[k] + 0.1, mid=calls[k], mark_source="quote", iv=0.3, delta=0.5))
        c.quotes.append(ch.OptionQuote(f"O:{underlying}261218P{tag}", "put", k, EXP, bid=puts[k] - 0.05,
                                       ask=puts[k] + 0.05, mid=puts[k], mark_source="quote", iv=0.3, delta=-0.5))
    return c


@pytest.fixture(autouse=True)
def _clean_option_caches(monkeypatch):
    from app.options import eightk as ek
    monkeypatch.setattr(ch, "_LAST", {})
    monkeypatch.setattr(ch, "_FOR", {})
    monkeypatch.setattr(ek, "_LIVE", {})


@pytest.fixture
def mocked_chain(monkeypatch):
    """Massive is replaced by a static chain; the 8-K refresh is a no-op and NVDA scores 0.6."""
    calls = []

    async def get_chain(underlying, **kw):
        calls.append((underlying, kw))
        return nvda_chain(underlying, (595.0, 600.0, 605.0) if underlying == "SPY" else (145.0, 150.0, 155.0)), False

    async def no_refresh(*a, **k):
        return None
    monkeypatch.setattr(ch, "get_chain", get_chain)
    monkeypatch.setattr(en, "refresh_eightk", no_refresh)
    monkeypatch.setattr(en, "eightk_score", lambda tk, as_of=None, **k: 0.6 if tk == "NVDA" else NAN)
    return calls


# ---------------------------------------------------------------- 1. ticks: enrich wiring

def test_enricher_fills_option_fields_for_a_mapped_question(mocked_chain):
    e = OptionsEnricher(Q_ABOVE, None, refresh_s=60)
    t = ts_of("2026-10-02")
    out = run(e({"yes_bid": 0.55, "yes_ask": 0.57, "opt_mid": NAN, "opt_implied_prob": NAN}, t))
    for f in ("opt_mid", "opt_delta", "opt_iv", "opt_implied_prob"):
        assert math.isfinite(out[f]), f
    assert out["opt_mid"] == pytest.approx(8.0 - 3.0)  # call spread C(145) - C(155)
    assert out["eightk_score"] == 0.6 and out["yes_bid"] == 0.55 and "ts_ns" not in out
    ctx = e.context()
    assert ctx["k_lo"] == 145.0 and ctx["k_hi"] == 155.0 and ctx["expiry"] == EXP and ctx["above"]
    assert ctx["chain"] is not None and len(mocked_chain) == 1
    out2 = run(e({"yes_bid": 0.5, "yes_ask": 0.52}, t))  # within refresh_s: network-free re-enrich
    assert len(mocked_chain) == 1 and out2["opt_mid"] == pytest.approx(5.0)


def test_enricher_leaves_unmapped_and_index_markets_honest(mocked_chain):
    e = OptionsEnricher("Will the Fed hike rates in October 2026?")
    f = {"yes_bid": 0.3, "yes_ask": 0.32, "opt_implied_prob": NAN, "eightk_score": 0.0}
    out = run(e(f, ts_of("2026-10-02")))
    assert math.isnan(out["opt_implied_prob"]) and e.context() is None and not e.supported()
    assert mocked_chain == []  # no chain fetched for an unsupported question
    spy = OptionsEnricher("Will SPY close above $600 on December 18, 2026?")
    out = run(spy({"yes_bid": 0.5, "yes_ask": 0.5}, ts_of("2026-10-02")))
    assert math.isfinite(out["opt_implied_prob"]) and math.isnan(out["eightk_score"])  # ETFs file no 8-Ks


def test_enricher_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("massive down")
    e = OptionsEnricher(Q_ABOVE, enrich_market=boom)
    f = {"yes_bid": 0.4, "yes_ask": 0.42, "opt_mid": NAN}
    assert run(e(f, ts_of("2026-10-02"))) == f


def test_live_source_applies_the_options_hook(mocked_chain):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bids": [{"price": "0.55", "size": "100"}],
                                         "asks": [{"price": "0.57", "size": "80"}]})
    seen = []

    async def hook(fields, ts):
        seen.append(ts)
        return {**fields, "opt_implied_prob": 0.41, "opt_mid": 4.1, "not_a_field": 1.0}

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await LiveSource("tok", http=http, options=hook).poll(http)
    t = run(go())
    assert t.fields["opt_implied_prob"] == 0.41 and t.fields["opt_mid"] == 4.1 and "not_a_field" not in t.fields
    assert seen == [t.ts_ns]


# ---------------------------------------------------------------- 2. fit: listed_options eligibility

def _points(n=24, t0=1_790_000_000):
    return [(t0 + 3600 * i, 0.4 + 0.01 * (i % 5)) for i in range(n)]


def test_available_requirements_flip_with_option_data():
    t = assemble(_points())
    assert "listed_options" not in available_requirements(TickSet(t, "replay", 24))
    t["opt_implied_prob"][5] = 0.42
    assert "listed_options" in available_requirements(TickSet(t, "replay", 24))


def test_join_options_builds_the_spread_history_from_leg_bars():
    pts = _points()
    ticks = assemble(pts)
    t0 = pts[0][0]
    leg_bars = {"O:NVDA261218C00145000": [(t0 + 3600 * 3, 8.0), (t0 + 3600 * 10, 9.0)],
                "O:NVDA261218C00155000": [(t0 + 3600 * 3, 3.0), (t0 + 3600 * 10, 3.5)]}

    async def refresh(und, k, expiry, **kw):
        return nvda_chain(), False
    out, info = run(join_options(ticks, Q_ABOVE, None, massive=lambda: object(), refresh=refresh,
                                 bars=lambda client, tk, s, e: leg_bars[tk], eightk=False,
                                 today=dt.date(2026, 10, 2)))
    assert info["available"] and info["structure"]["kind"] == "call_spread"
    assert math.isnan(out["opt_mid"][2]) and out["opt_mid"][3] == pytest.approx(5.0)  # as-of: known at bar end
    assert out["opt_mid"][12] == pytest.approx(5.5)
    assert 0.4 < out["opt_implied_prob"][3] < 0.6 and np.isnan(out["opt_iv"]).all()  # iv never back-filled
    assert "listed_options" in available_requirements(TickSet(out, "replay", len(pts)))


@pytest.mark.parametrize("question,massive,offline,why", [
    ("Will the Fed hike rates in October 2026?", lambda: object(), False, "not mapped"),
    (Q_ABOVE, None, False, "offline"),
    (Q_ABOVE, lambda: object(), True, "offline"),
    (Q_ABOVE, lambda: None, False, "MASSIVE_API_KEY"),
])
def test_join_options_degrades_without_data(question, massive, offline, why):
    ticks = assemble(_points())
    out, info = run(join_options(ticks, question, None, massive=massive, offline=offline,
                                 today=dt.date(2026, 10, 2)))
    assert out is ticks and not info["available"] and why in " ".join(info["notes"])


def test_spread_series_needs_every_leg():
    ts = np.array([10, 20, 30])
    assert np.isnan(spread_series(ts, [(1, [(15, 2.0)]), (-1, [])])).all()
    assert spread_series(ts, [(1, [(15, 2.0)]), (-1, [(5, 0.5)])]).tolist()[1:] == [1.5, 1.5]


def _fit(monkeypatch, with_options: bool, with_iv: bool = True, question: str = Q_ABOVE, hc=None):
    pts = _points(48)
    ticks = assemble(pts, bars=[(p[0] - 1, 100.0) for p in pts])

    async def fake_build(market, ticker, **kw):
        return TickSet(dict(ticks), "replay", len(pts), True)

    async def fake_join(t, question, end_date, **kw):
        if not with_options:
            return t, {"available": False, "notes": ["options: none"]}
        out = dict(t)
        out["opt_implied_prob"] = np.full(len(pts), 0.4)
        out["opt_mid"] = np.full(len(pts), 4.0)
        if with_iv:
            out["opt_iv"] = np.linspace(0.40, 0.45, len(pts))
        return out, {"available": True, "notes": []}
    monkeypatch.setattr(service, "build_ticks", fake_build)
    monkeypatch.setattr(service, "join_options", fake_join)
    hc = hc or fake_hedgecore()
    deps = service.Deps(adapter=EngineAdapter(module=hc))
    req = service.FitRequest(question=question, ticker="NVDA", division="opportunity")
    return run(service.run_fit(req, deps)), hc


def test_option_families_become_eligible_and_scored_only_with_option_data(monkeypatch):
    r, hc = _fit(monkeypatch, with_options=True)
    scored = {c[0] for c in hc.calls}
    assert {"binary_vs_spread_arb", "vol_vs_pm_move"} <= scored
    assert r["division"] == "opportunity" and r["score"] is not None
    r2, hc2 = _fit(monkeypatch, with_options=False)
    assert not {"binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity"} & {c[0] for c in hc2.calls}
    assert r2["family"] not in ("binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity")


def test_fit_division_override_is_honoured():
    lists = {"hedge": [{"id": "h"}], "opportunity": []}
    assert service.choose_division(lists, 100, "opportunity") is None
    assert service.choose_division(lists, 0, "hedge") == "hedge"
    assert service.choose_division(lists, 0) == "hedge"  # default falls back


# ---------------------------------------------------------------- 3. proposals and the approval gate

class FakeEnricher:
    """Option fields come from the replay recording; the chain prices the legs."""

    def __init__(self, chain=None, above=True, k=150.0):
        self.chain = chain if chain is not None else nvda_chain()
        self.detail = {"supported": True, "available": True, "underlying_used": "NVDA", "strike_used": k,
                       "expiry": EXP, "k_lo": 145.0, "k_hi": 155.0, "direction": "above" if above else "below",
                       "match": {"expiry": EXP}}
        self.calls = 0

    def context(self):
        return {"underlying": "NVDA", "strike": self.detail["strike_used"], "expiry": EXP, "k_lo": 145.0,
                "k_hi": 155.0, "above": self.detail["direction"] == "above", "chain": self.chain, "available": True}

    def supported(self):
        return True

    async def __call__(self, fields, ts=None):
        self.calls += 1
        return fields


@pytest.fixture
def opp_client(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    f = tmp_path / "opp.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_000_000_000 * (i + 1), "p": p, "opt_implied_prob": 0.35,
                                     "opt_mid": 3.5}) + "\n" for i, p in enumerate(PS)))
    app = create_app()
    app.state.replay_speed = 0
    app.state.replay_path = str(f)
    app.state.broker = SimBroker(None)
    app.state.enricher = FakeEnricher()
    app.state.options_enricher_factory = lambda market: app.state.enricher
    with TestClient(app) as c:
        yield c


def opp_proposal(c, algo=None, approve=True, **kw):
    body = {"ticker": "NVDA", "market": MKT, "division": "opportunity",
            "algo": algo or {"family": "binary_vs_spread_arb", "preset_index": 1}, **kw}
    r = c.post("/proposals", json=body)
    assert r.status_code == 201, r.text
    if approve:
        assert c.post(f"/proposals/{r.json()['id']}/approve").status_code == 200
    return r.json()


def test_opportunity_proposal_needs_an_options_family_and_carries_caps(opp_client):
    c = opp_client
    p = opp_proposal(c, approve=False)
    assert p["family"] == "opportunity" and p["basis"] == "market_event" and p["direction"] is None
    assert p["strategy"] == "options:call_spread/put_spread" and "simulated" in p["label"]
    assert p["max_contracts"] == 10 and p["max_notional"] == 10_000.0
    assert p["algo"]["coverage_cap"] is None
    for bad, msg in [(None, "needs an algo"), ({"family": "macro_fed_hedge"}, "not an options family"),
                     ({"family": "no_bid_seller"}, "not an options family"),
                     ({"family": "poly_kalshi_spread"}, "not an options family")]:
        body = {"ticker": "NVDA", "market": MKT, "division": "opportunity", **({"algo": bad} if bad else {})}
        r = c.post("/proposals", json=body)
        assert r.status_code == 422 and msg in json.dumps(r.json()), (bad, r.text)
    # max_contracts caps the per-entry size param, shown on the approved record
    p = opp_proposal(c, {"family": "binary_vs_spread_arb", "params": {"contracts": 10}}, approve=False,
                     max_contracts=3, max_notional=2500)
    assert p["algo"]["resolved_params"]["contracts"] == 3 and p["algo"]["capped"] == {"contracts": 10.0}
    assert p["max_notional"] == 2500
    # an options family on a hedge proposal, or caps on a hedge proposal: 422
    r = c.post("/proposals", json={"ticker": "NVDA", "market": MKT, "direction": "down_on_yes", "shares_held": 10,
                                   "algo": {"family": "binary_vs_spread_arb"}})
    assert r.status_code == 422
    r = c.post("/proposals", json={"ticker": "NVDA", "market": MKT, "direction": "down_on_yes", "shares_held": 10,
                                   "max_contracts": 3})
    assert r.status_code == 422
    # a hedge still needs shares
    r = c.post("/proposals", json={"ticker": "NVDA", "market": MKT, "direction": "down_on_yes"})
    assert r.status_code == 422


def test_opportunity_bridge_keeps_every_approval_gate(opp_client):
    c = opp_client
    body = lambda pid, src="replay": {"proposal_id": pid, "source": src}  # noqa: E731
    assert c.post("/bridges", json=body("nope")).status_code == 404
    p = opp_proposal(c, approve=False)
    assert c.post("/bridges", json=body(p["id"])).status_code == 409  # not approved
    c.post(f"/proposals/{p['id']}/approve")
    r = c.post("/bridges", json=body(p["id"]))
    assert r.status_code == 201
    bid = r.json()["bridge_id"]
    again = c.post("/bridges", json=body(p["id"]))
    assert again.status_code == 200 and again.json()["bridge_id"] == bid  # idempotent, same source
    assert c.post("/bridges", json=body(p["id"], "live")).status_code == 409  # one bridge per proposal
    other = c.post("/bridges", json={**body(p["id"]), "family": "vol_vs_pm_move"})
    assert other.status_code == 409  # the approval covers what runs
    _events(c, bid)
    # a filing opportunity proposal without an options algo still never reaches hedgecore
    pid = c.post("/proposals", json={"ticker": "ABNB", "tags": ["workforce_reduction"], "shares_held": 10}).json()["id"]
    c.post(f"/proposals/{pid}/approve")
    r = c.post("/bridges", json={**body(pid), "market": MKT})
    assert r.status_code == 409 and "single simulated options order" in r.json()["detail"]


def test_filing_opportunity_with_an_options_algo_can_bridge(opp_client):
    c = opp_client
    r = c.post("/proposals", json={"ticker": "ABNB", "tags": ["workforce_reduction"], "shares_held": 10,
                                   "algo": {"family": "eightk_opportunity"}})
    assert r.status_code == 201 and r.json()["max_contracts"] == 10
    pid = r.json()["id"]
    c.post(f"/proposals/{pid}/approve")
    r = c.post("/bridges", json={"proposal_id": pid, "source": "replay", "market": MKT})
    assert r.status_code == 201
    _events(c, r.json()["bridge_id"])


# ---------------------------------------------------------------- 4. multi-leg option orders and caps

def _start(c, p):
    r = c.post("/bridges", json={"proposal_id": p["id"], "source": "replay"})
    assert r.status_code == 201, r.text
    return r.json()["bridge_id"]


def test_option_intent_becomes_a_multi_leg_order_through_the_sim(opp_client):
    c = opp_client
    FakeAlgo.script = {3: {"instrument": "option", "side": 1, "qty": 2.0, "reason": "entry"},
                       8: {"instrument": "option", "side": -1, "qty": 2.0, "reason": "exit"}}
    p = opp_proposal(c)
    bid = _start(c, p)
    ev = _events(c, bid)
    a = FakeAlgo.instances[0]
    assert a.family == "binary_vs_spread_arb" and a.position == {"option": 0.0}
    ticks = [d for k, d in ev if k == "tick"]
    assert ticks[0]["options"]["opt_implied_prob"] == 0.35 and ticks[0]["options"]["gap"] == pytest.approx(0.2 - 0.35)
    assert a.ticks[0]["yes_bid"] == PS[0]  # opportunity ticks are never oriented
    fills = [d for k, d in ev if k == "fill"]
    assert [f["status"] for f in fills] == ["filled", "filled"]
    entry, exit_ = fills
    assert entry["structure"] == "call_spread" and entry["simulated"] and "simulated" in entry["fill_model"]
    assert [(lg["ticker"], lg["side"]) for lg in entry["legs"]] == [("O:NVDA261218C00145000", "buy"),
                                                                    ("O:NVDA261218C00155000", "sell")]
    # each leg at its quote mid +/- half the quoted spread; the structure price is the signed sum
    assert entry["legs"][0]["fill_px"] == pytest.approx(8.1) and entry["legs"][1]["fill_px"] == pytest.approx(2.9)
    assert entry["fill_px"] == pytest.approx(5.2) and entry["fee"] == pytest.approx(4 * 0.65)
    assert [(lg["ticker"], lg["side"]) for lg in exit_["legs"]] == [("O:NVDA261218C00145000", "sell"),
                                                                    ("O:NVDA261218C00155000", "buy")]
    assert a.fills == [("option", 2.0, pytest.approx(5.2)), ("option", -2.0, pytest.approx(4.8))]
    s = c.get(f"/bridges/{bid}").json()
    assert s["division"] == "opportunity" and s["option_position"] == 0 and s["option_structure"] is None
    assert s["option_data"] == "recorded" and s["pm_vs_options"]["opt_implied_prob"] == 0.35
    assert s["coverage_cap"] is None and s["equity_price"] is None
    sandbox = c.app.state.bridges[p["id"]].replay_broker  # replays trade an isolated simulator by default
    assert run(sandbox.positions()) == [] and len(run(sandbox.orders())) == 4  # round trip closed both legs


def test_risk_caps_clip_and_hold_option_entries(opp_client):
    c = opp_client
    FakeAlgo.script = {2: {"instrument": "option", "side": 1, "qty": 5.0},
                       4: {"instrument": "option", "side": 1, "qty": 5.0}}
    p = opp_proposal(c, max_contracts=3)
    ev = _events(c, _start(c, p))
    fills = [d for k, d in ev if k == "fill"]
    assert fills[0]["status"] == "filled" and fills[0]["qty"] == 3 and fills[0]["capped_from"] == 5
    assert fills[0]["cap"] == "max_contracts"
    assert fills[1]["status"] == "held" and "max_contracts" in fills[1]["reject_reason"]
    a = FakeAlgo.instances[0]
    assert a.rejects == ["option"] and a.fills[0][1] == 3.0
    legs = {x.symbol: x.qty for x in run(c.app.state.bridges[p["id"]].replay_broker.positions())}
    assert legs == {"O:NVDA261218C00145000": 3, "O:NVDA261218C00155000": -3}

    FakeAlgo.script, FakeAlgo.instances = {2: {"instrument": "option", "side": 1, "qty": 5.0},
                                           4: {"instrument": "option", "side": 1, "qty": 5.0}}, []
    p = opp_proposal(c, max_notional=1100)  # debit at the ask 5.2 -> $520 per spread -> 2 spreads fit
    bid = _start(c, p)
    fills = [d for k, d in _events(c, bid) if k == "fill"]
    assert fills[0]["qty"] == 2 and fills[0]["cap"] == "max_notional" and fills[0]["unit_risk"] == pytest.approx(520)
    assert fills[1]["status"] == "held"
    assert c.get(f"/bridges/{bid}").json()["risk_used"] == pytest.approx(1040)


def test_no_chain_rejects_option_intents_cleanly(opp_client):
    c = opp_client
    c.app.state.enricher = FakeEnricher(chain=ch.Chain("NVDA", 0.0))
    c.app.state.enricher.context = lambda: None
    FakeAlgo.script = {2: {"instrument": "option", "side": 1, "qty": 1.0}}
    ev = _events(c, _start(c, opp_proposal(c)))
    f = next(d for k, d in ev if k == "fill")
    assert f["status"] == "rejected" and "no option chain" in f["reject_reason"]
    assert FakeAlgo.instances[0].rejects == ["option"]


def test_webull_routes_option_combos_to_the_simulator_labelled(opp_client):
    c = opp_client
    sim = SimBroker(None, order_note="Routed to the simulator: Webull paper is only used for equities.")
    c.app.state.broker = WebullBroker(object(), sim)
    FakeAlgo.script = {2: {"instrument": "option", "side": 1, "qty": 1.0}}
    bid = _start(c, opp_proposal(c))  # replay sandbox by default: an isolated simulator
    ev = _events(c, bid)
    f = next(d for k, d in ev if k == "fill")
    assert f["status"] == "filled" and f["broker"] == "sim-replay" and f["simulated"]
    # a live-account replay goes to the Webull wrapper, whose combos land in its simulator with the label
    FakeAlgo.script, FakeAlgo.instances = {2: {"instrument": "option", "side": 1, "qty": 1.0}}, []
    p = opp_proposal(c)
    r = c.post("/bridges", json={"proposal_id": p["id"], "source": "replay", "replay_to_account": True})
    f = next(d for k, d in _events(c, r.json()["bridge_id"]) if k == "fill")
    assert f["status"] == "filled" and f["broker"] == "sim" and "Webull" in f["note"]
    assert f["routed"].startswith("simulator")
    assert {x.symbol for x in run(sim.positions())} == {"O:NVDA261218C00145000", "O:NVDA261218C00155000"}


# ---------------------------------------------------------------- SimBroker combos

def _legs(*specs):
    return [OrderRequest(symbol=s, asset="option", side=side, qty=q, ref_px=px, ref_half_spread=h,
                         client_order_id=f"c-{i}", combo_id="c") for i, (s, side, q, px, h) in enumerate(specs)]


def test_sim_combo_fills_all_legs_at_quoted_spreads():
    b = SimBroker(None)
    orders = run(b.place_combo(_legs(("O:A", "buy", 2, 8.0, 0.1), ("O:B", "sell", 2, 3.0, 0.1))))
    assert [o.status for o in orders] == ["filled", "filled"] and orders[0].combo_id == "c"
    assert orders[0].fill_px == 8.1 and orders[1].fill_px == 2.9
    acct = run(b.account())
    assert acct.cash == pytest.approx(1_000_000 - 2 * 100 * (8.1 - 2.9) - 4 * 0.65)
    assert run(b.place_combo(_legs(("O:A", "buy", 2, 8.0, 0.1), ("O:B", "sell", 2, 3.0, 0.1))))[0].id == orders[0].id


def test_sim_combo_is_all_or_none():
    b = SimBroker(None)  # NullQuotes: a leg without ref_px has no price
    orders = run(b.place_combo(_legs(("O:A", "buy", 1, 8.0, 0.1), ("O:B", "sell", 1, None, None))))
    assert [o.status for o in orders] == ["rejected", "rejected"] and "combo leg 2" in orders[0].reject_reason
    assert run(b.positions()) == [] and run(b.account()).cash == 1_000_000
    poor = SimBroker(None, starting_cash=500)
    orders = run(poor.place_combo(_legs(("O:A", "buy", 1, 8.0, 0.1), ("O:B", "sell", 1, 3.0, 0.1))))
    assert all(o.status == "rejected" and "buying_power" in o.reject_reason for o in orders)
    assert run(poor.positions()) == []
    with pytest.raises(BrokerError):
        run(b.place_combo([OrderRequest(symbol="SPY", asset="equity", side="buy", qty=1, ref_px=1.0)]))


# ---------------------------------------------------------------- the real engine, when built

def test_real_binary_vs_spread_arb_trades_the_gap(opp_client, monkeypatch):
    hc = pytest.importorskip("hedgecore")
    monkeypatch.setattr(bridges, "_load_engine", lambda: hc)
    c = opp_client
    p = opp_proposal(c, {"family": "binary_vs_spread_arb", "params": {"entry_gap": 0.05, "exit_gap": 0.01,
                                                                       "contracts": 2}})
    ev = _events(c, _start(c, p))
    decisions = [d for k, d in ev if k == "decision"]
    fills = [d for k, d in ev if k == "fill"]
    assert decisions and all(d["engine"] == "algo" and d["family"] == "binary_vs_spread_arb" for d in decisions)
    # PS starts at 0.20 vs an options-implied 0.35: PM trails by > entry_gap -> sell the call spread
    assert fills and fills[0]["status"] == "filled" and fills[0]["side"] == "sell" and fills[0]["qty"] == 2
    assert fills[0]["structure"] == "call_spread"


# ---------------------------------------------------------------- review fixes: honest scores, eightk orientation

from app.pipeline.ticks import orient_for_family  # noqa: E402
from app.pipeline.tune import missing_signal, score_row, tune  # noqa: E402


def test_zero_order_opportunity_replay_is_unscored():
    assert score_row({"n_orders": 0, "pnl": 0.0, "fees": 0.0, "max_dd": 0.0}, "opportunity") is None
    assert score_row({"n_orders": 2, "pnl": -10.0, "fees": 0.0, "max_dd": 20.0}, "opportunity") == pytest.approx(-0.5)
    assert score_row({"n_orders": 0, "hedge_var_reduction": 0.3}, "hedge") == 0.3  # hedge scoring unchanged


class _IdleAdapter:
    """Every preset of one family holds on every tick; another family trades at a loss."""
    can_score = True

    def __init__(self, idle=("vol_vs_pm_move",)):
        self.idle, self.calls = set(idle), []

    def replay_grid(self, family, position, ticks):
        self.calls.append(family)
        if family in self.idle:
            return [{"preset_index": i, "params": {}, "n_orders": 0, "pnl": 0.0, "fees": 0.0, "max_dd": 0.0}
                    for i in range(3)]
        return [{"preset_index": 0, "params": {}, "n_orders": 4, "pnl": -30.0, "fees": 2.0, "max_dd": 40.0}]


def _opt_ticks(n=48, iv=True, eightk=False):
    pts = _points(n)
    t = assemble(pts)
    t["opt_implied_prob"] = np.full(n, 0.4)
    t["opt_mid"] = np.full(n, 4.0)
    t["opt_iv"] = np.full(n, 0.4) if iv else np.full(n, NAN)
    t["eightk_score"] = np.full(n, 0.7) if eightk else np.full(n, NAN)
    return TickSet(t, "replay", n, True)


def test_idle_family_never_beats_a_losing_family_and_all_idle_is_unscored():
    fams = [{"id": "vol_vs_pm_move"}, {"id": "binary_vs_spread_arb"}]
    out = tune(_IdleAdapter(), fams, "opportunity", {"option": 0.0}, _opt_ticks())
    assert out["scored"] and out["family"] == "binary_vs_spread_arb" and out["score"] < 0
    out = tune(_IdleAdapter(idle=("vol_vs_pm_move", "binary_vs_spread_arb")), fams, "opportunity", {}, _opt_ticks())
    assert not out["scored"] and out["score"] is None and "no preset placed a single order" in out["unscored_reason"]


def test_family_without_its_signal_history_is_not_replayed():
    a = _IdleAdapter(idle=())
    fams = [{"id": "vol_vs_pm_move"}, {"id": "eightk_opportunity"}, {"id": "binary_vs_spread_arb"}]
    out = tune(a, fams, "opportunity", {}, _opt_ticks(iv=False, eightk=False))
    assert a.calls == ["binary_vs_spread_arb"] and out["family"] == "binary_vs_spread_arb"
    assert missing_signal("vol_vs_pm_move", _opt_ticks(iv=False).ticks) == "opt_iv"
    assert missing_signal("eightk_opportunity", _opt_ticks(eightk=True).ticks) is None
    a = _IdleAdapter(idle=())
    out = tune(a, fams[:2], "opportunity", {}, _opt_ticks(iv=False))
    assert a.calls == [] and not out["scored"] and "opt_iv has no history" in out["unscored_reason"]


def test_fit_skips_vol_vs_pm_move_without_iv_history(monkeypatch):
    r, hc = _fit(monkeypatch, with_options=True, with_iv=False)
    called = {c[0] for c in hc.calls}
    assert "binary_vs_spread_arb" in called and "vol_vs_pm_move" not in called


def test_orient_for_family_flips_only_eightk_on_above_questions():
    t = {"yes_bid": 0.30, "yes_ask": 0.32, "opt_implied_prob": 0.4}
    up = orient_for_family(t, "eightk_opportunity", "above")
    assert up["yes_bid"] == pytest.approx(0.68) and up["yes_ask"] == pytest.approx(0.70)
    assert orient_for_family(t, "eightk_opportunity", "below") is t
    assert orient_for_family(t, "eightk_opportunity", None) is t
    assert orient_for_family(t, "binary_vs_spread_arb", "above") is t
    assert orient_for_family(t, "vol_vs_pm_move", "above") is t


def test_fit_feeds_eightk_the_adverse_probability_on_an_above_question():
    fams = [{"id": "eightk_opportunity"}, {"id": "binary_vs_spread_arb"}]
    ts = _opt_ticks(eightk=True)
    seen = {}

    class Rec(_IdleAdapter):
        def replay_grid(self, family, position, ticks):
            seen[family] = np.array(ticks["yes_bid"], copy=True)
            return super().replay_grid(family, position, ticks)
    ft = {f["id"]: orient_for_family(ts.ticks, f["id"], "above") for f in fams}
    tune(Rec(idle=()), fams, "opportunity", {}, ts, ft)
    assert np.allclose(seen["binary_vs_spread_arb"], ts.ticks["yes_bid"])  # raw YES
    assert np.allclose(seen["eightk_opportunity"], 1.0 - ts.ticks["yes_ask"])  # adverse = NO on "above K"


def test_service_orients_eightk_by_the_matched_question(monkeypatch):
    seen = {}
    pts = _points(48)

    async def fake_build(market, ticker, **kw):
        return TickSet(assemble(pts, bars=[(p[0] - 1, 100.0) for p in pts]), "replay", len(pts), True)

    async def fake_join(t, question, end_date, **kw):
        out = dict(t)
        n = len(pts)
        out.update(opt_implied_prob=np.full(n, 0.4), opt_mid=np.full(n, 4.0), opt_iv=np.full(n, 0.4),
                   eightk_score=np.full(n, 0.8))
        return out, {"available": True, "notes": [], "match": {"direction": "above"}}

    class Rec(_IdleAdapter):
        def library(self):
            return EngineAdapter(module=fake_hedgecore()).library()

        def replay_grid(self, family, position, ticks):
            seen[family] = np.array(ticks["yes_bid"], copy=True)
            return super().replay_grid(family, position, ticks)
    monkeypatch.setattr(service, "build_ticks", fake_build)
    monkeypatch.setattr(service, "join_options", fake_join)
    monkeypatch.setattr(service, "shortlist", lambda manifest, ec, available: {
        "opportunity": [{"id": "eightk_opportunity"}, {"id": "binary_vs_spread_arb"}], "hedge": []})
    monkeypatch.setattr(service, "unmet_requirements", lambda f, available: [])
    req = service.FitRequest(question=Q_ABOVE, ticker="NVDA", division="opportunity")
    run(service.run_fit(req, service.Deps(adapter=Rec(idle=()))))
    raw_bid = seen["binary_vs_spread_arb"]
    assert not np.allclose(seen["eightk_opportunity"], raw_bid)
    assert np.allclose(seen["eightk_opportunity"], 1.0 - raw_bid, atol=0.05)  # NO side of the raw book


def test_hedge_fit_skips_the_options_join(monkeypatch):
    joins = []
    pts = _points(48)

    async def fake_build(market, ticker, **kw):
        return TickSet(assemble(pts, bars=[(p[0] - 1, 100.0) for p in pts]), "replay", len(pts), True)

    async def fake_join(t, question, end_date, **kw):
        joins.append(question)
        return t, {"available": False, "notes": []}
    monkeypatch.setattr(service, "build_ticks", fake_build)
    monkeypatch.setattr(service, "join_options", fake_join)
    deps = service.Deps(adapter=EngineAdapter(module=fake_hedgecore()))
    run(service.run_fit(service.FitRequest(question=Q_ABOVE, ticker="NVDA", division="hedge", shares_held=100), deps))
    run(service.run_fit(service.FitRequest(question=Q_ABOVE, ticker="NVDA", shares_held=100), deps))
    assert joins == []
    run(service.run_fit(service.FitRequest(question=Q_ABOVE, ticker="NVDA", division="opportunity"), deps))
    assert joins == [Q_ABOVE]


def test_bridge_feeds_eightk_the_adverse_probability(opp_client):
    c = opp_client
    p = opp_proposal(c, {"family": "eightk_opportunity", "preset_index": 0})
    ev = _events(c, _start(c, p))
    a = FakeAlgo.instances[-1]
    assert a.ticks[0]["yes_bid"] == pytest.approx(1 - PS[0])  # "above K": YES is bullish, adverse = NO
    tick = next(d for k, d in ev if k == "tick")
    assert tick["options"]["gap"] == pytest.approx(PS[0] - 0.35)  # the UI gap stays on raw YES
    FakeAlgo.instances = []
    c.app.state.enricher = FakeEnricher(above=False)
    p = opp_proposal(c, {"family": "eightk_opportunity", "preset_index": 1})
    _events(c, _start(c, p))
    assert FakeAlgo.instances[-1].ticks[0]["yes_bid"] == pytest.approx(PS[0])  # "below K": YES already adverse


def test_zero_risk_quotes_never_bypass_the_notional_cap(opp_client):
    c = opp_client
    crossed = ch.Chain(underlying="NVDA", fetched_at=time.time())
    for k, m in ((145.0, 3.0), (150.0, 4.0), (155.0, 5.0)):  # stale: the lower call is cheaper than the upper
        tag = f"{int(k * 1000):08d}"
        crossed.quotes.append(ch.OptionQuote(f"O:NVDA261218C{tag}", "call", k, EXP, bid=m, ask=m, mid=m,
                                             mark_source="quote"))
    c.app.state.enricher = FakeEnricher(chain=crossed)
    FakeAlgo.script = {2: {"instrument": "option", "side": 1, "qty": 3.0}}
    ev = _events(c, _start(c, opp_proposal(c, max_notional=1000)))
    f = next(d for k, d in ev if k == "fill")
    assert f["status"] == "rejected" and "non-positive risk" in f["reject_reason"]
    assert FakeAlgo.instances[0].rejects == ["option"]
