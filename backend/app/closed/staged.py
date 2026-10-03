"""Hedge B: staged session orders (docs/design.md, section 2, Product behaviour 5).

While equities are closed and the prediction market moves, an equity hedge order is *staged* for the next tradable
session. Nothing is sent before the user approves the plan.

Plan (``plan_for``)
  expected gap  from P1's gap service (``app.closed.gap``): gap_bp = rate x sign x YES move since the last regular close
                (pp); the market's own rate and research sign when gap_rates.json lists it with enough closures, else
                the pooled research rate (7.52 bp/pp, 380 closures) with the wide band; sign from the bridge direction
                (down_on_yes -1, up_on_yes +1). The plan keeps the band (80%), the rate band and n closures, and adds
                BAND_INCLUDES_ZERO when the rate band straddles zero (the pooled rate's always does).
  sizing        on the point estimate, for a long holder (only a negative gap is adverse):
                  total hedge = target_coverage x shares_held x min(1, |gap_bp| / full_size_gap_bp)
                  qty = floor(total hedge - equity hedge already held - PM-leg equivalent shares - other working orders)
                and never above the coverage room (target_coverage x shares_held minus everything already hedged, PM and
                equity legs combined). Below ``min_gap_bp`` (or not adverse) nothing is staged.
  timing        the next session's pre-market (04:00 ET) when the executing broker supports extended hours
                (``Broker.extended_hours``), else the 09:30 ET regular open; immediately when that session is already on.
Revert / resize (``reassess``)
  The plan's rate and band are kept; the gap is recomputed from the current PM move. Not adverse beyond min_gap_bp any
  more: cancelled (PM_REVERTED), at the broker too when the order already rests there. Smaller: an order not yet sent is
  resized down (PM_PARTIAL_REVERT_RESIZE); an order resting at the broker is not resized (only a full revert cancels
  it). Larger: a plan not yet approved follows the gap up too (PM_RESIZE_UP, within the coverage room); an approved
  one is never resized up past what was approved (RESIZE_UP_NEEDS_APPROVAL; a new plan must be approved).
Coverage (``coverage``, the same room at planning and just before sending)
  cap (target_coverage x shares_held) minus the bridge's filled hedge, the unfilled part of its resting sell, the
  unfilled part of this proposal's other staged sells resting at a broker, and hedge A's current PM leg in shares.
  ``reserved_sell_qty`` is subtracted in bridges._coverage_room (with hedge A's leg) so a bridge never sells that room
  too. A wall-clock order follows the proposal's current bridge (a restarted run gets the fill and the coverage check).
  A fill reaches the bridge's ``on_staged_fill`` hook: its own algo and hedge A hear of the equity sold (handoff).
Execution (``run_due`` on the wall clock; ``on_tick`` from every bridge tick, app/closed/bridge_mode.py)
  At the session start through the active broker. Pre-market orders are limit orders (Webull takes only limits outside
  09:30-16:00) with a collar around the lower of the quote and the expected open (a sell); regular-open orders are
  market orders. A pre-market limit still resting at 09:30 is cancelled and its rest sent as a market order. The
  model's expected open is never a fill price: a simulator with no quote waits (NO_QUOTE_WAIT) until the session ends.
  Webull paper takes orders only 09:30-16:00 ET (its ``extended_hours`` capability is off by default, so its orders are
  scheduled for the regular open). A broker refusal that only says the session is closed (``market_closed: ...``, the
  sandbox's 417) is not a failure: the order is HELD_FOR_NEXT_SESSION, rescheduled for the next regular open with a
  fresh client order id, and stays approved.
Replays
  A replay order (planned on a replay bridge named by bridge_id) moves only on replayed ticks: the tick's recorded time,
  its PM move and its recorded equity price (never today's quote or the live tracker), through the replay bridge's own
  sandbox broker (never the account; it waits while no sandbox is attached). Planning needs a replayed tick time
  (409 REPLAY_NO_TICK_TIME). The background runner never moves replay orders.
Every state change appends a reason code to ``decisions``.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from ..broker import Broker, BrokerError, OrderRequest, SimBroker, get_broker
from ..broker.webull import is_market_closed
from . import gap as gapsvc
from .session import ET, UTC, now_utc, regular_hours, session_at, to_utc
from .tracker import NO_CLOSE_PRICE, NO_PM_DATA, market_key, tracker_for

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_FULL_SIZE_GAP_BP = 50.0
DEFAULT_MIN_GAP_BP = 10.0
DEFAULT_COLLAR_BPS = 100.0
BROKER_TIMEOUT_S = 30.0
POLL_S = 15.0
EPS = 1e-9

StagedStatus = Literal["staged", "approved", "working", "filled", "cancelled", "rejected", "skipped"]
PENDING = ("staged", "approved", "working")  # still able to trade
SessionTarget = Literal["pre_market", "regular_open", "regular_now"]
FIXED = "Fills are simulated by the SimBroker unless the active broker is Webull paper (equities)."


def _iso(x: dt.datetime | None) -> str | None:
    return x.astimezone(UTC).isoformat().replace("+00:00", "Z") if x is not None else None


def _fin(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# --------------------------------------------------------------------------------------------- pure functions


def gap_rate_dict(r: "gapsvc.GapRate") -> dict:
    d = {k: getattr(r, k) for k in ("rate_bp_per_pp", "se", "n_closures", "n_nonzero", "label", "source",
                                   "resid_sd_bp", "se_eff", "sign", "ticker", "use")}
    return d


def choose(market_source: str | None, market_id: str | None, ticker: str, direction: str,
           token_id: str | None = None, rate_bp_per_pp: float | None = None, rate_se: float | None = None,
           n_closures: int | None = None) -> tuple["gapsvc.GapRate", int, list[str]]:
    """(rate, sign, reason codes): a supplied rate, else the gap service's choice for the market (own or pooled)."""
    rates = gapsvc.load_rates()
    if rate_bp_per_pp is not None:
        pooled = rates.pooled
        se = rate_se if rate_se is not None else abs(rate_bp_per_pp) * pooled.se_eff / pooled.rate_bp_per_pp
        r = gapsvc.GapRate(rate_bp_per_pp, se, int(n_closures or 0), int(n_closures or 0), "supplied", "request",
                           pooled.resid_sd_bp, se)
        own, codes = None, ["GAP_SUPPLIED_RATE"]
    elif market_source and market_id:
        r, own, codes = gapsvc.choose_rate(rates, market_source, market_id, ticker, token_id)
    else:
        r, own, codes = rates.pooled, None, [gapsvc.GAP_POOLED_RATE]
    sign = own.sign if own is not None and own.sign is not None else gapsvc.direction_sign(direction)
    if sign is None:
        sign = 1
        codes.append(gapsvc.GAP_ORIENTATION_ASSUMED)
    return r, sign, codes


def gap_estimate(move_pp: float, rate: "gapsvc.GapRate", sign: int, ticker: str | None = None,
                 codes: list[str] | None = None) -> dict:
    """Expected open gap (bp, positive = up) for the YES move since the close, through the gap service's formula, with
    its 80% band, the rate band, and n closures. ``adverse`` is True when the gap hurts a long holder (negative)."""
    g = gapsvc.expected_gap(move_pp, rate, sign=sign, in_closure=True, ticker=ticker, reasons=list(codes or []))
    lo_r, hi_r = g.band_rate
    reasons = list(g.reasons)
    if lo_r <= 0.0 <= hi_r:
        reasons.append("BAND_INCLUDES_ZERO")
    return {"pm_move_pp": move_pp, "sign": sign, "oriented_move_pp": g.oriented_move_pp,
            "gap_bp": round(g.expected_gap_bp, 6), "band_bp": [round(x, 6) for x in g.band_bp],
            "band_level": g.band_level, "rate_bp_per_pp": g.rate_bp_per_pp, "rate_band": [lo_r, hi_r],
            "n_closures": g.n_closures, "rate_source": g.label, "basis_ticker": g.basis_ticker,
            "reasons": reasons, "rate": gap_rate_dict(rate)}


def size_hedge(gap_bp: float, shares_held: float, target_coverage: float, existing_hedge: float,
               pm_leg_equiv_shares: float, other_pending: float, full_size_gap_bp: float,
               min_gap_bp: float) -> tuple[int, list[str], dict]:
    """(qty to sell short, reason codes, sizing detail). Coverage counts equity and PM legs together."""
    cap_total = math.floor(target_coverage * shares_held + EPS)
    hedged = max(0.0, existing_hedge) + max(0.0, pm_leg_equiv_shares) + max(0.0, other_pending)
    room = max(0, math.floor(cap_total - hedged + EPS))
    detail = {"cap_total": cap_total, "existing_hedge": existing_hedge, "pm_leg_equiv_shares": pm_leg_equiv_shares,
              "other_pending": other_pending, "coverage_room": room, "scale": 0.0, "target_hedge": 0}
    if gap_bp >= 0:
        return 0, ["GAP_NOT_ADVERSE"], detail
    if -gap_bp < min_gap_bp:
        return 0, ["GAP_BELOW_THRESHOLD"], detail
    scale = min(1.0, -gap_bp / full_size_gap_bp)
    target = math.floor(target_coverage * shares_held * scale + EPS)
    detail.update(scale=round(scale, 6), target_hedge=target)
    want = max(0, math.floor(target - hedged + EPS))
    if want <= 0:
        return 0, ["ALREADY_HEDGED"], detail
    if want > room:
        return room, (["COVERAGE_CAP"] if room > 0 else ["COVERAGE_CAP_REACHED"]), detail
    return want, ["SIZED_TO_EXPECTED_GAP"], detail


def schedule(now: Any, extended: bool) -> tuple[SessionTarget, dt.datetime, dt.date, list[str]]:
    """(target, execute_at UTC, session ET date, codes) for an order staged at ``now``."""
    sess = session_at(now)
    if sess.equities_open:
        return "regular_now", sess.at, sess.at.astimezone(ET).date(), ["SESSION_OPEN_NOW"]
    if sess.phase == "pre_market":
        if extended:
            return "pre_market", sess.at, sess.at.astimezone(ET).date(), ["PRE_MARKET_NOW"]
        return "regular_open", sess.next_open, sess.next_open.astimezone(ET).date(), ["NO_EXTENDED_HOURS_WAIT_OPEN"]
    if extended:
        return ("pre_market", sess.next_extended_open, sess.next_extended_open.astimezone(ET).date(),
                ["NEXT_PRE_MARKET"])
    return "regular_open", sess.next_open, sess.next_open.astimezone(ET).date(), ["NO_EXTENDED_HOURS_WAIT_OPEN"]


# ------------------------------------------------------------------------------------------------------ models


class Decision(BaseModel):
    at: str
    code: str
    detail: str | None = None


class StagedOrder(BaseModel):
    id: str
    status: StagedStatus
    proposal_id: str
    bridge_id: str | None = None
    ticker: str
    side: Literal["sell", "buy"] = "sell"
    qty: int                       # current quantity (after any resize)
    approved_qty: int | None = None  # ceiling once approved: a resize never goes above it
    planned_qty: int
    direction: str
    market_key: str | None = None  # tracker key of the PM market whose move drives the plan
    clock: Literal["wall", "replay"] = "wall"
    session_target: SessionTarget
    execute_at: str
    session_date: str
    broker: str | None = None
    extended_hours: bool = False
    order_type: Literal["market", "limit"] = "market"
    ref_px: float | None = None
    collar_bps: float = DEFAULT_COLLAR_BPS
    full_size_gap_bp: float = DEFAULT_FULL_SIZE_GAP_BP
    min_gap_bp: float = DEFAULT_MIN_GAP_BP
    shares_held: float
    target_coverage: float
    pm_leg_equiv_shares: float = 0.0
    estimate: dict                 # gap_estimate(...) at plan time
    current: dict | None = None    # gap_estimate(...) at the latest reassessment
    sizing: dict
    planned_at: str
    approved_at: str | None = None
    executed_at: str | None = None
    client_order_id: str
    broker_order: dict | None = None
    filled_qty: float = 0.0        # total filled over every broker order of this plan
    prior_filled: float = 0.0      # filled by earlier (cancelled and replaced) broker orders
    replacements: int = 0          # pre-market limits replaced by a regular-session order at the open
    holds: int = 0                 # times the broker refused it only because the market was closed (held, resent)
    fill_px: float | None = None
    ref_source: str | None = None  # where the price sent with the order came from: quote | tick | recorded
    limit_anchor: str | None = None  # a pre-market limit's anchor: quote | recorded | expected_open_estimate
    reason: str | None = None      # latest reason code
    decisions: list[Decision] = []
    label: str = "Staged session hedge: executes only after approval, at the next tradable session."


class PlanIn(BaseModel):
    bridge_id: str | None = Field(default=None, max_length=64)
    proposal_id: str | None = Field(default=None, max_length=64)
    # PM inputs (else read from the closure tracker / gap service for the bridge's market)
    pm_move_pp: float | None = Field(default=None, ge=-100, le=100, allow_inf_nan=False)
    rate_bp_per_pp: float | None = Field(default=None, allow_inf_nan=False)
    rate_se: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    n_closures: int | None = Field(default=None, ge=0)
    ref_px: float | None = Field(default=None, gt=0, allow_inf_nan=False)  # last equity close / quote
    pm_leg_equiv_shares: float | None = Field(default=None, ge=0, allow_inf_nan=False)  # hedge A, in shares
    full_size_gap_bp: float = Field(default=DEFAULT_FULL_SIZE_GAP_BP, gt=0, le=10_000, allow_inf_nan=False)
    min_gap_bp: float = Field(default=DEFAULT_MIN_GAP_BP, ge=0, le=10_000, allow_inf_nan=False)
    collar_bps: float = Field(default=DEFAULT_COLLAR_BPS, gt=0, le=1_000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _one(self) -> "PlanIn":
        if not (self.bridge_id or self.proposal_id):
            raise ValueError("Send bridge_id or proposal_id.")
        return self


# -------------------------------------------------------------------------------------------- app adapters


def _bridges(app) -> list:
    st = app.state
    live = list((getattr(st, "bridges", None) or {}).values())
    old = list((getattr(st, "bridge_history", None) or {}).values())
    return live + old


def find_bridge(app, bridge_id: str | None):
    if not bridge_id:
        return None
    return next((b for b in _bridges(app) if getattr(b, "id", None) == bridge_id), None)


def bridge_for_proposal(app, proposal_id: str):
    """The proposal's latest bridge run (running or stopped; a restart replaces it in ``app.state.bridges``)."""
    return (getattr(app.state, "bridges", None) or {}).get(proposal_id)


def is_replay(bridge) -> bool:
    return bridge is not None and getattr(bridge, "effective_source", None) == "replay"


def sandboxed(bridge) -> bool:
    """A replay bridge trading in its own in-memory sim (never the account)."""
    if not is_replay(bridge):
        return False
    return bool(bridge._sandboxed()) if hasattr(bridge, "_sandboxed") else True


def bridge_now(bridge) -> dt.datetime | None:
    """A replay bridge's "now" is its last replayed tick's recorded time (None until a tick has set it)."""
    if is_replay(bridge):
        ts = getattr(bridge, "last_replay_ts_ns", None)
        return to_utc(ts) if ts else None
    return None


def wall_now(app) -> dt.datetime:
    clock = getattr(app.state, "staged_clock", None)  # tests pin the wall clock
    return to_utc(clock()) if clock else now_utc()


def bridge_of(app, o: "StagedOrder"):
    """The bridge whose hedge a staged order belongs to *now*. A replay order stays with its own replay run (its
    sandbox holds the order). A wall-clock order follows the proposal: a bridge restarted after the plan (e.g. stopped
    over the weekend, restarted Monday) is the one whose coverage and hedge counters must see the fill."""
    orig = find_bridge(app, o.bridge_id)
    if o.clock == "replay":
        return orig
    cur = bridge_for_proposal(app, o.proposal_id)
    if cur is not None:
        return cur
    return None if is_replay(orig) else orig


def order_broker(app, bridge, clock: str = "wall") -> Broker | None:
    """The broker a staged order trades through. Replay: the replay bridge's own broker (its sandbox), never the
    account; None while a sandboxed replay has no sandbox attached yet (the order waits). Wall clock: a live bridge's
    broker, else the active (account) broker, never a replay sandbox."""
    if clock == "replay":
        b = bridge.order_broker() if bridge is not None and hasattr(bridge, "order_broker") else None
        if b is None and not sandboxed(bridge):
            return get_broker(app)  # replay_to_account without an attached broker: the account
        return b
    if bridge is not None and not is_replay(bridge) and hasattr(bridge, "order_broker"):
        b = bridge.order_broker()
        if b is not None:
            return b
    return get_broker(app)


def _summary_field(bridge, *names: str) -> Any:
    try:
        s = bridge.summary()
    except Exception:  # a half-built bridge never breaks planning
        return None
    for n in names:
        if s.get(n) is not None:
            return s[n]
    return None


def pm_leg_shares(bridge) -> float | None:
    """Hedge A's PM leg expressed in equity shares when the bridge reports it (P2/P5); None when it reports nothing
    (not wired), so callers can tell "no PM leg" from "unknown"."""
    if bridge is None:
        return None
    for name in ("hedge_a", "pm_hedge", "closed_hedge"):
        v = _summary_field(bridge, name)
        if isinstance(v, dict):
            for k in ("equity_equiv_shares", "equiv_shares", "shares_equiv", "covered_shares"):
                if (x := _fin(v.get(k))) is not None:
                    return max(0.0, x)
    return None


def current_move(app, mkey: str | None, at: dt.datetime) -> tuple[float | None, str]:
    """(YES move since the last close in points, tracker status) for a market key at an instant."""
    if not mkey:
        return None, NO_PM_DATA
    st = tracker_for(app).state(mkey, at)
    return st.move_pp, st.status


def _ref_px(bridge) -> float | None:
    for name in ("last_under_px", "under_px", "last_price"):
        if (x := _fin(getattr(bridge, name, None))) and x > 0:
            return x
    return None


# -------------------------------------------------------------------------------------------------------- book


class StagedBook:
    """In-memory staged orders for one app (like ProposalStore). One event loop; mutations under one asyncio lock."""

    def __init__(self) -> None:
        self._items: dict[str, StagedOrder] = {}
        self.lock = asyncio.Lock()
        self.runner: asyncio.Task | None = None
        self.brokers: dict[str, Broker] = {}  # staged id -> the broker holding its working order

    def list(self, bridge_id: str | None = None, proposal_id: str | None = None,
             status: str | None = None) -> list[StagedOrder]:
        rows = [o for o in self._items.values() if (bridge_id is None or o.bridge_id == bridge_id)
                and (proposal_id is None or o.proposal_id == proposal_id) and (status is None or o.status == status)]
        return sorted(rows, key=lambda o: o.planned_at, reverse=True)

    def get(self, sid: str) -> StagedOrder:
        if sid not in self._items:
            raise KeyError(sid)
        return self._items[sid]

    def put(self, o: StagedOrder) -> None:
        self._items[o.id] = o

    def pending(self) -> list[StagedOrder]:
        return [o for o in self._items.values() if o.status in PENDING]


def book_for(app) -> StagedBook:
    if getattr(app.state, "staged_book", None) is None:
        app.state.staged_book = StagedBook()
    return app.state.staged_book


def _note(o: StagedOrder, at: dt.datetime, code: str, detail: str | None = None) -> None:
    o.decisions.append(Decision(at=_iso(at), code=code, detail=detail))
    o.reason = code


def _note_once(o: StagedOrder, at: dt.datetime, code: str, detail: str | None = None) -> None:
    """A waiting state is logged once, not on every runner pass."""
    if o.reason != code:
        _note(o, at, code, detail)


# ------------------------------------------------------------------------------------------------- coverage


def reserved_sell_qty(app, proposal_id: str, clock: str = "wall", exclude: str | None = None) -> float:
    """Unfilled shares of this proposal's staged sells resting at a broker (status working). P5: subtract this in
    bridges._coverage_room so a live bridge never sells room a resting staged order already holds."""
    return sum(max(0.0, o.qty - o.filled_qty) for o in book_for(app).pending()
               if o.proposal_id == proposal_id and o.status == "working" and o.side == "sell" and o.clock == clock
               and o.id != exclude)


def _resting_sell(bridge) -> float:
    """Unfilled shares of the bridge's own resting equity sell (``bridge.resting``)."""
    r = getattr(bridge, "resting", None) if bridge is not None else None
    if not isinstance(r, dict) or r.get("side") != "sell" or (r.get("instrument") or "equity") != "equity":
        return 0.0
    return max(0.0, (_fin(r.get("qty")) or 0.0) - (_fin(r.get("hedged", r.get("applied"))) or 0.0))


def coverage(app, proposal_id: str, shares_held: float, target_coverage: float, bridge, clock: str,
             pm_leg: float, exclude: str | None = None) -> dict:
    """The one coverage room used for planning and again just before sending: the approved cap (target_coverage x
    shares_held) minus everything that holds or may still take hedge, PM and equity legs together:
      held      the bridge's filled equity hedge (its account total when the bridge is a replay sandbox and the order
                trades at the account)
      resting   the unfilled part of the bridge's own resting sell (it may still fill)
      working   the unfilled part of this proposal's other staged sells resting at a broker
      pm_leg    hedge A's PM leg in equity shares."""
    cap = math.floor(target_coverage * shares_held + EPS)
    held = resting = 0.0
    if bridge is not None:
        at_account_vs_sandbox = clock == "wall" and sandboxed(bridge)
        held = getattr(bridge, "account_hedge", 0.0) if at_account_vs_sandbox else getattr(bridge, "broker_hedge", 0.0)
        held = max(0.0, float(held or 0.0))
        resting = 0.0 if at_account_vs_sandbox else _resting_sell(bridge)
    working = reserved_sell_qty(app, proposal_id, clock, exclude)
    pm = max(0.0, pm_leg)
    room = max(0, math.floor(cap - held - resting - working - pm + EPS))
    return {"cap_total": cap, "held": held, "bridge_resting_sell": resting, "staged_working": working,
            "pm_leg_equiv_shares": pm, "room": room}


# ------------------------------------------------------------------------------------------------------- plan


def plan_for(app, body: PlanIn, store, remote: bool = False) -> StagedOrder:
    """Build (and store) a staged equity hedge for the next session. Raises HTTPException on bad input."""
    bridge = find_bridge(app, body.bridge_id) if body.bridge_id else None
    if body.bridge_id and bridge is None:
        raise HTTPException(404, f"No bridge {body.bridge_id}.")
    pid = body.proposal_id or bridge.proposal_id
    if bridge is not None and body.proposal_id and body.proposal_id != bridge.proposal_id:
        raise HTTPException(409, f"Bridge {bridge.id} runs proposal {bridge.proposal_id}, not {body.proposal_id}.")
    prop = next((p for p in store.list() if p.id == pid), None)
    if prop is None:
        raise HTTPException(404, f"No proposal {pid}.")
    if prop.status != "approved":
        raise HTTPException(409, f"Proposal {prop.id} is {prop.status}; only approved proposals can stage orders.")
    if prop.family != "hedge":
        raise HTTPException(409, "Staged session orders are equity hedges; this is an opportunity proposal.")
    if bridge is None:  # by proposal: its live bridge if one runs; a replay is staged only by naming its bridge_id
        cur = bridge_for_proposal(app, prop.id)
        bridge = None if is_replay(cur) else cur
    clock = "replay" if is_replay(bridge) else "wall"
    if clock == "replay":
        now = bridge_now(bridge)
        if now is None:  # never fall back to the wall clock for a replay
            raise HTTPException(409, "REPLAY_NO_TICK_TIME: this replay bridge has not reported a replayed tick time "
                                     "yet; a replay order is planned on the replayed time only.")
    else:
        now = wall_now(app)
    if session_at(now).equities_open:
        raise HTTPException(409, "MARKET_OPEN: the regular session is on; the bridge hedges live, nothing is staged.")
    broker = order_broker(app, bridge, clock)
    if broker is None:
        raise HTTPException(409, "REPLAY_SANDBOX_NOT_READY: the replay bridge has no sandbox broker attached yet; a "
                                 "replay order never falls back to the account broker.")
    direction = getattr(bridge, "direction", None) or prop.direction or "down_on_yes"
    market = getattr(bridge, "market", None) or prop.market
    mkey = market_key(market.source, market.id) if market is not None else None

    move = body.pm_move_pp
    status = "SUPPLIED"
    if move is None:
        if clock == "replay":
            raise HTTPException(422, "NO_PM_DATA: a replay plan needs pm_move_pp (the closure tracker follows the live "
                                     "market, not the replayed one).")
        move, status = current_move(app, mkey, now)
        if move is None:
            why = ("no PM price at the last close" if status == NO_CLOSE_PRICE else "no recent PM price")
            raise HTTPException(422, f"{status}: {why} for this market; send pm_move_pp.")
    rate, sign, gcodes = choose(getattr(market, "source", None), getattr(market, "id", None), prop.ticker, direction,
                                getattr(market, "token_id", None), body.rate_bp_per_pp, body.rate_se, body.n_closures)
    est = gap_estimate(move, rate, sign, prop.ticker, gcodes)

    extended = bool(getattr(broker, "extended_hours", False))
    target, execute_at, session_date, sched_codes = schedule(now, extended)
    book = book_for(app)
    if body.pm_leg_equiv_shares is not None:
        pm_eq = body.pm_leg_equiv_shares
    else:
        pm_eq = pm_leg_shares(bridge) or 0.0
    cov = coverage(app, prop.id, prop.shares_held, prop.target_coverage, bridge, clock, pm_eq)
    qty, size_codes, sizing = size_hedge(est["gap_bp"], prop.shares_held, prop.target_coverage, cov["held"],
                                         pm_eq, cov["staged_working"] + cov["bridge_resting_sell"],
                                         body.full_size_gap_bp, body.min_gap_bp)
    sizing.update(staged_working=cov["staged_working"], bridge_resting_sell=cov["bridge_resting_sell"])
    ref = None if remote else body.ref_px
    ref = ref or (_ref_px(bridge) if bridge is not None else None)
    sid = uuid.uuid4().hex[:12]
    o = StagedOrder(
        id=sid, status="staged" if qty > 0 else "skipped", proposal_id=prop.id,
        bridge_id=getattr(bridge, "id", None), ticker=prop.ticker, qty=qty, planned_qty=qty, direction=direction,
        market_key=mkey, clock=clock, session_target=target, execute_at=_iso(execute_at),
        session_date=session_date.isoformat(), broker=getattr(broker, "name", None),
        extended_hours=target == "pre_market", order_type="limit" if target == "pre_market" else "market",
        ref_px=ref, collar_bps=body.collar_bps, full_size_gap_bp=body.full_size_gap_bp, min_gap_bp=body.min_gap_bp,
        shares_held=prop.shares_held, target_coverage=prop.target_coverage, pm_leg_equiv_shares=pm_eq,
        estimate={**est, "pm_status": status}, sizing=sizing, planned_at=_iso(now), client_order_id=f"stg-{sid}")
    for c in sched_codes:
        _note(o, now, c, f"execute at {_iso(execute_at)} ({target}); broker {o.broker} "
                         f"extended_hours={extended}")
    _note(o, now, "EXPECTED_GAP",
          f"PM move {move:+.2f} pp -> gap {est['gap_bp']:.1f} bp, {est['band_level']:.0%} band "
          f"[{est['band_bp'][0]:.1f}, {est['band_bp'][1]:.1f}] bp, {est['rate_source']} rate "
          f"{est['rate_bp_per_pp']:.2f} bp/pp on n={est['n_closures']} closures ({', '.join(est['reasons'])})")
    for c in size_codes:
        _note(o, now, c, f"qty {qty}; coverage room {sizing['coverage_room']} of cap {sizing['cap_total']}")
    if qty > 0:
        for prev in book.list(proposal_id=prop.id):
            if prev.status in ("staged", "approved") and prev.clock == clock:
                prev.status = "cancelled"
                _note(prev, now, "SUPERSEDED", f"replaced by plan {sid}")
        _note(o, now, "AWAITING_APPROVAL")
    book.put(o)
    return o


def reassess(o: StagedOrder, move_pp: float, at: dt.datetime) -> str | None:
    """Apply the revert / resize rule to a pending order for the current PM move. Returns the code applied (None: no
    change). A working order (resting at the broker) is never resized; on a full revert it is only marked
    (PM_REVERTED, logged once) and the caller cancels it at the broker."""
    if o.status not in PENDING:
        return None
    e = o.estimate
    est = gap_estimate(move_pp, gapsvc.GapRate(**e["rate"]), e["sign"], o.ticker)
    o.current = est
    qty, codes, _ = size_hedge(est["gap_bp"], o.shares_held, o.target_coverage,
                               o.sizing["existing_hedge"], o.pm_leg_equiv_shares, o.sizing["other_pending"],
                               o.full_size_gap_bp, o.min_gap_bp)
    detail = f"PM move {move_pp:+.2f} pp -> gap {est['gap_bp']:.1f} bp"
    if qty <= 0:
        if o.status == "working":
            if o.reason not in ("PM_REVERTED", "CANCEL_FAILED"):
                _note(o, at, "PM_REVERTED", detail + f"; {codes[0]}")
            return "PM_REVERTED"
        o.status = "filled" if o.filled_qty > EPS else "cancelled"  # a replaced order keeps what already filled
        if o.filled_qty > EPS:
            o.qty = math.ceil(o.filled_qty - EPS)
        _note(o, at, "PM_REVERTED", detail + f"; {codes[0]}")
        return "PM_REVERTED"
    if o.status == "working":
        return None  # resting at the broker: only a full revert cancels it
    qty = max(qty, math.ceil(o.filled_qty - EPS))  # never below what already filled
    # An unapproved plan follows the gap both ways (within the coverage room size_hedge applies): what the user
    # approves is the plan as it stands, and approval freezes it as the ceiling. An approved plan is never resized up
    # past what was approved.
    ceiling = o.approved_qty if o.approved_qty is not None else (None if o.status == "staged" else o.planned_qty)
    if qty < o.qty:
        _note(o, at, "PM_PARTIAL_REVERT_RESIZE", detail + f"; qty {o.qty} -> {qty}")
        o.qty = qty
        return "PM_PARTIAL_REVERT_RESIZE"
    if qty > o.qty:
        new = qty if ceiling is None else min(qty, ceiling)
        if new > o.qty:  # back up toward what was planned / approved, never above it
            _note(o, at, "PM_RESIZE_UP", detail + f"; qty {o.qty} -> {new} "
                                                  f"({'not yet approved' if ceiling is None else f'ceiling {ceiling}'})")
            o.qty = new
            return "PM_RESIZE_UP"
        if o.reason != "RESIZE_UP_NEEDS_APPROVAL":
            _note(o, at, "RESIZE_UP_NEEDS_APPROVAL", detail + f"; wants {qty}, approved {ceiling}")
            return "RESIZE_UP_NEEDS_APPROVAL"
    return None


# ---------------------------------------------------------------------------------------------------- execution


async def _quote_mid(broker: Broker, symbol: str) -> float | None:
    sim = broker if hasattr(broker, "quotes") else getattr(broker, "sim", None)
    quotes = getattr(sim, "quotes", None)
    if quotes is None:
        return None
    try:
        q = await asyncio.wait_for(quotes.equity(symbol), 10.0)
    except Exception:
        return None
    return q.mid if q is not None and _fin(q.mid) else None


def _prices_itself(broker: Broker) -> bool:
    """True for a real broker that prices its own fills (Webull); a SimBroker needs a price (supplied or quoted)."""
    return not isinstance(broker, SimBroker)


def _apply_fill(o: StagedOrder, bridge, filled_this_order: float, at_account: bool) -> None:
    """Fold a staged fill into the bridge's hedge so its own coverage cap sees it. ``filled_this_order`` is the current
    broker order's cumulative fill; ``prior_filled`` holds what earlier (replaced) broker orders filled."""
    total = o.prior_filled + filled_this_order
    new = total - o.filled_qty
    if new <= EPS:
        return
    o.filled_qty = total
    if bridge is None:
        return
    signed = new if o.side == "sell" else -new
    if at_account:
        bridge.account_hedge = getattr(bridge, "account_hedge", 0.0) + signed
    if not (at_account and sandboxed(bridge)):  # a sandbox does not hold an account fill
        bridge.broker_hedge = getattr(bridge, "broker_hedge", 0.0) + signed
        if getattr(bridge, "algo", None):
            bridge.hedge = bridge.broker_hedge
        # handoff: the bridge's own algo (and hedge A) hear of the equity this plan sold, so the algo that resumes at
        # the open manages it and the combined PM + equity coverage stays one cap
        hook = getattr(bridge, "on_staged_fill", None)
        if callable(hook):
            px = _fin((o.broker_order or {}).get("fill_px")) or o.fill_px
            try:
                hook(signed, px)
            except Exception as e:  # a bridge-side bookkeeping failure never undoes a broker fill
                log.warning("staged fill hook failed: %s", type(e).__name__)


def _at_account(o: StagedOrder, bridge) -> bool:
    return o.clock == "wall" or not sandboxed(bridge)


def _hold_for_next_session(app, o: StagedOrder, order, at: dt.datetime) -> None:
    """The broker refused the order only because the regular session is not on (Webull paper: 417 outside 09:30-16:00
    ET; a holiday the calendar missed, a clock edge). Nothing traded: the plan stays approved and is rescheduled for the
    next regular open (market order), under a new client order id."""
    nxt = session_at(at).next_open
    book_for(app).brokers.pop(o.id, None)
    o.holds += 1
    o.status, o.broker_order = "approved", order.model_dump()
    o.session_target, o.execute_at, o.session_date = "regular_open", _iso(nxt), nxt.astimezone(ET).date().isoformat()
    o.extended_hours, o.order_type = False, "market"
    _note(o, at, "HELD_FOR_NEXT_SESSION", f"{order.broker}: {order.reject_reason}; held for the next regular session, "
                                          f"executes at {_iso(nxt)} (09:30 ET)")


def _take_order(app, o: StagedOrder, order, bridge, at: dt.datetime) -> None:
    if is_market_closed(order):
        _hold_for_next_session(app, o, order, at)
        return
    o.broker_order = order.model_dump()
    o.broker = order.broker
    if order.fill_px is not None:
        o.fill_px = order.fill_px
    if order.filled_qty:
        _apply_fill(o, bridge, float(order.filled_qty), _at_account(o, bridge))
    if order.status == "open":
        o.status = "working"
        _note_once(o, at, "WORKING", f"resting at {order.broker} as {order.id}")
        return
    book_for(app).brokers.pop(o.id, None)
    if order.status == "filled":
        o.status = "filled"
        _note(o, at, "FILLED", f"{o.filled_qty:g} @ {order.fill_px} via {order.broker}"
                               f"{f' ({order.price_source})' if order.price_source else ''}")
    elif o.filled_qty > EPS:  # rejected / cancelled after part of it (or an earlier leg) filled
        o.status = "filled"
        o.qty = math.ceil(o.filled_qty - EPS)
        _note(o, at, "PARTIAL_FILL_DONE", f"{o.filled_qty:g} filled; broker {order.status}: {order.reject_reason}")
    elif order.status == "rejected":
        o.status = "rejected"
        _note(o, at, "BROKER_REJECTED", order.reject_reason)
    else:
        o.status = "cancelled"
        _note(o, at, "BROKER_CANCELLED", order.reject_reason)


def _broker_of(app, o: StagedOrder, bridge) -> Broker | None:
    """The broker holding o's order once sent, else the one it would be sent to."""
    return book_for(app).brokers.get(o.id) or order_broker(app, bridge, o.clock)


async def _execute(app, o: StagedOrder, bridge, at: dt.datetime, ref_override: float | None = None) -> None:
    sess = session_at(at)
    target_day = dt.date.fromisoformat(o.session_date)
    hours = regular_hours(target_day)
    if hours is not None and at >= hours[1]:
        o.status = "filled" if o.filled_qty > EPS else "cancelled"
        _note(o, at, "SESSION_MISSED", f"the {o.session_date} regular session closed before execution")
        return
    broker = order_broker(app, bridge, o.clock)
    if broker is None:
        _note_once(o, at, "REPLAY_SANDBOX_NOT_READY", "waiting for the replay bridge's sandbox broker")
        return
    extended_ok = bool(getattr(broker, "extended_hours", False))
    if sess.equities_open:
        extended = False
    elif sess.phase == "pre_market" and o.session_target == "pre_market":
        if not extended_ok:
            o.session_target, o.execute_at = "regular_open", _iso(sess.next_open)
            o.extended_hours, o.order_type = False, "market"
            _note(o, at, "NO_EXTENDED_HOURS_WAIT_OPEN", f"broker {broker.name} has no extended hours")
            return
        extended = True
    else:
        return  # not yet tradable
    # coverage, checked again just before sending, with the same room function as the plan (current bridge hedge,
    # its resting sell, other working staged sells, and hedge A's current PM leg)
    pm_now = pm_leg_shares(bridge)
    pm = pm_now if pm_now is not None else o.pm_leg_equiv_shares
    cov = coverage(app, o.proposal_id, o.shares_held, o.target_coverage, bridge, o.clock, pm, exclude=o.id)
    remaining = max(0, math.ceil(o.qty - o.filled_qty - EPS))
    if cov["room"] < remaining:
        detail = (f"room {cov['room']} = cap {cov['cap_total']} - held {cov['held']:g} - resting "
                  f"{cov['bridge_resting_sell']:g} - staged working {cov['staged_working']:g} - PM leg {pm:g}")
        if cov["room"] <= 0:
            o.status = "filled" if o.filled_qty > EPS else "cancelled"
            _note(o, at, "COVERAGE_CAP_AT_EXECUTION", detail)
            return
        _note(o, at, "COVERAGE_CAP_AT_EXECUTION", f"qty {remaining} -> {cov['room']}; {detail}")
        remaining = cov["room"]
        o.qty = math.ceil(o.filled_qty - EPS) + remaining
    if remaining <= 0:
        o.status = "filled"
        return

    # price: a replay prices only from the replayed tick, never today's quote; a live order from the live quote. The
    # model's expected open is never a fill price: at most the anchor of a pre-market limit.
    from ..bridges import REPLAY_NOTE, REPLAY_RECORDED_NOTE

    note = f"staged session hedge (plan {o.id})"
    if o.clock == "replay":
        if ref_override is None:
            _note_once(o, at, "REPLAY_NEEDS_TICK_PRICE", "a replay order executes only on a replayed tick with its "
                                                         "recorded equity price")
            return
        ref, src = ref_override, "recorded"
        note += "; " + (REPLAY_NOTE if _prices_itself(broker) else REPLAY_RECORDED_NOTE)
    else:
        ref = ref_override or await _quote_mid(broker, o.ticker)
        src = ("tick" if ref_override else "quote") if ref else None
    if ref is None and not _prices_itself(broker):
        _note_once(o, at, "NO_QUOTE_WAIT", f"no current {o.ticker} price for the simulator; retried each pass until "
                                           "the session closes")
        return
    limit = anchor_src = None
    if extended:
        est_open = None
        if o.ref_px:
            est_open = o.ref_px * (1 + (o.current or o.estimate)["gap_bp"] / 1e4)
        cands = [(x, s) for x, s in ((ref, src), (est_open, "expected_open_estimate")) if x]
        if not cands:
            o.session_target, o.execute_at = "regular_open", _iso(sess.next_open)
            o.extended_hours, o.order_type = False, "market"
            _note(o, at, "NO_REFERENCE_PRICE_WAIT_OPEN", "a pre-market limit needs a reference price")
            return
        # a sell anchors on the lower of the quote and the expected open (a stale Friday quote never leaves an
        # adverse-gap limit unmarketable), a buy on the higher
        anchor, anchor_src = (min if o.side == "sell" else max)(cands, key=lambda c: c[0])
        f = (1 - o.collar_bps / 1e4) if o.side == "sell" else (1 + o.collar_bps / 1e4)
        limit = round(anchor * f, 2)
    if o.replacements or o.holds:  # a new broker order: never reuse the id of one the broker already answered
        o.client_order_id = (f"stg-{o.id}" + (f"-r{o.replacements}" if o.replacements else "")
                             + (f"-h{o.holds}" if o.holds else ""))
    req = OrderRequest(symbol=o.ticker, asset="equity", side=o.side, qty=remaining,
                       type="limit" if extended else "market", limit_px=limit, client_order_id=o.client_order_id,
                       tag=o.bridge_id or o.proposal_id, ref_px=ref, ref_source=src, extended_hours=extended,
                       note=note)
    o.extended_hours, o.order_type, o.executed_at = extended, req.type, _iso(at)
    o.ref_source, o.limit_anchor = src, anchor_src
    _note(o, at, "SUBMITTED", f"{req.side} {req.qty:g} {req.symbol} {req.type}"
                              f"{f' @ {limit} (anchor {anchor_src})' if limit else ''}"
                              f" {'pre-market' if extended else 'regular'} via {broker.name}"
                              f"{f'; price {src}' if src else ''}")
    book_for(app).brokers[o.id] = broker
    try:
        order = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:  # a failure or timeout may still have been accepted: reconcile by client id
        o.status = "working"
        o.broker_order = None
        _note(o, at, "BROKER_UNCONFIRMED", f"{type(e).__name__}; reconciled by client_order_id next run")
        return
    _take_order(app, o, order, bridge, at)


async def _reconcile(app, o: StagedOrder, bridge, at: dt.datetime) -> None:
    """Read the working order back (orders() first, then the broker's find-by-client-id, e.g. a Webull split sell
    or an order whose place call timed out). Only an order neither read knows is treated as never taken."""
    from ..bridges import _lookup  # the bridge's own order lookup: one pattern for every broker

    broker = _broker_of(app, o, bridge)
    if broker is None:
        return
    oid = (o.broker_order or {}).get("id") or o.client_order_id
    try:
        found = await _lookup(broker, oid, o.client_order_id)
    except Exception as e:
        log.warning("staged reconcile failed: %s", type(e).__name__)
        return
    if found is None:
        if o.broker_order is None:  # the place call never reached the broker
            o.status = "approved"
            book_for(app).brokers.pop(o.id, None)
            _note(o, at, "BROKER_NEVER_TOOK_IT", "will be sent again while the session is on")
        return
    if (found.status == "open" and o.status == "working" and o.broker_order
            and o.prior_filled + float(found.filled_qty or 0) == o.filled_qty):
        return
    _take_order(app, o, found, bridge, at)


async def _cancel_at_broker(app, o: StagedOrder, bridge, at: dt.datetime) -> bool:
    """Cancel o's working broker order. True: nothing rests there any more (its fills applied; ``o.status`` may now
    be filled). False: it may still be working (CANCEL_FAILED, logged once)."""
    broker = _broker_of(app, o, bridge)
    if broker is None:
        return False
    oid = (o.broker_order or {}).get("id") or o.client_order_id
    try:
        order = await asyncio.wait_for(broker.cancel(oid), BROKER_TIMEOUT_S)
    except Exception as e:
        await _reconcile(app, o, bridge, at)  # it may have filled (or never been taken) meanwhile
        if o.status == "working":
            _note_once(o, at, "CANCEL_FAILED", e.message if isinstance(e, BrokerError) else type(e).__name__)
            return False
        return True
    o.broker_order = order.model_dump()
    if order.filled_qty:
        _apply_fill(o, bridge, float(order.filled_qty), _at_account(o, bridge))
    if order.status == "open":
        _note_once(o, at, "CANCEL_FAILED", f"broker order {order.id} still open")
        return False
    book_for(app).brokers.pop(o.id, None)
    return True


async def _cancel_working(app, o: StagedOrder, bridge, at: dt.datetime, code: str) -> None:
    if await _cancel_at_broker(app, o, bridge, at) and o.status == "working":
        o.status = "filled" if o.filled_qty > EPS else "cancelled"
        if o.filled_qty > EPS:
            o.qty = math.ceil(o.filled_qty - EPS)
        _note(o, at, code, f"broker order {(o.broker_order or {}).get('id') or o.client_order_id} cancelled"
                           f"{f'; {o.filled_qty:g} had filled' if o.filled_qty > EPS else ''}")


async def _replace_at_open(app, o: StagedOrder, bridge, at: dt.datetime) -> None:
    """At the regular open, a pre-market limit still resting (unfilled or partly filled) is cancelled and its rest
    sent again as a regular-session market order, so a DAY limit left behind by an adverse gap never expires unfilled."""
    if not await _cancel_at_broker(app, o, bridge, at) or o.status != "working":
        return
    remaining = max(0, math.ceil(o.qty - o.filled_qty - EPS))
    if remaining <= 0:
        o.status = "filled"
        return
    o.prior_filled = o.filled_qty
    o.replacements += 1
    o.status, o.broker_order = "approved", None
    o.session_target, o.extended_hours, o.order_type = "regular_open", False, "market"
    _note(o, at, "PRE_MARKET_UNFILLED_REPLACED", f"{remaining} unfilled at the open: pre-market limit cancelled, "
                                                 "sent again as a regular-session market order")


async def step(app, o: StagedOrder, at: dt.datetime | None = None, move_pp: float | None = None,
               ref_px: float | None = None) -> None:
    """One pass over one pending order: reconcile a working order, apply the revert / resize rule for the current PM
    move, and execute it when approved and its session has started.

    A wall-clock order runs on the wall clock and reads the PM move from the closure tracker when ``move_pp`` is not
    given. A replay order moves only on replayed ticks: its time is ``at`` (else the bridge's last replayed tick time;
    with neither it waits), its PM move is only ``move_pp`` and its price only ``ref_px`` (the tick's under_px); the
    tracker and live quotes follow today's market, never the replayed one."""
    if o.status not in PENDING:
        return
    bridge = bridge_of(app, o)
    if o.clock == "replay":
        at = at or bridge_now(bridge)
        if at is None:
            return
    elif at is None:
        at = wall_now(app)
    if o.status == "working":
        await _reconcile(app, o, bridge, at)
        if o.status not in PENDING:
            return
    if move_pp is None and o.clock == "wall":
        move_pp, _ = current_move(app, o.market_key, at)
    if move_pp is not None:
        code = reassess(o, move_pp, at)
        if code == "PM_REVERTED" and o.status == "working":
            await _cancel_working(app, o, bridge, at, "PM_REVERTED")
            return
    if o.status == "working" and o.session_target == "pre_market" and session_at(at).equities_open:
        await _replace_at_open(app, o, bridge, at)
    if o.status == "approved" and at >= to_utc(o.execute_at):
        await _execute(app, o, bridge, at, ref_px)


async def on_tick(app, bridge, at: dt.datetime | None = None, move_pp: float | None = None,
                  ref_px: float | None = None) -> list[StagedOrder]:
    """P5's hook: step this bridge's proposal's pending orders of the bridge's clock on a tick, under the book lock.
    A replay bridge passes the tick's recorded time, its YES move since the close (pp) and its under_px."""
    book = book_for(app)
    clock = "replay" if is_replay(bridge) else "wall"
    changed = []
    async with book.lock:
        for o in book.pending():
            if o.proposal_id != getattr(bridge, "proposal_id", None) or o.clock != clock:
                continue
            if clock == "replay" and o.bridge_id != getattr(bridge, "id", None):
                continue
            before = (o.status, o.qty, len(o.decisions))
            await step(app, o, at, move_pp, ref_px)
            if (o.status, o.qty, len(o.decisions)) != before:
                changed.append(o)
    return changed


async def run_due(app) -> list[StagedOrder]:
    """Step every pending wall-clock order (replay orders move only on replayed ticks, through ``on_tick``); returns
    those whose status, quantity or log changed."""
    book = book_for(app)
    changed = []
    async with book.lock:
        for o in book.pending():
            if o.clock != "wall":
                continue
            before = (o.status, o.qty, len(o.decisions))
            await step(app, o)
            if (o.status, o.qty, len(o.decisions)) != before:
                changed.append(o)
    return changed


def _autorun(app) -> bool:
    v = getattr(app.state, "staged_autorun", None)
    if v is not None:
        return bool(v)
    return os.environ.get("POLYBRIDGE_STAGED_AUTORUN", "1").lower() not in ("0", "false", "no", "off")


def _runnable(book: StagedBook) -> bool:
    return any(o.status in ("approved", "working") and o.clock == "wall" for o in book.pending())


def ensure_runner(app) -> None:
    """Start the background runner (wall clock) while approved or working wall-clock orders exist."""
    book = book_for(app)
    if not _autorun(app) or not _runnable(book) or (book.runner is not None and not book.runner.done()):
        return
    poll = float(getattr(app.state, "staged_poll_s", None) or POLL_S)

    async def loop():
        while _runnable(book):
            try:
                await run_due(app)
            except Exception as e:  # one bad pass never kills the runner
                log.warning("staged runner pass failed: %s", type(e).__name__)
            await asyncio.sleep(poll)

    book.runner = asyncio.get_running_loop().create_task(loop())


# ------------------------------------------------------------------------------------------------------ routes


def _broker_info(app) -> dict:
    b = get_broker(app)
    return {"name": getattr(b, "name", None), "extended_hours": bool(getattr(b, "extended_hours", False))}


@router.get("/staged")
def list_staged(request: Request, bridge_id: str | None = None, proposal_id: str | None = None,
                status: StagedStatus | None = None) -> dict:
    app = request.app
    now = wall_now(app)
    sess = session_at(now)
    return {"orders": [o.model_dump() for o in book_for(app).list(bridge_id, proposal_id, status)],
            "broker": _broker_info(app), "session": {"phase": sess.phase, "label": sess.label,
                                                     "next_open": _iso(sess.next_open),
                                                     "next_extended_open": _iso(sess.next_extended_open)},
            "note": FIXED}


@router.post("/staged/plan", status_code=201)
async def post_plan(body: PlanIn, request: Request) -> dict:
    book = book_for(request.app)
    async with book.lock:
        o = plan_for(request.app, body, request.app.state.store, remote=getattr(request.state, "remote", False))
    return o.model_dump()


@router.post("/staged/run")
async def post_run(request: Request) -> dict:
    changed = await run_due(request.app)
    return {"changed": [o.model_dump() for o in changed]}


class ApproveIn(BaseModel):
    """What the user saw when they clicked: the plan's quantity. An unapproved plan resizes with the gap on every tick,
    so the approval names the quantity shown; a plan that changed since then is refused (409 PLAN_CHANGED) and the
    client re-renders it. Without a body the plan's current quantity is approved (legacy clients)."""
    qty: int | None = Field(default=None, ge=1)


@router.post("/staged/{sid}/approve")
async def approve_staged(sid: str, request: Request, body: ApproveIn | None = None) -> dict:
    app = request.app
    book = book_for(app)
    async with book.lock:
        try:
            o = book.get(sid)
        except KeyError:
            raise HTTPException(404, f"No staged order {sid}.")
        if o.status != "staged":
            raise HTTPException(409, f"Staged order {sid} is {o.status}; only a staged plan can be approved.")
        prop = next((p for p in app.state.store.list() if p.id == o.proposal_id), None)
        if prop is None or prop.status != "approved":
            raise HTTPException(409, f"Proposal {o.proposal_id} is no longer approved.")
        if body is not None and body.qty is not None and body.qty != o.qty:
            raise HTTPException(409, f"PLAN_CHANGED: staged order {sid} was resized to {o.qty} shares since it was "
                                     f"shown ({body.qty}); review the new quantity and approve again.")
        if o.clock == "replay":
            now = bridge_now(find_bridge(app, o.bridge_id)) or to_utc(o.planned_at)
        else:
            now = wall_now(app)
        o.status, o.approved_qty, o.approved_at = "approved", o.qty, _iso(now)
        _note(o, now, "APPROVED", f"qty {o.qty}; executes at {o.execute_at} ({o.session_target})"
                                  f"{' on replayed ticks' if o.clock == 'replay' else ''}")
        if o.clock == "wall":
            await step(app, o, now)  # executes at once when its session is already on
    ensure_runner(app)
    return o.model_dump()


@router.delete("/staged/{sid}")
async def delete_staged(sid: str, request: Request) -> dict:
    app = request.app
    book = book_for(app)
    async with book.lock:
        try:
            o = book.get(sid)
        except KeyError:
            raise HTTPException(404, f"No staged order {sid}.")
        if o.status not in PENDING:
            raise HTTPException(409, f"Staged order {sid} is {o.status}; nothing to cancel.")
        bridge = bridge_of(app, o)
        now = (bridge_now(bridge) if o.clock == "replay" else None) or wall_now(app)
        if o.status == "working":
            await _cancel_working(app, o, bridge, now, "USER_CANCELLED")
            if o.status == "working":
                raise HTTPException(502, f"Could not cancel the broker order for {sid}: {o.decisions[-1].detail}")
        else:
            o.status = "filled" if o.filled_qty > EPS else "cancelled"
            _note(o, now, "USER_CANCELLED")
    return o.model_dump()
