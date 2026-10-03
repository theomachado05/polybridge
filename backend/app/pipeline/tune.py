"""Step 4: replay every preset of every shortlisted family and pick the best (or pick by rules, unscored).

Score: hedge -> ``hedge_var_reduction``; opportunity -> P&L net of fees per unit of risk, where risk is the
replay's max drawdown (floored at $1 so a flat replay does not divide by zero). ``pnl`` is taken as gross of
fees unless the engine reports ``pnl_net`` / ``net_pnl``.
"""
from __future__ import annotations

import math
from typing import Any

from .engine_adapter import EngineAdapter, default_preset
from .ticks import MIN_TICKS, TickSet

STAT_KEYS = ("n_ticks", "n_orders", "pnl", "fees", "max_dd", "hedge_var_reduction", "turnover", "p50_ns", "p99_ns")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def score_row(row: dict, division: str) -> float | None:
    if division == "hedge":
        return _f(row.get("hedge_var_reduction"))
    net = _f(row.get("pnl_net", row.get("net_pnl")))
    if net is None:
        pnl, fees = _f(row.get("pnl")), _f(row.get("fees")) or 0.0
        if pnl is None:
            return None
        net = pnl - abs(fees)
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


def tune(adapter: EngineAdapter, families: list[dict], division: str, position: dict, ts: TickSet) -> dict:
    if not families:
        return rules_pick([], "no algo family in the library covers this event class")
    if not adapter.can_score:
        return rules_pick(families, "the compiled hedgecore engine is not available on this server")
    if ts.ticks is None or ts.n < MIN_TICKS:
        return rules_pick(families, "there is no price history to replay for this market")
    if division == "hedge" and not ts.has_underlying:
        return rules_pick(families, "there are no equity prices aligned to the history to measure the hedge against")
    ranked: list[dict] = []
    for fam in families:
        for row in adapter.replay_grid(fam["id"], position, ts.ticks) or []:
            s = score_row(row, division)
            if s is not None:
                ranked.append(_entry(fam, row["preset_index"], row["params"], s, row))
    if not ranked:
        return rules_pick(families, "the engine returned no defined replay scores for this market")
    # Highest score; ties -> fewer orders (cheaper to run), then the earlier family in rule order, then lower index.
    order = {f["id"]: i for i, f in enumerate(families)}
    ranked.sort(key=lambda e: (-e["score"], e.get("stats", {}).get("n_orders", 0), order[e["family"]], e["preset_index"]))
    best = ranked[0]
    return {**best, "scored": True, "alternatives": _alternatives(ranked, best), "unscored_reason": None}
