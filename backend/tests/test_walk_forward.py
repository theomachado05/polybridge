"""Walk-forward split / purge logic (scripts/walk_forward_fits.py), offline with a fake engine: tune sees only the
train slice, the pick is replayed only on the test slice, and the purge ticks are never seen by either."""
import asyncio
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from app.pipeline.engine_adapter import EngineAdapter
from app.pipeline.ticks import MIN_TICKS, TickSet
from app.ticks import TICK_FIELDS

_path = Path(__file__).resolve().parents[1] / "scripts" / "walk_forward_fits.py"
_spec = importlib.util.spec_from_file_location("walk_forward_fits", _path)
wf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wf)


def _ticks(n, seed=0):
    rng = np.random.default_rng(seed)
    p = np.clip(0.3 + np.cumsum(rng.normal(0, 0.01, n)), 0.02, 0.98)
    u = 100 + np.cumsum(rng.normal(0, 0.5, n))
    t = {k: np.full(n, np.nan) for k in TICK_FIELDS}
    t.update(yes_bid=p, yes_ask=p, no_bid=1 - p, no_ask=1 - p, under_px=u,
             ts_ns=(1_790_000_000 + 3600 * np.arange(n)).astype(np.int64) * 1_000_000_000, venue=np.zeros(n))
    return t


@pytest.mark.parametrize("n,expect", [
    (100, (60, 5, 65)),     # ceil(5) = 5
    (721, (432, 37, 469)),  # floor(432.6), ceil(36.05)
    (44, (26, 3, 29)),      # ceil(2.2) = 3
    (20, (12, 2, 14)),      # min purge 2
    (0, (0, 2, 0)),
    (1, (0, 2, 1)),         # test_start clipped to n
])
def test_split_indices(n, expect):
    assert wf.split_indices(n) == expect


@pytest.mark.parametrize("n", [30, 44, 91, 164, 374, 721])
def test_split_is_a_partition_with_a_purge_gap(n):
    n_train, n_purge, start = wf.split_indices(n)
    train, purge, test = range(0, n_train), range(n_train, start), range(start, n)
    assert len(train) + len(purge) + len(test) == n
    assert len(purge) == max(2, math.ceil(0.05 * n)) and len(purge) >= 2
    assert set(train).isdisjoint(test) and max(train) + len(purge) + 1 == min(test)
    assert len(test) / n == pytest.approx(0.35, abs=0.06)


def test_split_tickset_slices_every_array_and_drops_the_purge():
    ts = TickSet(_ticks(100), "live_history", 100, True)
    train, test, info = wf.split_tickset(ts)
    assert (train.n, test.n, info["n_purge"]) == (60, 35, 5)
    for k, v in ts.ticks.items():
        assert np.array_equal(train.ticks[k], v[:60], equal_nan=True)
        assert np.array_equal(test.ticks[k], v[65:], equal_nan=True)
    assert test.ticks["ts_ns"][0] - train.ticks["ts_ns"][-1] == 6 * 3600 * 10**9  # 5 purged hourly ticks between
    train.ticks["under_px"][0] = -1.0  # copies: slicing never aliases the source history
    assert ts.ticks["under_px"][0] != -1.0


def test_split_tickset_excludes_short_or_equity_less_slices():
    short = TickSet(_ticks(25), "live_history", 25, True)  # train 15, purge 2, test 8 < MIN_TICKS
    assert wf.split_tickset(short)[0] is None and "< 10" in wf.split_tickset(short)[2]["reason"]
    t = _ticks(100)
    t["under_px"][65:] = np.nan  # no equity in the test slice
    _, _, info = wf.split_tickset(TickSet(t, "live_history", 100, True))
    assert info["reason"] == "no equity prices in the test slice"
    assert wf.split_tickset(TickSet(None, "none", 0))[2]["reason"] == "no price history"
    assert MIN_TICKS == 10


class FakeEngine(EngineAdapter):
    """Two presets. On the train window preset 1 wins (0.3 vs 0.1); every call records the ticks it saw."""

    def __init__(self, test_scores=(0.05, -0.02), train_scores=(0.1, 0.3)):
        self._module, self.calls = None, []
        self.train_scores, self.test_scores = train_scores, test_scores
        self._library = ({"event_classes": ["crypto", "unsupported"], "families": []}, "fallback")

    @property
    def can_score(self):
        return True

    def replay_grid(self, family_id, position, ticks):
        self.calls.append((family_id, ticks["ts_ns"].copy()))
        scores = self.train_scores if len(self.calls) == 1 else self.test_scores
        return [{"preset_index": i, "params": {"k": float(i)}, "n_orders": 5, "avg_hedge_ratio": 0.3,
                 "hedge_var_reduction": 0.5, "hedge_var_reduction_vs_static": s} for i, s in enumerate(scores)]


MANIFEST = {"event_classes": ["crypto", "unsupported"],
            "families": [{"id": "crypto_reg_hedge", "divisions": ["hedge"], "division": "hedge",
                          "event_classes": ["crypto"], "params": [{"name": "k", "grid": [0.0, 1.0], "default": 0.0}],
                          "preset_count": 2, "requires": [], "generic": False}]}


def _run(engine, n=100):
    ts = TickSet(_ticks(n), "live_history", n, True)
    q = "Will the SEC approve a spot Solana ETF?"
    return asyncio.run(wf.evaluate_market(engine, MANIFEST, q, "COIN", "down_on_yes", ts)), ts


def test_tune_sees_only_train_and_the_pick_is_replayed_only_on_test():
    eng = FakeEngine()
    r, ts = _run(eng)
    (f1, seen_train), (f2, seen_test) = eng.calls
    assert f1 == f2 == "crypto_reg_hedge"
    assert np.array_equal(seen_train, ts.ticks["ts_ns"][:60])
    assert np.array_equal(seen_test, ts.ticks["ts_ns"][65:])
    purged = set(ts.ticks["ts_ns"][60:65].tolist())
    assert purged.isdisjoint(seen_train.tolist()) and purged.isdisjoint(seen_test.tolist())
    assert r["status"] == "tested" and r["event_class"] == "crypto"
    assert r["preset_index"] == 1 and r["train_vs_static"] == pytest.approx(0.3)  # picked on train
    assert r["test_vs_static"] == pytest.approx(-0.02)  # the SAME preset on test, not the test winner (0.05)
    assert r["default_preset_index"] == 0 and r["default_test_vs_static"] == pytest.approx(0.05)
    assert r["test_best_vs_static"] == pytest.approx(0.05)


def test_never_hedged_on_test_counts_as_zero_and_nan_is_excluded():
    class Idle(FakeEngine):
        def replay_grid(self, family_id, position, ticks):
            rows = super().replay_grid(family_id, position, ticks)
            if len(self.calls) == 2:
                rows[1].update(n_orders=0, avg_hedge_ratio=0.0, hedge_var_reduction_vs_static=0.0)
            return rows

    r, _ = _run(Idle())
    assert r["status"] == "tested" and r["test_vs_static"] == 0.0 and "never hedged" in r["reason"]
    r, _ = _run(FakeEngine(test_scores=(0.05, float("nan"))))
    assert r["status"] == "excluded" and "undefined" in r["reason"]


def test_stats_and_success_rule():
    assert wf.sign_test_greater([1, 2, -1, 0])["p"] == pytest.approx(0.5)
    assert wf.wilcoxon_greater([1, 2, 3, 4, 5])["p"] == pytest.approx(1 / 32)
    assert wf.t_sf(2.0, 10) == pytest.approx(0.036694, abs=1e-5)
    good = wf.describe([0.01 * i for i in range(1, 31)])
    assert wf.success(good)
    assert not wf.success(wf.describe([0.01, -0.02, 0.0, -0.01, 0.02]))
