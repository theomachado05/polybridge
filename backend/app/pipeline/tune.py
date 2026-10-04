from __future__ import annotations

import math
from typing import Any

from .engine_adapter import EngineAdapter, default_preset
from .ticks import MIN_TICKS, TickSet

SIGNAL_FIELDS: dict[str, tuple[str, ...]] = {
    "binary_vs_spread_arb": ("opt_implied_prob",),
    "vol_vs_pm_move": ("opt_iv", "opt_straddle_mid"),
    "eightk_opportunity": ("eightk_score", "opt_put_mid"),
}
SIGNAL_WHY: dict[str, str] = {
    "opt_straddle_mid": "no straddle price history; only the spread proxy exists, which is not what this family trades",
    "opt_put_mid": "no put price history; opt_mid is the YES spread, not the put this family trades",
}

STAT_KEYS = ("n_ticks", "n_orders", "pnl", "fees", "max_dd", "hedge_var_reduction", "hedge_var_reduction_vs_static",
             "avg_hedge_ratio", "turnover", "p50_ns", "p99_ns")

SCORE_BASIS = {"hedge": "hedge_var_reduction_vs_static", "opportunity": "net_pnl_per_drawdown"}
SCORE_NOTE = ("score = hedge variance reduction beyond a static short of the same average size "
              "(hedge_var_reduction_vs_static: what the prediction-market signal adds; 0 = no better than a static "
              "hedge). score_raw = plain hedge variance reduction, which any static short earns (1 - (1 - h)^2 at "
              "average hedge ratio h); it is reported, never ranked.")
NO_STATIC_BENCHMARK = ("no preset has a defined gain over a static hedge of the same average size "
                       "(hedge_var_reduction_vs_static is undefined: a full static short, or an equity that never "
                       "moved), and plain variance reduction would only rank hedge size")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def never_hedged(row: dict) -> bool:
    n_orders, h = _f(row.get("n_orders")), _f(row.get("avg_hedge_ratio"))
    return (n_orders is not None and n_orders <= 0) or (h is not None and abs(h) < 1e-9)


def score_row(row: dict, division: str) -> float | None:
    if division == "hedge":
        if never_hedged(row):
            return None
        return _f(row.get("hedge_var_reduction_vs_static"))
    n_orders = _f(row.get("n_orders"))
    if n_orders is not None and n_orders <= 0:
        return None
    net = _f(row.get("pnl_net", row.get("net_pnl")))
    if net is None:
        net = _f(row.get("pnl"))
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


def rules_pick(families: list[dict], reason: str, no_static_benchmark: bool = False) -> dict:
    if not families:
        return {"family": None, "preset_index": None, "params": {}, "score": None, "scored": False,
                "alternatives": [], "unscored_reason": reason, "no_static_benchmark": no_static_benchmark}
    picks = [_entry(f, *default_preset(f), None) for f in families[:4]]
    best = picks[0]
    return {**best, "scored": False, "alternatives": picks[1:], "unscored_reason": reason,
            "no_static_benchmark": no_static_benchmark}


def _alternatives(ranked: list[dict], best: dict, k: int = 3) -> list[dict]:
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
    import numpy as np
    for f in SIGNAL_FIELDS.get(family_id, ()):
        v = (ticks or {}).get(f)
        if v is None or not bool(np.isfinite(np.asarray(v, dtype=float)).any()):
            return f
    return None


def tune(adapter: EngineAdapter, families: list[dict], division: str, position: dict, ts: TickSet,
         family_ticks: dict[str, dict] | None = None) -> dict:
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
    raw_only = False
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
            elif division == "hedge" and never_hedged(row):
                idle += 1
            elif division == "hedge" and _f(row.get("hedge_var_reduction")) is not None:
                raw_only = True
    if not ranked:
        why = "the engine returned no defined replay scores for this market"
        if division == "hedge" and raw_only:
            why = NO_STATIC_BENCHMARK
        if idle and division == "hedge" and not raw_only:
            why = "no preset held a hedge on this market's history, so there is no replay score"
        elif idle and division == "opportunity":
            why = "no preset placed a single order on this market's history, so there is no replay score"
        if skipped:
            why += "; not replayed: " + ", ".join(skipped)
        return rules_pick(families, why, no_static_benchmark=division == "hedge" and raw_only)
    order = {f["id"]: i for i, f in enumerate(families)}
    ranked.sort(key=lambda e: (-e["score"], e.get("stats", {}).get("n_orders", 0), order[e["family"]], e["preset_index"]))
    best = ranked[0]
    out = {**best, "scored": True, "alternatives": _alternatives(ranked, best), "unscored_reason": None,
           "score_basis": SCORE_BASIS[division]}
    if division == "hedge":
        st = best.get("stats", {})
        out.update(score_vs_static=best["score"], score_raw=_f(st.get("hedge_var_reduction")),
                   avg_hedge_ratio=_f(st.get("avg_hedge_ratio")), score_note=SCORE_NOTE)
    return out
