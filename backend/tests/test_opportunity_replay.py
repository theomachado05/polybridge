"""The Opportunity division on a real recording: "Will NVIDIA (NVDA) close above $230 end of September?" (Polymarket
3961215, resolved NO), recorded with options-implied history by ``scripts/history_with_equity.py --options``.

Pins the recording (sidecar, replay index, the no-look-ahead rules its option rows follow), the fit on it (the
compiled engine scores binary_vs_spread_arb from the recorded option columns, offline) and an approved opportunity
bridge on it (multi-leg call-spread orders through the SimBroker, priced at the recorded leg closes because no
current chain lists the expired contracts, inside the approved max_contracts / max_notional caps). The numbers are
in-sample replay estimates on one market; the score is negative (backend/replays/README.md, docs/demo.md). The
recording ends with the expiry settlement (each leg at intrinsic from NVDA's official close), so the last spread is
marked and closed at what it was worth, not at its 15:00 bar closes."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pytest

from app import bridges
from app.markets import offline_search, recorded_file
from app.pipeline import service
from app.pipeline.options_join import session_fresh_mask, us_session
from app.pipeline.ticks import available_requirements, build_ticks, recording_meta, replay_points, replay_rows

REPLAYS = Path(__file__).resolve().parents[1] / "replays"
DATA = Path(__file__).resolve().parents[1] / "app" / "data"
NAME = "nvda-230-sep-2026-history.jsonl"
NVDA_REPLAY = REPLAYS / NAME
MARKET_ID = "3961215"
TOKEN = "19137250086147356524889435600121720329083521006343492236589155785492743914975"
MKT = {"source": "polymarket", "id": MARKET_ID, "token_id": TOKEN}
QUESTION = "Will NVIDIA (NVDA) close above $230 end of September?"
LEGS = ("O:NVDA260930C00227500", "O:NVDA260930C00232500")
N_ROWS, N_OPT = 353, 66
BINARY_SCORE = -0.95570  # binary_vs_spread_arb preset #6: 11 orders, -$276.15 net of fees, max drawdown $288.95
SETTLE_CLOSE = 228.38  # NVDA's official close on 2026-09-30 (Massive /v1/open-close): the spread settled at 0.88


def _rows() -> list[dict]:
    return [json.loads(line) for line in NVDA_REPLAY.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- the recording (no engine)

def test_recording_sidecar_and_index_name_the_market():
    assert NVDA_REPLAY.is_file() and NVDA_REPLAY.stat().st_size < 64_000  # small enough to ship
    meta = json.loads(NVDA_REPLAY.with_name(NAME + ".meta.json").read_text())
    assert {k: meta[k] for k in ("source", "id", "token_id", "question", "equity")} == {
        **MKT, "question": QUESTION, "equity": "NVDA"}
    assert meta["end_date"] == "2026-09-30T20:00:00Z" and meta["rows"] == N_ROWS
    o = meta["options"]
    assert (o["underlying"], o["kind"], o["expiry"], o["k_lo"], o["k_hi"], o["direction"]) == (
        "NVDA", "call_spread", "2026-09-30", 227.5, 232.5, "above")
    assert [(lg["sign"], lg["ticker"]) for lg in o["legs"]] == [(1, LEGS[0]), (-1, LEGS[1])]
    assert bridges.replay_meta(NVDA_REPLAY) == MKT
    assert bridges.replay_option_structure(NVDA_REPLAY)["legs"][1]["strike"] == 232.5
    index = json.loads((DATA / "replay_index.json").read_text())
    assert index[f"polymarket:{MARKET_ID}"] == NAME and index[f"token:{TOKEN}"] == NAME
    pts, name = replay_points("polymarket", MARKET_ID)
    assert name == NAME and len(pts) == N_ROWS
    assert recording_meta("polymarket", MARKET_ID)["question"] == QUESTION
    # search: the recording is named on the market (a resolved market with one stays listable), offline too
    assert recorded_file("polymarket", MARKET_ID) == NAME
    hit = next(m for m in offline_search("nvidia 230 end of september") if m.id == MARKET_ID)
    assert hit.recorded == NAME and hit.token_id == TOKEN and hit.end_date == "2026-09-30T20:00:00Z"


def test_option_rows_follow_the_no_look_ahead_rules():
    rows = _rows()
    ts_s = np.array([r["ts_ns"] // 1_000_000_000 for r in rows])
    assert all(b > a for a, b in zip(ts_s, ts_s[1:]))
    opt = [r for r in rows if "opt_implied_prob" in r]
    assert len(opt) == N_OPT and all("under_px" in r for r in rows)
    # option fields only inside the regular session, and only where the two legs' closes are a fresh pair; the one
    # exception is the expiry settlement, after the close
    sess = us_session(ts_s)
    assert all(sess[i] for i, r in enumerate(rows) if "opt_mid" in r and "opt_settlement" not in r)
    for r in rows:
        assert ("opt_legs" in r) == ("opt_mid" in r)
    for r in opt:
        lo, hi = (r["opt_legs"][t] for t in LEGS)
        assert r["opt_mid"] == pytest.approx(lo - hi, abs=1e-6)  # the call spread C(227.5) - C(232.5)
        day = dt.datetime.fromtimestamp(r["ts_ns"] // 1_000_000_000, dt.timezone.utc).date()
        df = math.exp(-0.04 * max((dt.date(2026, 9, 30) - day).days, 0) / 365.0)
        assert r["opt_implied_prob"] == pytest.approx(min(max(r["opt_mid"] / 5.0 / df, 0.0), 1.0), abs=1e-5)
        assert 0.0 < r["opt_iv"] < 5.0
    # the PM and the options agree closely on this market: a 3-point typical gap, larger only on expiry day
    gaps = np.array([r["p"] - r["opt_implied_prob"] for r in opt])
    assert abs(float(np.median(gaps))) < 0.02 and float(np.max(np.abs(gaps))) < 0.15


def test_the_recording_ends_with_the_expiry_settlement():
    """The last row is after the 16:00 expiry close: it carries the spread's value at expiry (each leg at intrinsic
    from NVDA's official close), not a quote, so no family opens on it, the engine marks to it and a bridge closes at
    it. Without it the open spread was marked (engine) and closed (bridge) at the 15:00 closes, about $2 too high."""
    rows = _rows()
    settled = [r for r in rows if "opt_settlement" in r]
    assert settled == rows[-1:]
    last = rows[-1]
    at = dt.datetime.fromtimestamp(last["ts_ns"] // 1_000_000_000, dt.timezone.utc)
    assert at >= dt.datetime(2026, 9, 30, 20, 0, tzinfo=dt.timezone.utc) and not us_session(np.array([at.timestamp()]))[0]
    assert last["opt_settlement"]["underlying_close"] == SETTLE_CLOSE and last["opt_settlement"]["expiry"] == "2026-09-30"
    assert last["opt_legs"] == {LEGS[0]: pytest.approx(SETTLE_CLOSE - 227.5), LEGS[1]: 0.0}
    assert last["opt_mid"] == pytest.approx(0.88) and "opt_implied_prob" not in last and "opt_iv" not in last
    meta = json.loads(NVDA_REPLAY.with_name(NAME + ".meta.json").read_text())
    assert meta["options"]["settlement"]["underlying_close"] == SETTLE_CLOSE
    assert meta["options"]["as_of"] == "2026-09-16"  # the listing as of the replay's own first day (point in time)
    assert bridges.replay_option_structure(NVDA_REPLAY)["settlement"]["underlying_close"] == SETTLE_CLOSE


def test_recorder_settles_rows_after_the_expiry_close_and_reads_the_listing_point_in_time():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import history_with_equity as hwe
    from app.pipeline.options_join import historical_structure
    st = {"expiry": "2026-09-30", "legs": [{"sign": 1, "ticker": "C1", "strike": 227.5, "kind": "call"},
                                            {"sign": -1, "ticker": "C2", "strike": 232.5, "kind": "call"}]}
    close_s = int(dt.datetime(2026, 9, 30, 20, 0, tzinfo=dt.timezone.utc).timestamp())  # 16:00 New York (EDT)
    rows = [{"ts_ns": (close_s - 3600) * 10**9, "p": 0.6, "opt_mid": 2.9, "opt_implied_prob": 0.58,
             "opt_legs": {"C1": 3.0, "C2": 0.1}},
            {"ts_ns": close_s * 10**9, "p": 0.01, "opt_implied_prob": 0.5}]
    assert hwe.settle_rows(rows, st, 234.0, "test") == 1
    assert rows[0]["opt_mid"] == 2.9 and "opt_settlement" not in rows[0]  # before the close: untouched
    assert rows[1]["opt_legs"] == {"C1": 6.5, "C2": 1.5} and rows[1]["opt_mid"] == 5.0
    assert "opt_implied_prob" not in rows[1] and rows[1]["opt_settlement"]["underlying_close"] == 234.0
    put = {"expiry": "2026-09-30", "legs": [{"sign": 1, "ticker": "P1", "strike": 232.5, "kind": "put"}]}
    r = [{"ts_ns": close_s * 10**9, "p": 0.5}]
    hwe.settle_rows(r, put, 230.0, "test")
    assert r[0]["opt_legs"] == {"P1": 2.5}

    class Listing:
        seen: list[dict] = []

        def get_all(self, path, params, max_pages=5):
            self.seen.append(params)
            return [{"expiration_date": "2026-09-30", "strike_price": k, "ticker": f"O:NVDA260930C{int(k * 1000):08d}"}
                    for k in (225.0, 227.5, 230.0, 232.5, 235.0)]
    c = Listing()
    got = historical_structure(c, "NVDA", 230.0, dt.date(2026, 9, 30), above=True, as_of=dt.date(2026, 9, 16))
    assert got["k_lo"] == 227.5 and got["k_hi"] == 232.5
    assert c.seen and all(p["as_of"] == "2026-09-16" for p in c.seen)  # only contracts listed on as_of


def test_session_fresh_mask_needs_both_legs_printed_in_the_session():
    day = dt.datetime(2026, 9, 17, tzinfo=dt.timezone.utc)  # a Thursday; 13:30 UTC = 09:30 New York (EDT)
    at = lambda h, m=0: int((day + dt.timedelta(hours=h, minutes=m)).timestamp())  # noqa: E731
    ts = np.array([at(13, 45), at(14, 30), at(19, 30), at(21, 0), at(14, 30) + 86400])
    prev = [(at(20) - 86400, 1.0)]                      # yesterday's 16:00 close
    fresh = [(at(14), 1.1), (at(19), 1.2)]              # bars that ended at 10:00 and 15:00 today
    assert us_session(ts).tolist() == [True, True, True, False, True]
    m = session_fresh_mask(ts, [prev + fresh, prev + fresh])
    assert m.tolist() == [False, True, True, False, False]  # before the first print, in session, after the close, next day
    assert not session_fresh_mask(ts, [prev + fresh, prev]).any()  # one leg has not printed today


def test_fit_ticks_from_the_recording_carry_its_option_columns():
    ts = asyncio.run(build_ticks(MKT, "NVDA", http=None, massive=None, offline=True))
    assert ts.source == "replay" and ts.n == N_ROWS and ts.has_underlying
    assert int(np.isfinite(ts.ticks["opt_implied_prob"]).sum()) == N_OPT
    assert "listed_options" in available_requirements(ts)
    other = asyncio.run(build_ticks(MKT, "AMD", http=None, massive=None, offline=True))  # no recorded AMD bars
    assert not other.has_underlying  # the recording's NVDA closes are never handed to another ticker
    rows, _ = replay_rows("polymarket", MARKET_ID)
    assert rows[0]["t"] == rows[0]["ts_ns"] // 1_000_000_000


def test_live_history_without_options_falls_back_to_the_recording(monkeypatch):
    """Online, the live CLOB history of a resolved market has no option history (its contracts expired, so today's
    chain cannot price it): the fit replays the recording, which carries it."""
    from app.pipeline.ticks import TickSet, assemble
    from tests.test_pipeline import fake_hedgecore
    from app.pipeline.engine_adapter import EngineAdapter
    real_build = service.build_ticks
    seen = []

    async def build(market, ticker, *, http=None, massive=None, offline=False, **kw):
        seen.append(offline)
        if offline:
            return await real_build(market, ticker, http=None, massive=None, offline=True)
        pts = [(1_789_600_000 + 3600 * i, 0.3) for i in range(30)]
        return TickSet(assemble(pts), "live_history", len(pts), False)

    async def no_options(t, question, end_date, **kw):
        return t, {"available": False, "notes": ["options: question not mapped (no resolution date (or it has passed))"]}
    monkeypatch.setattr(service, "build_ticks", build)
    monkeypatch.setattr(service, "join_options", no_options)
    deps = service.Deps(adapter=EngineAdapter(module=fake_hedgecore()))
    req = service.FitRequest(market={"source": "polymarket", "id": MARKET_ID}, question=QUESTION, ticker="NVDA",
                             division="opportunity")
    r = asyncio.run(service.run_fit(req, deps))
    assert seen == [False, True] and r["ticks_source"] == "replay" and r["n_ticks"] == N_ROWS
    assert r["division"] == "opportunity"


# ---------------------------------------------------------------- the engine (compiled hedgecore)

def test_fit_on_the_recording_scores_binary_vs_spread_arb():
    pytest.importorskip("hedgecore")
    from app.pipeline.engine_adapter import EngineAdapter
    deps = service.Deps(adapter=EngineAdapter(), offline=True)  # no network: question, end date, ticks recorded
    req = service.FitRequest(market={"source": "polymarket", "id": MARKET_ID}, ticker="NVDA", division="opportunity",
                             shares_held=0)
    r = asyncio.run(service.run_fit(req, deps))
    assert r["division"] == "opportunity" and r["ticks_source"] == "replay" and r["n_ticks"] == N_ROWS
    assert r["score_basis"] == "net_pnl_per_drawdown" and r["scored"]
    cands = [{"family": r["family"], "preset_index": r["preset_index"], "score": r["score"]}] + r["alternatives"]
    arb = next(c for c in cands if c["family"] == "binary_vs_spread_arb")
    assert arb["preset_index"] == 6 and arb["score"] == pytest.approx(BINARY_SCORE, abs=1e-4)
    assert arb["stats"]["n_orders"] == 11 and arb["stats"]["pnl"] == pytest.approx(-276.15, abs=0.01)
    assert arb["stats"]["max_dd"] == pytest.approx(288.95, abs=0.01)
    # The top opportunity pick is a prediction-market family (no_bid_seller, PM-only fills at the recorded mid,
    # spread unknown); a bridge runs only options families, so the UI offers the binary_vs_spread_arb alternative.
    assert r["family"] == "no_bid_seller"


@pytest.fixture
def nvda_client():
    pytest.importorskip("hedgecore")
    from fastapi.testclient import TestClient
    from app.broker import SimBroker
    from app.main import create_app
    from app.ticks import OptionsEnricher
    app = create_app()
    app.state.replay_speed = 0
    app.state.broker = SimBroker(None)
    # the real enricher: the question's resolution date has passed, so it finds no live chain (no network needed)
    app.state.options_enricher_factory = lambda market: OptionsEnricher(QUESTION, "2026-09-30T20:00:00Z")
    with TestClient(app) as c:
        yield c


def _opp_bridge(c, preset: int, **caps) -> tuple[str, list, dict]:
    from tests.test_bridges import _events
    r = c.post("/proposals", json={"ticker": "NVDA", "market": MKT, "division": "opportunity",
                                   "algo": {"family": "binary_vs_spread_arb", "preset_index": preset}, **caps})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert c.post("/bridges", json={"proposal_id": pid, "source": "replay"}).status_code == 409  # not approved yet
    assert c.post(f"/proposals/{pid}/approve", json={"ack_unvalidated": True}).status_code == 200
    r = c.post("/bridges", json={"proposal_id": pid, "source": "replay"})
    assert r.status_code == 201, r.text
    bid = r.json()["bridge_id"]
    ev = _events(c, bid)
    return pid, ev, c.get(f"/bridges/{bid}").json()


def test_opportunity_bridge_places_multi_leg_option_orders_on_the_recording(nvda_client):
    c = nvda_client
    pid, ev, s = _opp_bridge(c, 6)  # the fit's binary_vs_spread_arb preset: 1 spread per entry
    decisions = [d for k, d in ev if k == "decision"]
    assert len(decisions) == N_ROWS and {d["family"] for d in decisions} == {"binary_vs_spread_arb"}
    assert s["reasons"] == {"signal_missing": 287, "no_signal": 55, "entry": 6, "exit": 5}  # the engine's 11 orders
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["status"], f["qty"]) for f in fills] == [("filled", 1.0)] * 12
    assert [f["side"] for f in fills] == ["buy", "sell", "sell", "buy", "sell", "buy", "sell", "buy", "buy", "sell",
                                          "buy", "sell"]
    assert [f.get("close_reason") for f in fills] == [None] * 11 + ["bridge_end"]
    entry = fills[0]
    assert entry["structure"] == "call_spread" and entry["simulated"] and entry["price_source"] == "recorded"
    assert "recorded leg closes" in entry["price_note"] and entry["broker"] == "sim-replay"
    assert [(lg["ticker"], lg["side"], lg["quote_mid"], lg["price_source"]) for lg in entry["legs"]] == [
        (LEGS[0], "buy", 1.94, "recorded"), (LEGS[1], "sell", 0.7, "recorded")]
    # each leg at its recorded close +/- the sim's default 2% half-spread; the structure price is the signed sum
    assert entry["legs"][0]["fill_px"] == pytest.approx(1.9788) and entry["legs"][1]["fill_px"] == pytest.approx(0.686)
    assert entry["fill_px"] == pytest.approx(1.2928) and entry["fee"] == pytest.approx(2 * 0.65)
    assert entry["unit_risk"] == pytest.approx(129.28) and entry["unit_risk"] <= 10_000
    # the last spread (bought at 15:00 on expiry day) is closed at the recorded expiry settlement: NVDA closed at
    # 228.38, so C(227.5) is worth 0.88 and C(232.5) nothing; no spread on a settlement value
    close = fills[-1]
    assert "expiry settlement" in close["price_note"] and close["settlement"]["underlying_close"] == SETTLE_CLOSE
    assert [(lg["ticker"], lg["side"], lg["fill_px"]) for lg in close["legs"]] == [
        (LEGS[0], "sell", 0.88), (LEGS[1], "buy", bridges.SETTLE_MIN_PX)]
    net = -sum((1 if f["side"] == "buy" else -1) * f["qty"] * f["fill_px"] * 100 + f["fee"] for f in fills)
    assert net == pytest.approx(-294.77, abs=0.01)  # six round trips, simulated, net of $0.65 per leg contract
    assert s["option_position"] == 0 and s["option_structure"] is None and s["risk_used"] == 0
    assert s["broker_filled"] == 12 and s["recorded_option_fills"] == 12 and s["option_data"] == "recorded"
    assert s["options_detail"]["source"] == "recording" and s["options_detail"]["k_lo"] == 227.5
    assert s["replay_file"] == NAME and s["max_contracts"] == 10 and s["max_notional"] == 10_000
    gaps = [d["options"]["gap"] for k, d in ev if k == "tick" and d["options"]["gap"] is not None]
    assert len(gaps) == N_OPT  # the Bridge screen's PM-vs-options gap, on every tick the recording priced
    sandbox = c.app.state.bridges[pid].replay_broker
    orders = asyncio.run(sandbox.orders())
    assert len(orders) == 24 and {o.price_source for o in orders} == {"recorded"}  # 12 combos x 2 legs
    assert asyncio.run(sandbox.positions()) == []  # the bridge-end close flattened both legs


def test_preset_9_bridge_closes_its_expiry_day_spread_at_the_settlement(nvda_client):
    """#9 (entry gap 0.05; the fit's pick before the settlement was recorded): 3 orders, the last a spread bought
    at 2.95 an hour before the close, which settles at 0.88: about $210 of the $250 loss."""
    _, ev, s = _opp_bridge(nvda_client, 9)
    assert s["reasons"] == {"signal_missing": 287, "no_signal": 63, "entry": 2, "exit": 1}
    fills = [d for k, d in ev if k == "fill"]
    assert [(f["status"], f["side"], f.get("close_reason")) for f in fills] == [
        ("filled", "buy", None), ("filled", "sell", None), ("filled", "buy", None), ("filled", "sell", "bridge_end")]
    assert fills[-1]["fill_px"] == pytest.approx(0.88 - bridges.SETTLE_MIN_PX)
    net = -sum((1 if f["side"] == "buy" else -1) * f["qty"] * f["fill_px"] * 100 + f["fee"] for f in fills)
    assert net == pytest.approx(-249.75, abs=0.01)


def test_option_orders_stay_inside_the_approved_caps(nvda_client):
    c = nvda_client
    _, ev, s = _opp_bridge(c, 11, max_contracts=3)  # preset #11 asks for 10 spreads per entry
    fills = [d for k, d in ev if k == "fill"]
    assert fills[0]["qty"] == 3 and fills[0]["status"] == "filled"  # the approval already capped the entry size
    assert max(abs(d["option_position"]) for k, d in ev if k == "position") <= 3
    _, ev, s = _opp_bridge(c, 11, max_notional=500)  # $312.88 at risk per spread -> 1 fits in $500
    fills = [d for k, d in ev if k == "fill"]
    assert fills[0]["qty"] == 1 and fills[0]["capped_from"] == 10 and fills[0]["cap"] == "max_notional"
    assert max(d["risk_used"] for k, d in ev if k == "position") <= 500
    assert s["option_position"] == 0


def test_offline_options_route_names_the_recorded_question():
    """Wi-Fi off: the Opportunity card's GET /options/implied still knows the question (from the recording's
    sidecar), so its reason is the real one (the market resolved), not "market not found"."""
    import httpx
    from app.options.router import resolve_market

    def down(request):
        raise httpx.ConnectError("offline")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
            return await resolve_market(http, "polymarket", MARKET_ID)
    m = asyncio.run(go())
    assert m["origin"] == "recording" and m["question"] == QUESTION and m["end_date"] == "2026-09-30T20:00:00Z"
