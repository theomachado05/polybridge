"""Bridge loop: one bridge per approved hedge proposal drives the C++ hedgecore engine from a tick source
and publishes tick/decision/position events over SSE. hedgecore is imported lazily (engine group only)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .broker import Broker, OrderRequest, SimBroker, get_broker
from .models import MarketRef, Proposal
from .store import NotFound, ProposalStore
from .ticks import LiveSource, ReplaySource, SourceError

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


class Bridge:
    def __init__(self, proposal: Proposal, source: str, market: MarketRef, gap: float,
                 direction: str = "down_on_yes", replay_to_account: bool = False) -> None:
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
                "hedge_basis": "engine_intent", "broker_hedge": self.broker_hedge,
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


async def _run_source(bridge: Bridge, engine, hc, source) -> None:
    async for ts_ns, p in source:
        bridge.ticks += 1
        await bridge.emit("tick", {"ts_ns": ts_ns, "p": p})
        d = engine.on_tick(ts_ns=ts_ns, p=p if bridge.direction == "down_on_yes" else 1.0 - p,
                           now_ns=time.time_ns())
        bridge.reasons[d.reason] += 1
        bridge.latencies.append(d.latency_ns)
        await bridge.emit("decision", {"action": d.action, "reason": d.reason, "order_qty": d.order_qty,
                                       "target_hedge": d.target_hedge, "current_hedge": d.current_hedge,
                                       "latency_ns": d.latency_ns})
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


async def _run(bridge: Bridge, app, hc, source, fallback: Path | None) -> None:
    spec = hc.HedgeSpec(ticker=bridge.proposal.ticker, shares_held=bridge.proposal.shares_held,
                        target_coverage=bridge.proposal.target_coverage, gap_per_share=bridge.gap)
    engine = hc.Engine(spec)
    try:
        bridge.broker = get_broker(app)
    except Exception:  # an unavailable account must not stop the hedge loop
        bridge.broker = None
        await bridge.emit("error", {"message": "broker unavailable", "source": "broker"})
    try:
        try:
            await _run_source(bridge, engine, hc, source)
        except (SourceError, OSError) as e:
            await bridge.emit("error", {"message": str(e), "source": bridge.effective_source})
            if bridge.effective_source == "live" and fallback is not None and fallback.is_file():
                bridge.effective_source = "replay"
                await bridge.emit("status", {"status": "running", "source": "replay", "note": "live failed; replaying"})
                await _run_source(bridge, engine, hc, ReplaySource(fallback, speed=_replay_speed(app)))
            else:
                await bridge.emit("status", {"status": "stopped", "reason": "source_failed"}, status="stopped")
                return
        await bridge.emit("status", {"status": "finished"}, status="finished")
    except asyncio.CancelledError:
        await bridge.emit("status", {"status": "stopped", "reason": "cancelled"}, status="stopped")
        raise
    except Exception as e:  # never leave a stream hanging
        await bridge.emit("error", {"message": type(e).__name__})
        await bridge.emit("status", {"status": "stopped", "reason": "internal_error"}, status="stopped")


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
        response.status_code = 200
        return {"bridge_id": existing.id}
    market, direction = _resolve(prop, body)
    hc = _load_engine()
    if hc is None:
        raise HTTPException(503, NO_ENGINE)

    fallback = _fallback_path(request.app)
    if body.source == "replay":
        path = _replay_path(request, market, body.market)
        if path is None or not path.is_file():
            raise HTTPException(422, "No replay file configured (set POLYBRIDGE_REPLAY_PATH or add replays/<market id>.jsonl).")
        source: Any = ReplaySource(path, speed=_replay_speed(request.app))
    else:
        if not market.token_id:
            raise HTTPException(422, "Live bridge needs a Polymarket market.token_id.")
        factory = getattr(request.app.state, "live_source_factory", None)
        source = factory(market.token_id) if factory else LiveSource(market.token_id)

    # No await between the registry check above and this insert: exactly one bridge per proposal.
    bridge = Bridge(prop, body.source, market, body.gap_per_share, direction, body.replay_to_account)
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
