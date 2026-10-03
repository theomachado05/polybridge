"""The real compiled hedgecore: bridges running Algo, the orientation contract, and real replay_grid scoring.
Engine group only (skipped without the module)."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

hedgecore = pytest.importorskip("hedgecore")

from app.broker import SimBroker  # noqa: E402
from app.broker.quotes import Quote  # noqa: E402
from app.pipeline import service  # noqa: E402
from app.pipeline.engine_adapter import EngineAdapter, normalize_manifest, preset_grid  # noqa: E402
from app.pipeline.ticks import assemble, orient_to_adverse  # noqa: E402
from app.ticks import mid_only_fields  # noqa: E402
from tests.test_bridges import _events, client, replay_file  # noqa: E402,F401
from tests.test_broker_support import FakeQuotes  # noqa: E402

FED = {"source": "polymarket", "id": "2589813", "token_id": "tokYES"}


def real_families() -> dict:
    return {f["id"]: f for f in normalize_manifest(hedgecore.catalog())["families"]}


def test_engine_catalog_matches_the_committed_manifest():
    from app.pipeline.engine_adapter import ENGINE_MANIFEST
    committed = json.loads(ENGINE_MANIFEST.read_text())
    live = hedgecore.catalog()
    assert live["total"] == committed["total"] == 1278
    assert [f["id"] for f in live["families"]] == [f["id"] for f in committed["families"]]
    a = EngineAdapter()
    assert a.can_score and a.library()[1] == "engine"


def test_replay_grid_preset_order_matches_preset_grid():
    """preset_index from replay_grid is the same grid point the backend resolves for a bridge."""
    fams = real_families()
    n = 60
    ticks = assemble([(1_790_000_000 + 60 * i, 0.2 + 0.3 * (i % 10) / 10) for i in range(n)],
                     [(1_789_999_000, 500.0)])
    for fid in ("equity_delta_bridge", "macro_fed_hedge", "crypto_reg_hedge"):
        rows = hedgecore.replay_grid(fid, {"shares_held": 1000.0}, ticks)
        grid = preset_grid(fams[fid])
        assert len(rows) == len(grid) == fams[fid]["preset_count"]
        for r in rows[:: max(1, len(rows) // 7)]:
            assert r["params"] == grid[r["preset_index"]]


def _tick_seq(n=40):
    out = []
    for i in range(n):
        p = 0.2 + 0.5 * ((i * 7) % 13) / 13
        f = mid_only_fields(p)
        f["yes_bid"], f["yes_ask"] = p - 0.01, p + 0.01
        f["no_bid"], f["no_ask"] = 1 - (p + 0.01), 1 - (p - 0.01)
        for k in range(5):
            f[f"bid_px_{k}"], f[f"bid_qty_{k}"] = p - 0.01 - 0.01 * k, 100.0 + 50 * k
            f[f"ask_px_{k}"], f[f"ask_qty_{k}"] = p + 0.01 + 0.01 * k, 300.0 - 40 * k
        f["under_px"], f["under_bid"], f["under_ask"] = 100.0 - i * 0.1, 99.99 - i * 0.1, 100.01 - i * 0.1
        f["p_other_venue"] = p + 0.02
        out.append(f)
    return out


@pytest.mark.parametrize("family", ["equity_delta_bridge", "book_imbalance_hedge", "stress_lead_hedge",
                                    "macro_fed_hedge", "fig_stress"])
def test_python_orientation_equals_the_engine_flip_for_hedge_families(family):
    """The one orientation (orient_to_adverse) gives exactly what hedgecore's own up_on_yes flip gives, so a
    bridge feeding oriented ticks to Algo(direction='down_on_yes') is the engine's up_on_yes behaviour."""
    pos = {"shares_held": 1000.0}
    flipped = hedgecore.Algo(family, {}, pos, direction="up_on_yes")
    oriented = hedgecore.Algo(family, {}, pos)
    t0 = 1_790_000_000_000_000_000
    for i, f in enumerate(_tick_seq()):
        ts = t0 + i * 500_000_000
        a = flipped.on_tick({**f, "ts_ns": ts}, ts)
        b = oriented.on_tick({**orient_to_adverse(f, "up_on_yes"), "ts_ns": ts}, ts)
        assert (a["action"], a["reason"], a["side"], a["qty"]) == (b["action"], b["reason"], b["side"], b["qty"]), i
        if a["action"] == "order":
            px = f["under_px"]
            flipped.on_fill("equity", a["qty"] * a["side"], px)
            oriented.on_fill("equity", b["qty"] * b["side"], px)


def test_engine_refuses_up_on_yes_for_non_hedge_families():
    with pytest.raises(ValueError):
        hedgecore.Algo("no_bid_seller", {}, {}, direction="up_on_yes")


def test_real_algo_bridge_on_replay_orders_fills_and_reports(client, tmp_path):
    """Replay with recorded SPY bars (under_px) -> the real equity_delta_bridge hedges; every order reaches the
    broker, fills go back through on_fill, and the reported hedge is what the broker filled."""
    client.app.state.replay_path = str(client.app.state.replay_path)
    client.app.state.broker = SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")}))
    # a replay whose original timestamps fall inside the recorded SPY bars
    f = tmp_path / "fed.jsonl"
    ps = [0.20, 0.20, 0.35, 0.35, 0.50, 0.50, 0.65, 0.65, 0.40, 0.40, 0.25, 0.25]
    f.write_text("".join(json.dumps({"ts_ns": (1_790_000_000 + 3600 * i) * 1_000_000_000, "p": p}) + "\n"
                         for i, p in enumerate(ps)))
    client.app.state.replay_path = str(f)
    pid = client.post("/proposals", json={"ticker": "SPY", "market": FED, "direction": "down_on_yes",
                                          "shares_held": 1000, "algo": {"family": "equity_delta_bridge",
                                                                         "params": {"sigma_k": 0.0, "fee_ratio": 0.5,
                                                                                    "band_shares": 10.0}}}).json()["id"]
    client.post(f"/proposals/{pid}/approve")
    r = client.post("/bridges", json={"proposal_id": pid, "source": "replay", "replay_to_account": True})
    assert r.status_code == 201, r.text
    ev = _events(client, r.json()["bridge_id"])
    decisions = [d for k, d in ev if k == "decision"]
    assert len(decisions) == len(ps)
    reasons = {d["reason"] for d in decisions}
    assert reasons <= set(v["name"] for v in hedgecore.catalog()["reasons"].values())
    orders = [d for d in decisions if d["action"] == "order"]
    fills = [d for k, d in ev if k == "fill"]
    assert orders and len(fills) == len(orders)
    assert all(fl["status"] == "filled" for fl in fills)
    assert orders[0]["side"] == "sell" and orders[0]["family"] == "equity_delta_bridge" and orders[0]["preset"] is None
    s = client.get(f"/bridges/{r.json()['bridge_id']}").json()
    assert s["engine"] == "algo" and s["hedge"] == s["broker_hedge"] and s["hedge"] > 0
    assert s["status"] == "finished" and s["latency_ns"]["p50"] is not None


def test_pipeline_fit_scores_with_the_real_engine():
    """POST /pipeline/fit with the compiled library: a real replay score, and the preset it names resolves to the
    params replay_grid scored."""
    from tests.test_pipeline import N_POINTS, T0, FakeMassive, Router, history, make_client

    class WigglyMassive(FakeMassive):
        """Hourly closes that move by different amounts (a straight line has zero variance: no score defined)."""
        def get_all(self, path, params=None, max_pages=500):
            if "/range/1/hour/" in path:
                return [{"t": (T0 - 1800 + 3600 * i) * 1000, "c": 500.0 - 3 * ((i * 5) % 7) + 0.1 * i}
                        for i in range(N_POINTS)]
            return []

    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES"]'})
    c = make_client(module=hedgecore, router=r, massive=WigglyMassive())
    j = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": "2589813"}, "ticker": "SPY",
                                      "shares_held": 1000}).json()
    assert j["event_class"] == "macro_fed" and j["division"] == "hedge" and j["ticks_source"] == "live_history"
    assert j["score"] is not None and math.isfinite(j["score"])
    fam = real_families()[j["family"]]
    assert preset_grid(fam)[j["preset_index"]] == j["params"]
    assert c.get("/library").json()["source"] == "engine"
