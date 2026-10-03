"""Tick sources for the bridge loop.

Each source is an async iterator of ``Tick``: a ``(ts_ns, p)`` pair (``p`` = the market's raw YES mid, for the UI
and the legacy Engine) that also carries ``.fields``, the hedgecore ``MarketTick`` fields in the market's own YES
orientation (direction is applied later, in exactly one place: ``app.pipeline.ticks.orient_to_adverse``).

Honesty rules (same as the fit pipeline):
- A field the source does not have is NaN, never invented. ``eightk_score`` is 0 (= none, per the contract).
- Live (``LiveSource``): the primary venue's order book (Polymarket CLOB ``/book`` for the YES token, or the Kalshi
  orderbook), top 5 levels each side; ``no_bid = 1 - yes_ask`` and ``no_ask = 1 - yes_bid`` (YES and NO are one book
  on both venues). ``p_other_venue`` = the twin market's YES mid on the other venue when a twin is given and its
  book has both sides, else NaN. ``under_*`` from the broker's quote source (Massive), refreshed at most every
  ``equity_interval_s``; ``under_bid``/``under_ask`` only when the quote has a spread.
- Options (``OptionsEnricher``, opportunity bridges): for a threshold question ``app.options.match`` can map,
  ``app.options.enrich.enrich_market`` fills ``opt_mid`` / ``opt_delta`` / ``opt_iv`` / ``opt_implied_prob`` from the
  Massive chain snapshot (refreshed every ``refresh_s``; network-free in between) and ``eightk_score`` for a
  single-stock underlying (NaN when no 8-K data covers the date, and for indices / ETFs). Unmapped questions, no
  key or no listed contracts leave the option fields NaN.
- Replay (``ReplaySource``): the recorded mid (``yes_bid = yes_ask = p``, as in the fit replays) plus any other
  MarketTick field the JSONL row carries; ``under_px`` from recorded equity bars as of the row's ORIGINAL time
  (bar close known at that time), else NaN.
"""
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

Level = tuple[float, float]  # (px, qty)


class SourceError(RuntimeError):
    """The tick source failed and cannot continue."""


class Tick(tuple):
    """``(ts_ns, p)`` with the full MarketTick ``fields`` attached (raw YES orientation, NaN = unknown)."""

    def __new__(cls, ts_ns: int, p: float, fields: dict[str, float] | None = None, venue: int = 0) -> "Tick":
        t = super().__new__(cls, (int(ts_ns), float(p)))
        t.fields = fields if fields is not None else mid_only_fields(p)
        t.venue = venue
        return t

    @property
    def ts_ns(self) -> int:
        return self[0]

    @property
    def p(self) -> float:
        return self[1]


def as_tick(x: Any) -> Tick:
    """Accept a Tick or a bare (ts_ns, p) pair (e.g. a test source)."""
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
    """A mid-price-only tick: yes_bid = yes_ask = p (the spread is unknown), NO = 1 - p, everything else NaN."""
    f = blank_fields()
    f["yes_bid"] = f["yes_ask"] = float(p)
    f["no_bid"] = f["no_ask"] = 1.0 - float(p)
    return f


def book_fields(bids: list[Level], asks: list[Level]) -> dict[str, float]:
    """YES book (best first) -> MarketTick quote and depth fields."""
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


# ---------------------------------------------------------------- venue books

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
    """CLOB ``/book`` for one token: (bids best first, asks best first), top 5 each. The API's own ordering is not
    relied on: bids are sorted by price descending, asks ascending."""
    r = await http.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=POLL_TIMEOUT)
    r.raise_for_status()
    j = r.json() or {}
    bids = sorted(_levels(j.get("bids")), key=lambda lv: -lv[0])[:KDEPTH]
    asks = sorted(_levels(j.get("asks")), key=lambda lv: lv[0])[:KDEPTH]
    return bids, asks


def _kalshi_side(ob: dict, side: str) -> list[Level]:
    """Kalshi resting bids on one side as [(px in dollars, qty)]: ``<side>_dollars`` ([["0.4500", qty]]) or the
    legacy integer cents ``<side>`` ([[45, qty]])."""
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
    """Kalshi ``/markets/{ticker}/orderbook`` as the YES book. Kalshi lists bids only: YES bids are the ``yes`` side;
    a NO bid at q is a YES ask at 1 - q (same size)."""
    r = await http.get(f"{KALSHI_API}/markets/{ticker}/orderbook", params={"depth": KDEPTH}, timeout=POLL_TIMEOUT)
    r.raise_for_status()
    ob = (r.json() or {}).get("orderbook") or {}
    bids = sorted(_kalshi_side(ob, "yes"), key=lambda lv: -lv[0])[:KDEPTH]
    asks = sorted(((1.0 - px, q) for px, q in _kalshi_side(ob, "no")), key=lambda lv: lv[0])[:KDEPTH]
    return bids, asks


# ---------------------------------------------------------------- sources

EquityQuote = Callable[[], Awaitable[Any]]  # -> object with .mid and .half_spread (broker Quote), or None
OptionsHook = Callable[[dict, int], Awaitable[dict]]  # (fields, ts_ns) -> fields with opt_* / eightk_score filled
INDEX_LIKE = ("SPY", "QQQ", "IWM", "DIA")


class OptionsEnricher:
    """Fills a tick's option fields (and the 8-K score) for one prediction market's threshold question.

    ``question`` / ``end_date`` may be given, or resolved lazily by ``resolve`` (async () -> (question, end_date)).
    The first call (and one every ``refresh_s``) runs ``enrich_market`` (match + chain refresh + live 8-K refresh +
    enrich, bounded by ``timeout_s``); calls in between re-enrich from the cached snapshot without network. Never
    raises: on any failure the fields stay NaN. ``context()`` exposes what the bridge needs to price option legs:
    the matched underlying / strike, the listed expiry and bracketing strikes, and the chain snapshot."""

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
            out["eightk_score"] = NAN  # indices and ETFs file no 8-Ks: not available, not "none"
        if "ts_ns" not in fields:
            out.pop("ts_ns", None)
        return out


class LiveSource:
    """Polls the primary venue's book every ``interval_s`` (plus the twin's book and the equity quote).

    ``primary``: "polymarket" (``market_id`` = the YES token id) or "kalshi" (``market_id`` = the market ticker).
    ``twin``: (source, id) of the same question on the other venue, or None. Only a failure of the primary book (and
    of the Polymarket midpoint fallback) counts toward ``max_failures`` consecutive failures -> SourceError; a twin or
    equity failure leaves those fields NaN for that tick."""

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
    def token_id(self) -> str:  # backward compatible name
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
        """One tick, or raises when the primary venue gave nothing usable."""
        book_task = asyncio.ensure_future(self._book(http, self.primary, self.market_id))
        twin_mid, quote = await asyncio.gather(self._twin_mid(http), self._equity())
        try:
            bids, asks = await book_task
        except Exception:
            bids, asks = [], []
        p = book_mid(bids, asks)
        if p is None and self.primary == "polymarket":  # one-sided or empty book: fall back to the CLOB midpoint
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
        if self.options is not None:  # opt_* / eightk_score for a mapped threshold question; NaN on any failure
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


# ReplaySource only re-bases its schedule when the consumer is later than this; a sleep that overshoots by a few
# milliseconds is timer jitter, not a slow consumer, and re-basing on it would drift the recorded spacing.
REPLAY_REBASE_NS = 50_000_000


class ReplaySource:
    """Reads JSONL ``{ts_ns, p, ...}`` and re-emits it on the wall clock: the first tick is stamped "now" and recorded
    gaps are preserved divided by ``speed`` (speed 3600 plays hourly history at one tick per second). When the consumer
    falls behind by more than 50 ms (a slow broker call between ticks; a smaller sleep overshoot is ignored), the
    schedule shifts by the delay instead of catching up: every tick is stamped when it is handed over, so a replay tick
    is never "stale" because of the backend's own latency.
    speed <= 0 means no sleeping and each tick is stamped with the current time (used by tests).
    Rows with a non-finite p are skipped. ``bars``: recorded equity closes [(known_at_s, close)] joined as of each
    row's original time (see ``app.pipeline.ticks.recorded_bars``)."""

    def __init__(self, path: str | Path, speed: float = 1.0, bars: list[tuple[int, float]] | None = None) -> None:
        self.path, self.speed, self.bars = Path(path), speed, bars or []
        self._bar_t = [b[0] for b in self.bars]

    def fields_for(self, row: dict, p: float) -> dict[str, float]:
        f = mid_only_fields(p)
        for k in TICK_FIELDS:  # whatever the recording has, it keeps
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
                    # The consumer (the bridge awaiting its broker) fell behind the schedule: re-base the clock so
                    # this tick is stamped now and the gaps after it keep their recorded spacing. A replayed tick
                    # handed over late is not old data; stamping it at its past slot would make the engine's
                    # wall-clock staleness gate hold it (and the ticks behind it) for the backend's own latency.
                    start += now - target
                    target = now
                yield Tick(min(target, time.time_ns()), p, fields, venue)  # never future-dated vs. now_ns
            else:
                yield Tick(time.time_ns(), p, fields, venue)
