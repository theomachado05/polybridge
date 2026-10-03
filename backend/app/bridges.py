"""Bridge loop: one bridge per approved hedge proposal drives the C++ hedgecore library from a tick source
and publishes tick/decision/fill/position events over SSE. hedgecore is imported lazily (engine group only).

Two engines:
- ``algo`` (the proposal or the body names a fitted family + preset/params): ``hedgecore.Algo`` for that family is fed
  full MarketTicks (book, other venue, equity quote). Its Order intents go to the broker; a fill calls
  ``Algo.on_fill``, a reject / expiry / cancel calls ``Algo.on_reject``, and any resting order of the bridge is
  cancelled before a new one is sent. A place call that fails or times out is tracked as an unconfirmed resting order
  (by client_order_id) and reconciled first, never booked as "nothing traded". The hedge reported is what the broker
  filled.
- ``legacy`` (no fit): the original ``hedgecore.Engine`` default spec on the adverse probability. Its broker side is
  position-aware: buys never exceed the short the broker filled, sells never exceed the approved target_coverage, and
  open orders are tracked and cancelled like the algo path's.
A live bridge whose source fails falls back only to a recording of its own market, after settling what is open at the
account broker.
- opportunity (an approved opportunity proposal with an Opportunity-division options family): the same Algo loop
  on raw (never oriented) ticks whose option fields come from ``OptionsEnricher``; each Option intent becomes one
  multi-leg option order (``app.options.fills`` structure legs priced at the Massive quotes, filled all-or-none by
  the SimBroker; Webull paper routes options to the simulator). The proposal's max_contracts / max_notional cap it.

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
from .pipeline.engine_adapter import (AlgoChoiceError, cap_contracts, cap_coverage, is_option_family,
                                      normalize_manifest, resolve_algo)
from .pipeline.ticks import orient_for_family, orient_to_adverse, recorded_bars
from .store import NotFound, ProposalStore
from .ticks import TICK_FIELDS, LiveSource, OptionsEnricher, ReplaySource, SourceError, Tick, as_tick
from .twins import twin_of

router = APIRouter()
HEARTBEAT_S = 15.0
MAX_EVENTS = 20_000
REPLAYS_DIR = Path(__file__).resolve().parents[1] / "replays"
NO_ENGINE = "engine not installed (uv sync --group engine)"
# An order never stalls the bridge loop longer than this. It is above the longest chain of broker requests inside one
# place_order (Webull: 6 requests x 4 s hard deadline each = 24 s), so a call that may still place an order is never
# abandoned half-way; if it is (timeout or error after the request was built), the order is tracked as unconfirmed
# and reconciled by client_order_id before anything else is sent.
BROKER_TIMEOUT_S = 30.0
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
    # Replay decisions are historical; fills are priced at today's market when the broker has a current quote, else
    # (Wi-Fi off / no Massive key) at the replayed under_px, labelled "recorded price". By default a replay bridge
    # trades a throwaway in-memory simulator (never Webull, never the persistent account); set true to opt in to the
    # account (recorded-price fills then carry historical cost bases: see ``account_note`` in the summary).
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
        self.twin: dict | None = None  # the other-venue market feeding p_other_venue, and where it came from
        self.choice: AlgoChoice | None = None  # what the algo was chosen as (idempotent re-POSTs are compared to it)
        # The bridge's open broker order: {order_id, client_order_id, instrument, side, qty, applied (filled qty fed
        # back to the algo), hedged (filled qty already in broker_hedge), unconfirmed / unpriced flags}.
        self.resting: dict | None = None
        self.resting_broker: Broker | None = None  # the broker holding it (a live->replay fallback never loses it)
        self.cancels = 0
        self.cap_holds = 0  # sell intents the approved coverage cap clipped to zero
        self.equity_source: str | None = None  # where the last live under_px came from (None: no quote)
        self.equity_price = "live_quote"  # "live_quote" | "recorded" | "none": what under_px the algo can see
        self.quote_check: tuple[float, bool] | None = None  # replay: (monotonic, can the broker quote the ticker)
        self.recorded_fills = 0  # replay orders filled at the recorded under_px (no current quote)
        # Opportunity (options) bridges
        self.division = proposal.family  # "hedge" | "opportunity"
        self.options: OptionsEnricher | None = None
        self.opt_pos = 0.0           # signed structures the broker filled (+ long, - short)
        self.opt_open: dict | None = None  # the open structure: {kind, expiry, k_lo, k_hi, legs: [{sign, ticker}]}
        self.opt_risk_per_unit = 0.0  # USD at risk per open structure (premium or max loss), set at entry
        self.opt_last: dict | None = None  # latest PM-vs-options view for the UI
        self.option_data = "none"    # "live_chain" | "recorded" | "none"

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
                "coverage_cap": self.proposal.target_coverage if self.algo and self.division == "hedge" else None,
                "cap_holds": self.cap_holds,
                "equity_price": self.equity_price if self.algo and self.division == "hedge" else None,
                "equity_source": self.equity_source,
                "recorded_price_fills": self.recorded_fills,
                "account_note": self._account_note(),
                "broker_coverage": self.broker_hedge / self.proposal.shares_held if self.proposal.shares_held else 0.0,
                "broker_filled": self.broker_filled,
                "broker_rejects": self.broker_rejects, "broker_errors": self.broker_errors,
                "last_fill": self.fills[-1] if self.fills else None,
                "shares_held": self.proposal.shares_held, "target_coverage": self.proposal.target_coverage,
                "coverage": self.hedge / self.proposal.shares_held if self.proposal.shares_held else 0.0,
                "basis": self.proposal.basis, "label": self.proposal.label,
                "market": self.market.model_dump(), "twin": self.twin,
                "latency_ns": {"p50": q(0.5), "p99": q(0.99)},
                "division": self.division,
                **(self._opp_summary() if self.division == "opportunity" else {})}

    def _account_note(self) -> str | None:
        """Set when recorded-price replay fills went into the persistent account: their cost bases are historical, so
        the account's unrealized P&L against today's quotes mixes two price times and measures nothing."""
        if self.effective_source != "replay" or not self.replay_to_account or not self.recorded_fills:
            return None
        return (f"{self.recorded_fills} fill(s) entered the persistent sim account at recorded (historical) prices; "
                "once a current quote is available the account marks them at today's price, so that unrealized P&L "
                "comes from mixing the two price times, not from the hedge")

    def _opp_summary(self) -> dict:
        p = self.proposal
        return {"option_position": self.opt_pos, "option_structure": dict(self.opt_open) if self.opt_open else None,
                "risk_used": abs(self.opt_pos) * self.opt_risk_per_unit, "max_contracts": p.max_contracts,
                "max_notional": p.max_notional, "option_data": self.option_data,
                "pm_vs_options": dict(self.opt_last) if self.opt_last else None,
                "options_detail": _options_brief(self.options), "fills_label": OPTION_FILLS_LABEL}


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
    if prop.market is not None and (prop.direction is not None or prop.family == "opportunity"):
        token = prop.market.token_id
        if token is None and body.market is not None and body.market.id == prop.market.id:
            token = body.market.token_id
        # opportunity bridges never orient ticks; their direction is only a label
        return prop.market.model_copy(update={"token_id": token}), prop.direction or "down_on_yes"
    if body.market is None:
        raise HTTPException(422, "market is required for a filing-tags proposal.")
    return body.market, body.direction


def _fallback_path(app, market: MarketRef | None = None) -> Path | None:
    """The recording a live bridge falls back to when its source fails: only a recording of THIS market (the replay
    index / ``replays/<market id>.jsonl``, see ``pipeline.ticks._replay_candidates``). POLYBRIDGE_REPLAY_PATH is used
    only when it is one of those files; another market's history is never replayed under this market's title."""
    from .pipeline.ticks import DATA, _replay_candidates
    configured = getattr(app.state, "replay_path", None) or os.environ.get("POLYBRIDGE_REPLAY_PATH")
    if market is None:
        return None
    try:
        cands = _replay_candidates(market.source, market.id, market.token_id, DATA, REPLAYS_DIR)
    except Exception:
        cands = []
    if configured:
        conf = Path(configured)
        names = {c.name for c in cands}
        if conf.name in names or conf.stem in (market.id, market.token_id):
            return conf
    return next((c for c in cands if c.is_file()), None)


async def _send_to_broker(bridge: Bridge, order_qty: float) -> dict | None:
    """Route one engine order to the active broker: sell to add to the short hedge, buy to reduce it.
    Returns the fill record for the stream; never raises (a broker failure must not stop the bridge).

    The legacy Engine advances on every intent, whatever the broker did, so the broker side is position-aware: a buy
    never exceeds the short the broker really holds for this bridge (a rejected sell is never "bought back" into an
    unapproved long), a sell never exceeds the approved target_coverage, and an order left open is tracked as resting
    (settled before the next order and cancelled at bridge end), exactly like the algo path."""
    broker = bridge.order_broker()
    if broker is None:
        return None
    side = "sell" if order_qty > 0 else "buy"
    qty = abs(order_qty)
    rec: dict = {"broker": broker.name, "side": side, "qty": qty, "symbol": bridge.proposal.ticker}
    if not await _settle_resting(bridge, None, broker, "replace"):
        rec.update(status="held", reject_reason="previous order still resting at the broker (retried next time)",
                   filled_qty=0.0)
        return rec
    room = _coverage_room(bridge) if side == "sell" else max(0.0, bridge.broker_hedge)
    if qty > room:
        rec["capped_from"] = qty
        qty = float(math.floor(room + 1e-9)) if side == "sell" else room
        rec["qty"] = qty
        if qty <= 1e-9:
            bridge.cap_holds += 1
            why = (f"coverage cap: the approved target_coverage {bridge.proposal.target_coverage:g} is already hedged"
                   if side == "sell" else "no short filled at the broker to buy back (an earlier sell did not fill)")
            rec.update(status="held", reject_reason=why, filled_qty=0.0)
            return rec
    bridge.broker_name = broker.name
    note = None
    if bridge.effective_source == "replay":
        note = REPLAY_NOTE
        rec["price_note"] = "priced at the current market, not the replayed time"
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
    req = OrderRequest(symbol=bridge.proposal.ticker, asset="equity", side=side, qty=qty, type="market",
                       client_order_id=f"{bridge.id}-{bridge.orders}", tag=bridge.id, note=note)
    try:
        o = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
        _track_unconfirmed(bridge, broker, req, "equity")
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0, order_id=req.client_order_id,
                   kept_resting=True)
        return rec
    rec.update(status=o.status, order_id=o.id, fill_px=o.fill_px, fee=o.fee, price_source=o.price_source,
               reject_reason=o.reject_reason, note=o.note, broker=o.broker, filled_qty=o.filled_qty)
    await _apply_order_state(bridge, None, o, side, "equity", broker=broker)  # broker_hedge: only what really filled
    return rec


def _track_unconfirmed(bridge: Bridge, broker: Broker, req: OrderRequest, instrument: str) -> None:
    """The place call failed or timed out after the request was built: the broker may have accepted it. It is tracked
    as resting under its client_order_id, so the next order (or the bridge end) reconciles it first: a fill is booked,
    an open order is cancelled, an order the broker never saw is dropped. Never booked as "nothing traded"."""
    bridge.broker_errors += 1
    bridge.resting = {"order_id": req.client_order_id, "client_order_id": req.client_order_id,
                      "instrument": instrument, "side": req.side, "qty": req.qty, "applied": 0.0, "hedged": 0.0,
                      "unconfirmed": True}
    bridge.resting_broker = broker


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


RECORDED_SOURCE = "recorded"  # price_source of a replay fill priced at the replayed under_px
REPLAY_RECORDED_NOTE = "replay: recorded price (no current quote), not a live fill"
REPLAY_RECORDED_PRICE_NOTE = ("recorded price: no current market quote (offline or no Massive key), so the fill is "
                              "priced at the replayed under_px, not today's market")


async def _broker_can_price(bridge: Bridge, broker: Broker) -> bool:
    """Replay only: can the order broker price an equity order itself (a current Massive quote for the ticker)?
    A broker that prices its own fills (Webull) always can; a sim without a quote cannot, and the replay then
    supplies the replayed under_px. The answer is cached per bridge for EQUITY_TTL_S (one quote call per ticker per
    window, never one per order) and never consulted by a live bridge."""
    sim = broker if isinstance(broker, SimBroker) else None
    if sim is None:
        return True
    now = time.monotonic()
    hit = bridge.quote_check
    if hit is not None and now - hit[0] < EQUITY_TTL_S:
        return hit[1]
    quotes = getattr(sim, "quotes", None)
    try:
        q = await asyncio.wait_for(quotes.equity(bridge.proposal.ticker), BROKER_TIMEOUT_S) if quotes else None
    except Exception:
        q = None
    ok = q is not None and _fin(getattr(q, "mid", None)) is not None
    bridge.quote_check = (now, ok)
    return ok


def _side(intent: dict) -> str:
    return "buy" if int(intent.get("side") or 0) > 0 else "sell"


def _signed(side: str, qty: float) -> float:
    return qty if side == "buy" else -qty


def _positive(x: Any) -> float | None:
    v = _fin(x)
    return v if v is not None and v > 0 else None


async def _apply_order_state(bridge: Bridge, algo, o, side: str, instrument: str, applied: float = 0.0,
                             hedged: float | None = None, ref_px: float | None = None,
                             broker: Broker | None = None) -> None:
    """Feed the broker's answer back to the algo: filled -> on_fill(signed qty, fill px); rejected / cancelled ->
    on_reject; open -> the bridge remembers it as resting (cancel/replace before the next order). ``algo`` None is the
    legacy Engine (it already advanced on the intent): only the broker hedge and the resting order are tracked.

    ``filled_qty`` is cumulative per order, so only the part not fed back yet reaches on_fill (``applied``) and the
    broker hedge (``hedged``); a partial fill is never counted twice. The filled quantity always reaches broker_hedge
    (the coverage cap must see every share the broker sold). The algo's fill price is the broker's fill price, else
    the order's limit, else ``ref_px`` (the tick's equity price); with none of them the order stays resting (flagged
    ``unpriced``) so a later lookup can price it, and no further order is stacked on top of it."""
    filled = float(getattr(o, "filled_qty", 0.0) or 0.0)
    hedged = applied if hedged is None else hedged
    if filled - hedged > 1e-9:
        d = filled - hedged
        bridge.broker_hedge += d if side == "sell" else -d
        if algo is not None:
            bridge.hedge = bridge.broker_hedge
        hedged = filled
    unpriced = False
    if algo is not None and filled - applied > 1e-9:
        px = _positive(getattr(o, "fill_px", None)) or _positive(getattr(o, "limit_px", None)) or _positive(ref_px)
        if px is not None:
            algo.on_fill(instrument, _signed(side, filled - applied), px)
            applied = filled
        else:
            unpriced = True
    elif algo is None:
        applied = filled
    keep = {"order_id": o.id, "client_order_id": getattr(o, "client_order_id", None) or o.id,
            "instrument": instrument, "side": side, "qty": o.qty, "applied": applied, "hedged": hedged}
    if unpriced:
        bridge.resting = {**keep, "unpriced": True, "status": o.status}
        bridge.resting_broker = broker or bridge.resting_broker
        await bridge.emit("error", {"message": f"order {o.id} reports {filled:g} filled with no fill price; kept as "
                                               "resting until it can be priced", "source": "broker"})
        return
    if o.status == "filled":
        bridge.broker_filled += 1
        bridge.resting = bridge.resting_broker = None
    elif o.status == "open":
        bridge.resting = keep
        bridge.resting_broker = broker or bridge.resting_broker
    else:  # rejected or cancelled: nothing (more) traded
        if o.status == "rejected":
            bridge.broker_rejects += 1
        bridge.resting = bridge.resting_broker = None
        if algo is not None:
            algo.on_reject(instrument)


async def _lookup(broker: Broker, order_id: str, client_order_id: str | None = None):
    """The broker's current state of an order, by broker id or by our client_order_id (an unconfirmed order only has
    the latter). A broker that can read one order by client id (Webull) is asked directly when the list misses it."""
    ids = {order_id, client_order_id} - {None}
    rows = await asyncio.wait_for(broker.orders(), BROKER_TIMEOUT_S)
    hit = next((o for o in rows if o.id in ids or getattr(o, "client_order_id", None) in ids), None)
    find = getattr(broker, "find_order", None)
    if hit is None and find is not None:
        hit = await asyncio.wait_for(find(client_order_id or order_id), BROKER_TIMEOUT_S)
    return hit


async def _settle_resting(bridge: Bridge, algo, broker: Broker | None, why: str, ref_px: float | None = None) -> bool:
    """Cancel/replace: before a new order (or when the bridge ends), the bridge's resting order is looked up; if it
    filled meanwhile the fill goes to the algo, otherwise it is cancelled and the algo hears on_reject (expired).

    Returns True when nothing rests any more. When the broker cannot be read or the cancel did not take, the order
    may still be working: it stays in ``bridge.resting`` (retried before the next order and at bridge end) and the
    caller must not send another order on top of it (False)."""
    r = bridge.resting
    broker = bridge.resting_broker or broker  # the broker that took it, even after a live->replay switch
    if r is None or broker is None:
        return r is None
    cid = r.get("client_order_id")
    rec: dict = {"order_id": r["order_id"], "reason": why, "broker": broker.name}
    try:
        current = await _lookup(broker, r["order_id"], cid)
        if current is not None and current.status == "open":
            try:
                current = await asyncio.wait_for(broker.cancel(current.id), BROKER_TIMEOUT_S)
            except Exception:  # filled or gone between the lookup and the cancel: read it again
                current = await _lookup(broker, r["order_id"], cid)
    except Exception as e:
        bridge.broker_errors += 1
        rec.update(status="error", error=type(e).__name__, kept_resting=True)
        await bridge.emit("cancel", rec)
        return False
    applied, hedged = float(r.get("applied") or 0.0), float(r.get("hedged", r.get("applied")) or 0.0)
    if current is None:  # the broker no longer knows it: nothing can still trade, treat as expired
        bridge.resting = bridge.resting_broker = None
        if algo is not None:
            algo.on_reject(r["instrument"])
        rec["status"] = "unknown"
    elif current.status == "open":  # the cancel did not take: it may still fill, so keep tracking it
        await _apply_order_state(bridge, algo, current, r["side"], r["instrument"], applied, hedged, ref_px, broker)
        rec.update(status="cancel_failed", kept_resting=True, filled_qty=current.filled_qty)
        await bridge.emit("cancel", rec)
        return False
    else:
        if current.status == "cancelled":
            bridge.cancels += 1
        await _apply_order_state(bridge, algo, current, r["side"], r["instrument"], applied, hedged, ref_px, broker)
        rec.update(status=current.status, filled_qty=current.filled_qty, fill_px=current.fill_px)
        if bridge.resting is not None:  # filled but still unpriced: keep it, send nothing on top
            rec["kept_resting"] = True
            await bridge.emit("cancel", rec)
            return False
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
    if not await _settle_resting(bridge, algo, broker, "replace", _positive(t.fields.get("under_px"))):
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
    note = ref = ref_source = None
    if bridge.effective_source == "replay":
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
        recorded = _fin(t.fields.get("under_px"))
        if recorded is not None and recorded > 0 and not await _broker_can_price(bridge, broker):
            # Wi-Fi off / no Massive key: the sim has no current quote, so the replay fills at the replayed under_px
            ref, ref_source, note = recorded, RECORDED_SOURCE, REPLAY_RECORDED_NOTE
            rec["price_note"] = REPLAY_RECORDED_PRICE_NOTE
        else:
            note = REPLAY_NOTE  # replayed decisions, fills priced at today's market (the broker's own quote)
            rec["price_note"] = "priced at the current market, not the replayed time"
    else:
        ref = _fin(t.fields.get("under_px"))  # the live quote the algo just saw
        ref = ref if ref is not None and ref > 0 else None
    try:
        req = OrderRequest(symbol=bridge.proposal.ticker, asset="equity", side=side, qty=qty,
                           type="limit" if limit is not None else "market", limit_px=limit, ref_px=ref,
                           ref_source=ref_source, client_order_id=f"{bridge.id}-{bridge.orders}", tag=bridge.id,
                           note=note)
    except Exception as e:
        bridge.broker_errors += 1
        algo.on_reject(instrument)  # never sent: nothing traded
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0)
        return rec
    try:
        o = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
        # The broker may have accepted it (a timeout after the POST, a 5xx): track it under its client_order_id and
        # reconcile it before the next order, so an accepted order is never re-sent on top of itself.
        _track_unconfirmed(bridge, broker, req, instrument)
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0, order_id=req.client_order_id,
                   kept_resting=True)
        return rec
    await _apply_order_state(bridge, algo, o, side, instrument, ref_px=_positive(t.fields.get("under_px")),
                             broker=broker)
    if bridge.effective_source == "replay":
        if ref_source == RECORDED_SOURCE and o.filled_qty > 0:
            bridge.recorded_fills += 1
        elif o.status == "rejected" and str(o.reject_reason or "").startswith("no_price"):
            bridge.quote_check = (time.monotonic(), False)  # the quote vanished since the check: next order uses the recording
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
        opp = bridge.division == "opportunity"
        if opp:  # option families name the real YES contract: never oriented; the UI sees the PM-vs-options gap
            bridge.opt_last = pm_vs_options(t.fields)
            ev["options"] = bridge.opt_last
            if bridge.opt_last["opt_implied_prob"] is not None and bridge.option_data == "none":
                bridge.option_data = "live_chain" if bridge.effective_source == "live" else "recorded"
        else:
            ev["under_source"] = bridge.equity_source if bridge.effective_source == "live" else (
                "recorded" if ev["under_px"] is not None else None)
        await bridge.emit("tick", ev)
        # the one orientation step: hedge -> adverse per the proposal's direction; opportunity -> raw YES, except a
        # family that reads the PM adverse probability (eightk_opportunity), oriented by the matched question
        oriented = opp_engine_fields(bridge, t.fields) if opp else orient_to_adverse(t.fields, bridge.direction)
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
        fill = await (_send_option_intent if opp else _send_intent)(bridge, algo, i, t)
        bridge.fills.append(fill)
        del bridge.fills[:-MAX_FILLS]
        await bridge.emit("fill", fill)
        if opp:
            await bridge.emit("position", {
                "option_position": bridge.opt_pos, "option_structure": bridge.opt_open,
                "risk_used": abs(bridge.opt_pos) * bridge.opt_risk_per_unit,
                "max_contracts": bridge.proposal.max_contracts, "max_notional": bridge.proposal.max_notional,
                "broker": fill.get("broker"), "simulated": True})
            continue
        await bridge.emit("position", {"hedge": bridge.hedge, "coverage": bridge.hedge / shares if shares else 0.0,
                                       "hedge_basis": "broker_fill", "broker_hedge": bridge.broker_hedge,
                                       "broker_coverage": bridge.broker_hedge / shares if shares else 0.0,
                                       "resting_order": bridge.resting["order_id"] if bridge.resting else None,
                                       "broker": bridge.broker_name or getattr(bridge.broker, "name", None)})


# ---------------------------------------------------------------- opportunity engine (options)

OPTION_FILLS_LABEL = ("simulated option fills: Massive option quote mid +/- half the quoted spread, per-contract fee "
                      "(SimBroker; Webull paper does not take options here)")
OPTION_MULT = 100.0


def _options_brief(enricher: OptionsEnricher | None) -> dict | None:
    if enricher is None:
        return None
    d = enricher.detail or {}
    keep = ("supported", "available", "reason", "underlying_used", "strike_used", "expiry", "k_lo", "k_hi",
            "method", "direction", "expiry_gap_days", "notes", "eightk_coverage")
    return {k: (None if isinstance(d[k], float) and not math.isfinite(d[k]) else d[k]) for k in keep if k in d}


def opp_engine_fields(bridge: Bridge, fields: dict) -> dict:
    """The tick an opportunity family sees: raw YES, or for eightk_opportunity the adverse orientation of the matched
    threshold question ("above K" -> NO is adverse). The UI's PM-vs-options gap always uses the raw fields."""
    qdir = (bridge.options.detail or {}).get("direction") if bridge.options is not None else None
    return orient_for_family(fields, bridge.algo["family"], qdir)


def pm_vs_options(fields: dict) -> dict:
    """The PM YES mid vs the options-implied P(YES) on one tick (raw orientation). The option number is a
    risk-neutral estimate from listed prices, not a measured probability."""
    b, a = _fin(fields.get("yes_bid")), _fin(fields.get("yes_ask"))
    pm = (b + a) / 2.0 if b is not None and a is not None else None
    op = _fin(fields.get("opt_implied_prob"))
    return {"pm_mid": pm, "opt_implied_prob": op, "gap": (pm - op) if pm is not None and op is not None else None,
            "opt_mid": _fin(fields.get("opt_mid")), "opt_iv": _fin(fields.get("opt_iv")),
            "opt_delta": _fin(fields.get("opt_delta")), "eightk_score": _fin(fields.get("eightk_score")),
            "label": "PM price measured; options-implied probability is a risk-neutral estimate"}


def option_structure(family: str, ctx: dict, side: int) -> dict | None:
    """The unit an Option intent trades, as signed legs (+1 long / -1 short per unit bought), from the family and the
    matched question: binary_vs_spread_arb -> the YES-equivalent spread (call spread for "above", put spread for
    "below"); vol_vs_pm_move -> the straddle at the listed strike nearest K; eightk_opportunity -> selling opens a
    cash-secured put at k_lo (unit = one put), buying opens a put spread k_hi/k_lo."""
    k_lo, k_hi, K = ctx["k_lo"], ctx["k_hi"], _fin(ctx.get("strike"))
    if family == "binary_vs_spread_arb":
        if ctx["above"]:
            return {"kind": "call_spread", "legs": [(1, k_lo, "call"), (-1, k_hi, "call")], "width": k_hi - k_lo}
        return {"kind": "put_spread", "legs": [(1, k_hi, "put"), (-1, k_lo, "put")], "width": k_hi - k_lo}
    if family == "vol_vs_pm_move":
        k = k_lo if K is None or abs(K - k_lo) <= abs(k_hi - K) else k_hi
        return {"kind": "straddle", "legs": [(1, k, "call"), (1, k, "put")], "strike": k}
    if family == "eightk_opportunity":
        if side < 0:
            return {"kind": "cash_secured_put", "legs": [(1, k_lo, "put")], "strike": k_lo}
        return {"kind": "put_spread", "legs": [(1, k_hi, "put"), (-1, k_lo, "put")], "width": k_hi - k_lo}
    return None


def _quote_by_ticker(chain, ticker: str):
    for q in getattr(chain, "quotes", None) or []:
        if q.ticker == ticker:
            return q
    return None


def unit_risk(struct: dict, side: int, net_mid: float, net_half: float) -> float | None:
    """USD at risk per structure (x100 shares): a bought structure risks its debit (at the ask); a sold spread its
    width minus the credit; a cash-secured put its strike minus the credit; a sold straddle has no defined max loss
    and is counted at its strike notional (the cash-secured analogue). None when there is no price."""
    if net_mid is None or not math.isfinite(net_mid):
        return None
    if side > 0:
        per = net_mid + (net_half or 0.0)
    else:
        credit = max(net_mid - (net_half or 0.0), 0.0)
        if "width" in struct:
            per = struct["width"] - credit
        else:
            per = float(struct.get("strike") or 0.0) - credit
    return max(per, 0.0) * OPTION_MULT


async def _send_option_intent(bridge: Bridge, algo, intent: dict, t: Tick | None) -> dict:
    """One Option intent -> one multi-leg option order (all legs or none), capped by the approved max_contracts /
    max_notional. Fills go back to the algo as one structure price (per share). Never raises."""
    fam = bridge.algo["family"]
    side = 1 if int(intent.get("side") or 0) > 0 else -1
    qty = float(intent.get("qty") or 0.0)
    rec: dict = {"instrument": "option", "side": "buy" if side > 0 else "sell", "qty": qty, "family": fam,
                 "preset": bridge.algo.get("preset_index"), "reason": intent.get("reason"), "symbol": None,
                 "simulated": True, "fill_model": OPTION_FILLS_LABEL}
    broker = bridge.order_broker()
    rec["broker"] = getattr(broker, "name", None)

    def refuse(status: str, why: str, *, error: bool = False) -> dict:
        algo.on_reject("option")
        if error:
            bridge.broker_errors += 1
        rec.update(status=status, reject_reason=why, filled_qty=0.0)
        return rec

    if str(intent.get("instrument")) != "option" or not (qty > 0 and math.isfinite(qty)):
        return refuse("rejected", f"opportunity bridges route option intents only (got {intent.get('instrument')})")
    if broker is None:
        return refuse("error", "no broker", error=True)
    combo = getattr(broker, "place_combo", None)
    if combo is None:
        return refuse("rejected", f"broker {broker.name} cannot take multi-leg option orders")
    ctx = bridge.options.context() if bridge.options is not None else None
    closing = bridge.opt_pos != 0 and side * bridge.opt_pos < 0
    if closing and bridge.opt_open is not None:  # exits trade the open structure's own legs
        struct = {k: v for k, v in bridge.opt_open.items() if k != "legs"}
        legs = [(lg["sign"], lg["ticker"]) for lg in bridge.opt_open["legs"]]
        qty = min(qty, abs(bridge.opt_pos))
    else:
        if ctx is None:
            return refuse("rejected", "no option chain for this market (unmapped question, no listed contracts, "
                                      "or Massive unavailable)")
        struct = option_structure(fam, ctx, side)
        if struct is None:
            return refuse("rejected", f"no option structure for family {fam}")
        sl = ctx["chain"].slice(ctx["expiry"])
        legs = []
        for sign, k, kind in struct["legs"]:
            q = (sl.get(float(k)) or {}).get(kind)
            if q is None:
                return refuse("rejected", f"{kind} {k:g} {ctx['expiry']} is not listed in the snapshot")
            legs.append((sign, q.ticker))
        struct = {"kind": struct["kind"], "expiry": ctx["expiry"], "underlying": ctx.get("underlying"),
                  **{k: v for k, v in struct.items() if k in ("width", "strike")},
                  "strikes": sorted({float(k) for _, k, _ in struct["legs"]})}
    chain = ctx["chain"] if ctx else None
    priced, net_mid, net_half = [], 0.0, 0.0
    for sign, tk in legs:
        q = _quote_by_ticker(chain, tk) if chain is not None else None
        mid = _fin(getattr(q, "mid", None))
        b, a = _fin(getattr(q, "bid", None)), _fin(getattr(q, "ask", None))
        half = (a - b) / 2.0 if b is not None and a is not None and a >= b else None
        priced.append((sign, tk, mid, half, getattr(q, "mark_source", None)))
        if mid is None or net_mid is None:
            net_mid = None
        else:
            net_mid += sign * mid
            net_half += half if half is not None else mid * 0.02
    rec["symbol"] = struct.get("underlying") or bridge.proposal.ticker
    rec["structure"] = struct["kind"]
    if not closing:  # risk caps apply to anything that opens or adds exposure
        p = bridge.proposal
        room_c = max(0.0, float(p.max_contracts or 0) - abs(bridge.opt_pos)) if p.max_contracts else qty
        risk = unit_risk(struct, side, net_mid, net_half)
        if risk is None:
            return refuse("rejected", "no option quote to size the max_notional cap")
        if risk <= 0:  # stale / crossed leg quotes: zero risk is never unlimited room
            return refuse("rejected", "the leg quotes give a non-positive risk per structure (stale or crossed "
                                      "quotes), so the max_notional cap cannot be sized")
        used = abs(bridge.opt_pos) * bridge.opt_risk_per_unit
        room_n = math.floor((float(p.max_notional) - used) / risk + 1e-9) if p.max_notional else qty
        allowed = float(math.floor(min(qty, room_c, room_n)))
        if allowed < qty:
            rec["capped_from"] = qty
            rec["cap"] = "max_contracts" if room_c <= room_n else "max_notional"
            qty = allowed
            rec["qty"] = qty
            if qty <= 0:
                bridge.cap_holds += 1
                return refuse("held", f"risk cap: the approved {rec['cap']} "
                                      f"({p.max_contracts if rec['cap'] == 'max_contracts' else p.max_notional:g}) "
                                      "is used up")
        rec["unit_risk"] = risk
    note = None
    if bridge.effective_source == "replay":
        note = "replay: option legs priced at the current chain snapshot, not the replayed time"
        rec["price_note"] = note
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
    if not isinstance(bridge.broker, SimBroker):
        rec["routed"] = "simulator (Webull paper takes equities only)"
    cid = f"{bridge.id}-{bridge.orders}"
    try:
        reqs = [OrderRequest(symbol=tk, asset="option", side="buy" if sign * side > 0 else "sell", qty=qty,
                             type="market", ref_px=mid if mid is not None and mid > 0 else None,
                             ref_half_spread=half if mid is not None and mid > 0 else None,
                             client_order_id=f"{cid}-L{i}", tag=bridge.id, combo_id=cid, note=note)
                for i, (sign, tk, mid, half, _src) in enumerate(priced)]
        orders = await asyncio.wait_for(combo(reqs), BROKER_TIMEOUT_S)
    except Exception as e:
        return refuse("error", type(e).__name__, error=True)
    rec["legs"] = [{"ticker": o.symbol, "side": o.side, "qty": o.qty, "status": o.status, "fill_px": o.fill_px,
                    "fee": o.fee, "order_id": o.id, "price_source": o.price_source, "quote_mid": mid,
                    "quote_half_spread": half, "mark_source": src}
                   for o, (_s, _t, mid, half, src) in zip(orders, priced)]
    rec["combo_id"] = cid
    rec["broker"] = orders[0].broker if orders else rec["broker"]
    rec["note"] = orders[0].note if orders else None
    rec["quote"] = {"net_mid": net_mid, "half_spread": net_half if net_mid is not None else None}
    if orders and all(o.status == "filled" for o in orders):
        px = sum(sign * float(o.fill_px) for (sign, *_r), o in zip(priced, orders))
        fee = sum(o.fee for o in orders)
        algo.on_fill("option", side * qty, px)
        bridge.broker_filled += 1
        was_flat = bridge.opt_pos == 0
        bridge.opt_pos += side * qty
        if was_flat:
            bridge.opt_open = {**struct, "side": "long" if side > 0 else "short",
                               "legs": [{"sign": sign, "ticker": tk} for sign, tk, *_r in priced]}
            bridge.opt_risk_per_unit = float(rec.get("unit_risk") or 0.0)
        if abs(bridge.opt_pos) < 1e-9:
            bridge.opt_pos, bridge.opt_open, bridge.opt_risk_per_unit = 0.0, None, 0.0
        rec.update(status="filled", filled_qty=qty, fill_px=px, fee=fee, order_id=cid)
    else:
        bridge.broker_rejects += 1
        why = next((o.reject_reason for o in orders if o.reject_reason), "combo not filled")
        algo.on_reject("option")
        rec.update(status="rejected", reject_reason=why, filled_qty=0.0)
    return rec


async def _run(bridge: Bridge, app, hc, source, fallback: Path | None) -> None:
    if bridge.algo:
        # Position fields only: the direction already reached the ticks (orient_to_adverse); never passed to hedgecore.
        position = ({"option": 0.0} if bridge.division == "opportunity"
                    else {"shares_held": float(bridge.proposal.shares_held)})
        try:
            engine = hc.Algo(bridge.algo["family"], dict(bridge.algo["params"]), position)
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
    if bridge.options is not None and bridge.effective_source == "replay":
        # Replays keep the option fields they recorded; the current snapshot is only used to price the legs.
        await bridge.options({"ts_ns": time.time_ns()}, time.time_ns())
    if bridge.options is not None:
        await bridge.emit("status", {"status": "running", "options": _options_brief(bridge.options)
                                     if bridge.options.detail else {"supported": None, "reason": "resolving"}})
    try:
        try:
            await loop(source)
        except (SourceError, OSError) as e:
            await bridge.emit("error", {"message": str(e), "source": bridge.effective_source})
            if bridge.effective_source == "live" and fallback is not None and fallback.is_file():
                # Settle what is open at the account broker first (resting order, open option structure): after the
                # switch, orders go to the replay sandbox and must never orphan what the live phase left working.
                await _finish_orders(bridge, engine)
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


OPTION_CLOSE_LABEL = ("simulated close at bridge end: the open option structure is bought/sold back on its own legs "
                      "at the Massive quote mid +/- half the spread (SimBroker), so no option position outlives the "
                      "bridge")


async def _finish_orders(bridge: Bridge, engine) -> None:
    """A bridge that ends leaves no order resting at the broker, and an opportunity bridge leaves no option structure
    open: it is closed on its own legs (simulated, labelled). A close that cannot be priced is reported, not hidden:
    the structure then stays in the summary's option_structure."""
    if bridge.resting is not None:  # algo and legacy bridges alike
        await _settle_resting(bridge, engine if bridge.algo else None, bridge.order_broker(), "bridge_end")
    if bridge.algo and bridge.division == "opportunity" and bridge.opt_pos != 0 and bridge.opt_open is not None:
        bridge.orders += 1
        intent = {"action": "order", "instrument": "option", "side": -1 if bridge.opt_pos > 0 else 1,
                  "qty": abs(bridge.opt_pos), "reason": "bridge_end"}
        fill = await _send_option_intent(bridge, engine, intent, None)
        fill.update(close_reason="bridge_end", close_label=OPTION_CLOSE_LABEL)
        bridge.fills.append(fill)
        del bridge.fills[:-MAX_FILLS]
        await bridge.emit("fill", fill)
        await bridge.emit("position", {
            "option_position": bridge.opt_pos, "option_structure": bridge.opt_open,
            "risk_used": abs(bridge.opt_pos) * bridge.opt_risk_per_unit,
            "max_contracts": bridge.proposal.max_contracts, "max_notional": bridge.proposal.max_notional,
            "broker": fill.get("broker"), "simulated": True, "close_reason": "bridge_end"})


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
    opp = prop.family == "opportunity"
    try:
        r = resolve_algo(_catalog_manifest(hc), choice.family, choice.preset_index, choice.params,
                         division="opportunity" if opp else "hedge")
    except AlgoChoiceError as e:
        raise HTTPException(422, f"algo: {e}.")
    if opp:  # the approved max_contracts caps the per-entry size; the bridge also caps open contracts / notional
        run, lowered = cap_contracts(r["params"], prop.max_contracts)
        return ({"family": r["family"], "preset_index": r["preset_index"], "params": run, "source": choice.source,
                 "coverage_cap": None, "capped": lowered, "division": "opportunity",
                 "max_contracts": prop.max_contracts, "max_notional": prop.max_notional},
                AlgoChoice(family=choice.family, preset_index=choice.preset_index, params=choice.params))
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


def _has_options_algo(prop: Proposal, request: Request) -> bool:
    """An opportunity proposal reaches hedgecore only when it was approved with an Opportunity-division options
    family (checked against the library the proposal was validated with)."""
    if prop.algo is None:
        return False
    from .pipeline.router import get_adapter
    try:
        fams = get_adapter(request).library()[0].get("families") or []
    except Exception:
        return False
    fam = next((f for f in fams if f.get("id") == prop.algo.family), None)
    return fam is not None and is_option_family(fam)


def _options_enricher(request: Request, market: MarketRef) -> OptionsEnricher:
    """The option-field source for an opportunity bridge. Tests set app.state.options_enricher_factory."""
    factory = getattr(request.app.state, "options_enricher_factory", None)
    if factory is not None:
        return factory(market)

    async def resolve():
        import httpx
        from .options.router import resolve_market
        async with httpx.AsyncClient() as http:
            m = await resolve_market(http, market.source, market.id)
        return m.get("question"), m.get("end_date")
    return OptionsEnricher(resolve=resolve)


def _mapped_twin(market: MarketRef) -> tuple[str, str] | None:
    """The verified twin of the primary market from the twin map (app/data/kalshi_twins.json), as _twin() returns it."""
    t = twin_of(market.source, market.id, market.token_id)
    if t is None:
        return None
    return (t.source, t.token_id) if t.source == "polymarket" and t.token_id else (t.source, t.id)


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
    if prop.family != "hedge" and not _has_options_algo(prop, request):
        raise HTTPException(409, "This opportunity proposal was not approved with an options algo (fit an "
                                 "Opportunity-division options family in Build and propose it); without one it is "
                                 "executed as a single simulated options order, not by hedgecore.")
    reg = _registry(request)
    existing = reg.get(prop.id)
    if existing is not None and existing.status != "running":
        # finished / stopped: a new POST starts a fresh bridge (it replaces the registry entry); the old one stays
        # readable by its id (summary / stream) but is never handed back as if it were the new run
        _history(request)[existing.id] = existing
        existing = None
    if existing is not None:  # idempotent: one running bridge per approved proposal id
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

    fallback = _fallback_path(request.app, market)
    if body.source == "replay":
        path = _replay_path(request, market, body.market)
        if path is None or not path.is_file():
            raise HTTPException(422, "No replay file configured (set POLYBRIDGE_REPLAY_PATH or add replays/<market id>.jsonl).")
        bars = _bars(prop.ticker)
        source: Any = ReplaySource(path, speed=_replay_speed(request.app), bars=bars)
        bridge.equity_price = _replay_equity_price(path, bars)
        if bridge.division == "opportunity":
            bridge.options = _options_enricher(request, market)
    else:
        primary, mid = _live_primary(market)
        twin = _twin(body.twin, primary)
        origin = "request" if twin else None
        if twin is None and body.twin is None:  # no twin given: use the verified twin map
            twin = _mapped_twin(market)
            origin = "twin_map" if twin else None
        bridge.twin = {"source": twin[0], "id": twin[1], "origin": origin} if twin else None
        factory = getattr(request.app.state, "live_source_factory", None) or LiveSource
        if bridge.division == "opportunity":  # option fields from the chain; no equity quote needed
            bridge.options = _options_enricher(request, market)
            source = factory(mid, primary=primary, twin=twin, equity=None, options=bridge.options)
        else:
            # Only the algo reads under_px; a legacy bridge never polls the equity quote (Massive rate limits).
            source = factory(mid, primary=primary, twin=twin,
                             equity=_equity_quote(bridge, request.app) if algo else None)

    # No await between the registry check above and this insert: exactly one bridge per proposal.
    reg[prop.id] = bridge
    store.mark_bridge_started(prop.id)
    bridge.task = asyncio.create_task(_run(bridge, request.app, hc, source, fallback))
    return {"bridge_id": bridge.id}


def _history(request: Request) -> dict[str, Bridge]:
    if not hasattr(request.app.state, "bridge_history"):
        request.app.state.bridge_history = {}
    return request.app.state.bridge_history


def _find(request: Request, bridge_id: str) -> Bridge:
    for b in _registry(request).values():
        if b.id == bridge_id:
            return b
    if (old := _history(request).get(bridge_id)) is not None:
        return old
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
