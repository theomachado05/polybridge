from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import fresh_accuracy  # noqa: F401
from arbscan import datasrc as ds
from arbscan.costs import KalshiFee, PolyFee, commission_per_share
from arbscan.implied import Quote
from arbscan.score import score_row

from fresh_accuracy.config import KALSHI, PARAMS

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
NO_FEE = PolyFee(enabled=False)


def et_dt(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


def _iso(s: str) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC) if s else None


def snapshots(res_date: date, start: datetime | None, end: datetime, prev_session: date, p=PARAMS) -> tuple[list, dict]:
    out, drop = [], {}
    for label, d, hm in (("S1", prev_session, p.s1_hhmm), ("S2", res_date, p.s2_hhmm)):
        t = et_dt(d, *hm)
        if not t < end:
            drop["snapshot_not_before_end"] = drop.get("snapshot_not_before_end", 0) + 1
        elif start is not None and t < start:
            drop["snapshot_before_listing"] = drop.get("snapshot_before_listing", 0) + 1
        else:
            out.append((label, t))
    return out, drop


def pm_at(history: list[tuple[int, float]], snap_ts: float) -> tuple[float | None, float | None]:
    pts = [(t, p) for t, p in history if t <= snap_ts]
    if not pts:
        return None, None
    t, p = max(pts)
    return p, snap_ts - t


def strict_quote(get_quote: Callable[[str], Quote | None], snap_ts: float) -> Callable[[str], Quote | None]:
    def f(tk):
        q = get_quote(tk)
        if q is None or (not math.isnan(q.ts) and q.ts > snap_ts):
            return None
        return q
    return f


def option_row(*, mid: float, age: float, strike: float, chain: dict, get_quote, snap: datetime, res_date: date,
               fee=NO_FEE, meta: dict | None = None, p=PARAMS) -> dict:
    snap_ts = snap.timestamp()
    pm = dict(mid=mid, bid=mid, ask=mid, bid_size=None, ask_size=None, age_s=age, spread_assumed=False)
    r = score_row(pm=pm, strike=strike, chain=chain, get_quote=strict_quote(get_quote, snap_ts), snap_ts=snap_ts,
                  expiry_close_ts=et_dt(res_date, 16, 0).timestamp(), clean=True, live=False, fee=fee, meta=meta)
    if r.get("status") == "scored":
        r["opt_half_band"] = (r["p_hi"] - r["p_lo"]) / 2
        r["opt_comm_per_dollar"] = commission_per_share(r["width"])
    return r


def pm_market_rows(m: dict, *, history_fn, chain_fn, quote_fn, prev_session_fn, p=PARAMS) -> tuple[list[dict], dict]:
    rd = date.fromisoformat(m["res_date"])
    end = _iso(m["end"])
    start = _iso(m.get("start") or "")
    snaps, drop = snapshots(rd, start, end, prev_session_fn(rd), p)
    rows: list[dict] = []
    if not snaps:
        return rows, drop
    a = int(snaps[0][1].timestamp()) - p.hist_pad_before
    b = int(snaps[-1][1].timestamp()) + p.hist_pad_after
    hist = history_fn(m["token"], a, b)
    chain = None
    for label, snap in snaps:
        meta = dict(venue="polymarket", market_id=m["id"], ticker=m["ticker"], kind=m["kind"], res_date=m["res_date"],
                    event=f"{m['ticker']}|{m['res_date']}", snapshot=label, snap_utc=snap.astimezone(UTC).isoformat(),
                    strike=float(m["strike"]), hist_points=len(hist))
        mid, age = pm_at(hist, snap.timestamp())
        if mid is None:
            rows.append({**meta, "status": "no_pm_price"})
            continue
        meta.update(pm_mid=mid, pm_age_s=age)
        if age > p.pm_max_age:
            rows.append({**meta, "status": "pm_stale"})
            continue
        if mid == p.placeholder:
            rows.append({**meta, "status": "pm_placeholder"})
            continue
        if not (0.02 <= mid <= 0.98):
            rows.append({**meta, "status": "pm_extreme"})
            continue
        if chain is None:
            chain = chain_fn(m["ticker"], m["res_date"]) or {}
        if not chain:
            rows.append({**meta, "status": "no_clean_expiry"})
            continue
        r = option_row(mid=mid, age=age, strike=float(m["strike"]), chain=chain,
                       get_quote=lambda tk, s=snap: quote_fn(tk, s), snap=snap, res_date=rd, meta=meta, p=p)
        rows.append(r)
    return rows, drop


def is_scored(r: dict) -> bool:
    return r.get("status") == "scored" and bool(r.get("clean")) and r.get("pm_mid") != PARAMS.placeholder


def kalshi_event_ticker(series: str, d: date) -> str:
    return f"{series}-{d.strftime('%y%b%d').upper()}H1600"


def kalshi_event_markets(http: ds.Http, event_ticker: str) -> tuple[list[dict], str]:
    d = http.get_json(f"{KALSHI}/historical/markets", {"event_ticker": event_ticker, "limit": 1000}, allow_status=(400, 404))
    ms = (d or {}).get("markets") or [] if isinstance(d, dict) else []
    if ms:
        return ms, "historical"
    d = http.get_json(f"{KALSHI}/markets", {"event_ticker": event_ticker, "limit": 1000}, allow_status=(400, 404))
    return ((d or {}).get("markets") or [] if isinstance(d, dict) else []), "live"


def _f(x) -> float | None:
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def kalshi_select(markets: list[dict], top: int = PARAMS.kalshi_top) -> list[dict]:
    ok = [m for m in markets if m.get("strike_type") in ("greater", "greater_or_equal") and m.get("floor_strike") is not None
          and (_f(m.get("volume_fp")) or 0) > 0]
    return sorted(ok, key=lambda m: (-(_f(m.get("volume_fp")) or 0), m.get("ticker", "")))[:top]


def kalshi_candles(http: ds.Http, source: str, series: str, ticker: str, a: int, b: int) -> list[dict]:
    url = (f"{KALSHI}/historical/markets/{ticker}/candlesticks" if source == "historical"
           else f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks")
    d = http.get_json(url, {"start_ts": a, "end_ts": b, "period_interval": 1}, allow_status=(400, 404))
    return (d or {}).get("candlesticks", []) if isinstance(d, dict) else []


def _close(side: dict | None) -> float | None:
    side = side or {}
    v = _f(side.get("close_dollars"))
    return v if v is not None else _f(side.get("close"))


def kalshi_two_sided_at(candles: list[dict], snap_ts: float, max_age: float = PARAMS.pm_max_age) -> dict | None:
    best = None
    for c in candles:
        t = c.get("end_period_ts")
        if t is None or t > snap_ts:
            continue
        bid, ask = _close(c.get("yes_bid")), _close(c.get("yes_ask"))
        if bid is None or ask is None or not (0 < bid <= ask < 1):
            continue
        if best is None or t > best["t"]:
            best = {"t": float(t), "bid": bid, "ask": ask}
    if best and snap_ts - best["t"] <= max_age:
        return best
    return None


def kalshi_rows(m: dict, series: str, und: str, source: str, *, candles_fn, chain_fn, quote_fn, p=PARAMS) -> dict:
    close = _iso(m["close_time"])
    rd = close.astimezone(ET).date()
    snap = et_dt(rd, *p.s2_hhmm)
    opened = _iso(m.get("open_time") or "")
    meta = dict(venue="kalshi", market_id=m["ticker"], ticker=und, kind="kalshi_1600", res_date=rd.isoformat(),
                event=m.get("event_ticker"), snapshot="S2", snap_utc=snap.astimezone(UTC).isoformat(),
                strike=float(m["floor_strike"]), series=series, outcome={"yes": 1, "no": 0}.get(m.get("result")))
    if not snap < close or (opened is not None and opened > snap):
        return {**meta, "status": "snapshot_outside_life"}
    c = candles_fn(source, series, m["ticker"], int(snap.timestamp()) - p.kalshi_candle_pad, int(snap.timestamp()))
    ba = kalshi_two_sided_at(c, snap.timestamp())
    if ba is None:
        return {**meta, "status": "no_two_sided_candle"}
    mid = (ba["bid"] + ba["ask"]) / 2
    meta.update(pm_mid=mid, pm_age_s=snap.timestamp() - ba["t"], k_bid=ba["bid"], k_ask=ba["ask"],
                k_half_spread=(ba["ask"] - ba["bid"]) / 2, k_fee=KalshiFee().per_share(mid))
    if not (0.02 <= mid <= 0.98):
        return {**meta, "status": "pm_extreme"}
    chain = chain_fn(und, rd.isoformat()) or {}
    if not chain:
        return {**meta, "status": "no_clean_expiry"}
    return option_row(mid=mid, age=meta["pm_age_s"], strike=meta["strike"], chain=chain,
                      get_quote=lambda tk: quote_fn(tk, snap), snap=snap, res_date=rd, meta=meta, p=p)
