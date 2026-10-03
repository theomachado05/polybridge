"""Hedge tuning ranks presets by hedge_var_reduction_vs_static (the engine's variance cut beyond a static short of the
same average size), so a preset that merely shorts the most -- a static hedge -- never wins on hedge size alone."""
import math

import numpy as np
import pytest

from app.pipeline.engine_adapter import EngineAdapter
from app.pipeline.ticks import TickSet
from app.pipeline.tune import NO_STATIC_BENCHMARK, STAT_KEYS, score_row, tune
from app.ticks import TICK_FIELDS

N = 120
NAN = float("nan")


def _ticks(n=N, seed=3):
    rng = np.random.default_rng(seed)
    p = np.clip(0.3 + np.cumsum(rng.normal(0, 0.01, n)), 0.02, 0.98)
    u = 100 + np.cumsum(rng.normal(0, 0.5, n))
    t = {k: np.full(n, np.nan) for k in TICK_FIELDS}
    t.update(yes_bid=p - 0.005, yes_ask=p + 0.005, under_px=u, under_bid=u - 0.01, under_ask=u + 0.01,
             ts_ns=(1_790_000_000 + 3600 * np.arange(n)) * 1_000_000_000, venue=np.zeros(n))
    return t


def _row(i, raw, h, n_orders=3):
    """A replay row as the engine reports it: vs_static = 1 - var(hedged) / ((1 - h)^2 var(unhedged))
    = 1 - (1 - raw) / (1 - h)^2, NaN when h == 1."""
    vs = 1.0 - (1.0 - raw) / (1.0 - h) ** 2 if abs(1.0 - h) > 1e-9 else NAN
    return {"preset_index": i, "params": {"k": float(i)}, "n_orders": n_orders, "hedge_var_reduction": raw,
            "hedge_var_reduction_vs_static": vs, "avg_hedge_ratio": h, "pnl": 0.0, "max_dd": 0.0}


class _Adapter(EngineAdapter):
    def __init__(self, rows):
        self._module, self.rows = None, rows

    @property
    def can_score(self):
        return True

    def replay_grid(self, family_id, position, ticks):
        return [dict(r) for r in self.rows]


def _tune(rows, families=({"id": "fam"},)):
    return tune(_Adapter(rows), list(families), "hedge", {"shares_held": 1000.0}, TickSet(_ticks(), "replay", N, True))


def test_a_static_hedge_never_beats_a_signal_following_one():
    # #0: a static 90 % short. Its raw var reduction 1 - 0.1^2 = 0.99 is exactly what ANY static 0.9 short earns, so
    #     its vs-static gain is 0. #1: a half-size hedge that follows the PM signal: raw 0.80, where a static 0.5 short
    #     would give 0.75, so vs_static = 1 - 0.2 / 0.25 = +0.2. Ranking on raw would pick #0; the signal picks #1.
    static, signal = _row(0, 0.99, 0.9, n_orders=1), _row(1, 0.80, 0.5, n_orders=9)
    assert static["hedge_var_reduction_vs_static"] == pytest.approx(0.0, abs=1e-9)
    out = _tune([static, signal])
    assert out["scored"] and out["preset_index"] == 1
    assert out["score"] == pytest.approx(0.2) == out["score_vs_static"]
    assert out["score_raw"] == pytest.approx(0.80) and out["avg_hedge_ratio"] == pytest.approx(0.5)
    assert out["score_basis"] == "hedge_var_reduction_vs_static" and "static" in out["score_note"]
    alt = out["alternatives"][0]
    assert alt["preset_index"] == 0 and alt["score"] == pytest.approx(0.0, abs=1e-9)
    assert alt["stats"]["hedge_var_reduction"] == pytest.approx(0.99) and alt["stats"]["avg_hedge_ratio"] == 0.9


def test_a_bigger_static_short_does_not_win_across_families_either():
    """The full-size static short of one family vs a small timed hedge of another (rule order favours the first)."""
    class Two(_Adapter):
        def replay_grid(self, family_id, position, ticks):
            return [_row(0, 0.96, 0.8)] if family_id == "big_static" else [_row(0, 0.30, 0.1)]
    out = tune(Two([]), [{"id": "big_static"}, {"id": "timed"}], "hedge", {"shares_held": 1000.0},
               TickSet(_ticks(), "replay", N, True))
    # static 0.8: 1 - 0.04/0.04 = 0. timed: 1 - 0.7/0.81 = +0.136
    assert out["family"] == "timed" and out["score"] == pytest.approx(1 - 0.7 / 0.81)


def test_negative_gain_is_kept_honest_and_still_ranked():
    out = _tune([_row(0, 0.70, 0.5), _row(1, 0.60, 0.5)])  # both worse than a static 0.5 short (0.75)
    assert out["scored"] and out["preset_index"] == 0 and out["score"] == pytest.approx(1 - 0.3 / 0.25)
    assert out["score"] < 0


def test_nan_vs_static_is_not_ranked():
    # #0 is a full static short (h = 1: vs_static NaN, raw ~1.0): it must not be ranked at all, however high its raw.
    out = _tune([_row(0, 0.999, 1.0), _row(1, 0.40, 0.3)])
    assert out["scored"] and out["preset_index"] == 1
    assert [a["preset_index"] for a in out["alternatives"]] == []


def test_no_vs_static_anywhere_falls_back_to_rules_with_an_honest_reason():
    fams = [{"id": "fam", "params": [{"name": "k", "grid": [0.0, 1.0], "default": 0.0}]}]
    out = _tune([_row(0, 0.999, 1.0), _row(1, 0.99, 1.0)], fams)
    assert not out["scored"] and out["score"] is None and out["unscored_reason"] == NO_STATIC_BENCHMARK
    assert "score_vs_static" not in out and out["no_static_benchmark"] is True
    # An engine that does not report the benchmark at all (an older build) is not ranked on raw var reduction either.
    old = [{"preset_index": 0, "params": {}, "hedge_var_reduction": 0.95, "n_orders": 1}]
    out = _tune(old, fams)
    assert not out["scored"] and out["unscored_reason"] == NO_STATIC_BENCHMARK


def test_a_preset_that_never_hedges_is_unscored_not_zero():
    """'Do nothing' scores exactly 0 vs static; it must not win where every real hedge is worse than static."""
    idle = {**_row(0, 0.0, 0.0), "n_orders": 0}
    out = _tune([idle, _row(1, 0.70, 0.5)])
    assert out["scored"] and out["preset_index"] == 1 and out["score"] < 0
    assert out["alternatives"] == []
    fams = [{"id": "fam", "params": [{"name": "k", "grid": [0.0, 1.0], "default": 0.0}]}]
    out = _tune([idle, {**_row(1, 0.0, 0.0), "n_orders": 4}], fams)  # orders, but nothing ever filled / held
    assert not out["scored"] and "no preset held a hedge" in out["unscored_reason"]
    assert out["no_static_benchmark"] is False


def test_score_row_and_stat_keys():
    assert score_row({"hedge_var_reduction": 0.99, "hedge_var_reduction_vs_static": None}, "hedge") is None
    assert score_row({"hedge_var_reduction_vs_static": -0.1}, "hedge") == -0.1
    assert {"hedge_var_reduction", "hedge_var_reduction_vs_static", "avg_hedge_ratio"} <= set(STAT_KEYS)


def test_opportunity_fits_carry_no_hedge_fields():
    class Opp(_Adapter):
        def replay_grid(self, family_id, position, ticks):
            return [{"preset_index": 0, "params": {}, "n_orders": 4, "pnl": 10.0, "max_dd": 5.0}]
    out = tune(Opp([]), [{"id": "fam"}], "opportunity", {}, TickSet(_ticks(), "replay", N, True))
    assert out["score_basis"] == "net_pnl_per_drawdown" and out["score"] == pytest.approx(2.0)
    assert "score_raw" not in out and "avg_hedge_ratio" not in out


def test_real_engine_reports_the_static_benchmark_consistently():
    """The compiled replay's vs-static score obeys vs = 1 - (1 - raw) / (1 - h)^2 for every preset where it is
    defined, h is a fraction of shares_held, and tune ranks on it."""
    pytest.importorskip("hedgecore")
    ad = EngineAdapter()
    fams = {f["id"]: f for f in ad.library()[0]["families"]}
    if "macro_fed_hedge" not in fams:
        pytest.skip("catalog without macro_fed_hedge")
    t = _ticks(300)
    pos = {"shares_held": 1000.0, "equity": 0.0, "pred_yes": 0.0, "pred_no": 0.0, "option": 0.0}
    rows = ad.replay_grid("macro_fed_hedge", pos, t)
    assert rows and all("hedge_var_reduction_vs_static" in r and "avg_hedge_ratio" in r for r in rows)
    checked = 0
    for r in rows:
        raw, vs, h = r["hedge_var_reduction"], r["hedge_var_reduction_vs_static"], r["avg_hedge_ratio"]
        if raw is None or vs is None or h is None:
            continue
        assert math.isfinite(h) and -1e-9 <= h <= 1.0 + 1e-9
        assert vs == pytest.approx(1.0 - (1.0 - raw) / (1.0 - h) ** 2, rel=1e-6, abs=1e-9)
        checked += 1
    assert checked > 0
    out = tune(ad, [fams["macro_fed_hedge"]], "hedge", pos, TickSet(t, "replay", 300, True))
    best_vs = max(r["hedge_var_reduction_vs_static"] for r in rows if r["hedge_var_reduction_vs_static"] is not None)
    assert out["scored"] and out["score"] == pytest.approx(best_vs) and out["score_vs_static"] == out["score"]
