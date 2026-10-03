"""Step 4: replay every preset of every shortlisted family and pick the best (or pick by rules, unscored).

Score: hedge -> ``hedge_var_reduction`` (the top presets re-ranked by their gain over a same-size static hedge, see
``_rank_hedge_by_timing``); opportunity -> P&L net of fees per unit of risk, where risk is the
replay's max drawdown (floored at $1 so a flat replay does not divide by zero). ``pnl`` is already net of fees: the
engine's replay debits every fill's fee from cash before marking the book (``engine/hedgecore/src/replay.cpp``,
``ReplayStats::pnl`` "algo P&L net of fees"; pinned by ``tests/test_replay.cpp``), so ``fees`` is reported for
display and never subtracted again. ``pnl_net`` / ``net_pnl`` win when an engine reports them explicitly.

An opportunity replay that placed no order is unscored (None), not 0.0: holding on every tick measures nothing, and a
0.0 would otherwise beat every family that traded at a loss. A family whose own signal is NaN throughout the history
(``SIGNAL_FIELDS``: implied vol and a straddle price for vol_vs_pm_move, the 8-K score and a put price for
eightk_opportunity) is not replayed at all.
"""
from __future__ import annotations

import math
from typing import Any

from .engine_adapter import EngineAdapter, default_preset
from .ticks import MIN_TICKS, TickSet

# Per-tick fields a family cannot trade without; when every value in the history is NaN the family is not scored.
# vol_vs_pm_move trades a straddle at K, but the replay fills and marks every option at ``opt_mid``, which the fit's
# history builds from the YES-equivalent call / put SPREAD. Scoring it on that series would describe a spread traded
# on straddle signals, so it also needs a straddle price history (``opt_straddle_mid``) that nothing builds yet: until
# then it is never replayed and the fit says why.
# eightk_opportunity has the same mismatch: it sells a cash-secured put / buys a put spread, but ``opt_mid`` is the
# YES spread (a CALL spread for an "above K" question), so its replay would book a short call spread, the opposite
# exposure. It needs a put price history (``opt_put_mid``) that nothing builds yet: until then it is never replayed.
SIGNAL_FIELDS: dict[str, tuple[str, ...]] = {
    "binary_vs_spread_arb": ("opt_implied_prob",),
    "vol_vs_pm_move": ("opt_iv", "opt_straddle_mid"),
    "eightk_opportunity": ("eightk_score", "opt_put_mid"),
}
# Why a missing field matters, for the fit notes (default: "<field> has no history").
SIGNAL_WHY: dict[str, str] = {
    "opt_straddle_mid": "no straddle price history; only the spread proxy exists, which is not what this family trades",
    "opt_put_mid": "no put price history; opt_mid is the YES spread, not the put this family trades",
}

STAT_KEYS = ("n_ticks", "n_orders", "pnl", "fees", "max_dd", "hedge_var_reduction", "turnover", "p50_ns", "p99_ns",
             "mean_hedge_ratio")

# Hedge ranking. ``hedge_var_reduction`` = 1 - var(hedged)/var(unhedged) with the hedge a short in the same shares, so
# it rises with hedge SIZE whatever the signal does: a static short of the whole position scores ~1.0, and ranking on
# it alone always picks the preset that shorts the most. The presets with the best variance reduction are therefore
# re-ranked by their gain over a static hedge of the same average size (h = mean short / shares_held over the replay):
#     timing_gain = var_reduction - (1 - (1 - h)^2)
# which is what the dynamic timing (reading the event) adds; a static full short scores ~0. h comes from the engine's
# ``mean_hedge_ratio`` when it reports one, else from a short re-run of the preset through hedgecore.Algo (marketable
# equity orders filled at the touch, as in the engine replay). Without either, the ranking stays on var reduction.
TIMING_TOP_K = 12
SCORE_NOTE = ("hedge variance reduction grows with hedge size (a static short of the full position scores ~100%); "
              "the best presets are ranked by their gain over a static hedge of the same average size")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def score_row(row: dict, division: str) -> float | None:
    if division == "hedge":
        return _f(row.get("hedge_var_reduction"))
    n_orders = _f(row.get("n_orders"))
    if n_orders is not None and n_orders <= 0:  # never traded: nothing was measured
        return None
    net = _f(row.get("pnl_net", row.get("net_pnl")))
    if net is None:
        net = _f(row.get("pnl"))  # the engine contract: replay pnl already nets fees (never subtract them twice)
        if net is None:
            return None
    risk = max(abs(_f(row.get("max_dd")) or 0.0), 1.0)
    return net / risk


def _entry(family: dict | str, preset_index: int, params: dict, score: float | None, row: dict | None = None) -> dict:
    fid = family if isinstance(family, str) else family["id"]
    e = {"family": fid, "preset_index": int(preset_index), "params": dict(params), "score": score}
    if row is not None:
        e["stats"] = {k: row[k] for k in STAT_KEYS if k in row and _f(row[k]) is not None}
    return e


def rules_pick(families: list[dict], reason: str) -> dict:
    """The first family in rule order with its default preset; the next three families as alternatives."""
    if not families:
        return {"family": None, "preset_index": None, "params": {}, "score": None, "scored": False,
                "alternatives": [], "unscored_reason": reason}
    picks = [_entry(f, *default_preset(f), None) for f in families[:4]]
    best = picks[0]
    return {**best, "scored": False, "alternatives": picks[1:], "unscored_reason": reason}


def _alternatives(ranked: list[dict], best: dict, k: int = 3) -> list[dict]:
    """Best preset of each other family first, then the next presets overall."""
    out, seen = [], {best["family"]}
    for e in ranked:
        if e["family"] not in seen:
            out.append(e)
            seen.add(e["family"])
        if len(out) == k:
            return out
    for e in ranked:
        if e is not best and e not in out:
            out.append(e)
        if len(out) == k:
            break
    return out


def missing_signal(family_id: str, ticks: dict | None) -> str | None:
    """The first signal field this family needs that is NaN (or absent) on every tick, else None."""
    import numpy as np
    for f in SIGNAL_FIELDS.get(family_id, ()):
        v = (ticks or {}).get(f)
        if v is None or not bool(np.isfinite(np.asarray(v, dtype=float)).any()):
            return f
    return None


def mean_hedge_ratio(module: Any, family: str, params: dict, position: dict, ticks: dict) -> float | None:
    """Mean short / shares_held over the ticks with an equity price, from a re-run of the preset through
    hedgecore.Algo (equity intents filled at the touch when marketable, else rejected). None when it cannot run."""
    import numpy as np
    from ..ticks import TICK_FIELDS
    algo_cls = getattr(module, "Algo", None)
    shares = float(position.get("shares_held") or 0.0)
    if algo_cls is None or shares <= 0 or not ticks or "ts_ns" not in ticks:
        return None
    try:
        algo = algo_cls(family, {k: float(v) for k, v in params.items()}, {"shares_held": shares})
        cols = {k: np.asarray(ticks[k], dtype=float) for k in TICK_FIELDS if k in ticks}
        ts = np.asarray(ticks["ts_ns"], dtype=np.int64)
        venue = np.asarray(ticks.get("venue", np.zeros(len(ts))), dtype=float)
        nan = float("nan")
        book, total, n = 0.0, 0.0, 0
        for i in range(len(ts)):
            t = {k: (float(c[i]) if math.isfinite(c[i]) else nan) for k, c in cols.items()}
            for k in TICK_FIELDS:
                t.setdefault(k, nan)
            t["ts_ns"], t["venue"] = int(ts[i]), int(venue[i]) if math.isfinite(venue[i]) else 0
            intent = algo.on_tick(t, int(ts[i]))
            if intent.get("action") == "order":
                inst = str(intent.get("instrument") or "equity")
                side = 1 if int(intent.get("side") or 0) > 0 else -1
                qty = _f(intent.get("qty"))
                touch = _f(t.get("under_ask" if side > 0 else "under_bid")) or _f(t.get("under_px"))
                limit = _f(intent.get("limit_px"))
                marketable = limit is None or touch is None or (touch <= limit if side > 0 else touch >= limit)
                if inst == "equity" and qty and qty > 0 and touch is not None and marketable:
                    algo.on_fill(inst, side * qty, touch)
                    book += side * qty
                else:
                    algo.on_reject(inst)
            if _f(t.get("under_px")) is not None:
                total += max(0.0, -book) / shares
                n += 1
        return total / n if n else None
    except Exception:
        return None


def _rank_hedge_by_timing(adapter: EngineAdapter, ranked: list[dict], position: dict,
                          ticks_for: dict[str, dict]) -> bool:
    """Re-rank the top TIMING_TOP_K hedge entries (by var reduction) by timing_gain; True when that happened."""
    module = getattr(adapter, "_module", None)
    top = sorted(ranked, key=lambda e: -e["score"])[:TIMING_TOP_K]
    done = []
    for e in top:
        stats = e.setdefault("stats", {})
        h = _f(stats.get("mean_hedge_ratio"))
        if h is None:
            h = mean_hedge_ratio(module, e["family"], e["params"], position, ticks_for[e["family"]])
        if h is None:
            continue
        static = 1.0 - (1.0 - min(max(h, 0.0), 1.0)) ** 2
        stats.update(mean_hedge_ratio=h, static_var_reduction=static, timing_gain=e["score"] - static)
        e["timing_gain"] = e["score"] - static
        done.append(e)
    if not done:
        return False
    rest = [e for e in ranked if e not in done]
    done.sort(key=lambda e: (-e["timing_gain"], -e["score"], e.get("stats", {}).get("n_orders", 0)))
    ranked[:] = done + rest
    return True


def tune(adapter: EngineAdapter, families: list[dict], division: str, position: dict, ts: TickSet,
         family_ticks: dict[str, dict] | None = None) -> dict:
    """``family_ticks`` replays a family on its own tick dict instead of ``ts.ticks`` (eightk_opportunity reads
    the PM adverse probability, so the service orients the ticks for it alone)."""
    if not families:
        return rules_pick([], "no algo family in the library covers this event class")
    if not adapter.can_score:
        return rules_pick(families, "the compiled hedgecore engine is not available on this server")
    if ts.ticks is None or ts.n < MIN_TICKS:
        return rules_pick(families, "there is no price history to replay for this market")
    if division == "hedge" and not ts.has_underlying:
        return rules_pick(families, "there are no equity prices aligned to the history to measure the hedge against")
    ranked: list[dict] = []
    skipped: list[str] = []
    idle = 0
    for fam in families:
        ticks = (family_ticks or {}).get(fam["id"], ts.ticks)
        if division == "opportunity" and (miss := missing_signal(fam["id"], ticks)):
            skipped.append(f"{fam['id']} ({SIGNAL_WHY.get(miss, f'{miss} has no history')})")
            continue
        for row in adapter.replay_grid(fam["id"], position, ticks) or []:
            s = score_row(row, division)
            if s is not None:
                ranked.append(_entry(fam, row["preset_index"], row["params"], s, row))
            elif division == "opportunity" and (_f(row.get("n_orders")) or 0.0) <= 0 and "n_orders" in row:
                idle += 1
    if not ranked:
        why = "the engine returned no defined replay scores for this market"
        if idle:
            why = "no preset placed a single order on this market's history, so there is no replay score"
        if skipped:
            why += "; not replayed: " + ", ".join(skipped)
        return rules_pick(families, why)
    # Highest score; ties -> fewer orders (cheaper to run), then the earlier family in rule order, then lower index.
    order = {f["id"]: i for i, f in enumerate(families)}
    ranked.sort(key=lambda e: (-e["score"], e.get("stats", {}).get("n_orders", 0), order[e["family"]], e["preset_index"]))
    timed = division == "hedge" and _rank_hedge_by_timing(
        adapter, ranked, position, {f["id"]: (family_ticks or {}).get(f["id"], ts.ticks) for f in families})
    best = ranked[0]
    out = {**best, "scored": True, "alternatives": _alternatives(ranked, best), "unscored_reason": None}
    if division == "hedge":
        out["score_note"] = SCORE_NOTE if timed else (
            "hedge variance reduction grows with hedge size (a static short of the full position scores ~100%); "
            "no same-size static benchmark was available here, so this ranks size as much as timing")
    return out
