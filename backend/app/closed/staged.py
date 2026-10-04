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
from ..liquidity import gate as liquidity
from . import evidence as ev
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
PENDING = ("staged", "approved", "working")
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


def gap_rate_dict(r: "gapsvc.GapRate") -> dict:
    d = {k: getattr(r, k) for k in ("rate_bp_per_pp", "se", "n_closures", "n_nonzero", "label", "source",
                                   "resid_sd_bp", "se_eff", "sign", "ticker", "use")}
    return d


def choose(market_source: str | None, market_id: str | None, ticker: str, direction: str,
           token_id: str | None = None, rate_bp_per_pp: float | None = None, rate_se: float | None = None,
           n_closures: int | None = None) -> tuple["gapsvc.GapRate", int, list[str]]:
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
    qty: int
    approved_qty: int | None = None
    planned_qty: int
    direction: str
    market_key: str | None = None
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
    estimate: dict
    current: dict | None = None
    sizing: dict
    planned_at: str
    approved_at: str | None = None
    executed_at: str | None = None
    client_order_id: str
    broker_order: dict | None = None
    filled_qty: float = 0.0
    prior_filled: float = 0.0
    replacements: int = 0
    holds: int = 0
    fill_px: float | None = None
    ref_source: str | None = None
    limit_anchor: str | None = None
    reason: str | None = None
    evidence_gate: Literal["validated", "override"] | None = None
    evidence: dict | None = None
    liquidity: dict | None = None
    capital: dict | None = None
    decisions: list[Decision] = []
    label: str = "Staged session hedge: executes only after approval, at the next tradable session."


class PlanIn(BaseModel):
    bridge_id: str | None = Field(default=None, max_length=64)
    proposal_id: str | None = Field(default=None, max_length=64)
    pm_move_pp: float | None = Field(default=None, ge=-100, le=100, allow_inf_nan=False)
    rate_bp_per_pp: float | None = Field(default=None, allow_inf_nan=False)
    rate_se: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    n_closures: int | None = Field(default=None, ge=0)
    ref_px: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    pm_leg_equiv_shares: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    full_size_gap_bp: float = Field(default=DEFAULT_FULL_SIZE_GAP_BP, gt=0, le=10_000, allow_inf_nan=False)
    min_gap_bp: float = Field(default=DEFAULT_MIN_GAP_BP, ge=0, le=10_000, allow_inf_nan=False)
    collar_bps: float = Field(default=DEFAULT_COLLAR_BPS, gt=0, le=1_000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _one(self) -> "PlanIn":
        if not (self.bridge_id or self.proposal_id):
            raise ValueError("Send bridge_id or proposal_id.")
        return self


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
    return (getattr(app.state, "bridges", None) or {}).get(proposal_id)


def is_replay(bridge) -> bool:
    return bridge is not None and getattr(bridge, "effective_source", None) == "replay"


def sandboxed(bridge) -> bool:
    if not is_replay(bridge):
        return False
    return bool(bridge._sandboxed()) if hasattr(bridge, "_sandboxed") else True


def bridge_now(bridge) -> dt.datetime | None:
    if is_replay(bridge):
        ts = getattr(bridge, "last_replay_ts_ns", None)
        return to_utc(ts) if ts else None
    return None


def wall_now(app) -> dt.datetime:
    clock = getattr(app.state, "staged_clock", None)
    return to_utc(clock()) if clock else now_utc()


def bridge_of(app, o: "StagedOrder"):
    orig = find_bridge(app, o.bridge_id)
    if o.clock == "replay":
        return orig
    cur = bridge_for_proposal(app, o.proposal_id)
    if cur is not None:
        return cur
    return None if is_replay(orig) else orig


def order_broker(app, bridge, clock: str = "wall") -> Broker | None:
    if clock == "replay":
        b = bridge.order_broker() if bridge is not None and hasattr(bridge, "order_broker") else None
        if b is None and not sandboxed(bridge):
            return get_broker(app)
        return b
    if bridge is not None and not is_replay(bridge) and hasattr(bridge, "order_broker"):
        b = bridge.order_broker()
        if b is not None:
            return b
    return get_broker(app)


def _summary_field(bridge, *names: str) -> Any:
    try:
        s = bridge.summary()
    except Exception:
        return None
    for n in names:
        if s.get(n) is not None:
            return s[n]
    return None


def pm_leg_shares(bridge) -> float | None:
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
    if not mkey:
        return None, NO_PM_DATA
    st = tracker_for(app).state(mkey, at)
    return st.move_pp, st.status


def _ref_px(bridge) -> float | None:
    for name in ("last_under_px", "under_px", "last_price"):
        if (x := _fin(getattr(bridge, name, None))) and x > 0:
            return x
    return None


class StagedBook:

    def __init__(self) -> None:
        self._items: dict[str, StagedOrder] = {}
        self.lock = asyncio.Lock()
        self.runner: asyncio.Task | None = None
        self.brokers: dict[str, Broker] = {}

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
    if o.reason != code:
        _note(o, at, code, detail)


def reserved_sell_qty(app, proposal_id: str, clock: str = "wall", exclude: str | None = None) -> float:
    return sum(max(0.0, o.qty - o.filled_qty) for o in book_for(app).pending()
               if o.proposal_id == proposal_id and o.status == "working" and o.side == "sell" and o.clock == clock
               and o.id != exclude)


def _resting_sell(bridge) -> float:
    r = getattr(bridge, "resting", None) if bridge is not None else None
    if not isinstance(r, dict) or r.get("side") != "sell" or (r.get("instrument") or "equity") != "equity":
        return 0.0
    return max(0.0, (_fin(r.get("qty")) or 0.0) - (_fin(r.get("hedged", r.get("applied"))) or 0.0))


def coverage(app, proposal_id: str, shares_held: float, target_coverage: float, bridge, clock: str,
             pm_leg: float, exclude: str | None = None) -> dict:
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


def _liq_scope(clock: str, bridge) -> str:
    return f"sandbox:{getattr(bridge, 'id', None)}" if clock == "replay" and sandboxed(bridge) else "account"


def _liq_day(app, clock: str, bridge, day: dt.date | dt.datetime) -> str:
    if clock == "replay" and not sandboxed(bridge):
        return wall_now(app).astimezone(ET).date().isoformat()
    if isinstance(day, dt.datetime):
        return day.astimezone(ET).date().isoformat()
    return day.isoformat()


def plan_for(app, body: PlanIn, store, remote: bool = False) -> StagedOrder:
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
    if bridge is None:
        cur = bridge_for_proposal(app, prop.id)
        bridge = None if is_replay(cur) else cur
    clock = "replay" if is_replay(bridge) else "wall"
    if clock == "replay":
        now = bridge_now(bridge)
        if now is None:
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
    msrc, mid = getattr(market, "source", None), getattr(market, "id", None)
    evid = ev.market_evidence(msrc, mid, getattr(market, "token_id", None)) if msrc and mid else \
        {"validated": False, "status": ev.UNVALIDATED, "evidence": ev.NO_MARKET_EVIDENCE, "token_id": None}
    rate, sign, gcodes = choose(msrc, mid, prop.ticker, direction,
                                getattr(market, "token_id", None) or evid.get("token_id"), body.rate_bp_per_pp,
                                body.rate_se, body.n_closures)
    est = gap_estimate(move, rate, sign, prop.ticker, gcodes)
    validated, ev_status, ev_why = ev.gate(evid, est["rate_source"], prop.ticker, est["basis_ticker"], est["reasons"])
    prop_flag = bool(getattr(prop, "act_on_unvalidated", False))
    prop_override = prop_flag and bool(getattr(prop, "ack_unvalidated", False))
    override = prop_override or bool(getattr(bridge, "act_on_unvalidated", False))
    if not validated and not override:
        unconfirmed = (f" Proposal {prop.id} sets act_on_unvalidated but was approved without ack_unvalidated, so the "
                       "override is not confirmed: propose again and approve with ack_unvalidated: true."
                       if prop_flag else
                       " To stage anyway, propose with act_on_unvalidated: true and approve with ack_unvalidated: "
                       "true (an explicit override the approval confirms; every plan and order is labelled "
                       "'override').")
        raise HTTPException(409, f"EVIDENCE_GATE: no staged plan for {prop.ticker} on "
                                 f"{msrc}:{mid}: {ev_why} A market's signal acts only where it passed its "
                                 f"out-of-sample test.{unconfirmed}")
    gate_label = "validated" if validated else "override"

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
    liq = None
    if qty > 0:
        liq = liquidity.equity_check(app, prop.ticker, float(qty), scope=_liq_scope(clock, bridge),
                                     day=_liq_day(app, clock, bridge, session_date))
        if liq["status"] == "capped":
            size_codes.append("LIQUIDITY_CAPPED")
            qty = int(liq["allowed"])
        sizing["liquidity"] = {k: v for k, v in liq.items() if k != "allowed"}
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
        estimate={**est, "pm_status": status, "validated": validated, "status": ev_status, "evidence": ev_why},
        sizing=sizing, planned_at=_iso(now), client_order_id=f"stg-{sid}", evidence_gate=gate_label,
        evidence={"validated": validated, "status": ev_status, "evidence": ev_why, "label": gate_label,
                  "override": gate_label == "override"},
        liquidity=sizing.get("liquidity"))
    for c in sched_codes:
        _note(o, now, c, f"execute at {_iso(execute_at)} ({target}); broker {o.broker} "
                         f"extended_hours={extended}")
    _note(o, now, "EXPECTED_GAP",
          f"PM move {move:+.2f} pp -> gap {est['gap_bp']:.1f} bp, {est['band_level']:.0%} band "
          f"[{est['band_bp'][0]:.1f}, {est['band_bp'][1]:.1f}] bp, {est['rate_source']} rate "
          f"{est['rate_bp_per_pp']:.2f} bp/pp on n={est['n_closures']} closures ({', '.join(est['reasons'])})")
    _note(o, now, "EVIDENCE_" + gate_label.upper(), ev_why if gate_label == "validated" else
          f"OVERRIDE (act_on_unvalidated): {ev_why}")
    for c in size_codes:
        if c == "LIQUIDITY_CAPPED":
            _note(o, now, c, f"qty {liq['capped_from']:g} -> {qty}: {liq['rule']} (limit {liq['limit_qty']:g} sh)")
            continue
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
        o.status = "filled" if o.filled_qty > EPS else "cancelled"
        if o.filled_qty > EPS:
            o.qty = math.ceil(o.filled_qty - EPS)
        _note(o, at, "PM_REVERTED", detail + f"; {codes[0]}")
        return "PM_REVERTED"
    if o.status == "working":
        return None
    qty = max(qty, math.ceil(o.filled_qty - EPS))
    ceiling = o.approved_qty if o.approved_qty is not None else (None if o.status == "staged" else o.planned_qty)
    if qty < o.qty:
        _note(o, at, "PM_PARTIAL_REVERT_RESIZE", detail + f"; qty {o.qty} -> {qty}")
        o.qty = qty
        return "PM_PARTIAL_REVERT_RESIZE"
    if qty > o.qty:
        new = qty if ceiling is None else min(qty, ceiling)
        if new > o.qty:
            _note(o, at, "PM_RESIZE_UP", detail + f"; qty {o.qty} -> {new} "
                                                  f"({'not yet approved' if ceiling is None else f'ceiling {ceiling}'})")
            o.qty = new
            return "PM_RESIZE_UP"
        if o.reason != "RESIZE_UP_NEEDS_APPROVAL":
            _note(o, at, "RESIZE_UP_NEEDS_APPROVAL", detail + f"; wants {qty}, approved {ceiling}")
            return "RESIZE_UP_NEEDS_APPROVAL"
    return None


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
    return not isinstance(broker, SimBroker)


def _apply_fill(o: StagedOrder, bridge, filled_this_order: float, at_account: bool) -> None:
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
    if not (at_account and sandboxed(bridge)):
        bridge.broker_hedge = getattr(bridge, "broker_hedge", 0.0) + signed
        if getattr(bridge, "algo", None):
            bridge.hedge = bridge.broker_hedge
        hook = getattr(bridge, "on_staged_fill", None)
        if callable(hook):
            px = _fin((o.broker_order or {}).get("fill_px")) or o.fill_px
            try:
                hook(signed, px)
            except Exception as e:
                log.warning("staged fill hook failed: %s", type(e).__name__)


def _at_account(o: StagedOrder, bridge) -> bool:
    return o.clock == "wall" or not sandboxed(bridge)


def _hold_for_next_session(app, o: StagedOrder, order, at: dt.datetime) -> None:
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
    elif o.filled_qty > EPS:
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
    return book_for(app).brokers.get(o.id) or order_broker(app, bridge, o.clock)


def _capital_scope(o: StagedOrder, bridge) -> str:
    return "replay_sandbox" if o.clock == "replay" and sandboxed(bridge) else "account"


async def capital_check(app, o: StagedOrder, bridge, broker, qty: float, px: float | None) -> dict:
    from ..capital import service as cap
    scope = _capital_scope(o, bridge)
    try:
        px, src = await cap.order_price(app, broker, o.ticker, px, o.ref_px)
        sandbox_gross = (max(0.0, float(getattr(bridge, "broker_hedge", 0.0) or 0.0)) * px
                         if scope != "account" and px else 0.0)
        from ..capital.budget import REG_T_INITIAL
        chk = await cap.check(app, broker=broker, event=o.market_key, add_notional=qty * px if px else None,
                              add_margin=REG_T_INITIAL * qty * px if px else None, scope=scope,
                              sandbox_gross=sandbox_gross, exclude_staged=o.id)
        if px and src not in (None, "order"):
            chk = {**chk, "note": "; ".join(x for x in (chk.get("note"), f"priced from {src}") if x)}
        return chk
    except Exception as e:
        return {"ok": scope != "account", "enforced": scope == "account", "checked": False,
                "breaches": [{"kind": "check_failed", "detail": f"capital check failed ({type(e).__name__})"}]}


async def _capital_ok(app, o: StagedOrder, bridge, broker, qty: float, px: float | None, at: dt.datetime) -> bool:
    from ..capital import service as cap
    chk = await capital_check(app, o, bridge, broker, qty, px)
    o.capital = {k: chk.get(k) for k in ("ok", "enforced", "checked", "scope", "breaches", "note", "reason")}
    if cap.refused(chk):
        o.status = "filled" if o.filled_qty > EPS else "rejected"
        _note(o, at, "CAPITAL_BUDGET", cap.refusal_text(chk))
        return False
    if not chk.get("ok", True):
        _note_once(o, at, "CAPITAL_BUDGET_ADVISORY", cap.refusal_text(chk) + " (replay sandbox: not enforced)")
    return True


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
        return
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
    scope, day = _liq_scope(o.clock, bridge), _liq_day(app, o.clock, bridge, at)
    liq = liquidity.equity_check(app, o.ticker, float(remaining), scope=scope, day=day)
    o.liquidity = {k: v for k, v in liq.items() if k != "allowed"}
    if liq["status"] == "capped":
        allowed = int(liq["allowed"])
        detail = f"qty {remaining} -> {allowed}: {liq['rule']} (limit {liq['limit_qty']:g} sh)"
        if allowed <= 0:
            o.status = "filled" if o.filled_qty > EPS else "cancelled"
            _note(o, at, "LIQUIDITY_CAPPED", detail + "; nothing left to send today")
            return
        _note(o, at, "LIQUIDITY_CAPPED", detail)
        remaining = allowed
        o.qty = math.ceil(o.filled_qty - EPS) + remaining

    from ..bridges import REPLAY_NOTE, REPLAY_RECORDED_NOTE

    note = f"staged session hedge (plan {o.id}; evidence: {o.evidence_gate or 'unlabelled'})"
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
    if o.side == "sell" and not await _capital_ok(app, o, bridge, broker, remaining, ref, at):
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
        anchor, anchor_src = (min if o.side == "sell" else max)(cands, key=lambda c: c[0])
        f = (1 - o.collar_bps / 1e4) if o.side == "sell" else (1 + o.collar_bps / 1e4)
        limit = round(anchor * f, 2)
    if o.replacements or o.holds:
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
    liquidity.record_equity(app, o.ticker, float(remaining), scope=scope, day=day)
    try:
        order = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
        o.status = "working"
        o.broker_order = None
        _note(o, at, "BROKER_UNCONFIRMED", f"{type(e).__name__}; reconciled by client_order_id next run")
        return
    _take_order(app, o, order, bridge, at)


async def _reconcile(app, o: StagedOrder, bridge, at: dt.datetime) -> None:
    from ..bridges import _lookup

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
        if o.broker_order is None:
            o.status = "approved"
            book_for(app).brokers.pop(o.id, None)
            _note(o, at, "BROKER_NEVER_TOOK_IT", "will be sent again while the session is on")
        return
    if (found.status == "open" and o.status == "working" and o.broker_order
            and o.prior_filled + float(found.filled_qty or 0) == o.filled_qty):
        return
    _take_order(app, o, found, bridge, at)


async def _cancel_at_broker(app, o: StagedOrder, bridge, at: dt.datetime) -> bool:
    broker = _broker_of(app, o, bridge)
    if broker is None:
        return False
    oid = (o.broker_order or {}).get("id") or o.client_order_id
    try:
        order = await asyncio.wait_for(broker.cancel(oid), BROKER_TIMEOUT_S)
    except Exception as e:
        await _reconcile(app, o, bridge, at)
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
    book = book_for(app)
    if not _autorun(app) or not _runnable(book) or (book.runner is not None and not book.runner.done()):
        return
    poll = float(getattr(app.state, "staged_poll_s", None) or POLL_S)

    async def loop():
        while _runnable(book):
            try:
                await run_due(app)
            except Exception as e:
                log.warning("staged runner pass failed: %s", type(e).__name__)
            await asyncio.sleep(poll)

    book.runner = asyncio.get_running_loop().create_task(loop())


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
        if o.side == "sell" and o.clock == "wall":
            from ..capital import service as cap
            br = bridge_of(app, o)
            chk = await capital_check(app, o, br, order_broker(app, br, o.clock), float(o.qty), None)
            o.capital = {k: chk.get(k) for k in ("ok", "enforced", "checked", "scope", "breaches", "note", "reason")}
            if cap.refused(chk):
                _note(o, now, "CAPITAL_BUDGET", cap.refusal_text(chk))
                raise HTTPException(409, f"CAPITAL_BUDGET: staged order {sid} would breach the account risk budget: "
                                         f"{cap.refusal_text(chk)}")
        o.status, o.approved_qty, o.approved_at = "approved", o.qty, _iso(now)
        _note(o, now, "APPROVED", f"qty {o.qty}; executes at {o.execute_at} ({o.session_target})"
                                  f"{' on replayed ticks' if o.clock == 'replay' else ''}")
        if o.clock == "wall":
            await step(app, o, now)
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
