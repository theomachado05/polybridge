from __future__ import annotations

import asyncio
import bisect
import json
import math
import time
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from .markets import CLOB, polymarket_midpoint

KDEPTH = 5
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
POLL_TIMEOUT = httpx.Timeout(3.0)
NAN = math.nan
BOOK_FIELDS = [f"{side}_{kind}_{i}" for side in ("bid", "ask") for kind in ("px", "qty") for i in range(KDEPTH)]
TICK_FIELDS = (["yes_bid", "yes_ask", "no_bid", "no_ask"] + BOOK_FIELDS
               + ["p_other_venue", "under_px", "under_bid", "under_ask",
                  "opt_mid", "opt_delta", "opt_iv", "opt_implied_prob", "eightk_score"])

Level = tuple[float, float]


class SourceError(RuntimeError):
    pass


class Tick(tuple):

    def __new__(cls, ts_ns: int, p: float, fields: dict[str, float] | None = None, venue: int = 0,
                legs: dict[str, float] | None = None, recorded_ts_ns: int | None = None,
                settled: bool = False) -> "Tick":
        t = super().__new__(cls, (int(ts_ns), float(p)))
        t.fields = fields if fields is not None else mid_only_fields(p)
        t.venue = venue
        t.legs = legs
        t.recorded_ts_ns = recorded_ts_ns
        t.settled = bool(settled and legs)
        return t

    @property
    def ts_ns(self) -> int:
        return self[0]

    @property
    def p(self) -> float:
        return self[1]


def as_tick(x: Any) -> Tick:
    return x if isinstance(x, Tick) else Tick(x[0], x[1])


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def blank_fields() -> dict[str, float]:
    f = {k: NAN for k in TICK_FIELDS}
    f["eightk_score"] = 0.0
    return f


def mid_only_fields(p: float) -> dict[str, float]:
    f = blank_fields()
    f["yes_bid"] = f["yes_ask"] = float(p)
    f["no_bid"] = f["no_ask"] = 1.0 - float(p)
    return f


def book_fields(bids: list[Level], asks: list[Level]) -> dict[str, float]:
    f = blank_fields()
    for i in range(KDEPTH):
        if i < len(bids):
            f[f"bid_px_{i}"], f[f"bid_qty_{i}"] = bids[i]
        if i < len(asks):
            f[f"ask_px_{i}"], f[f"ask_qty_{i}"] = asks[i]
    if bids:
        f["yes_bid"] = bids[0][0]
        f["no_ask"] = 1.0 - bids[0][0]
    if asks:
        f["yes_ask"] = asks[0][0]
        f["no_bid"] = 1.0 - asks[0][0]
    return f


def book_mid(bids: list[Level], asks: list[Level]) -> float | None:
    return (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else None


def _levels(rows: Any, px_key: str = "price", qty_key: str = "size") -> list[Level]:
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            px, qty = _num(r.get(px_key)), _num(r.get(qty_key))
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            px, qty = _num(r[0]), _num(r[1])
        else:
            continue
        if px is not None and qty is not None and 0.0 <= px <= 1.0 and qty > 0:
            out.append((px, qty))
    return out


async def polymarket_book(http: httpx.AsyncClient, token_id: str) -> tuple[list[Level], list[Level]]:
    r = await http.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=POLL_TIMEOUT)
    r.raise_for_status()
    j = r.json() or {}
    bids = sorted(_levels(j.get("bids")), key=lambda lv: -lv[0])[:KDEPTH]
    asks = sorted(_levels(j.get("asks")), key=lambda lv: lv[0])[:KDEPTH]
    return bids, asks


def _kalshi_side(ob: dict, side: str) -> list[Level]:
    rows = ob.get(f"{side}_dollars")
    if rows:
        return _levels(rows)
    out = []
    for r in ob.get(side) or []:
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            c, q = _num(r[0]), _num(r[1])
            if c is not None and q is not None and 0 <= c <= 100 and q > 0:
                out.append((c / 100.0, q))
    return out


async def kalshi_book(http: httpx.AsyncClient, ticker: str) -> tuple[list[Level], list[Level]]:
    r = await http.get(f"{KALSHI_API}/markets/{ticker}/orderbook", params={"depth": KDEPTH}, timeout=POLL_TIMEOUT)
    r.raise_for_status()
    ob = (r.json() or {}).get("orderbook") or {}
    bids = sorted(_kalshi_side(ob, "yes"), key=lambda lv: -lv[0])[:KDEPTH]
    asks = sorted(((1.0 - px, q) for px, q in _kalshi_side(ob, "no")), key=lambda lv: lv[0])[:KDEPTH]
    return bids, asks


EquityQuote = Callable[[], Awaitable[Any]]
OptionsHook = Callable[[dict, int], Awaitable[dict]]
INDEX_LIKE = ("SPY", "QQQ", "IWM", "DIA")


class OptionsEnricher:

    def __init__(self, question: str | None = None, end_date: Any = None, *,
                 resolve: Callable[[], Awaitable[tuple[str | None, Any]]] | None = None,
                 refresh_s: float = 60.0, timeout_s: float = 10.0, enrich_market: Callable | None = None) -> None:
        self.question, self.end_date, self._resolve = question, end_date, resolve
        self.refresh_s, self.timeout_s = refresh_s, timeout_s
        self._enrich_market = enrich_market
        self._at = -math.inf
        self._resolved = question is not None
        self.detail: dict = {}
        self.chain: Any = None

    async def _question(self) -> str | None:
        if not self._resolved and self._resolve is not None:
            self._resolved = True
            try:
                self.question, end = await asyncio.wait_for(self._resolve(), self.timeout_s)
                self.end_date = self.end_date or end
            except Exception:
                self.question = None
        return self.question

    def supported(self) -> bool:
        return bool(self.detail.get("supported"))

    def context(self) -> dict | None:
        d = self.detail
        if not d.get("supported") or not d.get("expiry") or d.get("k_lo") is None or self.chain is None:
            return None
        return {"underlying": d.get("underlying_used"), "strike": d.get("strike_used"), "expiry": d["expiry"],
                "k_lo": float(d["k_lo"]), "k_hi": float(d["k_hi"]), "above": d.get("direction", "above") == "above",
                "chain": self.chain, "available": bool(d.get("available"))}

    async def __call__(self, fields: dict, ts_ns: int | None = None) -> dict:
        from .options import enrich as en
        from .options import chain as ch
        f = dict(fields)
        if ts_ns is not None:
            f.setdefault("ts_ns", ts_ns)
        try:
            q = await self._question()
            if not q:
                self.detail = {"supported": False, "reason": "no question text for this market"}
                return fields
            now = time.monotonic()
            if now - self._at >= self.refresh_s:
                self._at = now
                fn = self._enrich_market or en.enrich_market
                out, det = await asyncio.wait_for(fn(f, q, self.end_date), self.timeout_s)
                self.detail = det
                if det.get("supported"):
                    m = det.get("match") or {}
                    self.chain = (ch.chain_for(det.get("underlying_used"), det.get("strike_used"), m.get("expiry"))
                                  or ch.last_chain(det.get("underlying_used") or "") or self.chain)
            elif self.detail.get("supported") and self.chain is not None:
                d, m = self.detail, self.detail.get("match") or {}
                und = d.get("underlying_used") or ""
                tk = None if (und.startswith("I:") or und in INDEX_LIKE) else und
                out = en.enrich(f, und, d.get("strike_used"), m.get("expiry"),
                                above=m.get("direction", "above") == "above", chain=self.chain, eightk_ticker=tk)
            else:
                return fields
        except Exception:
            return fields
        und = self.detail.get("underlying_used") or ""
        if self.detail.get("supported") and (und.startswith("I:") or und in INDEX_LIKE):
            out["eightk_score"] = NAN
        if "ts_ns" not in fields:
            out.pop("ts_ns", None)
        return out


class LiveSource:

    def __init__(self, market_id: str, interval_s: float = 1.0, max_failures: int = 3,
                 http: httpx.AsyncClient | None = None, *, primary: str = "polymarket",
                 twin: tuple[str, str] | None = None, equity: EquityQuote | None = None,
                 equity_interval_s: float = 5.0, options: OptionsHook | None = None) -> None:
        self.market_id, self.interval_s, self.max_failures, self._http = market_id, interval_s, max_failures, http
        self.primary, self.twin, self.equity, self.equity_interval_s = primary, twin, equity, equity_interval_s
        self.options = options
        self._quote: Any = None
        self._quote_at = -math.inf

    @property
    def token_id(self) -> str:
        return self.market_id

    async def _book(self, http: httpx.AsyncClient, source: str, mid: str) -> tuple[list[Level], list[Level]]:
        return await (kalshi_book(http, mid) if source == "kalshi" else polymarket_book(http, mid))

    async def _twin_mid(self, http: httpx.AsyncClient) -> float:
        if not self.twin:
            return NAN
        try:
            m = book_mid(*await self._book(http, *self.twin))
        except Exception:
            return NAN
        return m if m is not None else NAN

    async def _equity(self) -> Any:
        if self.equity is None:
            return None
        now = time.monotonic()
        if now - self._quote_at >= self.equity_interval_s:
            self._quote_at = now
            try:
                self._quote = await asyncio.wait_for(self.equity(), 10.0)
            except Exception:
                self._quote = None
        return self._quote

    async def poll(self, http: httpx.AsyncClient) -> Tick:
        book_task = asyncio.ensure_future(self._book(http, self.primary, self.market_id))
        twin_mid, quote = await asyncio.gather(self._twin_mid(http), self._equity())
        try:
            bids, asks = await book_task
        except Exception:
            bids, asks = [], []
        p = book_mid(bids, asks)
        if p is None and self.primary == "polymarket":
            p = await polymarket_midpoint(http, self.market_id)
        if p is None:
            raise ValueError("no book and no midpoint")
        f = book_fields(bids, asks) if (bids or asks) else mid_only_fields(p)
        f["p_other_venue"] = twin_mid
        mid = _num(getattr(quote, "mid", None))
        if mid is not None and mid > 0:
            f["under_px"] = mid
            hs = _num(getattr(quote, "half_spread", None))
            if hs is not None and hs >= 0:
                f["under_bid"], f["under_ask"] = mid - hs, mid + hs
        ts = time.time_ns()
        if self.options is not None:
            try:
                f = {**f, **{k: v for k, v in (await self.options(f, ts)).items() if k in TICK_FIELDS}}
            except Exception:
                pass
        return Tick(ts, p, f, venue=1 if self.primary == "kalshi" else 0)

    async def __aiter__(self) -> AsyncIterator[Tick]:
        http = self._http or httpx.AsyncClient()
        failures = 0
        try:
            while True:
                try:
                    tick = await self.poll(http)
                except Exception as e:
                    failures += 1
                    if failures >= self.max_failures:
                        raise SourceError(f"live source failed {failures}x: {type(e).__name__}") from e
                else:
                    failures = 0
                    yield tick
                await asyncio.sleep(self.interval_s)
        finally:
            if self._http is None:
                await http.aclose()


REPLAY_REBASE_NS = 50_000_000


class ReplaySource:

    def __init__(self, path: str | Path, speed: float = 1.0, bars: list[tuple[int, float]] | None = None) -> None:
        self.path, self.speed, self.bars = Path(path), speed, bars or []
        self._bar_t = [b[0] for b in self.bars]

    @staticmethod
    def legs_for(row: dict) -> dict[str, float] | None:
        legs = row.get("opt_legs")
        if not isinstance(legs, dict) or not legs:
            return None
        out = {}
        for tk, v in legs.items():
            x = _num(v)
            if not isinstance(tk, str) or x is None or x < 0:
                return None
            out[tk] = x
        return out

    def fields_for(self, row: dict, p: float) -> dict[str, float]:
        f = mid_only_fields(p)
        for k in TICK_FIELDS:
            if k in row:
                v = _num(row[k])
                f[k] = v if v is not None else NAN
        if "under_px" not in row and self.bars:
            j = bisect.bisect_right(self._bar_t, int(row["ts_ns"]) // 1_000_000_000) - 1
            if j >= 0:
                f["under_px"] = self.bars[j][1]
        return f

    async def __aiter__(self) -> AsyncIterator[Tick]:
        start = time.time_ns()
        first: int | None = None
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            ts, p = int(row["ts_ns"]), float(row["p"])
            if not math.isfinite(p):
                continue
            fields = self.fields_for(row, p)
            venue = 1 if row.get("venue") in (1, "kalshi") else 0
            if first is None:
                first = ts
            if self.speed > 0:
                target = start + int((ts - first) / self.speed)
                now = time.time_ns()
                if target > now:
                    await asyncio.sleep((target - now) / 1e9)
                elif now - target > REPLAY_REBASE_NS:
                    start += now - target
                    target = now
                yield Tick(min(target, time.time_ns()), p, fields, venue, self.legs_for(row), ts,
                           bool(row.get("opt_settlement")))
            else:
                yield Tick(time.time_ns(), p, fields, venue, self.legs_for(row), ts, bool(row.get("opt_settlement")))
