"""Bridge loop: one bridge per approved hedge proposal drives the C++ hedgecore library from a tick source
and publishes tick/decision/fill/position events over SSE. hedgecore is imported lazily (engine group only).

Two engines:
- ``algo`` (the proposal or the body names a fitted family + preset/params): ``hedgecore.Algo`` for that family is fed
  full MarketTicks (book, other venue, equity quote). Its Order intents go to the broker; a fill calls
  ``Algo.on_fill``, a reject / expiry / cancel / broker error calls ``Algo.on_reject``, and any resting order of the
  bridge is cancelled before a new one is sent. The hedge reported is what the broker filled.
- ``legacy`` (no fit): the original ``hedgecore.Engine`` default spec on the adverse probability, unchanged.

Direction is applied in ONE place: ``app.pipeline.ticks.orient_to_adverse`` turns every tick into "YES = the outcome
that hurts the holder" before either engine sees it; hedgecore is always called with its default direction."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from .broker import Broker, OrderRequest, SimBroker, get_broker
from .models import AlgoChoice, MarketRef, Proposal
from .pipeline.engine_adapter import AlgoChoiceError, cap_coverage, normalize_manifest, resolve_algo
from .pipeline.ticks import orient_to_adverse, recorded_bars
from .store import NotFound, ProposalStore
from .ticks import TICK_FIELDS, LiveSource, ReplaySource, SourceError, Tick, as_tick

router = APIRouter()
HEARTBEAT_S = 15.0
MAX_EVENTS = 20_000
REPLAYS_DIR = Path(__file__).resolve().parents[1] / "replays"
NO_ENGINE = "engine not installed (uv sync --group engine)"
BROKER_TIMEOUT_S = 20.0  # an order never stalls the bridge loop longer than this
MAX_FILLS = 500
REPLAY_NOTE = "replay: priced at the current market, not the replayed time"
REPLAY_BROKER_NAME = "sim-replay"


def _load_engine():
    """Import hedgecore lazily; None when the engine group is not installed."""
    try:
        import hedgecore
    except ImportError:
        return None
    return hedgecore


class BridgeIn(BaseModel):
    proposal_id: str
    source: Literal["live", "replay"]
    market: MarketRef | None = None  # optional for market-event proposals (their own market is used)
    gap_per_share: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    direction: Literal["down_on_yes", "up_on_yes"] = "down_on_yes"  # which outcome hurts a long holder
    # Replay decisions are historical but fills are priced at today's market. By default a replay bridge trades a
    # throwaway in-memory simulator (never Webull, never the persistent account); set true to opt in to the account.
    replay_to_account: bool = False
    # The fitted algo to run (spec §3.4 hedgecore.Algo): a catalog family plus preset_index or params. Ignored when
    # the proposal already carries an algo (it was approved with it; a different one is a 409).
    family: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    preset_index: int | None = Field(default=None, ge=0)
    params: dict[str, float] | None = None
    # The same question on the other venue (e.g. the Kalshi twin of a Polymarket market) -> p_other_venue.
    twin: MarketRef | None = None


class Bridge:
    def __init__(self, proposal: Proposal, source: str, market: MarketRef, gap: float,
                 direction: str = "down_on_yes", replay_to_account: bool = False,
                 algo: dict | None = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.proposal_id, self.requested_source, self.market, self.gap = proposal.id, source, market, gap
        self.proposal = proposal
        self.direction = direction
        self.effective_source = source
        self.status = "running"
        self.started_at = dt.datetime.now(dt.UTC)
        self.events: list[tuple[str, dict]] = []
        self.dropped = 0
        self.cond = asyncio.Condition()
        self.reasons: Counter[str] = Counter()
        self.latencies: list[int] = []
        self.ticks = self.orders = 0
        self.hedge = 0.0
        self.task: asyncio.Task | None = None
        self.broker: Broker | None = None  # active broker for engine orders (None: no account attached)
        self.replay_to_account = replay_to_account
        self.replay_broker: Broker | None = None  # isolated in-memory sim used by replay bridges by default
        self.broker_name: str | None = None  # the broker that took the latest order (else the active one)
        self.broker_hedge = 0.0  # net short quantity actually filled by the broker (sell adds, buy reduces)
        self.fills: list[dict] = []
        self.broker_filled = self.broker_rejects = self.broker_errors = 0
        self.algo = algo  # {family, preset_index, params, source, coverage_cap, capped} or None (legacy Engine)
        self.choice: AlgoChoice | None = None  # what the algo was chosen as (idempotent re-POSTs are compared to it)
        # The bridge's open broker order: {order_id, instrument, side, qty, applied (filled qty already fed back)}.
        self.resting: dict | None = None
        self.cancels = 0
        self.cap_holds = 0  # sell intents the approved coverage cap clipped to zero
        self.equity_source: str | None = None  # where the last live under_px came from (None: no quote)
        self.equity_price = "live_quote"  # "live_quote" | "recorded" | "none": what under_px the algo can see

    async def emit(self, kind: str, data: dict, status: str | None = None) -> None:
        async with self.cond:
            if status:  # set atomically with the final event so streams end right after it
                self.status = status
            if len(self.events) >= MAX_EVENTS:  # bound memory on long live runs; indexes stay stable via `dropped`
                del self.events[: MAX_EVENTS // 2]
                self.dropped += MAX_EVENTS // 2
            self.events.append((kind, data))
            self.cond.notify_all()

    def _sandboxed(self) -> bool:
        return self.effective_source == "replay" and not self.replay_to_account

    def order_broker(self) -> Broker | None:
        """The broker for the next order. Replay bridges get an isolated in-memory sim (never Webull, never the
        persistent account) unless replay_to_account was set; it shares the active broker's market-data source."""
        if self.broker is None or not self._sandboxed():
            return self.broker
        if self.replay_broker is None:
            sim = self.broker if isinstance(self.broker, SimBroker) else getattr(self.broker, "sim", None)
            start = getattr(sim, "starting_cash", None) or 1_000_000.0
            self.replay_broker = SimBroker(None, getattr(sim, "quotes", None), start)
            self.replay_broker.name = REPLAY_BROKER_NAME
        return self.replay_broker

    def summary(self) -> dict:
        lat = sorted(self.latencies)
        q = lambda f: lat[min(len(lat) - 1, int(f * len(lat)))] if lat else None
        return {"bridge_id": self.id, "proposal_id": self.proposal_id, "ticker": self.proposal.ticker,
                "status": self.status, "direction": self.direction, "source": self.effective_source, "requested_source": self.requested_source,
                "started_at": self.started_at.isoformat(), "ticks": self.ticks, "orders": self.orders,
                "hedge": self.hedge, "reasons": dict(self.reasons),
                "broker": self.broker_name or getattr(self.broker, "name", None),
                "account_scope": "replay_sandbox" if self._sandboxed() else "account",
                "engine": "algo" if self.algo else "legacy",
                "algo": dict(self.algo) if self.algo else None,
                "resting_order": dict(self.resting) if self.resting else None, "cancels": self.cancels,
                "hedge_basis": "broker_fill" if self.algo else "engine_intent", "broker_hedge": self.broker_hedge,
                "coverage_cap": self.proposal.target_coverage if self.algo else None, "cap_holds": self.cap_holds,
                "equity_price": self.equity_price if self.algo else None, "equity_source": self.equity_source,
                "broker_coverage": self.broker_hedge / self.proposal.shares_held if self.proposal.shares_held else 0.0,
                "broker_filled": self.broker_filled,
                "broker_rejects": self.broker_rejects, "broker_errors": self.broker_errors,
                "last_fill": self.fills[-1] if self.fills else None,
                "shares_held": self.proposal.shares_held, "target_coverage": self.proposal.target_coverage,
                "coverage": self.hedge / self.proposal.shares_held if self.proposal.shares_held else 0.0,
                "basis": self.proposal.basis, "label": self.proposal.label,
                "market": self.market.model_dump(),
                "latency_ns": {"p50": q(0.5), "p99": q(0.99)}}


def _replay_speed(app) -> float:
    """app.state.replay_speed (tests) or POLYBRIDGE_REPLAY_SPEED; 1.0 = real time."""
    v = getattr(app.state, "replay_speed", None)
    if v is None:
        try:
            v = float(os.environ.get("POLYBRIDGE_REPLAY_SPEED", "1"))
        except ValueError:
            v = 1.0
    return v


def _replay_path(request: Request, *markets: MarketRef | None) -> Path | None:
    configured = getattr(request.app.state, "replay_path", None) or os.environ.get("POLYBRIDGE_REPLAY_PATH")
    if configured:
        return Path(configured)
    for market in markets:
        if market is None:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", market.id):
            raise HTTPException(422, "market.id must match [A-Za-z0-9_-]+ to select a replay file.")
        guess = REPLAYS_DIR / f"{market.id}.jsonl"
        if guess.is_file():
            return guess
    return None


def _resolve(prop: Proposal, body: BridgeIn) -> tuple[MarketRef, str]:
    """Market-event proposals carry their own market and direction; filing proposals take them from the body."""
    if prop.market is not None and prop.direction is not None:
        token = prop.market.token_id
        if token is None and body.market is not None and body.market.id == prop.market.id:
            token = body.market.token_id
        return prop.market.model_copy(update={"token_id": token}), prop.direction
    if body.market is None:
        raise HTTPException(422, "market is required for a filing-tags proposal.")
    return body.market, body.direction


def _fallback_path(app) -> Path | None:
    configured = getattr(app.state, "replay_path", None) or os.environ.get("POLYBRIDGE_REPLAY_PATH")
    return Path(configured) if configured else None


async def _send_to_broker(bridge: Bridge, order_qty: float) -> dict | None:
    """Route one engine order to the active broker: sell to add to the short hedge, buy to reduce it.
    Returns the fill record for the stream; never raises (a broker failure must not stop the bridge)."""
    broker = bridge.order_broker()
    if broker is None:
        return None
    bridge.broker_name = broker.name
    side = "sell" if order_qty > 0 else "buy"
    rec: dict = {"broker": broker.name, "side": side, "qty": abs(order_qty), "symbol": bridge.proposal.ticker}
    note = None
    if bridge.effective_source == "replay":
        note = REPLAY_NOTE
        rec["price_note"] = "priced at the current market, not the replayed time"
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
    try:
        req = OrderRequest(symbol=bridge.proposal.ticker, asset="equity", side=side, qty=abs(order_qty), type="market",
                           client_order_id=f"{bridge.id}-{bridge.orders}", tag=bridge.id, note=note)
        o = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
        bridge.broker_errors += 1
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0)
        return rec
    rec.update(status=o.status, order_id=o.id, fill_px=o.fill_px, fee=o.fee, price_source=o.price_source,
               reject_reason=o.reject_reason, note=o.note, broker=o.broker, filled_qty=o.filled_qty)
    bridge.broker_hedge += o.filled_qty if side == "sell" else -o.filled_qty  # only what was really filled
    if o.status == "filled":
        bridge.broker_filled += 1
    elif o.status == "rejected":
        bridge.broker_rejects += 1
    return rec


def _fin(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _tick_event(t: Tick) -> dict:
    """The raw market as the UI shows it (YES orientation, never re-oriented); unknown fields are null."""
    f = t.fields
    return {"ts_ns": t.ts_ns, "p": t.p, "venue": "kalshi" if t.venue == 1 else "poly",
            "yes_bid": _fin(f.get("yes_bid")), "yes_ask": _fin(f.get("yes_ask")),
            "p_other_venue": _fin(f.get("p_other_venue")), "under_px": _fin(f.get("under_px")),
            "depth": sum(1 for i in range(5) if _fin(f.get(f"bid_px_{i}")) is not None)}


def adverse_p(oriented: dict, t: Tick, direction: str) -> float:
    """The adverse probability for the legacy Engine: the oriented YES mid; for a one-sided tick, the raw p
    oriented the same way (identical to the old ``p`` / ``1 - p`` for mid-only ticks)."""
    b, a = _fin(oriented.get("yes_bid")), _fin(oriented.get("yes_ask"))
    if b is not None and a is not None:
        return (b + a) / 2.0
    return t.p if direction != "up_on_yes" else 1.0 - t.p


def engine_tick(oriented: dict, ts_ns: int, venue: int) -> dict:
    """MarketTick dict for hedgecore.Algo.on_tick: only MarketTick keys, NaN for unknown."""
    d: dict[str, Any] = {k: (v if (v := _fin(oriented.get(k))) is not None else math.nan) for k in TICK_FIELDS}
    d["ts_ns"], d["venue"] = int(ts_ns), int(venue)
    return d


async def _run_source(bridge: Bridge, engine, hc, source) -> None:
    async for raw in source:
        t = as_tick(raw)
        bridge.ticks += 1
        await bridge.emit("tick", _tick_event(t))
        oriented = orient_to_adverse(t.fields, bridge.direction)  # the one orientation step
        d = engine.on_tick(ts_ns=t.ts_ns, p=adverse_p(oriented, t, bridge.direction), now_ns=time.time_ns())
        bridge.reasons[d.reason] += 1
        bridge.latencies.append(d.latency_ns)
        await bridge.emit("decision", {"action": d.action, "reason": d.reason, "order_qty": d.order_qty,
                                       "target_hedge": d.target_hedge, "current_hedge": d.current_hedge,
                                       "latency_ns": d.latency_ns, "engine": "legacy", "family": None,
                                       "preset": None, "signal": None})
        if d.action == "order":
            # The engine tracks the intended hedge and advances on every order (as before); the broker holds the
            # account record. A rejected or failed broker order is flagged on the "fill" event and in the summary.
            engine.on_fill(d.order_qty)
            bridge.orders += 1
            bridge.hedge = engine.current_hedge
            fill = await _send_to_broker(bridge, d.order_qty)
            if fill is not None:
                bridge.fills.append(fill)
                del bridge.fills[:-MAX_FILLS]
                await bridge.emit("fill", fill)
            shares = bridge.proposal.shares_held
            # "hedge"/"coverage" are the engine's intended position (it advances on every order). "broker_hedge" /
            # "broker_coverage" are what the broker actually filled; they differ when orders are rejected or fail.
            await bridge.emit("position", {"hedge": bridge.hedge, "coverage": bridge.hedge / shares,
                                           "hedge_basis": "engine_intent",
                                           "broker_hedge": bridge.broker_hedge,
                                           "broker_coverage": bridge.broker_hedge / shares if shares else 0.0,
                                           "broker": bridge.broker_name or getattr(bridge.broker, "name", None)})


# ---------------------------------------------------------------- algo engine (hedgecore.Algo)

EQUITY_TTL_S = 15.0  # one Massive quote per ticker per 15 s, shared by every bridge on that ticker
STALE_QUOTE_SOURCES = ("massive_prev_close",)  # yesterday's close is not a current under_px


def _equity_quote(bridge: Bridge, app):
    """Async callable -> the broker's equity quote for the proposal's ticker (Massive via the broker quote source),
    or None. Used by the live source of an algo bridge to fill under_px / under_bid / under_ask. Quotes are cached
    per ticker for EQUITY_TTL_S across bridges (rate limits); a previous-close fallback is reported as the source but
    returned as None, so the algo sees NaN (unknown) rather than a stale price as current."""
    if not hasattr(app.state, "equity_quotes"):
        app.state.equity_quotes = {}
    cache: dict = app.state.equity_quotes

    async def quote():
        ticker = bridge.proposal.ticker
        hit = cache.get(ticker)
        now = time.monotonic()
        if hit is not None and now - hit[0] < EQUITY_TTL_S:
            q = hit[1]
        else:
            b = bridge.broker
            quotes = getattr(b, "quotes", None) or getattr(getattr(b, "sim", None), "quotes", None)
            if quotes is None:
                bridge.equity_source = None
                return None
            q = await quotes.equity(ticker)
            cache[ticker] = (now, q)
        src = getattr(q, "source", None) if q is not None else None
        if src in STALE_QUOTE_SOURCES:
            bridge.equity_source = f"{src} (stale: not used)"
            return None
        bridge.equity_source = src
        return q
    return quote


def _side(intent: dict) -> str:
    return "buy" if int(intent.get("side") or 0) > 0 else "sell"


def _signed(side: str, qty: float) -> float:
    return qty if side == "buy" else -qty


async def _apply_order_state(bridge: Bridge, algo, o, side: str, instrument: str, applied: float = 0.0) -> None:
    """Feed the broker's answer back to the algo: filled -> on_fill(signed qty, fill px); rejected / cancelled ->
    on_reject; open -> the bridge remembers it as resting (cancel/replace before the next order).

    ``filled_qty`` is cumulative per order, so only the part not fed back yet (``applied``: a partial fill already
    applied while the order rested) reaches on_fill and the broker hedge; a partial fill is never counted twice."""
    filled = float(getattr(o, "filled_qty", 0.0) or 0.0)
    new = filled - applied
    px = _fin(getattr(o, "fill_px", None))
    if new > 1e-9 and px is not None:
        algo.on_fill(instrument, _signed(side, new), px)
        bridge.broker_hedge += new if side == "sell" else -new
        bridge.hedge = bridge.broker_hedge
        applied = filled
    if o.status == "filled":
        bridge.broker_filled += 1
        bridge.resting = None
    elif o.status == "open":
        bridge.resting = {"order_id": o.id, "instrument": instrument, "side": side, "qty": o.qty, "applied": applied}
    else:  # rejected or cancelled: nothing (more) traded
        if o.status == "rejected":
            bridge.broker_rejects += 1
        bridge.resting = None
        algo.on_reject(instrument)


async def _lookup(broker: Broker, order_id: str):
    rows = await asyncio.wait_for(broker.orders(), BROKER_TIMEOUT_S)
    return next((o for o in rows if o.id == order_id), None)


async def _settle_resting(bridge: Bridge, algo, broker: Broker | None, why: str) -> bool:
    """Cancel/replace: before a new order (or when the bridge ends), the bridge's resting order is looked up; if it
    filled meanwhile the fill goes to the algo, otherwise it is cancelled and the algo hears on_reject (expired).

    Returns True when nothing rests any more. When the broker cannot be read or the cancel did not take, the order
    may still be working: it stays in ``bridge.resting`` (retried before the next order and at bridge end) and the
    caller must not send another order on top of it (False)."""
    r = bridge.resting
    if r is None or broker is None:
        return r is None
    rec: dict = {"order_id": r["order_id"], "reason": why, "broker": broker.name}
    try:
        current = await _lookup(broker, r["order_id"])
        if current is not None and current.status == "open":
            try:
                current = await asyncio.wait_for(broker.cancel(r["order_id"]), BROKER_TIMEOUT_S)
            except Exception:  # filled or gone between the lookup and the cancel: read it again
                current = await _lookup(broker, r["order_id"])
    except Exception as e:
        bridge.broker_errors += 1
        rec.update(status="error", error=type(e).__name__, kept_resting=True)
        await bridge.emit("cancel", rec)
        return False
    if current is None:  # the broker no longer knows it: nothing can still trade, treat as expired
        bridge.resting = None
        algo.on_reject(r["instrument"])
        rec["status"] = "unknown"
    elif current.status == "open":  # the cancel did not take: it may still fill, so keep tracking it
        await _apply_order_state(bridge, algo, current, r["side"], r["instrument"], float(r.get("applied") or 0.0))
        rec.update(status="cancel_failed", kept_resting=True, filled_qty=current.filled_qty)
        await bridge.emit("cancel", rec)
        return False
    else:
        if current.status == "cancelled":
            bridge.cancels += 1
        await _apply_order_state(bridge, algo, current, r["side"], r["instrument"], float(r.get("applied") or 0.0))
        rec.update(status=current.status, filled_qty=current.filled_qty, fill_px=current.fill_px)
    await bridge.emit("cancel", rec)
    return True


def _coverage_room(bridge: Bridge) -> float:
    """Shares the bridge may still sell short: the approved target_coverage of shares_held minus the hedge the broker
    filled. The approval gate is a hard cap for every family, including one without a coverage param."""
    cap = math.floor(bridge.proposal.target_coverage * bridge.proposal.shares_held + 1e-9)
    return max(0.0, cap - bridge.broker_hedge)


async def _send_intent(bridge: Bridge, algo, intent: dict, t: Tick) -> dict:
    """Route one Algo Order intent to the broker; returns the fill record for the stream. Never raises."""
    instrument = str(intent.get("instrument") or "equity")
    side, qty = _side(intent), float(intent.get("qty") or 0.0)
    rec: dict = {"side": side, "qty": qty, "symbol": bridge.proposal.ticker, "instrument": instrument,
                 "family": bridge.algo["family"], "preset": bridge.algo.get("preset_index"),
                 "reason": intent.get("reason")}
    broker = bridge.order_broker()
    if instrument != "equity" or not (qty > 0 and math.isfinite(qty)):  # hedge families trade equity only
        algo.on_reject(instrument)
        rec.update(status="rejected", reject_reason=f"bridge routes equity intents only (got {instrument})",
                   filled_qty=0.0, broker=getattr(broker, "name", None))
        return rec
    if broker is None:
        algo.on_reject(instrument)
        bridge.broker_errors += 1
        rec.update(status="error", error="no broker", filled_qty=0.0, broker=None)
        return rec
    rec["broker"] = broker.name
    if not await _settle_resting(bridge, algo, broker, "replace"):
        algo.on_reject(instrument)  # the old order may still be working: never stack a new one on top of it
        rec.update(status="held", reject_reason="previous order still resting at the broker (retried next time)",
                   filled_qty=0.0)
        return rec
    if side == "sell":
        room = _coverage_room(bridge)
        if qty > room:
            rec["capped_from"] = qty
            qty = float(math.floor(room))
            rec["qty"] = qty
            if qty <= 0:
                bridge.cap_holds += 1
                algo.on_reject(instrument)
                rec.update(status="held", reject_reason=f"coverage cap: the approved target_coverage "
                           f"{bridge.proposal.target_coverage:g} is already hedged", filled_qty=0.0)
                return rec
    bridge.broker_name = broker.name
    limit = _fin(intent.get("limit_px"))
    limit = limit if limit is not None and limit > 0 else None
    note = ref = None
    if bridge.effective_source == "replay":
        note = REPLAY_NOTE  # replayed decisions, fills priced at today's market (the broker's own quote)
        rec["price_note"] = "priced at the current market, not the replayed time"
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
    else:
        ref = _fin(t.fields.get("under_px"))  # the live quote the algo just saw
        ref = ref if ref is not None and ref > 0 else None
    try:
        req = OrderRequest(symbol=bridge.proposal.ticker, asset="equity", side=side, qty=qty,
                           type="limit" if limit is not None else "market", limit_px=limit, ref_px=ref,
                           client_order_id=f"{bridge.id}-{bridge.orders}", tag=bridge.id, note=note)
        o = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
        bridge.broker_errors += 1
        algo.on_reject(instrument)  # nothing is known to have traded
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0)
        return rec
    await _apply_order_state(bridge, algo, o, side, instrument)
    rec.update(status=o.status, order_id=o.id, fill_px=o.fill_px, fee=o.fee, price_source=o.price_source,
               reject_reason=o.reject_reason, note=o.note, broker=o.broker, filled_qty=o.filled_qty,
               type=req.type, limit_px=req.limit_px)
    return rec


async def _run_algo_source(bridge: Bridge, algo, source) -> None:
    fam, preset = bridge.algo["family"], bridge.algo.get("preset_index")
    shares = bridge.proposal.shares_held
    async for raw in source:
        t = as_tick(raw)
        bridge.ticks += 1
        ev = _tick_event(t)
        ev["under_source"] = bridge.equity_source if bridge.effective_source == "live" else (
            "recorded" if ev["under_px"] is not None else None)
        await bridge.emit("tick", ev)
        oriented = orient_to_adverse(t.fields, bridge.direction)  # the one orientation step
        i = algo.on_tick(engine_tick(oriented, t.ts_ns, t.venue), time.time_ns())
        reason = str(i.get("reason"))
        bridge.reasons[reason] += 1
        bridge.latencies.append(int(i.get("latency_ns") or 0))
        is_order = i.get("action") == "order"
        side = _side(i)
        qty = float(i.get("qty") or 0.0) if is_order else 0.0
        await bridge.emit("decision", {
            "engine": "algo", "family": fam, "preset": preset, "action": i.get("action"), "reason": reason,
            "reason_code": i.get("reason_code"), "reason_block": i.get("reason_block"), "signal": i.get("signal"),
            "instrument": i.get("instrument"), "side": side if is_order else None, "qty": qty,
            "limit_px": i.get("limit_px"),
            # legacy-compatible fields: order_qty > 0 adds to the short hedge; the hedge is what the broker filled
            "order_qty": (qty if side == "sell" else -qty) if is_order else 0.0,
            "target_hedge": None, "current_hedge": bridge.hedge, "latency_ns": i.get("latency_ns")})
        if not is_order:
            continue
        bridge.orders += 1
        fill = await _send_intent(bridge, algo, i, t)
        bridge.fills.append(fill)
        del bridge.fills[:-MAX_FILLS]
        await bridge.emit("fill", fill)
        await bridge.emit("position", {"hedge": bridge.hedge, "coverage": bridge.hedge / shares if shares else 0.0,
                                       "hedge_basis": "broker_fill", "broker_hedge": bridge.broker_hedge,
                                       "broker_coverage": bridge.broker_hedge / shares if shares else 0.0,
                                       "resting_order": bridge.resting["order_id"] if bridge.resting else None,
                                       "broker": bridge.broker_name or getattr(bridge.broker, "name", None)})


async def _run(bridge: Bridge, app, hc, source, fallback: Path | None) -> None:
    if bridge.algo:
        # Position fields only: the direction already reached the ticks (orient_to_adverse); never passed to hedgecore.
        try:
            engine = hc.Algo(bridge.algo["family"], dict(bridge.algo["params"]),
                             {"shares_held": float(bridge.proposal.shares_held)})
        except Exception as e:  # a catalog/engine mismatch must end the stream cleanly, never hang it
            await bridge.emit("error", {"message": f"hedgecore.Algo refused {bridge.algo['family']}: {e}",
                                        "source": "engine"})
            await bridge.emit("status", {"status": "stopped", "reason": "engine_error"}, status="stopped")
            return
        loop = lambda src: _run_algo_source(bridge, engine, src)  # noqa: E731
    else:
        spec = hc.HedgeSpec(ticker=bridge.proposal.ticker, shares_held=bridge.proposal.shares_held,
                            target_coverage=bridge.proposal.target_coverage, gap_per_share=bridge.gap)
        engine = hc.Engine(spec)
        loop = lambda src: _run_source(bridge, engine, hc, src)  # noqa: E731
    try:
        bridge.broker = get_broker(app)
    except Exception:  # an unavailable account must not stop the hedge loop
        bridge.broker = None
        await bridge.emit("error", {"message": "broker unavailable", "source": "broker"})
    try:
        try:
            await loop(source)
        except (SourceError, OSError) as e:
            await bridge.emit("error", {"message": str(e), "source": bridge.effective_source})
            if bridge.effective_source == "live" and fallback is not None and fallback.is_file():
                bridge.effective_source = "replay"
                await bridge.emit("status", {"status": "running", "source": "replay", "note": "live failed; replaying"})
                bars = _bars(bridge.proposal.ticker)
                bridge.equity_price = _replay_equity_price(fallback, bars)
                await loop(ReplaySource(fallback, speed=_replay_speed(app), bars=bars))
            else:
                await _finish_orders(bridge, engine)
                await bridge.emit("status", {"status": "stopped", "reason": "source_failed"}, status="stopped")
                return
        await _finish_orders(bridge, engine)
        await bridge.emit("status", {"status": "finished"}, status="finished")
    except asyncio.CancelledError:
        await bridge.emit("status", {"status": "stopped", "reason": "cancelled"}, status="stopped")
        raise
    except Exception as e:  # never leave a stream hanging
        await bridge.emit("error", {"message": type(e).__name__})
        await bridge.emit("status", {"status": "stopped", "reason": "internal_error"}, status="stopped")


async def _finish_orders(bridge: Bridge, engine) -> None:
    """A bridge that ends leaves no order resting at the broker."""
    if bridge.algo and bridge.resting is not None:
        await _settle_resting(bridge, engine, bridge.order_broker(), "bridge_end")


def _replay_equity_price(path: Path, bars: list[tuple[int, float]]) -> str:
    """"recorded" when a replay can show the algo an equity price (an under_px column in the recording, or a recorded
    bar known by its last row), else "none": the hedge families then hold (fee_unknown) on every tick."""
    try:
        last_s = None
        for line in path.read_text().splitlines():
            if '"under_px"' in line:
                return "recorded"
            if line.strip():
                last_s = int(json.loads(line)["ts_ns"]) // 1_000_000_000
    except (OSError, ValueError, KeyError, TypeError):
        return "none"
    return "recorded" if bars and last_s is not None and bars[0][0] <= last_s else "none"


def _bars(ticker: str) -> list[tuple[int, float]]:
    try:
        return recorded_bars(ticker)
    except Exception:
        return []


def _catalog_manifest(hc) -> dict:
    """The compiled catalog (authoritative at run time), normalized like the pipeline's library."""
    try:
        m = normalize_manifest(hc.catalog())
        if m["families"]:
            return m
    except Exception:
        pass
    from .pipeline.engine_adapter import EngineAdapter
    return EngineAdapter(module=None).library()[0]


def _asked_algo(body: BridgeIn) -> AlgoChoice | None:
    """The algo named in a POST /bridges body, or None."""
    if body.family is not None:
        try:
            return AlgoChoice(family=body.family, preset_index=body.preset_index, params=body.params)
        except ValidationError as e:
            raise HTTPException(422, f"algo: {e.errors()[0]['msg']}")
    if body.preset_index is not None or body.params is not None:
        raise HTTPException(422, "algo: preset_index / params need a family.")
    return None


def _same_algo(a: AlgoChoice, b: AlgoChoice) -> bool:
    return (a.family == b.family and a.preset_index == b.preset_index
            and (a.params or None) == (b.params or None))


def _algo_label(c: AlgoChoice | None) -> str:
    if c is None:
        return "no algo (the legacy Engine)"
    return f"algo {c.family}{'' if c.preset_index is None else ' preset ' + str(c.preset_index)}"


def _algo_for(prop: Proposal, body: BridgeIn, hc) -> tuple[dict | None, AlgoChoice | None]:
    """Which algo this bridge runs. A proposal approved with an algo runs exactly that algo (a body naming another is
    a 409: the approval gate covers what runs); otherwise the body's algo; otherwise None (legacy Engine).

    The approved target_coverage caps every hedge-size param (``cap_coverage``): a preset with coverage 1.0 on a 0.5
    proposal runs with coverage 0.5. The bridge also clips sell intents at that coverage (``_coverage_room``)."""
    asked = _asked_algo(body)
    choice = prop.algo
    if choice is not None and asked is not None and not _same_algo(asked, choice):
        raise HTTPException(409, f"Proposal {prop.id} was approved with {_algo_label(choice)};"
                                 " a bridge runs exactly what was approved.")
    choice = choice or asked
    if choice is None:
        return None, None
    try:
        r = resolve_algo(_catalog_manifest(hc), choice.family, choice.preset_index, choice.params)
    except AlgoChoiceError as e:
        raise HTTPException(422, f"algo: {e}.")
    run, lowered = cap_coverage(r["params"], prop.target_coverage)
    return ({"family": r["family"], "preset_index": r["preset_index"], "params": run, "source": choice.source,
             "coverage_cap": prop.target_coverage, "capped": lowered},
            AlgoChoice(family=choice.family, preset_index=choice.preset_index, params=choice.params))


def _live_primary(market: MarketRef) -> tuple[str, str]:
    """(venue, id the venue's book is keyed by): a Polymarket YES token id, or a Kalshi market ticker."""
    if market.source == "kalshi":
        return "kalshi", market.id
    if not market.token_id:
        raise HTTPException(422, "Live bridge needs a Polymarket market.token_id (or a Kalshi market).")
    return "polymarket", market.token_id


def _twin(twin: MarketRef | None, primary: str) -> tuple[str, str] | None:
    if twin is None:
        return None
    if twin.source not in ("polymarket", "kalshi") or twin.source == primary:
        raise HTTPException(422, "twin must be the same question on the OTHER venue (polymarket <-> kalshi).")
    if twin.source == "polymarket":
        if not twin.token_id:
            raise HTTPException(422, "A Polymarket twin needs its YES token_id.")
        return "polymarket", twin.token_id
    return "kalshi", twin.id


def _registry(request: Request) -> dict[str, Bridge]:
    if not hasattr(request.app.state, "bridges"):
        request.app.state.bridges = {}
    return request.app.state.bridges


@router.post("/bridges", status_code=201)
async def start_bridge(body: BridgeIn, request: Request, response: Response) -> dict:
    store: ProposalStore = request.app.state.store
    prop = next((p for p in store.list() if p.id == body.proposal_id), None)
    if prop is None:
        raise HTTPException(404, f"No proposal {body.proposal_id}.")
    if prop.status != "approved":
        raise HTTPException(409, f"Proposal {prop.id} is {prop.status}; only approved proposals can start a bridge.")
    if prop.family != "hedge":
        raise HTTPException(409, "Opportunity proposals are executed as a single simulated options order, not by hedgecore.")
    reg = _registry(request)
    existing = reg.get(prop.id)
    if existing is not None:  # idempotent: one bridge per approved proposal id
        if existing.requested_source != body.source:
            raise HTTPException(409, f"Bridge {existing.id} already started for proposal {prop.id} with source {existing.requested_source}.")
        asked = _asked_algo(body)  # a body naming an algo must name the one running (else the caller is misled)
        if asked is not None and (existing.choice is None or not _same_algo(asked, existing.choice)):
            raise HTTPException(409, f"Bridge {existing.id} for proposal {prop.id} already runs "
                                     f"{_algo_label(existing.choice)}; it cannot switch algos.")
        response.status_code = 200
        return {"bridge_id": existing.id}
    market, direction = _resolve(prop, body)
    hc = _load_engine()
    if hc is None:
        raise HTTPException(503, NO_ENGINE)

    algo, choice = _algo_for(prop, body, hc)
    bridge = Bridge(prop, body.source, market, body.gap_per_share, direction, body.replay_to_account, algo)
    bridge.choice = choice

    fallback = _fallback_path(request.app)
    if body.source == "replay":
        path = _replay_path(request, market, body.market)
        if path is None or not path.is_file():
            raise HTTPException(422, "No replay file configured (set POLYBRIDGE_REPLAY_PATH or add replays/<market id>.jsonl).")
        bars = _bars(prop.ticker)
        source: Any = ReplaySource(path, speed=_replay_speed(request.app), bars=bars)
        bridge.equity_price = _replay_equity_price(path, bars)
    else:
        primary, mid = _live_primary(market)
        twin = _twin(body.twin, primary)
        factory = getattr(request.app.state, "live_source_factory", None) or LiveSource
        # Only the algo reads under_px; a legacy bridge never polls the equity quote (Massive rate limits).
        source = factory(mid, primary=primary, twin=twin,
                         equity=_equity_quote(bridge, request.app) if algo else None)

    # No await between the registry check above and this insert: exactly one bridge per proposal.
    reg[prop.id] = bridge
    store.mark_bridge_started(prop.id)
    bridge.task = asyncio.create_task(_run(bridge, request.app, hc, source, fallback))
    return {"bridge_id": bridge.id}


def _find(request: Request, bridge_id: str) -> Bridge:
    for b in _registry(request).values():
        if b.id == bridge_id:
            return b
    raise HTTPException(404, f"No bridge {bridge_id}.")


@router.get("/bridges/{bridge_id}")
def bridge_summary(bridge_id: str, request: Request) -> dict:
    return _find(request, bridge_id).summary()


@router.get("/bridges/{bridge_id}/stream")
async def bridge_stream(bridge_id: str, request: Request) -> StreamingResponse:
    bridge = _find(request, bridge_id)

    async def gen():
        seen = 0  # absolute index into the event history (incl. dropped)
        while True:
            batch: list = []
            done = heartbeat = False
            async with bridge.cond:  # decide what to send under the lock, send after releasing it
                start = max(seen, bridge.dropped)
                batch = bridge.events[start - bridge.dropped:]
                seen = start + len(batch)
                done = bridge.status != "running" and not batch
                if not batch and not done:
                    try:
                        await asyncio.wait_for(bridge.cond.wait(), HEARTBEAT_S)
                        continue
                    except asyncio.TimeoutError:
                        heartbeat = True
            if heartbeat:
                yield ": heartbeat\n\n"
                continue
            for kind, data in batch:
                yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
            if done:
                return

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
