from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Callable, Iterable

import numpy as np

from arbscan.parse import parse_pm_question
from pm_taker import core as P

from . import config as C

ET = P.ET


def reopenings(sessions: Iterable[date], lo: str = C.REOPEN_MIN, hi: str = C.REOPEN_MAX) -> list[date]:
    s = set(sessions)
    a, b = date.fromisoformat(lo), date.fromisoformat(hi)
    return sorted(d for d in s if a <= d <= b and (d - timedelta(days=1)) not in s)


def week_end(d: date, sessions: Iterable[date]) -> date:
    s = set(sessions)
    fri = d + timedelta(days=4 - d.weekday())
    while fri not in s and fri > d:
        fri -= timedelta(days=1)
    return fri


def _jl(x) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def strip_meta(m: dict, event_title: str = "") -> dict:
    out = {k: m.get(k) for k in C.META_FIELDS}
    out["event_title"] = event_title
    return out


def select(m: dict, d: date, sessions: set[date]) -> tuple[dict | None, str]:
    th, why = parse_pm_question(m.get("question") or "", m.get("event_title") or "")
    if th is None:
        return None, f"parse_{why}"
    if th.kind not in C.KINDS:
        return None, f"kind_{th.kind}"
    if not m.get("endDate") or not m.get("conditionId"):
        return None, "no_date_or_condition"
    r = P.parse_iso(m["endDate"]).astimezone(ET).date()
    if not (d <= r <= week_end(d, sessions)):
        return None, "outside_week"
    if r not in sessions:
        return None, "resolution_not_session"
    w0 = P.et(d, C.WINDOW_START_HM)
    if m.get("startDate"):
        w0 = max(w0, P.parse_iso(m["startDate"]) + timedelta(seconds=C.LISTING_LAG_SEC))
    w1 = P.et(d, C.WINDOW_END_HM)
    toks, outs = _jl(m.get("clobTokenIds")), [str(o).lower() for o in _jl(m.get("outcomes"))]
    yes = toks[outs.index("yes")] if "yes" in outs and len(toks) == len(outs) else (toks[0] if toks else "")
    return {"id": str(m["id"]), "cond": m["conditionId"], "tok": yes, "tk": th.ticker, "k": th.strike, "kind": th.kind,
            "reopening": d.isoformat(), "res_date": r.isoformat(), "w0": int(w0.timestamp()), "w1": int(w1.timestamp()),
            "exp_close": int(P.et(r, C.EXPIRY_CLOSE_HM).timestamp()), "fees_listing": bool(m.get("feesEnabled")),
            "listed": m.get("startDate") or "", "empty_window": w0 >= w1}, ""


def evaluate(prints, spread_at: Callable):
    return P.evaluate_market(prints, spread_at, taus=C.TAUS, tau_stop=C.TAU_STOP)


def net(side: str, px: float, y: int, tick: float, enabled: bool, rate: float, exp: float) -> float:
    return P.net_pnl(side, px, y, tick, lambda p: P.fee_per_share(p, enabled, rate, exp))


def summarize(values, clusters) -> dict:
    v = np.asarray(values, float)
    if len(v) == 0:
        return {"n": 0, "clusters": 0, "mean": None, "ci_lo": None, "ci_hi": None}
    lo, hi = P.cluster_boot(v, np.asarray(clusters), draws=C.BOOT_DRAWS, seed=C.SEED)
    return {"n": int(len(v)), "clusters": int(len(np.unique(clusters))), "mean": float(v.mean()), "ci_lo": lo, "ci_hi": hi}


def verdict(n: int, k: int, lo, hi, window_over: bool) -> str:
    if n < C.MIN_TRADES or k < C.MIN_REOPENINGS:
        return "INSUFFICIENT" if window_over else "RUNNING"
    if lo > 0:
        return "PASS"
    if hi < 0:
        return "NEGATIVE"
    return "NULL"
