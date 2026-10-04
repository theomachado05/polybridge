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


def test_a_slow_consumer_never_makes_replayed_ticks_stale(tmp_path):
    f = tmp_path / "hourly.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_790_000_000_000_000_000 + i * 3_600_000_000_000, "p": 0.3}) + "\n"
                         for i in range(6)))

    async def go():
        ages, stamps = [], []
        async for t in ReplaySource(f, speed=360_000):
            ages.append(time.time_ns() - t[0])
            stamps.append(t[0])
            await asyncio.sleep(0.15)
        return ages, stamps
    ages, stamps = asyncio.run(go())
    assert len(ages) == 6
    assert max(ages) < 60_000_000, ages
    assert all(b > a for a, b in zip(stamps, stamps[1:]))
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 9_000_000 for g in gaps)


def test_an_on_time_replay_keeps_the_recorded_spacing(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text("".join(json.dumps({"ts_ns": 1_000 + i * 20_000_000_000, "p": 0.2}) + "\n" for i in range(4)))

    async def go():
        return [t[0] async for t in ReplaySource(f, speed=1000)]
    st = asyncio.run(go())
    gaps = [b - a for a, b in zip(st, st[1:])]
    assert all(18_000_000 <= g <= 60_000_000 for g in gaps), gaps


def _replay_fields(path: Path) -> tuple[list[int], list[dict]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    src = ReplaySource(path, speed=0)
    return [int(r["ts_ns"]) for r in rows], [src.fields_for(r, float(r["p"])) for r in rows]


def _capped_params(hc) -> dict:
    from app.pipeline.engine_adapter import cap_coverage, normalize_manifest, preset_grid
    fam = next(f for f in normalize_manifest(hc.catalog())["families"] if f["id"] == FAMILY)
    params, lowered = cap_coverage(preset_grid(fam)[PRESET], COVERAGE)
    assert lowered == {"coverage": 0.75}
    return params


def _engine_decisions(hc, params: dict) -> list[tuple]:
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
    hc = pytest.importorskip("hedgecore")
    from app.broker import SimBroker
    from app.broker.quotes import Quote
    from tests.test_broker_support import FakeQuotes
    meta = json.loads(FED_REPLAY.with_name(FED_REPLAY.name + ".meta.json").read_text())
    market = {"source": "polymarket", "id": meta["id"], "token_id": meta["token_id"]}
    client.app.state.broker = SimBroker(tmp_path / "s.json", FakeQuotes(equity={"TLT": Quote(77.5, None, "q")}))
    client.app.state.replay_path = str(FED_REPLAY)
    client.app.state.replay_speed = 1e9
    prop = client.post("/proposals", json={"ticker": "TLT", "market": market, "direction": "down_on_yes",
                                           "shares_held": SHARES, "target_coverage": COVERAGE,
                                           "algo": {"family": FAMILY, "preset_index": PRESET}}).json()
    client.post(f"/proposals/{prop['id']}/approve", json={"ack_unvalidated": True})
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
    client.app.state.replay_speed = 36_000
    write_meta(f, FED)
    pid = client.post("/proposals", json={"ticker": "SPY", "market": FED, "direction": "down_on_yes",
                                          "shares_held": 1000, "algo": {"family": "equity_delta_bridge",
                                                                         "params": {"sigma_k": 0.0, "fee_ratio": 0.5,
                                                                                    "band_shares": 10.0}}}).json()["id"]
    client.post(f"/proposals/{pid}/approve", json={"ack_unvalidated": True})
    r = client.post("/bridges", json={"proposal_id": pid, "source": "replay", "replay_to_account": True})
    ev = _events(client, r.json()["bridge_id"])
    reasons = [d["reason"] for k, d in ev if k == "decision"]
    assert len(reasons) == len(ps)
    assert "stale" not in reasons, reasons


ITA_REPLAY = REPLAYS / "russia-eu-military-2026-history.jsonl"
DEMO_MD = Path(__file__).resolve().parents[2] / "docs" / "demo.md"


def _ita_bridge_orders(hc, shares: float, coverage: float) -> int:
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
    hc = pytest.importorskip("hedgecore")
    assert _ita_bridge_orders(hc, 500.0, 1.0) == 17
    assert _ita_bridge_orders(hc, 1000.0, 1.0) == 31
    assert _ita_bridge_orders(hc, 1000.0, 0.5) == 17
    doc = DEMO_MD.read_text()
    assert "9 orders uncapped at 1,000 shares and 5 at a 50% cap or at the 500 shares the UI sizes" in doc
    assert "it would be 31 and 17" in doc
