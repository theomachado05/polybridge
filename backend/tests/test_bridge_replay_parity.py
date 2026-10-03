"""A bridge on a replay makes the same decisions as the engine for the same preset (docs/contracts.md, "Bridge vs
engine replay"). Engine group only for the parity tests; the replay clock tests need no engine.

Pinned on the default demo recording (Another Fed hike 2026 -> TLT, equity_delta_bridge #75, 1,000 shares, approved
at 50% coverage): the bridge places 3 orders, and so does the engine replay once its fills are not refused. The
engine replay's own count (11 orders, 9 of them rejected) differs only because its fill model refuses an equity fill
at a stale recorded close (outside regular hours, or in a session before a new bar), and the algo re-sends the
refused order on the next tick; the SimBroker fills a market order at today's quote whenever it arrives."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest

from app.ticks import TICK_FIELDS, ReplaySource
from tests.test_bridges import _events, client, replay_file  # noqa: F401

REPLAYS = Path(__file__).resolve().parents[1] / "replays"
FED_REPLAY = REPLAYS / "another-fed-hike-2026-history.jsonl"
SHARES, COVERAGE, FAMILY, PRESET = 1000.0, 0.5, "equity_delta_bridge", 75


# --- replay clock (no engine) -------------------------------------------------------------------------------------

def test_a_slow_consumer_never_makes_replayed_ticks_stale(tmp_path):
    """The bridge awaits the broker between ticks. A replayed tick is stamped when it is handed over, never at its
    schedule slot in the past: the backend's own processing time is not data age, so the engine's 2 s staleness gate
    (measured against the wall clock) never holds a replay tick because an earlier order was slow."""
    f = tmp_path / "hourly.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_790_000_000_000_000_000 + i * 3_600_000_000_000, "p": 0.3}) + "\n"
                         for i in range(6)))

    async def go():
        ages, stamps = [], []
        async for t in ReplaySource(f, speed=360_000):  # 1 h -> 10 ms
            ages.append(time.time_ns() - t[0])
            stamps.append(t[0])
            await asyncio.sleep(0.15)  # a broker round trip 15x longer than the replay gap
        return ages, stamps
    ages, stamps = asyncio.run(go())
    assert len(ages) == 6
    assert max(ages) < 60_000_000, ages  # was ~0.75 s by the last tick (the lag accumulated)
    assert all(b > a for a, b in zip(stamps, stamps[1:]))  # still strictly increasing
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 9_000_000 for g in gaps)  # recorded gaps are never shortened below gap / speed


def test_an_on_time_replay_keeps_the_recorded_spacing(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_000 + i * 20_000_000_000, "p": 0.2}) + "\n" for i in range(4)))

    async def go():
        return [t[0] async for t in ReplaySource(f, speed=1000)]  # 20 s -> 20 ms
    st = asyncio.run(go())
    gaps = [b - a for a, b in zip(st, st[1:])]
    assert all(18_000_000 <= g <= 60_000_000 for g in gaps), gaps


# --- parity with the engine (compiled hedgecore) -------------------------------------------------------------------

def _replay_fields(path: Path) -> tuple[list[int], list[dict]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    src = ReplaySource(path, speed=0)
    return [int(r["ts_ns"]) for r in rows], [src.fields_for(r, float(r["p"])) for r in rows]


def _capped_params(hc) -> dict:
    from app.pipeline.engine_adapter import cap_coverage, normalize_manifest, preset_grid
    fam = next(f for f in normalize_manifest(hc.catalog())["families"] if f["id"] == FAMILY)
    params, lowered = cap_coverage(preset_grid(fam)[PRESET], COVERAGE)
    assert lowered == {"coverage": 0.75}  # preset #75 hedges 75%; the approval caps it at 50%
    return params


def _engine_decisions(hc, params: dict) -> list[tuple]:
    """hedgecore.Algo stepped on tick time (now = the recorded ts, as hedgecore.replay does), every order filled at
    the recorded under_px: what the engine decides when the broker fills each order on arrival."""
    from app.bridges import engine_tick
    from app.pipeline.ticks import orient_to_adverse
    algo = hc.Algo(FAMILY, dict(params), {"shares_held": SHARES})
    out = []
    for ts, f in zip(*_replay_fields(FED_REPLAY)):
        i = algo.on_tick(engine_tick(orient_to_adverse(f, "down_on_yes"), ts, 0), ts)
        order = i["action"] == "order"
        if order:
            algo.on_fill("equity", float(i["qty"]) * int(i["side"]), f["under_px"])
        out.append((i["reason"], i["action"], ("buy" if int(i["side"]) > 0 else "sell") if order else None,
                    float(i["qty"]) if order else 0.0))
    return out


def _array_ticks(quote_half_spread: float | None = None) -> dict:
    ts, fields = _replay_fields(FED_REPLAY)
    t = {k: np.array([f[k] for f in fields], dtype=float) for k in TICK_FIELDS}
    t["ts_ns"], t["venue"] = np.array(ts, dtype=np.int64), np.zeros(len(ts), dtype=np.int64)
    if quote_half_spread is not None:
        t["under_bid"], t["under_ask"] = t["under_px"] - quote_half_spread, t["under_px"] + quote_half_spread
    return t


def test_engine_replay_order_count_differs_only_by_refused_stale_close_fills():
    """The engine replay's 11 orders are 2 fills + 9 refused sends; give every tick a tradable quote (half spread =
    the fee model's default, so the fee gate prices the same cost) and it places exactly the bridge's 3 orders."""
    hc = pytest.importorskip("hedgecore")
    params = _capped_params(hc)
    pos = {"shares_held": SHARES}
    own = hc.replay(FAMILY, params, pos, _array_ticks())
    assert (own["n_orders"], own["n_fills"], own["n_rejected"]) == (11, 2, 9)
    fillable = hc.replay(FAMILY, params, pos, _array_ticks(quote_half_spread=0.01))
    assert (fillable["n_orders"], fillable["n_fills"], fillable["n_rejected"]) == (3, 3, 0)
    ref = _engine_decisions(hc, params)
    assert sum(1 for r in ref if r[1] == "order") == 3


def test_bridge_on_the_demo_replay_decides_exactly_like_the_engine(client, tmp_path):  # noqa: F811
    """POST /bridges on the default demo recording (SimBroker, today's quote): every one of the 401 decisions equals
    the engine's for the same preset and fills (reason, action, side, qty), and 361 ticks are held by the sigma gate
    in both. The bridge's wall-clock timestamps at replay speed change nothing."""
    hc = pytest.importorskip("hedgecore")
    from app.broker import SimBroker
    from app.broker.quotes import Quote
    from tests.test_broker_support import FakeQuotes
    meta = json.loads(FED_REPLAY.with_name(FED_REPLAY.name + ".meta.json").read_text())
    market = {"source": "polymarket", "id": meta["id"], "token_id": meta["token_id"]}
    client.app.state.broker = SimBroker(tmp_path / "s.json", FakeQuotes(equity={"TLT": Quote(77.5, None, "q")}))
    client.app.state.replay_path = str(FED_REPLAY)
    client.app.state.replay_speed = 1e9  # wall-clock stamping, as in the demo, without waiting
    prop = client.post("/proposals", json={"ticker": "TLT", "market": market, "direction": "down_on_yes",
                                           "shares_held": SHARES, "target_coverage": COVERAGE,
                                           "algo": {"family": FAMILY, "preset_index": PRESET}}).json()
    client.post(f"/proposals/{prop['id']}/approve")
    # session_hold False: this contract is the engine's decisions when every order fills, at any hour (closed-market
    # mode would hold the off-session intents; see tests/test_closed_bridge.py)
    r = client.post("/bridges", json={"proposal_id": prop["id"], "source": "replay", "replay_to_account": True,
                                      "session_hold": False})
    assert r.status_code == 201, r.text
    ev = _events(client, r.json()["bridge_id"])
    got = [(d["reason"], d["action"], d["side"], float(d["qty"] or 0.0)) for k, d in ev if k == "decision"]
    want = _engine_decisions(hc, _capped_params(hc))
    assert len(got) == len(want) == 401
    assert got == want
    s = client.get(f"/bridges/{r.json()['bridge_id']}").json()
    assert s["orders"] == s["broker_filled"] == 3 and s["broker_rejects"] == 0
    assert s["reasons"] == {"rebalance": 3, "inside_band": 37, "below_sigma": 361}
    assert s["broker_hedge"] == 378 + 65 - 55


def test_slow_broker_does_not_turn_replay_ticks_stale(client, tmp_path):  # noqa: F811
    """A broker that takes longer than the engine's 2 s staleness window to price the first order: the replayed
    ticks after it are still fresh (never held as 'stale'), so the decisions stay the engine's."""
    hc = pytest.importorskip("hedgecore")
    from app.broker import SimBroker
    from app.broker.quotes import Quote
    from tests.test_bridges import write_meta
    from tests.test_bridges_algo_engine import FED

    class SlowQuotes:
        def __init__(self):
            self.slow = True

        async def equity(self, symbol):
            if self.slow:
                self.slow = False
                await asyncio.sleep(2.3)
            return Quote(500.0, None, "q")

        async def option(self, symbol):
            return None

    client.app.state.broker = SimBroker(tmp_path / "s.json", SlowQuotes())
    f = tmp_path / "fed.jsonl"
    ps = [0.20, 0.20, 0.35, 0.35, 0.50, 0.50, 0.65, 0.65, 0.40, 0.40, 0.25, 0.25]
    f.write_text("".join(json.dumps({"ts_ns": (1_790_000_000 + 3600 * i) * 1_000_000_000, "p": p,
                                     "under_px": 500.0 + i}) + "\n" for i, p in enumerate(ps)))
    client.app.state.replay_path = str(f)
    client.app.state.replay_speed = 36_000  # 1 h -> 0.1 s: the 2.3 s stall spans ~23 recorded hours
    write_meta(f, FED)
    pid = client.post("/proposals", json={"ticker": "SPY", "market": FED, "direction": "down_on_yes",
                                          "shares_held": 1000, "algo": {"family": "equity_delta_bridge",
                                                                         "params": {"sigma_k": 0.0, "fee_ratio": 0.5,
                                                                                    "band_shares": 10.0}}}).json()["id"]
    client.post(f"/proposals/{pid}/approve")
    r = client.post("/bridges", json={"proposal_id": pid, "source": "replay", "replay_to_account": True})
    ev = _events(client, r.json()["bridge_id"])
    reasons = [d["reason"] for k, d in ev if k == "decision"]
    assert len(reasons) == len(ps)
    assert "stale" not in reasons, reasons


# --- Russia/EU -> ITA order counts quoted in docs/demo.md ----------------------------------------------------------

ITA_REPLAY = REPLAYS / "russia-eu-military-2026-history.jsonl"
DEMO_MD = Path(__file__).resolve().parents[2] / "docs" / "demo.md"


def _ita_bridge_orders(hc, shares: float, coverage: float) -> int:
    """hedgecore.Algo (energy_geo_hedge #54, up on YES) stepped over the Russia/EU recording with every order filled,
    which is what a replay bridge does (the SimBroker fills each order on arrival)."""
    from app.bridges import engine_tick
    from app.pipeline.engine_adapter import cap_coverage, normalize_manifest, preset_grid
    from app.pipeline.ticks import orient_to_adverse
    fam = next(f for f in normalize_manifest(hc.catalog())["families"] if f["id"] == "energy_geo_hedge")
    params, _ = cap_coverage(preset_grid(fam)[54], coverage)
    algo = hc.Algo("energy_geo_hedge", dict(params), {"shares_held": shares})
    n = 0
    for ts, f in zip(*_replay_fields(ITA_REPLAY)):
        i = algo.on_tick(engine_tick(orient_to_adverse(f, "up_on_yes"), ts, 0), ts)
        if i["action"] == "order":
            n += 1
            algo.on_fill("equity", float(i["qty"]) * int(i["side"]), f["under_px"])
    return n


def test_ita_bridge_order_count_in_demo_doc_matches_the_ui_share_count():
    """ITA is not held, so the UI sizes the bridge (and the fit) at 500 shares; the demo doc's order count must be the
    500-share one (17 uncapped), with 31 only at 1,000 shares (backend/replays/README.md)."""
    hc = pytest.importorskip("hedgecore")
    assert _ita_bridge_orders(hc, 500.0, 1.0) == 17
    assert _ita_bridge_orders(hc, 1000.0, 1.0) == 31
    assert _ita_bridge_orders(hc, 1000.0, 0.5) == 17
    doc = DEMO_MD.read_text()
    # The doc quotes the closed-market-mode default (equity algo held outside regular hours) and the any-hour counts.
    assert "9 orders uncapped at 1,000 shares and 5 at a 50% cap or at the 500 shares the UI sizes" in doc
    assert "it would be 31 and 17" in doc
