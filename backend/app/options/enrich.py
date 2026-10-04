from __future__ import annotations

import datetime as dt
import math
from typing import Any

from . import chain as ch
from .eightk import eightk_coverage, eightk_score, refresh_eightk
from .implied import RISK_FREE, _date, _g, implied_for_threshold, max_expiry_gap_days

NAN = math.nan
OPT_FIELDS = ("opt_mid", "opt_delta", "opt_iv", "opt_implied_prob")
EXPIRY_STEPS = (3, 10, 30, 60)
STRIKE_PAD = 0.10
NARROW_PAD = 0.03


def _fin(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _tick_date(tick: dict) -> dt.date | None:
    try:
        ts = int(tick.get("ts_ns"))
        return dt.datetime.fromtimestamp(ts / 1e9, tz=dt.timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def structure_mid(sl: dict, k_lo: float | None, k_hi: float | None, above: bool) -> float:
    if k_lo is None or k_hi is None:
        return NAN
    lo, hi = sl.get(k_lo, {}), sl.get(k_hi, {})
    if above:
        a, b = _g(lo.get("call"), "mid"), _g(hi.get("call"), "mid")
    else:
        a, b = _g(hi.get("put"), "mid"), _g(lo.get("put"), "mid")
    v = a - b
    return v if _fin(v) and v >= 0 else NAN


def enrich_detail(tick: dict | None, underlying: str, K: float, expiry: Any, *, above: bool = True,
                  chain: Any = None, as_of: Any = None, r: float = RISK_FREE,
                  eightk_ticker: str | None = None) -> tuple[dict, dict]:
    out = dict(tick or {})
    for f in OPT_FIELDS:
        v = out.get(f, NAN)
        out[f] = float(v) if _fin(v) else NAN
    detail: dict = {"available": False, "notes": []}
    try:
        a = _date(as_of) or _tick_date(out) or dt.date.today()
        if eightk_ticker:
            out["eightk_score"] = eightk_score(eightk_ticker, as_of=a)
            detail["eightk_coverage"] = eightk_coverage(a)
        c, origin = chain, "caller"
        if c is None and underlying:
            c, origin = ch.chain_for(underlying, K, expiry), "query"
            if c is None:
                c, origin = ch.last_chain(underlying), "underlying_latest"
        if c is None:
            detail["notes"].append("no option chain cached for this underlying")
            return out, detail
        try:
            k = float(K)
        except (TypeError, ValueError):
            k = NAN
        if not _fin(k) or _date(expiry) is None:
            detail["notes"].append("missing threshold or expiry")
            return out, detail
        res = implied_for_threshold(c, k, expiry, above=above, r=r, as_of=a)
        res["chain_origin"] = origin
        res["chain_truncated"] = bool(getattr(c, "truncated", False))
        if "eightk_coverage" in detail:
            res["eightk_coverage"] = detail["eightk_coverage"]
        detail = res
        detail["available"] = _fin(res.get("prob")) and bool(res.get("expiry_gap_ok"))
        if res.get("expiry") and not res.get("expiry_gap_ok"):
            return out, detail
        if res.get("expiry"):
            mid = structure_mid(c.slice(res["expiry"]), res.get("k_lo"), res.get("k_hi"), above)
            res["structure_mid"] = mid
            vals = {"opt_implied_prob": res.get("prob"), "opt_delta": res.get("delta"), "opt_iv": res.get("iv"),
                    "opt_mid": mid}
            for f, v in vals.items():
                if _fin(v):
                    out[f] = float(v)
    except Exception as e:
        detail = {"available": False, "notes": [f"enrich failed: {type(e).__name__}"]}
        for f in OPT_FIELDS:
            out[f] = out.get(f, NAN) if _fin(out.get(f)) else NAN
    return out, detail


def enrich(tick: dict | None, underlying: str, K: float, expiry: Any, **kw) -> dict:
    return enrich_detail(tick, underlying, K, expiry, **kw)[0]


async def refresh(underlying: str, K: float, expiry: Any, *, as_of: Any = None, client=None,
                  cache=None) -> tuple[Any, bool] | None:
    e = _date(expiry)
    a = _date(as_of) or dt.date.today()
    try:
        k = float(K)
    except (TypeError, ValueError):
        return None
    if e is None or not _fin(k) or k <= 0:
        return None
    limit = max_expiry_gap_days(e, a)
    steps = sorted({w for w in EXPIRY_STEPS if w < limit} | {limit})
    for w in steps:
        lo = max(a, e - dt.timedelta(days=w))
        hi = max(e, a) + dt.timedelta(days=w)
        try:
            c, stale = await ch.get_chain(underlying, expiry_from=lo, expiry_to=hi, strike_min=k * (1 - STRIKE_PAD),
                                          strike_max=k * (1 + STRIKE_PAD), client=client, cache=cache)
            if c.quotes and c.truncated:
                c2, stale2 = await ch.get_chain(underlying, expiry_from=lo, expiry_to=hi,
                                                strike_min=k * (1 - NARROW_PAD), strike_max=k * (1 + NARROW_PAD),
                                                client=client, cache=cache)
                if c2.quotes:
                    c, stale = c2, stale2
        except Exception:
            return None
        if c.quotes:
            ch.remember(c)
            ch.remember_for(underlying, k, e, c)
            return c, stale
    return None


async def enrich_market(tick: dict | None, question: str, resolution_date: Any = None, *, as_of: Any = None,
                        eightk: bool = True, client=None) -> tuple[dict, dict]:
    from .match import match_question, why_no_match
    a = _date(as_of) or _tick_date(tick or {}) or dt.date.today()
    try:
        m = match_question(question, resolution_date, as_of=a)
    except Exception:
        m = None
    if m is None:
        out, det = enrich_detail(tick, "", NAN, None, as_of=a)
        det.update(supported=False, reason=why_no_match(question or "", resolution_date, as_of=a))
        return out, det
    und, k = m.underlying, m.strike
    got = await refresh(und, k, m.expiry, as_of=a, client=client)
    if got is None and m.fallback:
        und, k = m.fallback[0], round(m.level * m.fallback[1], 6)
        got = await refresh(und, k, m.expiry, as_of=a, client=client)
    tk = None
    if eightk and not und.startswith("I:") and und not in ("SPY", "QQQ", "IWM", "DIA"):
        await refresh_eightk(a, client=client)
        tk = und
    out, det = enrich_detail(tick, und, k, m.expiry, above=m.direction == "above", as_of=a, eightk_ticker=tk,
                             chain=got[0] if got else None)
    det.update(supported=True, match=m.to_dict(), underlying_used=und, strike_used=k)
    return out, det
