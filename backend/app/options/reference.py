from __future__ import annotations

import asyncio
import bisect
import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..cache import TTLCache
from ..chain import bounded, make_client
from . import chain as ch
from . import quotes as qt

RATE = 0.04
STALE_OPTION_S = 600
MAX_STEP_OUT = 2
MAX_EXPIRY_GAP_DAYS = 45
MAX_EXPIRY_TRIES = 3
CENTRAL_MULTIPLE = 2.0
FEED_DELAY_S = 15 * 60
STRIKE_WINDOW = 0.25
REF_TTL_S = 30.0
CHAIN_TTL_S = 60.0
TOTAL_TIMEOUT_S = 20.0
INDEX = {"SPX": ("I:SPX", "SPXW"), "I:SPX": ("I:SPX", "SPXW"), "^SPX": ("I:SPX", "SPXW"), "^GSPC": ("I:SPX", "SPXW")}

STATUS = "OPEN LEAD, unvalidated (touch tickets); reference only, not a trade signal"
SOURCE = ("Massive: /v3/snapshot/options (listed contracts) and /v3/quotes (last NBBO per leg, 15-minute delayed "
          "during the session)")
METHOD_NOTE = (
    "Rules of research/s21_options_anchor/METHOD.md section 3. Expiry: the first listed expiry on or after the last "
    "weekday of the ticket window that gives two usable legs (at most 45 days later, at most 3 expiries tried). Strikes: "
    "the two listed strikes bracketing the level (its neighbours if it is listed), a leg without a usable quote moved "
    "outward at most twice. Finish beyond = call spread long the lower strike ('above') or put spread long the higher "
    "strike ('below'), divided by the width and grossed up by exp(0.04 x years); lo/hi cross the spread both ways. "
    "Touch = min(1, 2 x finish beyond): the reflection-principle approximation, which ignores drift; the option expiry "
    "may be later than the ticket window, which makes it a little high. American options read as European. A zero bid "
    "is accepted and flagged.")
_TICKER = re.compile(r"^(?:I:|\^)?[A-Z][A-Z.]{0,7}$")

_REF = TTLCache(REF_TTL_S)
_CHAINS = TTLCache(CHAIN_TTL_S)


def reset_caches() -> None:
    global _REF, _CHAINS
    _REF, _CHAINS = TTLCache(REF_TTL_S), TTLCache(CHAIN_TTL_S)


@dataclass(frozen=True)
class Leg:
    ticker: str
    strike: float
    bid: float
    ask: float
    ts: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def bracket_indices(strikes: Sequence[float], k: float) -> tuple[int, int] | None:
    s = list(strikes)
    j = bisect.bisect_left(s, k - 1e-9)
    if j < len(s) and abs(s[j] - k) < 1e-6:
        lo, hi = j - 1, j + 1
    else:
        lo, hi = j - 1, j
    if lo < 0 or hi >= len(s):
        return None
    return lo, hi


def usable(leg: Leg | None, instant: float, now: float) -> bool:
    if leg is None or not (math.isfinite(leg.bid) and math.isfinite(leg.ask)):
        return False
    if not (leg.ask > 0 and leg.ask >= leg.bid >= 0):
        return False
    return math.isfinite(leg.ts) and instant - leg.ts <= STALE_OPTION_S and leg.ts <= now + 60


@dataclass
class SpreadProb:
    k_lo: float
    k_hi: float
    long: Leg
    short: Leg
    t_years: float
    stepped: int = 0
    rate: float = RATE

    @property
    def width(self) -> float:
        return self.k_hi - self.k_lo

    @property
    def _gross(self) -> float:
        return math.exp(self.rate * max(self.t_years, 0.0)) / self.width

    @property
    def raw_mid(self) -> float:
        return (self.long.mid - self.short.mid) * self._gross

    @property
    def p_mid(self) -> float:
        return _clamp(self.raw_mid)

    @property
    def p_lo(self) -> float:
        return _clamp((self.long.bid - self.short.ask) * self._gross)

    @property
    def p_hi(self) -> float:
        return _clamp((self.long.ask - self.short.bid) * self._gross)

    @property
    def noarb_violation(self) -> bool:
        return not (-1e-9 <= self.raw_mid <= 1 + 1e-9)


def touch_from(p: float) -> float:
    return min(1.0, CENTRAL_MULTIPLE * p)


async def pick_spread(strikes: Sequence[float], level: float, above: bool,
                      get_leg: Callable[[float], Any], t_years: float, instant: float, now: float) -> SpreadProb | None:
    s = sorted(strikes)
    ij = bracket_indices(s, level)
    if ij is None:
        return None
    lo, hi = ij
    q_lo = q_hi = None
    stepped = 0
    for n in range(MAX_STEP_OUT + 1):
        want_lo = q_lo is None and lo - n >= 0
        want_hi = q_hi is None and hi + n < len(s)
        got_lo, got_hi = await asyncio.gather(get_leg(s[lo - n]) if want_lo else _none(),
                                              get_leg(s[hi + n]) if want_hi else _none())
        if want_lo and usable(got_lo, instant, now):
            q_lo, lo, stepped = got_lo, lo - n, stepped + n
        if want_hi and usable(got_hi, instant, now):
            q_hi, hi, stepped = got_hi, hi + n, stepped + n
        if q_lo is not None and q_hi is not None:
            break
    if q_lo is None or q_hi is None:
        return None
    long_leg, short_leg = (q_lo, q_hi) if above else (q_hi, q_lo)
    return SpreadProb(s[lo], s[hi], long_leg, short_leg, t_years, stepped=stepped)


async def _none() -> None:
    return None


def end_session_day(window_end: dt.date) -> dt.date:
    d = window_end
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def underlying_and_root(ticker: str) -> tuple[str, str]:
    t = ticker.strip().upper()
    if t in INDEX:
        return INDEX[t]
    return t, t


def data_instant(now: dt.datetime) -> tuple[dt.datetime, dict, str]:
    market = qt.market_state(now)
    if market.get("market_open"):
        inst = now - dt.timedelta(seconds=FEED_DELAY_S)
        return inst, market, ("live session: Massive quotes delayed about 15 minutes; reference as of "
                              f"{inst.astimezone(qt.ET):%H:%M} ET")
    lc = market.get("last_close")
    if lc is None:
        return now, market, "session unknown: the latest available quotes"
    close = dt.datetime.fromisoformat(lc.replace("Z", "+00:00"))
    c_et = close.astimezone(qt.ET)
    phase = market.get("phase") or "closed"
    why = {"weekend": "weekend", "holiday": "holiday", "overnight": "overnight", "pre_market": "pre-market",
           "after_hours": "after hours"}.get(phase, phase)
    return close, market, (f"market closed ({why}): {c_et:%A}'s close ({c_et:%Y-%m-%d %H:%M} ET), the last session's "
                           "quotes, not tradable now")


def _fetch_contracts_sync(client, underlying: str, params: dict) -> ch.Chain:
    pages = ch.fetch_pages(client, underlying, params)
    chain = ch.parse_snapshot(underlying, pages)
    chain.truncated = bool(pages and (pages[-1] or {}).get("next_url"))
    return chain


async def _contracts(client, underlying: str, kind: str, d0: dt.date, level: float) -> ch.Chain:
    params = ch.snapshot_params(d0, d0 + dt.timedelta(days=MAX_EXPIRY_GAP_DAYS), level * (1 - STRIKE_WINDOW),
                                level * (1 + STRIKE_WINDOW), kind)
    key = (underlying, tuple(sorted(params.items())))
    chain, _ = await _CHAINS.get_or_set(key, lambda: bounded(_fetch_contracts_sync, client, underlying, params))
    return chain


def _listed(chain: ch.Chain, root: str, kind: str) -> dict[str, dict[float, str]]:
    pat = re.compile(rf"^O:{re.escape(root)}\d{{6}}{'C' if kind == 'call' else 'P'}\d{{8}}$")
    out: dict[str, dict[float, str]] = {}
    for q in chain.quotes:
        if q.kind == kind and pat.match(q.ticker or "") and q.shares_per_contract == 100 and math.isfinite(q.strike):
            out.setdefault(q.expiry, {})[q.strike] = q.ticker
    return dict(sorted(out.items()))


def _iso(t: float | None) -> str | None:
    if t is None or not math.isfinite(t):
        return None
    return dt.datetime.fromtimestamp(t, qt.UTC).isoformat().replace("+00:00", "Z")


def _band(mid: float, lo: float, hi: float) -> dict:
    return {"mid": round(mid, 6), "lo": round(lo, 6), "hi": round(hi, 6)}


async def _compute(client, ticker: str, level: float, direction: str, window_end: dt.date, kind: str,
                   now: dt.datetime, base: dict) -> dict:
    above = direction == "above"
    opt_kind = "call" if above else "put"
    underlying, root = underlying_and_root(ticker)
    instant, market, label = data_instant(now)
    inst_s, now_s = instant.timestamp(), now.timestamp()
    data_day = instant.astimezone(qt.ET).date()
    d0 = end_session_day(window_end)
    base.update(session_label=label, market_open=market.get("market_open"), market_phase=market.get("phase"),
                as_of=_iso(inst_s), underlying=underlying, option_root=root, end_session_day=d0.isoformat(),
                option_type=opt_kind)
    if window_end < data_day:
        return {**base, "reason": "the ticket's window ended before the data instant"}
    try:
        chain = await _contracts(client, underlying, opt_kind, d0, level)
    except Exception as e:  # noqa: BLE001
        return {**base, "reason": f"Massive unavailable ({type(e).__name__})"}
    listed = _listed(chain, root, opt_kind)
    expiries = [e for e in listed if qt.years_to_expiry(e, now) > 0
                and 0 <= (dt.date.fromisoformat(e) - d0).days <= MAX_EXPIRY_GAP_DAYS]
    tried, reason, legs_seen = 0, f"no listed expiry within {MAX_EXPIRY_GAP_DAYS} days of the window's end", {}
    for exp in expiries:
        tried += 1
        strikes = listed[exp]
        ks = sorted(strikes)

        async def get_leg(k: float, _s=strikes) -> Leg | None:
            tk = _s[k]
            nb = await qt.get_nbbo(client, tk)
            leg = None
            if nb and nb.get("updated_ns"):
                leg = Leg(tk, k, nb["bid"], nb["ask"], nb["updated_ns"] / 1e9)
            legs_seen[tk] = leg
            return leg

        t_years = (dt.date.fromisoformat(exp) - data_day).days / 365.0
        sp = await pick_spread(ks, level, above, get_leg, t_years, inst_s, now_s)
        if sp is None:
            if bracket_indices(ks, level) is None:
                reason = "no listed strikes bracket the level"
            elif not any(legs_seen.values()):
                reason = "no quote on the bracketing strikes"
            else:
                reason = "no usable pair of leg quotes (stale, or no offer)"
            if tried >= MAX_EXPIRY_TRIES:
                break
            continue
        fb = _band(sp.p_mid, sp.p_lo, sp.p_hi)
        tc = _band(touch_from(sp.p_mid), touch_from(sp.p_lo), touch_from(sp.p_hi))
        central = tc if kind == "touch" else fb
        leg_rows = [{"role": role, "ticker": lg.ticker, "strike": lg.strike, "bid": lg.bid, "ask": lg.ask,
                     "quote_time": _iso(lg.ts), "age_vs_instant_s": round(inst_s - lg.ts, 1)}
                    for role, lg in (("long", sp.long), ("short", sp.short))]
        notes = []
        exp_d = dt.date.fromisoformat(exp)
        if exp_d > window_end and kind == "touch":
            notes.append(f"the option expiry ({exp}) is {(exp_d - window_end).days} days after the ticket window ends: "
                         "the touch reference is a little high")
        if sp.stepped:
            notes.append(f"a leg was moved outward by {sp.stepped} listed strike(s) for a usable quote")
        zero_bid = sp.long.bid <= 0 or sp.short.bid <= 0
        if zero_bid:
            notes.append("a leg has a zero bid (accepted, as in S21; the lo bound leans on it)")
        if sp.noarb_violation:
            notes.append("the spread mid is outside 0..1 per unit width (inconsistent quotes); clamped")
        if chain.truncated:
            notes.append("contract list truncated at the page limit; later expiries may be missing")
        return {**base, "available": True, "reason": None,
                "finish_beyond": fb, "touch": tc,
                "central": {"kind": kind, **central},
                "lower_bound": fb["mid"] if kind == "touch" else None,
                "expiry": exp, "expiry_rank": tried, "days_expiry_after_window_end": (exp_d - window_end).days,
                "years_to_expiry": round(t_years, 6),
                "strikes": {"lo": sp.k_lo, "hi": sp.k_hi, "width": sp.width, "stepped": sp.stepped,
                            "width_pct_of_level": round(100.0 * sp.width / level, 4)},
                "legs": leg_rows, "zero_bid_leg": zero_bid, "noarb_violation": sp.noarb_violation,
                "quote_times": {"oldest": _iso(min(sp.long.ts, sp.short.ts)),
                                "newest": _iso(max(sp.long.ts, sp.short.ts))},
                "notes": notes}
    out = {**base, "reason": reason, "expiries_tried": tried}
    if chain.truncated:
        out["notes"] = ["contract list truncated at the page limit; later expiries may be missing"]
    return out


def _base(ticker: str, level: float, direction: str, window_end: dt.date | None, kind: str) -> dict:
    return {"available": False, "reason": None, "ticker": ticker, "level": level, "direction": direction,
            "window_end": window_end.isoformat() if window_end else None, "kind": kind,
            "finish_beyond": None, "touch": None, "central": None, "expiry": None, "strikes": None,
            "as_of": None, "session_label": None, "status": STATUS, "method_note": METHOD_NOTE, "source": SOURCE,
            "label": "options reference (risk-neutral estimate from the bid/ask band; not a measured probability)"}


def _parse_date(x: Any) -> dt.date | None:
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


async def reference_for(ticker: str, level: float, direction: str, window_end: Any, kind: str = "touch", *,
                        client: Any = ..., now: dt.datetime | None = None) -> dict:
    tk = str(ticker or "").strip().upper()
    d = str(direction or "").strip().lower()
    k = str(kind or "").strip().lower()
    we = _parse_date(window_end)
    try:
        lv = float(level)
    except (TypeError, ValueError):
        lv = math.nan
    base = _base(tk, lv if math.isfinite(lv) else None, d, we, k)
    if not _TICKER.match(tk):
        return {**base, "reason": "ticker must look like NVDA, SPY or SPX"}
    if not (math.isfinite(lv) and lv > 0):
        return {**base, "reason": "level must be a positive number"}
    if d not in ("above", "below"):
        return {**base, "reason": "direction must be above or below"}
    if k not in ("touch", "finish"):
        return {**base, "reason": "kind must be touch or finish"}
    if we is None:
        return {**base, "reason": "window_end must be YYYY-MM-DD"}
    if client is ...:
        client = make_client()
    if client is None:
        return {**base, "reason": "MASSIVE_API_KEY not set"}
    now = now or qt.now_utc()
    key = (tk, round(lv, 6), d, we.isoformat(), k, int(now.timestamp() // 60))

    async def run() -> dict:
        return await asyncio.wait_for(_compute(client, tk, lv, d, we, k, now, dict(base)), TOTAL_TIMEOUT_S)

    try:
        out, _ = await _REF.get_or_set(key, run)
        return out
    except asyncio.TimeoutError:
        return {**base, "reason": f"timed out after {TOTAL_TIMEOUT_S:.0f} s (Massive slow)"}
    except Exception as e:  # noqa: BLE001 - never a 500
        return {**base, "reason": f"reference could not be built ({type(e).__name__})"}
