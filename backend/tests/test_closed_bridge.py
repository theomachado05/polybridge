from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import bridges
from app.broker import SimBroker
from app.broker.quotes import NullQuotes, Quote
from app.closed import bridge_mode, evidence, staged
from app.closed import gap as gapsvc
from app.main import create_app
from tests.test_bridges import _events, write_meta
from tests.test_broker_support import FakeQuotes

ET = ZoneInfo("America/New_York")
REPLAYS = Path(__file__).resolve().parents[1] / "replays"
WEEKEND = REPLAYS / "us-recession-in-2025-weekend-2025-04-04.jsonl"
RECESSION_TOKEN = "104173557214744537570424345347209544585775842950109756851652855913015295701992"
ELECTION_TOKEN = "21742633143463906290569050155826241533067272736897614950488156847949938836455"
MKT = {"source": "polymarket", "id": "m-closed", "token_id": "tok-closed"}


def et_ns(y, mo, d, h, mi=0) -> int:
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ET).timestamp()) * 1_000_000_000


ROWS = [
    ((2026, 10, 2, 15, 0), 0.30, 500.0),
    ((2026, 10, 2, 15, 50), 0.30, 500.0),
    ((2026, 10, 2, 17, 0), 0.32, 499.0),
    ((2026, 10, 2, 22, 0), 0.36, 499.0),
    ((2026, 10, 3, 12, 0), 0.40, 499.0),
    ((2026, 10, 4, 12, 0), 0.42, 499.0),
    ((2026, 10, 4, 20, 0), 0.45, 499.0),
    ((2026, 10, 5, 4, 0), 0.45, 499.0),
    ((2026, 10, 5, 4, 30), 0.46, 490.0),
    ((2026, 10, 5, 9, 30), 0.46, 488.0),
    ((2026, 10, 5, 10, 0), 0.46, 492.0),
]
SCRIPT = {1: 100.0, 5: 50.0}


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


@pytest.fixture
def fake_engine(monkeypatch):
    monkeypatch.setattr(bridges, "_load_engine", lambda: SimpleNamespace(HedgeSpec=lambda **kw: SimpleNamespace(**kw),
                                                                         Engine=FakeEngine))


@pytest.fixture
def research_rate(monkeypatch):
    monkeypatch.setattr(gapsvc, "load_rates", lambda path=None: gapsvc.GapRates())
    monkeypatch.setattr(bridge_mode, "load_rates", lambda path=None: gapsvc.GapRates())


def write_rows(path: Path, rows=ROWS) -> Path:
    path.write_text("".join(json.dumps({"ts_ns": et_ns(*t), "p": p, "under_px": u}) + "\n" for t, p, u in rows))
    write_meta(path, MKT)
    return path


def make_client(tmp_path, replay: Path | None, quotes=None):
    app = create_app()
    app.state.broker = SimBroker(tmp_path / "s.json", quotes or FakeQuotes(equity={"SPY": Quote(500.0, None, "q")}))
    app.state.replay_speed = 0
    app.state.staged_autorun = False
    if replay is not None:
        app.state.replay_path = str(replay)
    return TestClient(app)


def approved(c, *, market=MKT, shares=1000, cov=0.5, algo=None, hedge_a=False, override=True) -> str:
    body = {"ticker": "SPY", "market": market, "direction": "down_on_yes", "shares_held": shares,
            "target_coverage": cov, "act_on_unvalidated": override}
    if algo:
        body["algo"] = algo
    if hedge_a:
        body["closed_pm_hedge"] = True
    r = c.post("/proposals", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["closed_pm_hedge"] is hedge_a
    c.post(f"/proposals/{r.json()['id']}/approve", json={"ack_unvalidated": True})
    return r.json()["id"]


def auto_approve(monkeypatch, when):
    orig = bridge_mode.ClosedMode._step_staged

    async def step(self, at):
        o = self._plan_order()
        if o is not None and o.status == "staged" and when(o):
            o.status, o.approved_qty, o.approved_at = "approved", o.qty, staged._iso(at)
            staged._note(o, at, "APPROVED", "test click")
        return await orig(self, at)
    monkeypatch.setattr(bridge_mode.ClosedMode, "_step_staged", step)


def test_only_the_recession_market_is_validated_and_the_hedges_carry_the_research_verdicts():
    doc = evidence.load()
    assert [k for k, v in doc["markets"].items() if v["validated"]] == ["us-recession-in-2025"]
    rec = evidence.market_evidence("polymarket", "516710")
    assert rec["validated"] and rec["status"] == "validated" and "97 of 151" in rec["evidence"]
    assert evidence.market_evidence("polymarket", "x", RECESSION_TOKEN)["validated"]
    el = evidence.market_evidence("polymarket", "nope", ELECTION_TOKEN)
    assert not el["validated"] and el["status"] == "unvalidated estimate" and "fails" in el["evidence"]
    unk = evidence.market_evidence("polymarket", "4620900")
    assert not unk["validated"] and unk["oos"] is None
    h = evidence.hedge_evidence()
    assert h["hedge_a"]["verdict"] == "no evidence" and h["hedge_a"]["default"] is False
    assert "not protection" in h["hedge_a"]["label"].lower()
    assert h["hedge_b"]["verdict"] == "reduces the loss variance" and h["hedge_b"]["default"] is True
    assert h["opportunity"]["verdict"] == "NULL" and h["opportunity"]["research_only"] is True
    assert h["hedge_b"]["vr0_ci"][0] > 0 > h["hedge_a"]["vr0_ci"][0]


def test_evidence_and_expected_gap_routes_gate_validation(tmp_path):
    with make_client(tmp_path, None) as c:
        e = c.get("/closed/evidence").json()
        assert e["validated_markets"] == ["us-recession-in-2025"]
        assert e["opportunity"]["research_only"] and e["overnight_gap_replication"]["verdict"] == "does not replicate"
        q = "/closed/expected-gap?market_source=polymarket&market_id=516710&ticker=SPY&direction=down_on_yes"
        g = c.get(q + f"&token_id={RECESSION_TOKEN}&at=2025-04-05T16:00:00Z&move_pp=5").json()
        assert g["expected_gap"]["validated"] is True and g["expected_gap"]["label"] == "market"
        assert g["expected_gap"]["expected_gap_bp"] == pytest.approx(-5 * 10.732000656751016)
        g2 = c.get("/closed/expected-gap?market_source=polymarket&market_id=4620900&ticker=TLT&direction=down_on_yes"
                   "&at=2026-10-03T16:00:00Z&move_pp=5").json()
        assert g2["expected_gap"]["validated"] is False and g2["expected_gap"]["status"] == "unvalidated estimate"
        assert g2["expected_gap"]["n_closures"] == 1591
        assert g2["expected_gap"]["band_bp"][0] < 0 < g2["expected_gap"]["band_bp"][1]


def test_the_gate_needs_the_ticker_the_rate_was_validated_on(tmp_path):
    with make_client(tmp_path, None) as c:
        q = ("/closed/expected-gap?market_source=polymarket&market_id=516710&direction=down_on_yes"
             f"&token_id={RECESSION_TOKEN}&at=2025-04-05T16:00:00Z&move_pp=5")
        for tick in ("TLT", "NVDA"):
            g = c.get(q + f"&ticker={tick}").json()["expected_gap"]
            assert g["validated"] is False and g["status"] == "unvalidated estimate", tick
            assert g["basis_ticker"] == "SPY" and "GAP_PROXY_TICKER" in g["reasons"] and g["label"] == "market"
            assert "proxy" in g["evidence"] and "SPY" in g["evidence"] and tick in g["evidence"]
        g = c.get("/closed/expected-gap?market_source=polymarket&market_id=516710&ticker=SPY&direction=down_on_yes"
                  "&at=2025-04-05T16:00:00Z&move_pp=5").json()["expected_gap"]
        assert g["label"] == "market" and g["validated"] is True and g["n_closures"] == 231
    rates = gapsvc.load_rates()
    own = rates.lookup("polymarket", "x", None, RECESSION_TOKEN)
    evid = evidence.market_evidence("polymarket", "516710")
    tlt = bridge_mode.gap_view(gapsvc.expected_gap(5.0, own, sign=-1, ticker="TLT", reasons=["GAP_MARKET_RATE"]), evid)
    assert tlt["validated"] is False and tlt["status"] == "unvalidated estimate" and "proxy" in tlt["evidence"]
    spy = bridge_mode.gap_view(gapsvc.expected_gap(5.0, own, sign=-1, ticker="SPY", reasons=["GAP_MARKET_RATE"]), evid)
    assert spy["validated"] is True and spy["status"] == "validated"
    pooled = evidence.gate(evid, "pooled", "SPY", "SPY", ["GAP_POOLED_RATE"])
    assert pooled[0] is False and "no per-market rate matched" in pooled[2]
    few = evidence.gate(evid, "pooled", "SPY", "SPY", ["GAP_TOO_FEW_CLOSURES"])
    assert few[0] is False and "too few closures" in few[2]
    el = evidence.market_evidence("polymarket", "nope", ELECTION_TOKEN)
    assert evidence.gate(el, "market", "SPY", "SPY", [])[:2] == (False, "unvalidated estimate")


def test_closed_pm_hedge_is_for_hedge_proposals_only(tmp_path):
    with make_client(tmp_path, None) as c:
        r = c.post("/proposals", json={"ticker": "NVDA", "market": MKT, "division": "opportunity",
                                       "closed_pm_hedge": True,
                                       "algo": {"family": "binary_vs_spread_arb", "preset_index": 0}})
        assert r.status_code == 422
        r = c.post("/proposals", json={"ticker": "SPY", "market": MKT, "direction": "down_on_yes",
                                       "shares_held": 10})
        assert r.json()["closed_pm_hedge"] is False


def test_weekend_replay_holds_the_equity_algo_stages_hedge_b_and_executes_at_the_first_fresh_price(
        tmp_path, fake_engine, research_rate, monkeypatch):
    f = write_rows(tmp_path / "wk.jsonl")
    auto_approve(monkeypatch, lambda o: (o.current or o.estimate)["gap_bp"] <= -o.full_size_gap_bp)
    with make_client(tmp_path, f) as c:
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]

    ticks = [d for k, d in ev if k == "tick"]
    phases = [d["closed"]["session"]["phase"] for d in ticks]
    assert phases == ["regular", "regular", "after_hours", "overnight", "weekend", "weekend", "weekend",
                      "pre_market", "pre_market", "regular", "regular"]
    assert all(d["closed"]["hold"] == (ph != "regular") for d, ph in zip(ticks, phases))
    dec = [d for k, d in ev if k == "decision"]
    assert [d["action"] == "hold" and d["reason"] == "session_closed" for d in dec] == [ph != "regular" for ph in phases]
    assert all(d["qty"] == 0.0 and d["order_qty"] == 0.0 for d in dec if d["reason"] == "session_closed")
    fills = [d for k, d in ev if k == "fill"]
    assert [(x["side"], x["qty"], x["status"]) for x in fills] == [("sell", 100.0, "filled")]
    assert s["reasons"]["session_closed"] == 7 and s["closed_mode"]["holds"] == 7

    sat = ticks[4]["closed"]
    assert sat["closure"]["pm_move_pp"] == pytest.approx(10.0) and sat["closure"]["since"] == "2026-10-02T20:00:00Z"
    g = sat["expected_gap"]
    assert g["bp"] == pytest.approx(-10.0 * gapsvc.POOLED_RATE) and g["validated"] is False
    assert g["status"] == "unvalidated estimate" and g["n"] == 380 and g["band"][0] < g["bp"] < g["band"][1]
    assert sat["session"]["next_open"] == "2026-10-05T13:30:00Z"
    assert sat["session"]["next_premarket"] == "2026-10-05T08:00:00Z"

    assert len(orders) == 1
    o = orders[0]
    assert o["status"] == "filled" and o["clock"] == "replay" and o["qty"] == 400 and o["filled_qty"] == 400
    assert o["session_target"] == "pre_market" and o["executed_at"] == "2026-10-05T08:30:00Z"
    assert o["fill_px"] == pytest.approx(490.0, abs=0.5) and o["ref_source"] == "recorded"
    codes = [d["code"] for d in o["decisions"]]
    assert "AWAITING_APPROVAL" in codes and "APPROVED" in codes and "REPLAY_NEEDS_TICK_PRICE" in codes
    assert codes.index("APPROVED") < codes.index("SUBMITTED")
    assert o["estimate"]["validated"] is False and "unvalidated" in o["label"]
    assert o["evidence_gate"] == "override" and "OVERRIDE" in o["label"]
    assert "pre-market" in o["label"]

    assert s["broker_hedge"] == 500.0 and s["hedge"] == 500.0
    tl = [r["event"] for r in s["closed_mode"]["timeline"]]
    assert tl[0] == "close" and "plan" in tl and "staged_approved" in tl and "staged_filled" in tl and tl[-1] == "open"
    assert any(k == "handoff" for k, _ in ev)

    p = s["closed_mode"]["pnl"]
    assert p["s_close"] == 500.0 and p["s_now"] == 492.0 and p["unhedged_usd"] == pytest.approx(-8000.0)
    assert p["carried_hedge_shares"] == 100.0 and p["carried_hedge_usd"] == pytest.approx(800.0)
    assert p["staged_short_shares"] == 400.0
    assert p["staged_usd"] == pytest.approx(400 * (o["fill_px"] - 492.0))
    assert p["vs_no_hedge_usd"] == pytest.approx(p["carried_hedge_usd"] + p["staged_usd"])
    assert p["hedged_usd"] == pytest.approx(p["unhedged_usd"] + p["vs_no_hedge_usd"])
    assert s["hedge_a"]["enabled"] is False and s["session"]["phase"] == "regular"


def test_an_unapproved_plan_never_executes_and_follows_the_gap(tmp_path, fake_engine, research_rate):
    f = write_rows(tmp_path / "wk.jsonl")
    with make_client(tmp_path, f) as c:
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        ev = _events(c, bid)
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
        s = c.get(f"/bridges/{bid}").json()
    assert len(orders) == 1 and orders[0]["status"] == "staged" and orders[0]["filled_qty"] == 0
    o = orders[0]
    assert o["planned_qty"] < o["qty"] == 400
    assert "PM_RESIZE_UP" in [d["code"] for d in o["decisions"]]
    assert "RESIZE_UP_NEEDS_APPROVAL" not in [d["code"] for d in o["decisions"]]
    assert [x["qty"] for k, x in ev if k == "fill"] == [100.0] and s["broker_hedge"] == 100.0
    assert s["closed_mode"]["pnl"]["staged_short_shares"] == 0.0


def test_approval_names_the_quantity_the_user_saw(tmp_path, fake_engine, research_rate):
    f = write_rows(tmp_path / "wk.jsonl")
    with make_client(tmp_path, f) as c:
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        _events(c, bid)
        o = c.get(f"/staged?bridge_id={bid}").json()["orders"][0]
        assert o["status"] == "staged" and o["planned_qty"] < o["qty"] == 400
        r = c.post(f"/staged/{o['id']}/approve", json={"qty": o["planned_qty"]})
        assert r.status_code == 409 and "PLAN_CHANGED" in r.json()["detail"]
        assert c.get(f"/staged?bridge_id={bid}").json()["orders"][0]["status"] == "staged"
        r = c.post(f"/staged/{o['id']}/approve", json={"qty": 400})
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_qty"] == 400


def test_a_plan_made_elsewhere_for_the_proposal_is_adopted_not_superseded(tmp_path, fake_engine, research_rate,
                                                                         monkeypatch):
    f = write_rows(tmp_path / "wk.jsonl")
    made: list[str] = []
    orig = bridge_mode.ClosedMode._maybe_plan

    def maybe_plan(self, at):
        g = self.gap
        if not made and g is not None and g.active and g.expected_gap_bp is not None and g.expected_gap_bp <= -10:
            o = staged.plan_for(self.app, staged.PlanIn(bridge_id=self.bridge.id, pm_move_pp=self.state.move_pp),
                                self.app.state.store)
            o.status, o.approved_qty, o.approved_at = "approved", o.qty, staged._iso(at)
            made.append(o.id)
        return orig(self, at)
    monkeypatch.setattr(bridge_mode.ClosedMode, "_maybe_plan", maybe_plan)
    with make_client(tmp_path, f) as c:
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        _events(c, bid)
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
        s = c.get(f"/bridges/{bid}").json()
    assert made and [o["id"] for o in orders] == made
    assert orders[0]["status"] == "filled" and "SUPERSEDED" not in [d["code"] for d in orders[0]["decisions"]]
    tl = [r["event"] for r in s["closed_mode"]["timeline"]]
    assert "plan_adopted" in tl and "plan" not in tl


def test_session_hold_false_keeps_the_old_behaviour(tmp_path, fake_engine, research_rate):
    f = write_rows(tmp_path / "wk.jsonl")
    with make_client(tmp_path, f) as c:
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay", "session_hold": False}).json()[
            "bridge_id"]
        ev = _events(c, bid)
    assert [(x["side"], x["qty"]) for k, x in ev if k == "fill"] == [("sell", 100.0), ("sell", 50.0)]
    assert all(not d["closed"]["hold"] for k, d in ev if k == "tick")


def test_a_live_bridge_uses_the_wall_clock_and_seeds_the_close_from_history(tmp_path, fake_engine, research_rate):
    sat = dt.datetime(2026, 10, 3, 16, 0, tzinfo=dt.timezone.utc)
    close_s = int(dt.datetime(2026, 10, 2, 20, 0, tzinfo=dt.timezone.utc).timestamp())

    class Live:
        def __init__(self, mid, **kw):
            self.n = 0

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            from app.ticks import Tick
            for i in range(6):
                yield Tick(1_790_000_000_000_000_000 + i, 0.40)

    async def fetcher(source, token, start, end):
        return [(close_s - 600, 0.30), (close_s - 60, 0.31)]

    with make_client(tmp_path, None) as c:
        c.app.state.live_source_factory = Live
        c.app.state.staged_clock = lambda: sat
        c.app.state.closed_history_fetcher = fetcher
        pid = approved(c)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "live"}).json()["bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
    ticks = [d for k, d in ev if k == "tick"]
    assert all(d["closed"]["session"]["phase"] == "weekend" and d["closed"]["hold"] for d in ticks)
    assert ticks[-1]["closed"]["closure"]["pm_move_pp"] == pytest.approx(9.0)
    assert [x for k, x in ev if k == "fill"] == []
    assert s["closed_mode"]["holds"] == 6 and s["session"]["label"].startswith("Market closed")
    assert len(orders) == 1 and orders[0]["clock"] == "wall" and orders[0]["status"] == "staged"


def test_coverage_room_counts_resting_staged_sells_and_the_pm_leg(tmp_path):
    app = create_app()
    prop = app.state.store.approve(app.state.store.propose(
        ticker="SPY", family="hedge", strategy="s", shares_held=1000, target_coverage=0.5, basis="market_event",
        market=bridges.MarketRef(**MKT), direction="down_on_yes").id)
    b = bridges.Bridge(prop, "live", bridges.MarketRef(**MKT), 0.0)
    assert bridges._coverage_room(b) == 500
    b.app, b.broker_hedge = app, 100.0
    o = staged.StagedOrder(id="s1", status="working", proposal_id=prop.id, ticker="SPY", qty=150, planned_qty=150,
                           direction="down_on_yes", session_target="pre_market", execute_at="x", session_date="x",
                           shares_held=1000, target_coverage=0.5, estimate={}, sizing={}, planned_at="x",
                           client_order_id="c", filled_qty=30)
    staged.book_for(app).put(o)
    b.closed = SimpleNamespace(pm_leg_shares=lambda: 70.5)
    assert bridges._coverage_room(b) == pytest.approx(500 - 100 - 120 - 70.5)


EDB = {"family": "equity_delta_bridge", "params": {"sigma_k": 0.0, "fee_ratio": 0.5, "band_shares": 10.0}}


def _weekend_market():
    meta = json.loads(WEEKEND.with_name(WEEKEND.name + ".meta.json").read_text())
    return {"source": "polymarket", "id": meta["id"], "token_id": meta["token_id"]}, meta


def test_the_weekend_recording_is_the_rule_pick_with_its_sidecar_and_index():
    m, meta = _weekend_market()
    assert m["id"] == "516710" and m["token_id"] == RECESSION_TOKEN and meta["equity"] == "SPY"
    w = meta["weekend"]
    assert (w["closure"], w["open_day"], w["sign"]) == ("2025-04-04", "2025-04-07", -1)
    assert w["validated_oos"]["verdict"] == "Accurate out of sample"
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import csv

    import record_weekend
    pick = record_weekend.pick(evidence.load(), list(csv.DictReader(record_weekend.CLOSURES.open())))
    assert pick["slug"] == "us-recession-in-2025" and pick["row"]["closure"] == "2025-04-04"
    rows = [json.loads(x) for x in WEEKEND.read_text().splitlines()]
    t0 = dt.datetime.fromtimestamp(rows[0]["ts_ns"] / 1e9, ET)
    t1 = dt.datetime.fromtimestamp(rows[-1]["ts_ns"] / 1e9, ET)
    assert (t0.strftime("%a %H:%M"), t1.strftime("%a %H:%M")) == ("Fri 15:30", "Mon 10:00")
    assert all("under_px" in r for r in rows) and len(rows) == 799
    idx = json.loads((Path(bridges.__file__).parent / "data" / "replay_index.json").read_text())
    assert idx["polymarket:516710"] == WEEKEND.name and idx[f"token:{RECESSION_TOKEN}"] == WEEKEND.name


def test_a_bridge_on_the_recorded_weekend_shows_the_whole_closed_market_path(tmp_path, monkeypatch):
    pytest.importorskip("hedgecore")
    m, _ = _weekend_market()
    auto_approve(monkeypatch, lambda o: (o.current or o.estimate)["gap_bp"] <= -o.full_size_gap_bp)
    with make_client(tmp_path, WEEKEND, quotes=FakeQuotes(equity={"SPY": Quote(700.0, None, "today")})) as c:
        pid = approved(c, market=m, algo=EDB)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
    ticks = [d for k, d in ev if k == "tick"]
    assert len(ticks) == 799 and ticks[0]["closed"]["session"]["phase"] == "regular"
    gaps = [d["closed"]["expected_gap"] for d in ticks if d["closed"]["expected_gap"]["active"]]
    assert gaps and all(g["validated"] and g["status"] == "validated" and g["rate_source"] == "market" for g in gaps)
    assert all(g["n"] == 231 for g in gaps)
    peak = min(g["bp"] for g in gaps)
    assert peak == pytest.approx(-12.0 * 10.732000656751016)
    held = [d for k, d in ev if k == "decision" and d["reason"] == "session_closed"]
    assert held and all(d["action"] == "hold" and d["qty"] == 0.0 for d in held)
    filled = [o for o in orders if o["status"] == "filled"]
    assert len(filled) == 1
    o = filled[0]
    assert o["executed_at"] == "2025-04-07T08:05:05Z" and o["session_target"] == "pre_market"
    assert o["fill_px"] == pytest.approx(488.5, abs=0.2) and o["ref_source"] == "recorded"
    assert o["estimate"]["validated"] is True and o["evidence_gate"] == "validated"
    assert s["evidence_label"] == "validated" and "evidence: validated" in o["broker_order"]["note"]
    p = s["closed_mode"]["pnl"]
    assert p["s_close"] == 506.56 and p["s_now"] == 495.69 and p["unhedged_usd"] == pytest.approx(-10870.0)
    total_short = p["carried_hedge_shares"] + p["staged_short_shares"] + p["algo_short_shares"]
    assert p["carried_hedge_shares"] + p["staged_short_shares"] <= 500
    assert total_short == pytest.approx(s["broker_hedge"])
    assert p["vs_no_hedge_usd"] == pytest.approx(p["carried_hedge_usd"] + p["staged_usd"] + p["algo_usd"])
    algo_fills = [x for k, x in ev if k == "fill" and x["status"] == "filled"]
    assert algo_fills and all(x["fill_px"] == pytest.approx(700.0, abs=1.0) for x in algo_fills)
    assert p["algo_short_shares"] < 0 and p["algo_usd"] == pytest.approx(p["algo_short_shares"] * (489.21 - 495.69))
    assert s["closed_mode"]["last_expected_gap"]["bp"] == pytest.approx(-7.5 * 10.732000656751016, rel=0.2)


def test_hedge_a_is_an_opt_in_estimate_that_unwinds_at_the_open_inside_the_combined_cap(tmp_path, monkeypatch):
    pytest.importorskip("hedgecore")
    m, _ = _weekend_market()
    auto_approve(monkeypatch, lambda o: True)
    with make_client(tmp_path, WEEKEND, quotes=NullQuotes()) as c:
        pid = approved(c, market=m, algo=EDB, hedge_a=True)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
    legs = [d for k, d in ev if k == "hedge_a"]
    assert legs and all(d["simulated"] and d["estimate"] and d["instrument"] == "pred_yes" for d in legs)
    ha = s["hedge_a"]
    assert ha["enabled"] and ha["estimate"] and "not protection" in ha["label"].lower()
    assert ha["rate_bp_per_pp"] == pytest.approx(10.732000656751016) and ha["rate_source"] == "market"
    assert legs[-1]["reason"] == "handoff" and ha["contracts"] == 0.0
    peak_equiv = max(d["summary"]["sim_equity_equiv_shares"] for d in legs)
    assert peak_equiv > 0
    assert all(d["summary"]["equity_equiv_shares"] == 0.0 and d["summary"]["counts_toward_cap"] is False for d in legs)
    plans = [o for o in orders if o["status"] in ("filled", "staged", "approved", "cancelled")]
    assert plans and all(o["pm_leg_equiv_shares"] == 0 for o in plans)
    p = s["closed_mode"]["pnl"]
    assert p["hedge_a_estimate"] is True and p["hedge_a_usd"] == pytest.approx(ha["pnl_usd"])


def test_hedge_a_never_changes_the_real_staged_order(tmp_path, monkeypatch):
    pytest.importorskip("hedgecore")
    m, _ = _weekend_market()
    auto_approve(monkeypatch, lambda o: True)
    qty = {}
    for flag in (False, True):
        with make_client(tmp_path / str(flag), WEEKEND, quotes=NullQuotes()) as c:
            pid = approved(c, market=m, algo=EDB, hedge_a=flag)
            bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
            ev = _events(c, bid)
            orders = c.get(f"/staged?bridge_id={bid}").json()["orders"]
        assert any(k == "hedge_a" for k, _ in ev) is flag
        qty[flag] = [(o["status"], o["filled_qty"]) for o in orders if o["filled_qty"] > 0]
    assert qty[False] and qty[True] == qty[False]


def test_without_the_opt_in_no_pm_leg_is_ever_simulated(tmp_path):
    pytest.importorskip("hedgecore")
    m, _ = _weekend_market()
    with make_client(tmp_path, WEEKEND, quotes=NullQuotes()) as c:
        pid = approved(c, market=m, algo=EDB)
        bid = c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).json()["bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
    assert not any(k == "hedge_a" for k, _ in ev) and s["hedge_a"]["enabled"] is False


def test_the_default_demo_replay_trades_only_in_regular_hours(tmp_path):
    pytest.importorskip("hedgecore")
    f = REPLAYS / "another-fed-hike-2026-history.jsonl"
    meta = json.loads(f.with_name(f.name + ".meta.json").read_text())
    m = {"source": "polymarket", "id": meta["id"], "token_id": meta["token_id"]}
    with make_client(tmp_path, f, quotes=FakeQuotes(equity={"TLT": Quote(77.5, None, "q")})) as c:
        p = c.post("/proposals", json={"ticker": "TLT", "market": m, "direction": "down_on_yes", "shares_held": 1000,
                                       "target_coverage": 0.5,
                                       "algo": {"family": "equity_delta_bridge", "preset_index": 75}}).json()
        c.post(f"/proposals/{p['id']}/approve", json={"ack_unvalidated": True})
        bid = c.post("/bridges", json={"proposal_id": p["id"], "source": "replay", "replay_to_account": True}).json()[
            "bridge_id"]
        ev = _events(c, bid)
        s = c.get(f"/bridges/{bid}").json()
        assert c.get(f"/staged?bridge_id={bid}").json()["orders"] == []
    assert s["orders"] == s["broker_filled"] == 3 and s["broker_hedge"] == 360
    assert s["reasons"]["session_closed"] == 328
    phase = None
    for k, d in ev:
        if k == "tick":
            phase = d["closed"]["session"]["phase"]
        elif k == "fill":
            assert phase == "regular"
    closed = [d["closed"] for k, d in ev if k == "tick" and d["closed"]["session"]["closed"]]
    assert closed and all(not c["expected_gap"]["active"] and c["closure"]["status"] == "NO_CLOSE_PRICE"
                          for c in closed)
    assert all(c["expected_gap"]["status"] == "unvalidated estimate" for c in closed)


def test_generic_fit_needs_the_acknowledgement_even_on_a_validated_market(tmp_path):
    rec = {"source": "polymarket", "id": "516710", "token_id": RECESSION_TOKEN}
    with make_client(tmp_path, None) as c:
        def propose(source):
            r = c.post("/proposals", json={"ticker": "SPY", "market": rec, "direction": "down_on_yes", "shares_held": 1000,
                                           "target_coverage": 0.5, "algo": {**EDB, "source": source}})
            assert r.status_code == 201, r.text
            assert r.json()["evidence"]["validated"] is True
            return r.json()["id"]

        pid = propose("ai_fit")
        r = c.post(f"/proposals/{pid}/approve")
        assert r.status_code == 409 and "GENERIC_FIT_UNVALIDATED" in r.json()["detail"]
        assert "ack_unvalidated" in r.json()["detail"] and "walk-forward" in r.json()["detail"]
        r = c.post(f"/proposals/{pid}/approve", json={"ack_unvalidated": True})
        assert r.status_code == 200 and r.json()["ack_unvalidated"] is True
        uid = propose("user")
        r = c.post(f"/proposals/{uid}/approve")
        assert r.status_code == 200 and r.json()["ack_unvalidated"] is False


def test_bridge_start_refuses_a_generic_fit_proposal_approved_without_ack(tmp_path):
    rec = {"source": "polymarket", "id": "516710", "token_id": RECESSION_TOKEN}
    with make_client(tmp_path, WEEKEND) as c:
        r = c.post("/proposals", json={"ticker": "SPY", "market": rec, "direction": "down_on_yes", "shares_held": 1000,
                                       "target_coverage": 0.5, "algo": {**EDB, "source": "ai_fit"}})
        pid = r.json()["id"]
        from app.routes import _store
        req = type("R", (), {"app": c.app})()
        _store(req).approve(pid, ack_unvalidated=False)
        b = c.post("/bridges", json={"proposal_id": pid, "source": "replay", "market": rec})
        assert b.status_code == 409 and "GENERIC_FIT_UNVALIDATED" in b.json()["detail"], b.text
