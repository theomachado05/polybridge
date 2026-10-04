from __future__ import annotations

import datetime as dt
import math
from statistics import NormalDist, median
from typing import Any, Mapping

NAN = math.nan
RISK_FREE = 0.04
ARB_TOL = 0.02
GAP_MIN_DAYS = 7
GAP_FRAC = 0.2
_N = NormalDist()


def _fin(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _g(q: Any, name: str) -> float:
    if q is None:
        return NAN
    v = q.get(name) if isinstance(q, Mapping) else getattr(q, name, NAN)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return NAN
    return v if math.isfinite(v) else NAN


def _date(d: Any) -> dt.date | None:
    if d is None:
        return None
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    try:
        return dt.date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def year_frac(expiry: Any, as_of: Any = None) -> float:
    e, a = _date(expiry), _date(as_of) or dt.date.today()
    if e is None:
        return NAN
    return max((e - a).days, 1) / 365.0


def discount_factor(r: float, T: float) -> float:
    return math.exp(-r * T) if _fin(r) and _fin(T) else NAN


def max_expiry_gap_days(target: Any, as_of: Any = None) -> int:
    t, a = _date(target), _date(as_of) or dt.date.today()
    horizon = (t - a).days if t else 0
    return int(max(GAP_MIN_DAYS, math.floor(GAP_FRAC * max(horizon, 0))))


def nearest_expiry(expiries: list[str], target: Any, as_of: Any = None) -> str | None:
    t = _date(target)
    a = _date(as_of)
    cands = [(e, _date(e)) for e in expiries]
    cands = [(e, d) for e, d in cands if d is not None and (a is None or d >= a)]
    if t is None or not cands:
        return None
    return min(cands, key=lambda ed: (abs((ed[1] - t).days), -ed[1].toordinal()))[0]


def bracket(strikes: list[float], K: float) -> tuple[float, float] | None:
    ks = sorted({float(k) for k in strikes if _fin(k)})
    if not _fin(K) or len(ks) < 2:
        return None
    below = [k for k in ks if k < K]
    above = [k for k in ks if k > K]
    if not below or not above:
        return None
    return below[-1], above[0]


def forward_from_parity(sl: Mapping[float, Mapping[str, Any]], DF: float) -> float:
    if not _fin(DF) or DF <= 0:
        return NAN
    fs = []
    for k, legs in sl.items():
        c, p = _g(legs.get("call"), "mid"), _g(legs.get("put"), "mid")
        if _fin(c) and _fin(p):
            fs.append(k + (c - p) / DF)
    return median(fs) if fs else NAN


def _interp(k1: float, v1: float, k2: float, v2: float, K: float) -> float:
    if _fin(v1) and _fin(v2):
        w = (K - k1) / (k2 - k1)
        return v1 + w * (v2 - v1)
    return v1 if _fin(v1) else v2 if _fin(v2) else NAN


def _leg_iv(legs: Mapping[str, Any]) -> float:
    ivs = [v for v in (_g(legs.get("call"), "iv"), _g(legs.get("put"), "iv")) if _fin(v) and v > 0]
    return sum(ivs) / len(ivs) if ivs else NAN


def _call_delta(legs: Mapping[str, Any]) -> float:
    d = _g(legs.get("call"), "delta")
    if _fin(d):
        return d
    p = _g(legs.get("put"), "delta")
    return 1.0 + p if _fin(p) else NAN


def delta_prob(delta: float, iv: float, T: float) -> float:
    if not _fin(delta):
        return NAN
    d = min(max(delta, 0.0), 1.0)
    if _fin(iv) and iv > 0 and _fin(T) and T > 0 and 1e-9 < d < 1 - 1e-9:
        return _N.cdf(_N.inv_cdf(d) - iv * math.sqrt(T))
    return d


def _clamp_prob(p: float, notes: list[str], what: str) -> float:
    if not _fin(p):
        return NAN
    if p < -ARB_TOL or p > 1 + ARB_TOL:
        notes.append(f"{what} outside no-arbitrage bounds ({p:.3f}); not used")
        return NAN
    return min(max(p, 0.0), 1.0)


def _bound(x: float) -> float:
    return min(max(x, 0.0), 1.0) if _fin(x) else NAN


def implied_prob_above(sl: Mapping[float, Mapping[str, Any]], K: float, T: float, r: float = RISK_FREE) -> dict:
    out: dict[str, Any] = {"prob": NAN, "lo": NAN, "hi": NAN, "method": None, "k_lo": None, "k_hi": None,
                           "center": None, "spread_mid": NAN, "spread_bid": NAN, "spread_ask": NAN,
                           "delta": NAN, "iv": NAN, "delta_prob": NAN, "T": T, "r": r, "notes": []}
    notes: list[str] = out["notes"]
    DF = discount_factor(r, T)
    if not _fin(K) or not _fin(DF):
        notes.append("missing threshold or time to expiry")
        return out
    br = bracket(list(sl.keys()), K)
    if br is None:
        notes.append("threshold outside the listed strikes")
        return out
    k1, k2 = br
    w = k2 - k1
    out.update(k_lo=k1, k_hi=k2, center=(k1 + k2) / 2)
    if abs((k1 + k2) / 2 - K) > 1e-9:
        notes.append(f"spread centred at {(k1 + k2) / 2:g}, nearest listed strikes around {K:g}")
    l1, l2 = sl.get(k1, {}), sl.get(k2, {})
    c1, c2, p1, p2 = l1.get("call"), l2.get("call"), l1.get("put"), l2.get("put")

    out["delta"] = _interp(k1, _call_delta(l1), k2, _call_delta(l2), K)
    out["iv"] = _interp(k1, _leg_iv(l1), k2, _leg_iv(l2), K)
    out["delta_prob"] = delta_prob(out["delta"], out["iv"], T)

    C1, C2, P1, P2 = (_g(q, "mid") for q in (c1, c2, p1, p2))
    if _fin(C1) and _fin(C2):
        out["method"] = "call_spread"
        out["spread_mid"] = C1 - C2
        out["prob"] = _clamp_prob((C1 - C2) / w / DF, notes, "call-spread probability")
        b1, a1, b2, a2 = (_g(c1, "bid"), _g(c1, "ask"), _g(c2, "bid"), _g(c2, "ask"))
        if all(_fin(x) for x in (b1, a1, b2, a2)):
            out["spread_bid"], out["spread_ask"] = b1 - a2, a1 - b2
            out["lo"], out["hi"] = _bound((b1 - a2) / w / DF), _bound((a1 - b2) / w / DF)
    elif _fin(P1) and _fin(P2):
        out["method"] = "put_spread_parity"
        out["spread_mid"] = P2 - P1
        out["prob"] = _clamp_prob(1.0 - (P2 - P1) / w / DF, notes, "put-spread (parity) probability")
        b1, a1, b2, a2 = (_g(p1, "bid"), _g(p1, "ask"), _g(p2, "bid"), _g(p2, "ask"))
        if all(_fin(x) for x in (b1, a1, b2, a2)):
            out["spread_bid"], out["spread_ask"] = b2 - a1, a2 - b1
            out["lo"], out["hi"] = _bound(1.0 - (a2 - b1) / w / DF), _bound(1.0 - (b2 - a1) / w / DF)
    else:
        F = forward_from_parity(sl, DF)
        syn1 = C1 if _fin(C1) else (P1 + DF * (F - k1) if _fin(P1) and _fin(F) else NAN)
        syn2 = C2 if _fin(C2) else (P2 + DF * (F - k2) if _fin(P2) and _fin(F) else NAN)
        if _fin(syn1) and _fin(syn2):
            out["method"] = "parity_synthetic"
            out["spread_mid"] = syn1 - syn2
            out["prob"] = _clamp_prob((syn1 - syn2) / w / DF, notes, "synthetic call-spread probability")
            notes.append(f"missing calls synthesised from puts by put-call parity (F={F:.4g})")
    if not _fin(out["prob"]) and _fin(out["delta_prob"]):
        out["prob"], out["method"] = out["delta_prob"], "delta"
        notes.append("no usable spread; delta approximation")
    if not _fin(out["prob"]):
        out["method"] = None
        notes.append("no usable option prices at this threshold")
    if _fin(out["prob"]) and _fin(out["lo"]) and _fin(out["hi"]) and out["lo"] > out["hi"]:
        out["lo"], out["hi"] = out["hi"], out["lo"]
    return out


def flip(res: dict) -> dict:
    o = dict(res)
    inv = lambda x: 1.0 - x if _fin(x) else NAN  # noqa: E731
    o["prob"], o["delta_prob"] = inv(res.get("prob", NAN)), inv(res.get("delta_prob", NAN))
    o["lo"], o["hi"] = inv(res.get("hi", NAN)), inv(res.get("lo", NAN))
    d = res.get("delta", NAN)
    o["delta"] = d - 1.0 if _fin(d) else NAN
    o["notes"] = list(res.get("notes", []))
    return o


def implied_for_threshold(chain, K: float, target: Any, *, above: bool = True, r: float = RISK_FREE,
                          as_of: Any = None) -> dict:
    as_of_d = _date(as_of) or dt.date.today()
    expiries = chain.expiries() if chain is not None else []
    exp = nearest_expiry(expiries, target, as_of_d)
    if exp is None:
        res = implied_prob_above({}, K, NAN, r)
        res["notes"] = ["no listed expiry near the resolution date"]
        res.update(expiry=None, expiry_gap_days=None, expiry_gap_max_days=max_expiry_gap_days(target, as_of_d),
                   expiry_gap_ok=False, direction="above" if above else "below")
        return res
    T = year_frac(exp, as_of_d)
    res = implied_prob_above(chain.slice(exp), K, T, r)
    if not above:
        res = flip(res)
    t = _date(target)
    gap = (_date(exp) - t).days if t else None
    limit = max_expiry_gap_days(t, as_of_d)
    ok = gap is not None and abs(gap) <= limit
    res.update(expiry=exp, expiry_gap_days=gap, expiry_gap_max_days=limit, expiry_gap_ok=ok,
               direction="above" if above else "below")
    if gap is not None and abs(gap) > GAP_MIN_DAYS:
        res["notes"].append(f"nearest listed expiry is {gap:+d} days from the resolution date")
    if not ok:
        res["notes"].append(f"expiry gap exceeds {limit} days: the estimate prices a different date; not used")
    return res


def jsonable(d: dict) -> dict:
    return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()}
