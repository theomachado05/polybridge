"""Join options-implied history (and the 8-K score) onto fit replay ticks, for threshold questions that
``app.options.match`` can map (equities / indices, "above/below K on date").

Honesty rules:
- The structure (expiry, strikes k_lo / k_hi) comes from today's Massive snapshot via ``app.options.enrich.refresh``
  and ``implied_for_threshold``: the YES-equivalent spread (call spread C(k_lo) - C(k_hi) for "above", put spread
  P(k_hi) - P(k_lo) for "below"), exactly the unit the C++ option families trade.
- Its history is built from Massive hourly (else daily) bar CLOSES of those two listed contracts, joined as of the
  time each close became known (bar end). ``opt_mid`` = the spread's close-to-close value, ``opt_implied_prob`` =
  ``opt_mid / (k_hi - k_lo) / DF`` (the digital approximation) when it lies in [0, 1] (within a small tolerance).
  These are estimates from bar closes, not quotes; ``quote_model`` on the result says so.
- ``opt_iv`` / ``opt_delta`` have no history in bars: they stay NaN (never back-filled from today's snapshot).
- ``eightk_score`` per tick date from ``app.options.eightk`` for single-stock underlyings; NaN where no loaded 8-K
  data covers the date (and for indices / ETFs, which file no 8-Ks).
- Anything missing (no key, unsupported question, no listed contracts, an expiry too far from the resolution
  date, Massive down) leaves the ticks unchanged and says why in the notes. Never raises.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Awaitable, Callable

import numpy as np

ARB_TOL = 0.02
INDEX_LIKE = ("SPY", "QQQ", "IWM", "DIA")
NAN = math.nan


def _bars_for(client: Any, option_ticker: str, start_s: int, end_s: int) -> list[tuple[int, float]]:
    from .ticks import massive_bars
    return massive_bars(client, option_ticker, start_s, end_s)


def _discount(r: float, expiry: dt.date, at: dt.date) -> float:
    T = max((expiry - at).days, 0) / 365.0
    return math.exp(-r * T)


def spread_series(ts_s: np.ndarray, legs: list[tuple[int, list[tuple[int, float]]]]) -> np.ndarray:
    """As-of join of signed leg closes: sum(sign * close of the last bar known at t); NaN until every leg has one."""
    out = np.zeros(len(ts_s))
    for sign, bars in legs:
        if not bars:
            return np.full(len(ts_s), NAN)
        known = np.array([b[0] for b in bars], dtype=np.int64)
        close = np.array([b[1] for b in bars], dtype=np.float64)
        j = np.searchsorted(known, ts_s, side="right") - 1
        vals = np.where(j >= 0, close[np.clip(j, 0, None)], NAN)
        out = out + sign * vals
    return out


async def join_options(ticks: dict[str, np.ndarray], question: str | None, end_date: Any, *,
                       massive: Callable[[], Any] | None, offline: bool = False,
                       refresh: Callable[..., Awaitable[Any]] | None = None,
                       bars: Callable[[Any, str, int, int], list[tuple[int, float]]] | None = None,
                       eightk: bool = True, today: dt.date | None = None) -> tuple[dict[str, np.ndarray], dict]:
    """(ticks with opt_* / eightk_score joined where available, info {available, notes, match, structure, ...})."""
    from ..chain import bounded
    from ..options import enrich as en
    from ..options.eightk import eightk_score, refresh_eightk
    from ..options.implied import RISK_FREE, implied_for_threshold
    from ..options.match import match_question, why_no_match

    info: dict[str, Any] = {"available": False, "notes": [], "quote_model": "option_bar_closes"}
    notes: list[str] = info["notes"]
    if ticks is None or not len(ticks.get("ts_ns", [])):
        notes.append("options: no ticks to join")
        return ticks, info
    if offline or massive is None:
        notes.append("options: offline (no option history joined)")
        return ticks, info
    today = today or dt.date.today()
    try:
        m = match_question(question or "", end_date, as_of=today)
    except Exception:
        m = None
    if m is None:
        notes.append(f"options: question not mapped ({why_no_match(question or '', end_date, as_of=today)})")
        return ticks, info
    info["match"] = m.to_dict()
    try:
        client = massive()
    except Exception:
        client = None
    if client is None:
        notes.append("options: MASSIVE_API_KEY not set")
        return ticks, info
    refresh = refresh or en.refresh
    bars = bars or _bars_for
    try:
        und, k = m.underlying, m.strike
        got = await refresh(und, k, m.expiry, as_of=today, client=client)
        if got is None and m.fallback:
            und, k = m.fallback[0], round(m.level * m.fallback[1], 6)
            got = await refresh(und, k, m.expiry, as_of=today, client=client)
        if got is None:
            notes.append("options: no listed contracts near the threshold and date (or Massive unavailable)")
            return ticks, info
        chain = got[0]
        above = m.direction == "above"
        res = implied_for_threshold(chain, k, m.expiry, above=above, as_of=today)
        if not res.get("expiry") or not res.get("expiry_gap_ok") or res.get("k_lo") is None:
            notes.append("options: " + "; ".join(res.get("notes") or ["no usable expiry / strikes"]))
            return ticks, info
        expiry = dt.date.fromisoformat(res["expiry"])
        k_lo, k_hi = float(res["k_lo"]), float(res["k_hi"])
        sl = chain.slice(res["expiry"])
        kind = "call" if above else "put"
        lo_q, hi_q = (sl.get(k_lo) or {}).get(kind), (sl.get(k_hi) or {}).get(kind)
        if lo_q is None or hi_q is None:
            notes.append(f"options: the {kind} legs at {k_lo:g}/{k_hi:g} are not listed in the snapshot")
            return ticks, info
        signed = [(1, lo_q.ticker), (-1, hi_q.ticker)] if above else [(1, hi_q.ticker), (-1, lo_q.ticker)]
        ts_s = (np.asarray(ticks["ts_ns"], dtype=np.int64) // 1_000_000_000)
        start_s, end_s = int(ts_s.min()), int(ts_s.max())
        legs = []
        for sign, tk in signed:
            legs.append((sign, await bounded(bars, client, tk, start_s, end_s)))
        mid = spread_series(ts_s, legs)
        width = k_hi - k_lo
        dates = [dt.datetime.fromtimestamp(int(t), dt.timezone.utc).date() for t in ts_s]
        df = np.array([_discount(RISK_FREE, expiry, d) for d in dates])
        prob = mid / width / df
        ok = np.isfinite(prob) & (prob >= -ARB_TOL) & (prob <= 1 + ARB_TOL) & (mid >= 0)
        out = dict(ticks)
        out["opt_mid"] = np.where(ok, mid, NAN)
        out["opt_implied_prob"] = np.where(ok, np.clip(prob, 0.0, 1.0), NAN)
        out["opt_iv"] = np.full(len(ts_s), NAN)
        out["opt_delta"] = np.full(len(ts_s), NAN)
        n_ok = int(ok.sum())
        info.update(available=n_ok > 0, n_with_options=n_ok, underlying_used=und, strike_used=k,
                    structure={"kind": "call_spread" if above else "put_spread", "expiry": res["expiry"],
                               "k_lo": k_lo, "k_hi": k_hi, "legs": [t for _, t in signed]})
        if n_ok == 0:
            notes.append("options: no bar closes for both legs inside the history window")
        else:
            notes.append(f"options: {n_ok}/{len(ts_s)} ticks carry a {info['structure']['kind']} estimate from bar "
                         "closes (opt_iv / opt_delta not available historically)")
        if eightk and not und.startswith("I:") and und not in INDEX_LIKE:
            try:
                await refresh_eightk(today, client=client)
            except Exception:
                pass
            cache: dict[dt.date, float] = {}
            for d in set(dates):
                try:
                    cache[d] = float(eightk_score(und, as_of=d))
                except Exception:
                    cache[d] = NAN
            out["eightk_score"] = np.array([cache[d] for d in dates], dtype=np.float64)
            info["eightk"] = "joined per tick date (NaN where no 8-K data covers the date)"
        else:
            out["eightk_score"] = np.full(len(ts_s), NAN)
            info["eightk"] = "not applicable (index / ETF underlying)"
        return out, info
    except Exception as e:  # never break the fit
        notes.append(f"options: join failed ({type(e).__name__})")
        return ticks, info
