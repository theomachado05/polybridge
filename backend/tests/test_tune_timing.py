"""Hedge tuning ranks the best presets by their gain over a static hedge of the same average size, so the preset
that merely shorts the most no longer wins on hedge size alone."""
import math
import types

import numpy as np
import pytest

from app.pipeline.engine_adapter import EngineAdapter
from app.pipeline.ticks import TickSet
from app.pipeline.tune import mean_hedge_ratio, tune
from app.ticks import TICK_FIELDS

N = 120


def _ticks(n=N, seed=3):
    rng = np.random.default_rng(seed)
    p = np.clip(0.3 + np.cumsum(rng.normal(0, 0.01, n)), 0.02, 0.98)
    u = 100 + np.cumsum(rng.normal(0, 0.5, n))
    t = {k: np.full(n, np.nan) for k in TICK_FIELDS}
    t.update(yes_bid=p - 0.005, yes_ask=p + 0.005, under_px=u, under_bid=u - 0.01, under_ask=u + 0.01,
             ts_ns=(1_790_000_000 + 3600 * np.arange(n)) * 1_000_000_000, venue=np.zeros(n))
    return t


class StaticAlgo:
    """Shorts `size` x shares_held on the first tick and holds (any static hedge)."""

    def __init__(self, family, params, position):
        self.size, self.shares, self.done = params["size"], position["shares_held"], False

    def on_tick(self, tick, now_ns=None):
        if self.done:
            return {"action": "hold"}
        self.done = True
        return {"action": "order", "instrument": "equity", "side": -1, "qty": self.size * self.shares}

    def on_fill(self, inst, qty, px):
        pass

    def on_reject(self, inst):
        pass


def test_mean_hedge_ratio_of_a_static_short():
    mod = types.SimpleNamespace(Algo=StaticAlgo)
    h = mean_hedge_ratio(mod, "f", {"size": 0.5}, {"shares_held": 1000.0}, _ticks())
    assert h == pytest.approx(0.5)
    assert mean_hedge_ratio(types.SimpleNamespace(), "f", {}, {"shares_held": 1.0}, _ticks()) is None  # no Algo


class _Adapter(EngineAdapter):
    """Two presets: #0 a static full short (var reduction ~1.0), #1 a half-size hedge that times the move."""

    def __init__(self):
        self._module = types.SimpleNamespace(Algo=StaticAlgo)

    @property
    def can_score(self):
        return True

    def replay_grid(self, family_id, position, ticks):
        return [{"preset_index": 0, "params": {"size": 1.0}, "hedge_var_reduction": 0.999, "n_orders": 1},
                {"preset_index": 1, "params": {"size": 0.5}, "hedge_var_reduction": 0.90, "n_orders": 9}]


def test_the_biggest_short_no_longer_wins_on_size_alone():
    ts = TickSet(_ticks(), "replay", N, True)
    out = tune(_Adapter(), [{"id": "fam"}], "hedge", {"shares_held": 1000.0}, ts)
    # static at h = 0.5 would reduce variance by 1 - 0.5^2 = 0.75; 0.90 is a +0.15 timing gain. The full short's
    # 0.999 is only what any static full short gets (gain ~0).
    assert out["preset_index"] == 1 and out["score"] == 0.90
    alt = out["alternatives"][0]
    assert alt["preset_index"] == 0 and alt["stats"]["timing_gain"] == pytest.approx(-0.001, abs=1e-9)
    assert "same average size" in out["score_note"]


def test_without_a_benchmark_the_ranking_is_unchanged_and_says_so():
    class NoAlgo(_Adapter):
        def __init__(self):
            self._module = types.SimpleNamespace()
    out = tune(NoAlgo(), [{"id": "fam"}], "hedge", {"shares_held": 1000.0}, TickSet(_ticks(), "replay", N, True))
    assert out["preset_index"] == 0 and "ranks size as much as timing" in out["score_note"]


def test_real_engine_mean_hedge_ratio_is_a_fraction():
    hc = pytest.importorskip("hedgecore")
    ad = EngineAdapter()
    fams = {f["id"]: f for f in ad.library()[0]["families"]}
    if "macro_fed_hedge" not in fams:
        pytest.skip("catalog without macro_fed_hedge")
    t = _ticks(300)
    pos = {"shares_held": 1000.0, "equity": 0.0, "pred_yes": 0.0, "pred_no": 0.0, "option": 0.0}
    rows = ad.replay_grid("macro_fed_hedge", pos, t)
    best = max(rows, key=lambda r: r["hedge_var_reduction"] if r["hedge_var_reduction"] is not None else -1)
    h = mean_hedge_ratio(hc, "macro_fed_hedge", best["params"], pos, t)
    assert h is not None and 0.0 <= h <= 1.0 + 1e-9 and math.isfinite(h)
