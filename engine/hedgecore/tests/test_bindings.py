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
