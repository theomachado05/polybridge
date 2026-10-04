from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

from ..cache import TTLCache
from ..chain import bounded
from . import chain as ch

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
YEAR_S = 365.0 * 86400.0
NAN = math.nan

STOCK_SNAPSHOT = "/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
STOCK_PREV = "/v2/aggs/ticker/{ticker}/prev"
OPTION_QUOTES = "/v3/quotes/{ticker}"
OPTION_CONTRACT = "/v3/snapshot/options/{underlying}/{ticker}"
DIVIDENDS = "/v3/reference/dividends"

SPOT_TTL_S = 30.0
NBBO_TTL_S = 30.0
DIV_TTL_S = 6 * 3600.0
MAX_NBBO = 30
DELAYED_MAX_AGE_S = 20 * 60

_SPOT = TTLCache(SPOT_TTL_S)
_NBBO = TTLCache(NBBO_TTL_S)
_DIVS = TTLCache(DIV_TTL_S)

_OCC = re.compile(r"^(?:O:)?([A-Z][A-Z0-9.]{0,6}?)(\d{6})([CP])(\d{8})$")


def fnum(x: Any) -> float:
    return ch._f(x)


def clean(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 6) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def parse_occ(ticker: str) -> dict | None:
    m = _OCC.match((ticker or "").strip().upper())
    if not m:
        return None
    und, ymd, cp, k = m.groups()
    try:
        exp = dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    return {"ticker": f"O:{und}{ymd}{cp}{k}", "underlying": und, "expiry": exp.isoformat(),
            "right": "call" if cp == "C" else "put", "strike": int(k) / 1000.0}


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def expiry_close(expiry: str | dt.date) -> dt.datetime:
    d = expiry if isinstance(expiry, dt.date) else dt.date.fromisoformat(str(expiry)[:10])
    return dt.datetime.combine(d, dt.time(16, 0), ET).astimezone(UTC)


def years_to_expiry(expiry: str | dt.date, now: dt.datetime | None = None) -> float:
    try:
        return (expiry_close(expiry) - (now or now_utc())).total_seconds() / YEAR_S
    except (TypeError, ValueError):
        return NAN


def market_state(now: dt.datetime | None = None) -> dict:
    from ..closed.session import session_at
    try:
        s = session_at(now or now_utc())
    except Exception:  # noqa: BLE001 - a clock error must not break a quote
        return {"market_open": None, "phase": "unknown", "label": "session unknown", "last_close": None,
                "next_open": None, "last_close_s": None}
    return {"market_open": bool(s.equities_open), "phase": s.phase, "label": s.label,
            "last_close": s.last_close.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "next_open": s.next_open.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "last_close_s": s.last_close.timestamp()}


def quote_age(updated_ns: int | None, now: dt.datetime | None = None) -> float | None:
    if not updated_ns:
        return None
    return max(0.0, (now or now_utc()).timestamp() - updated_ns / 1e9)


def is_stale(updated_ns: int | None, market: dict, now: dt.datetime | None = None,
             max_age_s: float = DELAYED_MAX_AGE_S) -> tuple[bool, str | None]:
    if not updated_ns:
        return True, "no timestamp"
    t = updated_ns / 1e9
    now_s = (now or now_utc()).timestamp()
    if market.get("market_open"):
        age = now_s - t
        return (age > max_age_s, f"{age / 60:.0f} min old during the session" if age > max_age_s else None)
    lc = market.get("last_close_s")
    if lc is None:
        return False, None
    gap = lc - t
    return (gap > max_age_s, f"predates the last close by {gap / 3600:.1f} h" if gap > max_age_s else None)


OI_LOW, OI_THIN = 100, 500
SPREAD_WIDE, SPREAD_VERY_WIDE = 0.10, 0.25
SIZE_VS_OI = 0.20


def liquidity_flags(*, bid: float, ask: float, mid: float, oi: float, volume: float, contracts: int | None = None,
                    quoted: bool = True, stale: bool = False) -> tuple[list[str], str]:
    flags: list[str] = []
    severe = moderate = 0
    if not quoted:
        flags.append("no_live_quote")
        moderate += 1
    elif math.isfinite(bid) and math.isfinite(ask) and math.isfinite(mid) and mid > 0:
        rel = (ask - bid) / mid
        rel -= 1e-9
        if rel > SPREAD_VERY_WIDE:
            flags.append("very_wide_spread")
            severe += 1
        elif rel > SPREAD_WIDE:
            flags.append("wide_spread")
            moderate += 1
    if math.isfinite(bid) and bid <= 0:
        flags.append("no_bid")
        moderate += 1
    if not math.isfinite(oi) or oi <= 0:
        flags.append("no_open_interest")
        severe += 1
    elif oi < OI_LOW:
        flags.append("low_open_interest")
        moderate += 1
    elif oi < OI_THIN:
        flags.append("modest_open_interest")
    if not math.isfinite(volume) or volume <= 0:
        flags.append("no_volume_last_session")
        moderate += 1
    if contracts and math.isfinite(oi) and oi > 0 and contracts / oi > SIZE_VS_OI:
        flags.append("size_vs_open_interest")
        moderate += 1
    if stale:
        flags.append("stale_quote")
        moderate += 1
    grade = "illiquid" if severe or moderate >= 3 else "thin" if moderate else "liquid"
    return flags, grade


GRADE_RANK = {"liquid": 0, "thin": 1, "illiquid": 2}


def worst_grade(grades: list[str]) -> str:
    return max(grades, key=lambda g: GRADE_RANK.get(g, 2)) if grades else "illiquid"


def _get(client, url: str, params: dict | None = None) -> dict:
    return ch._get(client, url, params)


def parse_spot(snap: dict | None, prev: dict | None, market_open: bool | None) -> dict:
    out: dict[str, Any] = {"price": None, "source": None, "updated_ns": None, "bid": None, "ask": None,
                           "change_pct": None}
    t = (snap or {}).get("ticker") or {}
    lt, day, prev_day, lq = t.get("lastTrade") or {}, t.get("day") or {}, t.get("prevDay") or {}, t.get("lastQuote") or {}
    cands = ([(fnum(lt.get("p")), "last_trade", lt.get("t"))] if market_open else []) + [
        (fnum(day.get("c")), "session_close", t.get("updated")),
        (fnum(lt.get("p")), "last_trade", lt.get("t")),
        (fnum(prev_day.get("c")), "prev_close", None)]
    for px, src, ts in cands:
        if math.isfinite(px) and px > 0:
            out.update(price=px, source=src, updated_ns=ch._ns(ts))
            break
    if out["price"] is None:
        res = ((prev or {}).get("results") or [{}])[0]
        px = fnum(res.get("c"))
        if math.isfinite(px) and px > 0:
            out.update(price=px, source="prev_close", updated_ns=ch._ns(fnum(res.get("t")) * 1e6))
    b, a = fnum(lq.get("p")), fnum(lq.get("P"))
    if math.isfinite(b) and math.isfinite(a) and 0 < b < a and (a - b) / ((a + b) / 2) < 0.01:
        out.update(bid=b, ask=a)
    cp = fnum(t.get("todaysChangePerc"))
    out["change_pct"] = cp if math.isfinite(cp) else None
    return out


def fetch_spot_sync(client, ticker: str, market_open: bool | None = None) -> dict:
    snap = prev = None
    try:
        snap = _get(client, STOCK_SNAPSHOT.format(ticker=ticker))
    except Exception:  # noqa: BLE001
        snap = None
    got = parse_spot(snap, None, market_open)
    if got["price"] is None:
        try:
            prev = _get(client, STOCK_PREV.format(ticker=ticker))
        except Exception:  # noqa: BLE001
            prev = None
        got = {**parse_spot(None, prev, market_open), **{k: v for k, v in got.items() if v is not None}}
    return got


def parse_nbbo(payload: dict | None) -> dict | None:
    rows = (payload or {}).get("results") or []
    if not rows:
        return None
    r = rows[0]
    b, a = fnum(r.get("bid_price")), fnum(r.get("ask_price"))
    if not (math.isfinite(b) and math.isfinite(a)) or b < 0 or a <= 0 or b > a:
        return None
    return {"bid": b, "ask": a, "bid_size": fnum(r.get("bid_size")), "ask_size": fnum(r.get("ask_size")),
            "updated_ns": ch._ns(r.get("sip_timestamp")), "timeframe": (payload or {}).get("status")}


def fetch_nbbo_sync(client, opt_ticker: str) -> dict | None:
    return parse_nbbo(_get(client, OPTION_QUOTES.format(ticker=opt_ticker),
                           {"order": "desc", "sort": "timestamp", "limit": 1}))


def fetch_contract_sync(client, underlying: str, opt_ticker: str) -> tuple[ch.OptionQuote | None, float]:
    payload = _get(client, OPTION_CONTRACT.format(underlying=underlying, ticker=opt_ticker))
    r = (payload or {}).get("results") or {}
    q = ch.parse_result(r) if isinstance(r, dict) else None
    spot = fnum((r.get("underlying_asset") or {}).get("price")) if isinstance(r, dict) else NAN
    return q, spot


def parse_dividends(payload: dict | None, start: dt.date, end: dt.date) -> dict:
    rows = [r for r in (payload or {}).get("results") or [] if r.get("ex_dividend_date")]
    out: dict[str, Any] = {"status": "none_in_horizon", "ex_date": None, "amount": None, "source": "massive_dividends"}
    if not rows:
        out["status"] = "no_dividend_history"
        return out
    rows.sort(key=lambda r: r["ex_dividend_date"])
    for r in rows:
        ex = dt.date.fromisoformat(r["ex_dividend_date"][:10])
        if start <= ex <= end:
            return {**out, "status": "declared", "ex_date": ex.isoformat(), "amount": fnum(r.get("cash_amount"))}
    last = rows[-1]
    freq = fnum(last.get("frequency"))
    if math.isfinite(freq) and freq > 0:
        ex = dt.date.fromisoformat(last["ex_dividend_date"][:10])
        step = dt.timedelta(days=round(365 / freq))
        while ex < start:
            ex += step
        if ex <= end:
            return {**out, "status": "projected", "ex_date": ex.isoformat(), "amount": fnum(last.get("cash_amount"))}
    return out


def fetch_dividends_sync(client, ticker: str, start: dt.date, end: dt.date) -> dict:
    p = _get(client, DIVIDENDS, {"ticker": ticker, "order": "desc", "sort": "ex_dividend_date", "limit": 8})
    return parse_dividends(p, start, end)


def _spot_or_raise(client, ticker: str, market_open: bool | None) -> dict:
    got = fetch_spot_sync(client, ticker, market_open)
    if got.get("price") is None:
        raise LookupError("no underlying price")
    return got


async def get_spot(client, ticker: str, market_open: bool | None = None) -> tuple[dict, bool]:
    try:
        return await _SPOT.get_or_set(("spot", ticker), lambda: bounded(_spot_or_raise, client, ticker, market_open))
    except Exception:  # noqa: BLE001
        return {"price": None, "source": None, "updated_ns": None, "bid": None, "ask": None, "change_pct": None}, False


async def get_nbbo(client, opt_ticker: str) -> dict | None:
    try:
        v, stale = await _NBBO.get_or_set(("nbbo", opt_ticker), lambda: bounded(fetch_nbbo_sync, client, opt_ticker))
    except Exception:  # noqa: BLE001
        return None
    return None if v is None else {**v, "cache_stale": stale}


async def get_nbbos(client, tickers: list[str]) -> dict[str, dict | None]:
    tickers = list(dict.fromkeys(t for t in tickers if t))[:MAX_NBBO]
    got = await asyncio.gather(*(get_nbbo(client, t) for t in tickers), return_exceptions=True)
    return {t: (g if isinstance(g, dict) else None) for t, g in zip(tickers, got)}


async def get_dividends(client, ticker: str, start: dt.date, end: dt.date) -> dict:
    try:
        v, _ = await _DIVS.get_or_set(("div", ticker, start, end),
                                      lambda: bounded(fetch_dividends_sync, client, ticker, start, end))
        return v
    except Exception:  # noqa: BLE001
        return {"status": "unknown", "ex_date": None, "amount": None, "source": "massive_dividends (unavailable)"}


def apply_nbbo(q: ch.OptionQuote, nbbo: dict | None) -> ch.OptionQuote:
    if nbbo and math.isfinite(nbbo["bid"]) and math.isfinite(nbbo["ask"]):
        return dataclasses.replace(q, bid=nbbo["bid"], ask=nbbo["ask"], mid=(nbbo["bid"] + nbbo["ask"]) / 2.0,
                                   mark_source="quote", updated_ns=nbbo.get("updated_ns") or q.updated_ns)
    return q


def reset_caches() -> None:
    global _SPOT, _NBBO, _DIVS
    _SPOT, _NBBO, _DIVS = TTLCache(SPOT_TTL_S), TTLCache(NBBO_TTL_S), TTLCache(DIV_TTL_S)
