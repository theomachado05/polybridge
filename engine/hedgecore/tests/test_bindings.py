import hedgecore


def test_round_trip_matches_cpp_semantics():
    spec = hedgecore.HedgeSpec(ticker="ABNB", shares_held=1000, target_coverage=0.5, band_shares=10)
    eng = hedgecore.Engine(spec)
    d = eng.on_tick(ts_ns=1_000_000_000, p=0.2, now_ns=1_000_000_000)
    assert (d.action, d.reason, d.order_qty, d.target_hedge) == ("order", "rebalance", 100.0, 100.0)
    eng.on_fill(100)
    assert eng.current_hedge == 100.0
    d = eng.on_tick(ts_ns=2_000_000_000, p=0.21, now_ns=2_000_000_000)
    assert (d.action, d.reason) == ("hold", "inside_band")


def test_stale_tick_holds():
    eng = hedgecore.Engine(hedgecore.HedgeSpec(ticker="X", shares_held=10))
    assert eng.on_tick(ts_ns=0, p=0.5, now_ns=10_000_000_000).reason == "stale"


def test_nan_fill_latches_invalid():
    eng = hedgecore.Engine(hedgecore.HedgeSpec(ticker="X", shares_held=1000, target_coverage=0.5, band_shares=10))
    eng.on_fill(float("nan"))
    assert eng.current_hedge == 0.0
    d = eng.on_tick(ts_ns=1_000_000_000, p=0.2, now_ns=1_000_000_000)
    assert (d.action, d.reason) == ("hold", "invalid")
    assert d.order_qty == 0.0


def test_fee_gate_fields_and_reason():
    spec = hedgecore.HedgeSpec(ticker="X", shares_held=1000, band_shares=0, gap_per_share=1.0, half_spread=0.01)
    assert (spec.gap_per_share, spec.fee_per_share, spec.half_spread, spec.min_benefit_ratio) == (1.0, 0.0035, 0.01, 1.0)
    eng = hedgecore.Engine(spec)
    assert eng.on_tick(ts_ns=1_000_000_000, p=0.2, now_ns=1_000_000_000).action == "order"
    eng.on_fill(100)
    d = eng.on_tick(ts_ns=2_000_000_000, p=0.21, now_ns=2_000_000_000)
    assert (d.action, d.reason) == ("hold", "below_fees")


# ---- v4 algo library ----
import math

import numpy as np
import pytest


def test_catalog_shape_and_honest_total():
    cat = hedgecore.catalog()
    assert cat["n_families"] == 16
    assert cat["total"] == sum(f["preset_count"] for f in cat["families"]) == 1287
    ids = [f["id"] for f in cat["families"]]
    assert ids[:8] == ["equity_delta_bridge", "stress_lead_hedge", "book_imbalance_hedge", "poly_kalshi_spread",
                       "no_bid_seller", "fig_stress", "housing_rates", "macro_fed_hedge"]
    edb = cat["families"][0]
    assert edb["division"] == "hedge"
    assert "macro_fed" in edb["event_classes"]
    assert {b["kind"] for b in edb["blocks"]} >= {"signals", "gates", "sizers", "execution", "risk", "tax"}
    assert set(edb["ui_kinds"]) <= {"Gate", "Reader", "Impact", "Execution", "Tax", "Routing"}
    n = 1
    for p in edb["params"]:
        assert p["min"] <= p["default"] <= p["max"]
        assert edb["grid"][p["name"]] == p["grid"]
        n *= len(p["grid"])
    assert n == edb["preset_count"] == 144
    assert cat["block_kinds"]["sizers"] == "Impact"
    assert cat["reasons"][str(0x0601)]["name"] == "wash_sale"


def test_algo_on_tick_matches_cpp_semantics():
    a = hedgecore.Algo("equity_delta_bridge", {"coverage": 0.5}, {"shares_held": 1000})
    assert a.family == "equity_delta_bridge"
    assert a.params["coverage"] == 0.5
    tick = {"ts_ns": 1_000_000_000, "yes_bid": 0.195, "yes_ask": 0.205,
            "under_px": 100.0, "under_bid": 99.99, "under_ask": 100.01}
    d = a.on_tick(tick)
    assert (d["action"], d["instrument"], d["side"], d["qty"], d["reason"]) == ("order", "equity", -1, 100.0, "rebalance")
    assert d["limit_px"] is None and d["reason_block"] == "sizers" and d["latency_ns"] >= 0
    a.on_fill("equity", -100, 99.99)
    d = a.on_tick({**tick, "ts_ns": 2_000_000_000, "yes_bid": 0.205, "yes_ask": 0.215})
    assert (d["action"], d["reason"]) == ("hold", "inside_band")


def test_algo_missing_fields_are_nan_not_zero_and_stale():
    a = hedgecore.Algo("equity_delta_bridge", {}, {"shares_held": 1000})
    assert a.on_tick({"ts_ns": 1, "yes_bid": None})["reason"] == "signal_missing"
    assert a.on_tick({"ts_ns": 0, "yes_bid": 0.4, "yes_ask": 0.42}, now_ns=10_000_000_000)["reason"] == "stale"


def test_algo_direction_up_on_yes_flips_the_book():
    tick = {"ts_ns": 1, "yes_bid": 0.795, "yes_ask": 0.805, "under_px": 100.0, "under_bid": 99.99, "under_ask": 100.01}
    a = hedgecore.Algo("equity_delta_bridge", {}, {"shares_held": 1000}, direction="up_on_yes")
    assert a.on_tick(tick)["qty"] == 100.0  # adverse prob = 1 - 0.8


def test_algo_rejects_unknown_names():
    with pytest.raises(ValueError):
        hedgecore.Algo("nope")
    with pytest.raises(KeyError):
        hedgecore.Algo("equity_delta_bridge", {"not_a_param": 1.0})
    with pytest.raises(KeyError):
        hedgecore.Algo("equity_delta_bridge", {}, {"cash": 1.0})


def _ticks(n=300):
    rng = np.random.default_rng(7)
    p = np.clip(0.2 + np.cumsum(rng.normal(0.001, 0.005, n)), 0.05, 0.95)
    u = 100 * np.cumprod(1 - 0.5 * np.diff(p, prepend=p[0]))
    return {
        "ts_ns": (np.arange(n, dtype=np.int64) + 1) * 1_000_000_000,
        "yes_bid": p - 0.005, "yes_ask": p + 0.005,
        "under_px": u, "under_bid": u - 0.01, "under_ask": u + 0.01,
        "bid_px_0": p - 0.005, "bid_qty_0": np.full(n, 500.0),
        "ask_px_0": p + 0.005, "ask_qty_0": np.full(n, 500.0),
    }


def test_replay_returns_stats_dict():
    s = hedgecore.replay("equity_delta_bridge", {"coverage": 1.0, "sigma_k": 0.0, "impact": 0.0},
                         {"shares_held": 1000}, _ticks())
    assert s["n_ticks"] == 300 and s["n_fills"] > 0
    assert s["hedge_var_reduction"] is not None and s["hedge_var_reduction"] > 0
    assert s["p99_ns"] >= s["p50_ns"] >= 0
    assert s["params"]["coverage"] == 1.0
    assert set(s) >= {"n_ticks", "n_orders", "pnl", "fees", "max_dd", "hedge_var_reduction", "turnover",
                      "p50_ns", "p99_ns"}


def test_replay_without_underlying_has_no_var_reduction():
    t = _ticks()
    for k in ("under_px", "under_bid", "under_ask"):
        del t[k]
    s = hedgecore.replay("equity_delta_bridge", {}, {"shares_held": 1000}, t)
    assert s["hedge_var_reduction"] is None and s["n_fills"] == 0


def test_replay_grid_covers_every_preset_deterministically():
    t = _ticks()
    g1 = hedgecore.replay_grid("macro_fed_hedge", {"shares_held": 1000}, t)
    g2 = hedgecore.replay_grid("macro_fed_hedge", {"shares_held": 1000}, t)
    assert [r["preset_index"] for r in g1] == list(range(72))
    assert len({tuple(sorted(r["params"].items())) for r in g1}) == 72
    for a, b in zip(g1, g2):
        assert (a["pnl"], a["n_fills"], a["turnover"]) == (b["pnl"], b["n_fills"], b["turnover"])


def test_committed_manifest_matches_compiled_catalog():
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).resolve().parent.parent / "manifest.json").read_text())
    assert manifest == json.loads(json.dumps(hedgecore.catalog()))


def test_replay_rejects_ragged_ticks():
    t = _ticks()
    t["yes_bid"] = t["yes_bid"][:-1]
    with pytest.raises(ValueError):
        hedgecore.replay("equity_delta_bridge", {}, {"shares_held": 1}, t)
    assert math.isfinite(hedgecore.replay("equity_delta_bridge", {}, {"shares_held": 1}, _ticks())["pnl"])
