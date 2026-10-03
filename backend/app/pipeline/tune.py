"""Step 4: replay every preset of every shortlisted family and pick the best (or pick by rules, unscored).

Score (the RANKING score, reported as ``score`` with ``score_basis`` naming it):

* hedge -> ``hedge_var_reduction_vs_static`` = 1 - var(hedged) / var(unhedged * (1 - avg_hedge_ratio)), from the
  engine replay (``engine/hedgecore/src/replay.cpp``): the variance cut BEYOND a static short of the same average size,
  i.e. what reading the prediction market adds. 0 for a static hedge, negative when the timing hurts. The raw
  ``hedge_var_reduction`` (1 - var(hedged)/var(unhedged)) rewards ANY short, signal or not -- a static short of a
  fraction h scores 1 - (1 - h)^2, so ranking on it always picks the preset that shorts the most -- and is only
  reported (``score_raw``), next to ``avg_hedge_ratio``. A preset whose vs-static score is NaN / absent (a full
  static short, avg_hedge_ratio == 1, or an equity that never moved) is not ranked; when no preset has one the fit
  falls back to the rules pick and says why. A preset that never held a hedge (avg_hedge_ratio 0 / no order) is
  unscored too: its vs-static score is 0 by construction, and "do nothing" must not win where every hedge loses.
* opportunity -> P&L net of fees per unit of risk, where risk is the replay's max drawdown (floored at $1 so a flat
  replay does not divide by zero). ``pnl`` is already net of fees: the engine's replay debits every fill's fee from
  cash before marking the book (``ReplayStats::pnl`` "algo P&L net of fees"; pinned by ``tests/test_replay.cpp``), so
  ``fees`` is reported for display and never subtracted again. ``pnl_net`` / ``net_pnl`` win when an engine reports
  them explicitly.

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

# Stats copied from each replay row into the fit (fits.json, /pipeline/fit alternatives). The hedge ranking score
# (hedge_var_reduction_vs_static) and the raw hedge_var_reduction + avg_hedge_ratio it is read against are all kept.
STAT_KEYS = ("n_ticks", "n_orders", "pnl", "fees", "max_dd", "hedge_var_reduction", "hedge_var_reduction_vs_static",
             "avg_hedge_ratio", "turnover", "p50_ns", "p99_ns")

# What ``score`` measures, per division (the fit response carries it as ``score_basis``).
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
    """A hedge replay that never held a short (no order, or an average hedge ratio of 0). Its vs-static score is 0
    by construction (hedged == unhedged), so it is unscored, not 0.0: otherwise "do nothing" would win every market
    where each real hedge does worse than a static one."""
    n_orders, h = _f(row.get("n_orders")), _f(row.get("avg_hedge_ratio"))
    return (n_orders is not None and n_orders <= 0) or (h is not None and abs(h) < 1e-9)


def score_row(row: dict, division: str) -> float | None:
    if division == "hedge":  # what the signal adds beyond a same-size static hedge (never the raw var reduction)
        if never_hedged(row):  # vs_static is exactly 0 by construction: nothing was measured
            return None
        return _f(row.get("hedge_var_reduction_vs_static"))
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
    raw_only = False  # a hedge row with a raw var reduction but no vs-static score (not ranked)
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
        return rules_pick(families, why)
    # Highest score; ties -> fewer orders (cheaper to run), then the earlier family in rule order, then lower index.
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
