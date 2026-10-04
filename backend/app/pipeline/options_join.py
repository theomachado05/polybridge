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


IV_LO, IV_HI = 1e-3, 5.0
IV_ITERS = 60
_erf = np.frompyfunc(math.erf, 1, 1)


def _ncdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.asarray(_erf(np.asarray(x, dtype=np.float64) / math.sqrt(2.0)), dtype=np.float64))


def bs_price(S, K, T, r: float, sigma, call: bool) -> np.ndarray:
    S, K, T, sigma = (np.asarray(x, dtype=np.float64) for x in (S, K, T, sigma))
    with np.errstate(divide="ignore", invalid="ignore"):
        v = sigma * np.sqrt(T)
        d1 = (np.log(S / K) + (r + 0.5 * sigma * sigma) * T) / v
        d2 = d1 - v
        df = np.exp(-r * T)
        if call:
            return S * _ncdf(d1) - K * df * _ncdf(d2)
        return K * df * _ncdf(-d2) - S * _ncdf(-d1)


def implied_vol(price, S, K, T, r: float, call: bool) -> np.ndarray:
    price, S, K, T = np.broadcast_arrays(*(np.asarray(x, dtype=np.float64) for x in (price, S, K, T)))
    out = np.full(price.shape, NAN)
    ok = np.isfinite(price) & np.isfinite(S) & np.isfinite(K) & np.isfinite(T) & (S > 0) & (K > 0) & (T > 0) & (price > 0)
    if not ok.any():
        return out
    p, s, k, t = price[ok], S[ok], K[ok], T[ok]
    lo, hi = np.full(p.shape, IV_LO), np.full(p.shape, IV_HI)
    p_lo, p_hi = bs_price(s, k, t, r, lo, call), bs_price(s, k, t, r, hi, call)
    inside = (p >= p_lo) & (p <= p_hi)
    for _ in range(IV_ITERS):
        mid = 0.5 * (lo + hi)
        above = bs_price(s, k, t, r, mid, call) > p
        hi = np.where(above, mid, hi)
        lo = np.where(above, lo, mid)
    iv = np.where(inside, 0.5 * (lo + hi), NAN)
    out[ok] = iv
    return out


def iv_at_strike(iv_lo: np.ndarray, iv_hi: np.ndarray, k_lo: float, k_hi: float, k: float) -> np.ndarray:
    w = 0.0 if k_hi == k_lo else min(max((k - k_lo) / (k_hi - k_lo), 0.0), 1.0)
    both = np.isfinite(iv_lo) & np.isfinite(iv_hi)
    return np.where(both, iv_lo + w * (iv_hi - iv_lo), np.where(np.isfinite(iv_lo), iv_lo, iv_hi))


def asof_known(ts_s: np.ndarray, bars: list[tuple[int, float]]) -> np.ndarray:
    if not bars:
        return np.full(len(ts_s), NAN)
    known = np.array([b[0] for b in bars], dtype=np.int64)
    j = np.searchsorted(known, ts_s, side="right") - 1
    return np.where(j >= 0, known[np.clip(j, 0, None)].astype(np.float64), NAN)


def bar_interval(bars: list[tuple[int, float]], default: float = 3600.0) -> float:
    if len(bars) < 2:
        return default
    gaps = np.diff(np.array([b[0] for b in bars], dtype=np.float64))
    gaps = gaps[gaps > 0]
    return float(np.median(gaps)) if len(gaps) else default


MAX_PAIR_AGE_S = 3.5 * 86400.0


def leg_sync_mask(ts_s: np.ndarray, leg_bars: list[list[tuple[int, float]]]) -> tuple[np.ndarray, int]:
    n = len(ts_s)
    if not leg_bars or any(not b for b in leg_bars):
        return np.zeros(n, dtype=bool), 0
    known = [asof_known(ts_s, b) for b in leg_bars]
    tol = min(bar_interval(b) for b in leg_bars)
    lo, hi = np.fmin.reduce(known), np.fmax.reduce(known)
    have = np.all([np.isfinite(k) for k in known], axis=0)
    with np.errstate(invalid="ignore"):
        ok = have & (hi - lo <= tol) & (ts_s.astype(np.float64) - hi <= max(2.0 * tol, MAX_PAIR_AGE_S))
    return ok, int((have & ~ok).sum())


def spread_series(ts_s: np.ndarray, legs: list[tuple[int, list[tuple[int, float]]]]) -> np.ndarray:
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


def _ny_dates(ts_s: np.ndarray) -> list[dt.date]:
    from ..options.match import _NY
    return [dt.datetime.fromtimestamp(int(t), dt.timezone.utc).astimezone(_NY).date() for t in ts_s]


def us_session(ts_s: np.ndarray) -> np.ndarray:
    from ..chain import calendar
    from ..options.match import _NY
    cal = calendar()
    out = np.zeros(len(ts_s), dtype=bool)
    open_day: dict[dt.date, bool] = {}
    for i, t in enumerate(np.asarray(ts_s, dtype=np.int64)):
        d = dt.datetime.fromtimestamp(int(t), dt.timezone.utc).astimezone(_NY)
        day = d.date()
        if day not in open_day:
            try:
                open_day[day] = day.weekday() < 5 and cal.on_or_after(day).date() == day
            except Exception:
                open_day[day] = day.weekday() < 5
        sod = d.hour * 3600 + d.minute * 60 + d.second
        out[i] = open_day[day] and 9 * 3600 + 30 * 60 <= sod < 16 * 3600
    return out


def session_fresh_mask(ts_s: np.ndarray, leg_bars: list[list[tuple[int, float]]]) -> np.ndarray:
    ts_s = np.asarray(ts_s, dtype=np.int64)
    n = len(ts_s)
    if not leg_bars or any(not b for b in leg_bars) or n == 0:
        return np.zeros(n, dtype=bool)
    ok = us_session(ts_s)
    day_t = _ny_dates(ts_s)
    for bars in leg_bars:
        known = asof_known(ts_s, bars)
        for i in np.where(ok)[0]:
            k = known[i]
            ok[i] = bool(np.isfinite(k)) and _ny_dates(np.array([int(k) - 1]))[0] == day_t[i]
    return ok


def leg_closes(ts_s: np.ndarray, bars: list[tuple[int, float]]) -> np.ndarray:
    return spread_series(ts_s, [(1, bars or [])])


async def option_columns(ts_s: np.ndarray, legs: list[tuple[int, list[tuple[int, float]]]], *, above: bool,
                         k_lo: float, k_hi: float, k: float, expiry: dt.date, und: str, client: Any,
                         bars: Callable[[Any, str, int, int], list[tuple[int, float]]], bounded,
                         session_fresh: bool = False) -> tuple[dict[str, np.ndarray], dict]:
    from ..options.implied import RISK_FREE
    ts_s = np.asarray(ts_s, dtype=np.int64)
    mid = spread_series(ts_s, legs)
    synced, n_unsynced = leg_sync_mask(ts_s, [b for _, b in legs])
    keep = synced
    n_off = 0
    if session_fresh:
        fresh = session_fresh_mask(ts_s, [b for _, b in legs])
        n_off = int((synced & ~fresh).sum())
        keep = synced & fresh
    mid = np.where(keep, mid, NAN)
    width = k_hi - k_lo
    dates = [dt.datetime.fromtimestamp(int(t), dt.timezone.utc).date() for t in ts_s]
    df = np.array([_discount(RISK_FREE, expiry, d) for d in dates])
    prob = mid / width / df
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(prob) & (prob >= -ARB_TOL) & (prob <= 1 + ARB_TOL) & (mid >= 0)
    signed = [(s, None) for s, _ in legs]
    iv = await _iv_history(client, bars, und, ts_s, legs, signed, above, k_lo, k_hi, k, expiry, RISK_FREE, bounded)
    if session_fresh:
        iv = np.where(keep, iv, NAN)
    cols = {"opt_mid": np.where(ok, mid, NAN), "opt_implied_prob": np.where(ok, np.clip(prob, 0.0, 1.0), NAN),
            "opt_iv": iv, "opt_delta": np.full(len(ts_s), NAN)}
    stats = {"n_with_options": int(ok.sum()), "n_with_iv": int(np.isfinite(iv).sum()), "n_unsynced_legs": n_unsynced,
             "n_off_session": n_off, "keep": ok}
    return cols, stats


REFERENCE_CONTRACTS = "/v3/reference/options/contracts"


def historical_structure(client: Any, underlying: str, strike: float, resolution: dt.date, *, above: bool,
                         as_of: dt.date, strike_pad: float = 0.2) -> dict | None:
    from ..options.implied import bracket, max_expiry_gap_days, nearest_expiry
    kind = "call" if above else "put"
    root = underlying[2:] if underlying.startswith("I:") else underlying
    limit = max_expiry_gap_days(resolution, as_of)
    lo = max(as_of, resolution - dt.timedelta(days=limit))
    hi = resolution + dt.timedelta(days=limit)
    rows: list[dict] = []
    for expired in ("true", "false"):
        rows += client.get_all(REFERENCE_CONTRACTS, {
            "underlying_ticker": root, "contract_type": kind, "expired": expired, "as_of": as_of.isoformat(),
            "expiration_date.gte": lo.isoformat(), "expiration_date.lte": hi.isoformat(),
            "strike_price.gte": round(strike * (1 - strike_pad), 4), "strike_price.lte": round(strike * (1 + strike_pad), 4),
            "limit": 1000}, max_pages=5) or []
    by_exp: dict[str, dict[float, str]] = {}
    for r in rows:
        try:
            e, k_, tk = str(r["expiration_date"])[:10], float(r["strike_price"]), str(r["ticker"])
        except (KeyError, TypeError, ValueError):
            continue
        cur = by_exp.setdefault(e, {}).get(k_)
        if cur is None or (underlying.startswith("I:") and not tk.startswith(f"O:{root}2") and cur.startswith(f"O:{root}2")):
            by_exp[e][k_] = tk
    exp = nearest_expiry(sorted(by_exp), resolution, as_of)
    if exp is None:
        return None
    gap = (dt.date.fromisoformat(exp) - resolution).days
    if abs(gap) > limit:
        return None
    br = bracket(list(by_exp[exp]), strike)
    if br is None:
        return None
    k_lo, k_hi = br
    t_lo, t_hi = by_exp[exp][k_lo], by_exp[exp][k_hi]
    legs = ([{"sign": 1, "ticker": t_lo, "strike": k_lo, "kind": kind}, {"sign": -1, "ticker": t_hi, "strike": k_hi, "kind": kind}]
            if above else
            [{"sign": 1, "ticker": t_hi, "strike": k_hi, "kind": kind}, {"sign": -1, "ticker": t_lo, "strike": k_lo, "kind": kind}])
    return {"underlying": underlying, "strike": strike, "direction": "above" if above else "below",
            "kind": "call_spread" if above else "put_spread", "expiry": exp, "expiry_gap_days": gap,
            "k_lo": k_lo, "k_hi": k_hi, "width": k_hi - k_lo, "legs": legs,
            "listing": f"Massive /v3/reference/options/contracts as of {as_of.isoformat()} (point in time)"}


async def join_options(ticks: dict[str, np.ndarray], question: str | None, end_date: Any, *,
                       massive: Callable[[], Any] | None, offline: bool = False,
                       refresh: Callable[..., Awaitable[Any]] | None = None,
                       bars: Callable[[Any, str, int, int], list[tuple[int, float]]] | None = None,
                       eightk: bool = True, today: dt.date | None = None,
                       session_fresh: bool = False) -> tuple[dict[str, np.ndarray], dict]:
    from ..chain import bounded
    from ..options import enrich as en
    from ..options.eightk import eightk_score, refresh_eightk
    from ..options.implied import implied_for_threshold
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
        cols, st = await option_columns(ts_s, legs, above=above, k_lo=k_lo, k_hi=k_hi, k=k, expiry=expiry, und=und,
                                        client=client, bars=bars, bounded=bounded, session_fresh=session_fresh)
        out = dict(ticks)
        out.update(cols)
        n_ok, n_iv, n_unsynced = st["n_with_options"], st["n_with_iv"], st["n_unsynced_legs"]
        dates = [dt.datetime.fromtimestamp(int(t), dt.timezone.utc).date() for t in ts_s]
        info.update(available=n_ok > 0, n_with_options=n_ok, underlying_used=und, strike_used=k,
                    structure={"kind": "call_spread" if above else "put_spread", "expiry": res["expiry"],
                               "k_lo": k_lo, "k_hi": k_hi, "legs": [t for _, t in signed]})
        info["n_unsynced_legs"] = n_unsynced
        if n_unsynced:
            notes.append(f"options: {n_unsynced}/{len(ts_s)} ticks dropped because the two legs' last bar closes "
                         "were more than one bar interval apart (or stale), so their spread never traded at once")
        if session_fresh:
            info["n_off_session"] = st["n_off_session"]
            notes.append(f"options: {st['n_off_session']}/{len(ts_s)} synced ticks dropped outside the regular "
                         "session or before both legs printed in it (a stale close is not a tradable price)")
        if n_ok == 0:
            notes.append("options: no bar closes for both legs inside the history window")
        else:
            notes.append(f"options: {n_ok}/{len(ts_s)} ticks carry a {info['structure']['kind']} estimate from bar "
                         "closes (opt_delta not available historically)")
        info["n_with_iv"] = n_iv
        notes.append(f"options: opt_iv on {n_iv}/{len(ts_s)} ticks (Black-Scholes inversion of the leg bar closes "
                     "against the underlying's bar closes, paired only when both closed within one bar interval; "
                     "NaN where they are not in sync or it does not solve; an estimate, not a quoted vol)")
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
    except Exception as e:
        notes.append(f"options: join failed ({type(e).__name__})")
        return ticks, info


async def _iv_history(client, bars, und: str, ts_s: np.ndarray, legs: list, signed: list, above: bool,
                      k_lo: float, k_hi: float, k: float, expiry: dt.date, r: float, bounded) -> np.ndarray:
    n = len(ts_s)
    try:
        spot_bars = await bounded(bars, client, und, int(ts_s.min()), int(ts_s.max()))
    except Exception:
        return np.full(n, NAN)
    spot = spread_series(ts_s, [(1, spot_bars or [])])
    if not np.isfinite(spot).any():
        return np.full(n, NAN)
    exp_s = dt.datetime.combine(expiry, dt.time(20, 0), dt.timezone.utc).timestamp()
    T = (exp_s - ts_s.astype(np.float64)) / (365.0 * 86400.0)
    by_strike: dict[float, np.ndarray] = {}
    strikes = (k_lo, k_hi) if above else (k_hi, k_lo)
    spot_t = asof_known(ts_s, spot_bars or [])
    tol = bar_interval(spot_bars or [])
    for (_, leg_bars), strike in zip(legs, strikes):
        close = spread_series(ts_s, [(1, leg_bars)])
        with np.errstate(invalid="ignore"):
            synced = np.abs(asof_known(ts_s, leg_bars or []) - spot_t) <= tol
        by_strike[strike] = implied_vol(np.where(synced, close, NAN), spot, strike, T, r, call=above)
    return iv_at_strike(by_strike[k_lo], by_strike[k_hi], k_lo, k_hi, k)
