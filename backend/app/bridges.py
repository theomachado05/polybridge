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
from .capital import budget as capital_budget
from .capital import service as capital
from .closed import bridge_mode
from .closed import evidence as evidence_gate
from .closed import staged as staged_book
from .liquidity import gate as liquidity
from .models import AlgoChoice, MarketRef, Proposal
from .pipeline.engine_adapter import (AlgoChoiceError, cap_contracts, cap_coverage, is_option_family,
                                      normalize_manifest, resolve_algo)
from .pipeline.ticks import orient_for_family, orient_to_adverse, recorded_bars
from .store import NotFound, ProposalStore
from .ticks import TICK_FIELDS, LiveSource, OptionsEnricher, ReplaySource, SourceError, Tick, as_tick
from .twins import twin_of

router = APIRouter()
LABELLED_EVENTS = ("decision", "fill", "staged", "hedge_a")
HEARTBEAT_S = 15.0
MAX_EVENTS = 20_000
REPLAYS_DIR = Path(__file__).resolve().parents[1] / "replays"
NO_ENGINE = "engine not installed (uv sync --group engine)"
BROKER_TIMEOUT_S = 30.0
MAX_FILLS = 500
REPLAY_NOTE = "replay: priced at the current market, not the replayed time"
REPLAY_BROKER_NAME = "sim-replay"


def _load_engine():
    try:
        import hedgecore
    except ImportError:
        return None
    return hedgecore


class BridgeIn(BaseModel):
    proposal_id: str
    source: Literal["live", "replay"]
    market: MarketRef | None = None
    gap_per_share: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    direction: Literal["down_on_yes", "up_on_yes"] = "down_on_yes"
    replay_to_account: bool = False
    family: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    preset_index: int | None = Field(default=None, ge=0)
    params: dict[str, float] | None = None
    twin: MarketRef | None = None
    replay_file: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.-]+$")
    session_hold: bool = True
    act_on_unvalidated: bool = False


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
        self.broker: Broker | None = None
        self.replay_to_account = replay_to_account
        self.replay_broker: Broker | None = None
        self.broker_name: str | None = None
        self.broker_hedge = 0.0
        self.account_hedge = 0.0
        self.fills: list[dict] = []
        self.broker_filled = self.broker_rejects = self.broker_errors = 0
        self.algo = algo
        self.twin: dict | None = None
        self.choice: AlgoChoice | None = None
        self.resting: dict | None = None
        self.resting_broker: Broker | None = None
        self.cancels = 0
        self.cap_holds = 0
        self.equity_source: str | None = None
        self.equity_price = "live_quote"
        self.quote_check: tuple[float, bool] | None = None
        self.recorded_fills = 0
        self.division = proposal.family
        self.options: OptionsEnricher | None = None
        self.opt_pos = 0.0
        self.opt_open: dict | None = None
        self.opt_risk_per_unit = 0.0
        self.opt_last: dict | None = None
        self.option_data = "none"
        self.replay_file: str | None = None
        self.replay_market: dict | None = None
        self.recorded_options: dict | None = None
        self.last_legs: dict[str, float] | None = None
        self.last_legs_ts_ns: int | None = None
        self.last_legs_settled = False
        self.last_replay_ts_ns: int | None = None
        self.recorded_option_fills = 0
        self.app: Any = None
        self.session_hold = True
        self.closed: bridge_mode.ClosedMode | None = None
        self.closed_errors = 0
        self.engine: Any = None
        self.last_under_px: float | None = None
        self.broker_note: str | None = None
        self.evidence: dict | None = None
        self.evidence_label: str | None = None
        self.act_on_unvalidated = False
        self.liquidity_capped = 0
        self.capital_refused = 0

    def on_staged_fill(self, signed_short: float, px: float | None) -> None:
        eng = self.engine
        if eng is not None and px:
            if self.algo and self.division == "hedge":
                eng.on_fill("equity", -float(signed_short), float(px))
            elif not self.algo and hasattr(eng, "on_fill"):
                eng.on_fill(float(signed_short))
                self.hedge = getattr(eng, "current_hedge", self.hedge)
        if self.closed is not None:
            self.closed.on_staged_fill(signed_short, px)

    async def emit(self, kind: str, data: dict, status: str | None = None) -> None:
        if self.evidence_label and kind in LABELLED_EVENTS and isinstance(data, dict):
            data.setdefault("evidence", self.evidence_label)
        async with self.cond:
            if status:
                self.status = status
            if len(self.events) >= MAX_EVENTS:
                del self.events[: MAX_EVENTS // 2]
                self.dropped += MAX_EVENTS // 2
            self.events.append((kind, data))
            self.cond.notify_all()

    def _sandboxed(self) -> bool:
        return self.effective_source == "replay" and not self.replay_to_account

    def order_broker(self) -> Broker | None:
        if self.broker is None or not self._sandboxed():
            return self.broker
        if self.replay_broker is None:
            sim = self.broker if isinstance(self.broker, SimBroker) else getattr(self.broker, "sim", None)
            start = getattr(sim, "starting_cash", None) or 1_000_000.0
            self.replay_broker = SimBroker(None, getattr(sim, "quotes", None), start)
            self.replay_broker.name = REPLAY_BROKER_NAME
        return self.replay_broker

    def set_replay(self, path: Path) -> None:
        self.replay_file, self.replay_market = path.name, replay_meta(path)
        self.recorded_options = replay_option_structure(path) if self.replay_market is not None else None

    def options_brief(self) -> dict | None:
        live = _options_brief(self.options)
        rec = self.recorded_options
        if rec is None or self.effective_source != "replay" or (self.options is not None and self.options.context()):
            return live
        return {"supported": True, "available": True, "source": "recording", "underlying_used": rec["underlying"],
                "strike_used": rec.get("strike"), "expiry": rec["expiry"], "k_lo": rec["k_lo"], "k_hi": rec["k_hi"],
                "direction": rec["direction"], "method": rec["kind"],
                "live_reason": (live or {}).get("reason"),
                "notes": ["the structure and its prices come from the recording (leg bar closes at the replayed "
                          "time); no current chain lists these contracts"]}

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
                "account_hedge": self.account_hedge,
                "coverage_cap": self.proposal.target_coverage if self.algo and self.division == "hedge" else None,
                "cap_holds": self.cap_holds,
                "equity_price": self.equity_price if self.algo and self.division == "hedge" else None,
                "equity_source": self.equity_source,
                "recorded_price_fills": self.recorded_fills,
                "account_note": self._account_note(),
                "broker_note": self.broker_note,
                "broker_coverage": self.broker_hedge / self.proposal.shares_held if self.proposal.shares_held else 0.0,
                "broker_filled": self.broker_filled,
                "broker_rejects": self.broker_rejects, "broker_errors": self.broker_errors,
                "last_fill": self.fills[-1] if self.fills else None,
                "shares_held": self.proposal.shares_held, "target_coverage": self.proposal.target_coverage,
                "coverage": self.hedge / self.proposal.shares_held if self.proposal.shares_held else 0.0,
                "basis": self.proposal.basis, "label": self.proposal.label,
                "market": self.market.model_dump(), "twin": self.twin,
                "replay_file": self.replay_file, "replay_market": self.replay_market,
                "latency_ns": {"p50": q(0.5), "p99": q(0.99)},
                "division": self.division,
                "evidence": dict(self.evidence) if self.evidence else None, "evidence_label": self.evidence_label,
                "act_on_unvalidated": self.act_on_unvalidated,
                "liquidity_capped": self.liquidity_capped, "capital_refused": self.capital_refused,
                **(self._opp_summary() if self.division == "opportunity" else {}),
                **self._closed_summary()}

    def _closed_summary(self) -> dict:
        if self.closed is None:
            return {"session": None, "closure": None, "expected_gap": None, "closed_mode": None, "hedge_a": None}
        try:
            return self.closed.summary()
        except Exception as e:
            return {"session": None, "closure": None, "expected_gap": None,
                    "closed_mode": {"error": type(e).__name__}, "hedge_a": None}

    def _account_note(self) -> str | None:
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
                "options_detail": self.options_brief(),
                "fills_label": OPTION_FILLS_LABEL_BROKER if not self._sandboxed() and _options_at_broker(self.broker) else
                OPTION_FILLS_LABEL,
                "recorded_option_fills": self.recorded_option_fills}


def _replay_speed(app, path: Path | None = None) -> float:
    v = getattr(app.state, "replay_speed", None)
    if v is not None:
        return v
    if path is not None and (own := _sidecar_speed(app, path)) is not None:
        return own
    try:
        return float(os.environ.get("POLYBRIDGE_REPLAY_SPEED", "1"))
    except ValueError:
        return 1.0


def _sidecar_speed(app, path: Path) -> float | None:
    configured = getattr(app.state, "replay_path", None) or os.environ.get("POLYBRIDGE_REPLAY_PATH")
    try:
        if configured and Path(configured).resolve() == path.resolve():
            return None
        v = float(json.loads(path.with_name(path.name + ".meta.json").read_text()).get("replay_speed"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def replay_meta(path: Path) -> dict | None:
    try:
        raw = json.loads(path.with_name(path.name + ".meta.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not raw.get("source") or not (raw.get("id") or raw.get("token_id")):
        return None
    return {"source": str(raw["source"]), "id": str(raw["id"]) if raw.get("id") else None,
            "token_id": str(raw["token_id"]) if raw.get("token_id") else None}


def replay_option_structure(path: Path) -> dict | None:
    try:
        o = json.loads(path.with_name(path.name + ".meta.json").read_text()).get("options")
        legs = [{"sign": 1 if int(lg["sign"]) > 0 else -1, "ticker": str(lg["ticker"]), "strike": float(lg["strike"]),
                 "kind": str(lg["kind"])} for lg in o["legs"]]
        out = {"underlying": str(o["underlying"]), "strike": float(o.get("strike") or "nan"),
               "direction": "below" if o.get("direction") == "below" else "above", "kind": str(o["kind"]),
               "expiry": str(o["expiry"])[:10], "k_lo": float(o["k_lo"]), "k_hi": float(o["k_hi"]), "legs": legs}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    if not legs or any(lg["kind"] not in ("call", "put") for lg in legs) or not out["k_lo"] < out["k_hi"]:
        return None
    st = o.get("settlement")
    if isinstance(st, dict) and isinstance(st.get("underlying_close"), (int, float)):
        out["settlement"] = {k: st[k] for k in ("underlying_close", "source", "rule") if k in st}
    return out


def _meta_matches(meta: dict, market: MarketRef) -> bool:
    if meta["source"] != market.source:
        return False
    keys = {k for k in (market.id, market.token_id) if k}
    return bool(({meta.get("id"), meta.get("token_id")} - {None}) & keys)


def _names_file(path: Path, market: MarketRef, replay_file: str | None) -> bool:
    if replay_file and replay_file in (path.name, path.stem):
        return True
    stems = {k for k in (market.id, market.token_id) if k}
    return path.stem in stems | {f"{k}-history" for k in stems}


def _check_replay_market(path: Path, market: MarketRef | None, replay_file: str | None) -> None:
    if market is None:
        return
    meta = replay_meta(path)
    label = f"{market.source}:{market.id}"
    if meta is not None:
        if not _meta_matches(meta, market):
            raise HTTPException(422, f"The configured replay file {path.name} records {meta['source']}:"
                                     f"{meta.get('id') or meta.get('token_id')}, not the requested market {label} "
                                     "(see its .meta.json sidecar). Point POLYBRIDGE_REPLAY_PATH at a recording of "
                                     "this market.")
        return
    if not _names_file(path, market, replay_file):
        raise HTTPException(422, f"The configured replay file {path.name} has no {path.name}.meta.json sidecar, so its "
                                 f"market is unknown; it is replayed for {label} only when the request names it "
                                 "(replay_file) or a sidecar says it records this market.")


def _own_recordings(market: MarketRef) -> list[Path]:
    from .pipeline.ticks import DATA, _replay_candidates
    try:
        return _replay_candidates(market.source, market.id, market.token_id, DATA, REPLAYS_DIR)
    except Exception:
        return []


def _first_recording(candidates: list[Path], market: MarketRef) -> Path | None:
    for c in candidates:
        if c.is_file() and ((meta := replay_meta(c)) is None or _meta_matches(meta, market)):
            return c
    return None


def _replay_path(request: Request, *markets: MarketRef | None, replay_file: str | None = None) -> Path | None:
    configured = getattr(request.app.state, "replay_path", None) or os.environ.get("POLYBRIDGE_REPLAY_PATH")
    target = next((m for m in markets if m is not None), None)
    mismatch: HTTPException | None = None
    if configured:
        path = Path(configured)
        if target is None:
            return path
        if path.is_file():
            try:
                _check_replay_market(path, target, replay_file)
                return path
            except HTTPException as e:
                mismatch = e
    for market in markets:
        if market is None:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", market.id):
            if configured:
                continue
            raise HTTPException(422, "market.id must match [A-Za-z0-9_-]+ to select a replay file.")
        if (own := _first_recording(_own_recordings(market), target)) is not None:
            return own
    if mismatch is not None:
        raise mismatch
    return Path(configured) if configured else None


def _resolve(prop: Proposal, body: BridgeIn) -> tuple[MarketRef, str]:
    if prop.market is not None and (prop.direction is not None or prop.family == "opportunity"):
        token = prop.market.token_id
        if token is None and body.market is not None and body.market.id == prop.market.id:
            token = body.market.token_id
        return prop.market.model_copy(update={"token_id": token}), prop.direction or "down_on_yes"
    if body.market is None:
        raise HTTPException(422, "market is required for a filing-tags proposal.")
    return body.market, body.direction


def _fallback_path(app, market: MarketRef | None = None) -> Path | None:
    configured = getattr(app.state, "replay_path", None) or os.environ.get("POLYBRIDGE_REPLAY_PATH")
    if market is None:
        return None
    cands = _own_recordings(market)
    if configured:
        conf = Path(configured)
        meta = replay_meta(conf)
        names = {c.name for c in cands}
        if meta is not None:
            if _meta_matches(meta, market):
                return conf
        elif conf.name in names or conf.stem in (market.id, market.token_id):
            return conf
    return _first_recording(cands, market)


async def _send_to_broker(bridge: Bridge, order_qty: float) -> dict | None:
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
    gated = await _equity_gates(bridge, broker, rec, side, qty)
    if gated is None:
        return rec
    qty = gated
    bridge.broker_name = broker.name
    note = None
    if bridge.effective_source == "replay":
        note = REPLAY_NOTE
        rec["price_note"] = "priced at the current market, not the replayed time"
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
    req = OrderRequest(symbol=bridge.proposal.ticker, asset="equity", side=side, qty=qty, type="market",
                       client_order_id=f"{bridge.id}-{bridge.orders}", tag=bridge.id, note=note)
    _record_participation(bridge, qty)
    try:
        o = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
        _track_unconfirmed(bridge, broker, req, "equity")
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0, order_id=req.client_order_id,
                   kept_resting=True)
        return rec
    rec.update(status=o.status, order_id=o.id, fill_px=o.fill_px, fee=o.fee, price_source=o.price_source,
               reject_reason=o.reject_reason, note=o.note, broker=o.broker, filled_qty=o.filled_qty)
    await _apply_order_state(bridge, None, o, side, "equity", broker=broker)
    return rec


def _liq_scope(bridge: Bridge) -> str:
    return f"sandbox:{bridge.id}" if bridge._sandboxed() else "account"


def _liq_day(bridge: Bridge, t: Tick | None = None) -> str:
    rts = getattr(t, "recorded_ts_ns", None) if t is not None and bridge._sandboxed() else None
    if rts is None and bridge._sandboxed():
        rts = bridge.last_replay_ts_ns
    try:
        if rts is not None:
            return liquidity.session_day(dt.datetime.fromtimestamp(int(rts) / 1e9, dt.UTC))
        return liquidity.session_day(bridge_mode.live_now(bridge.app) if bridge.app is not None else None)
    except (ValueError, OverflowError, OSError):
        return liquidity.session_day()


def _equity_liquidity(bridge: Bridge, rec: dict, qty: float, t: Tick | None = None) -> float:
    if bridge.app is None:
        return qty
    chk = liquidity.equity_check(bridge.app, bridge.proposal.ticker, qty, scope=_liq_scope(bridge),
                                 day=_liq_day(bridge, t))
    liquidity.tag(rec, chk)
    if chk["status"] == "capped":
        bridge.liquidity_capped += 1
        bridge.reasons[liquidity.LIQUIDITY_CAPPED] += 1
        rec.setdefault("capped_from", qty)
        rec["qty"] = chk["allowed"]
        return float(chk["allowed"])
    return qty


def _record_participation(bridge: Bridge, qty: float, t: Tick | None = None) -> None:
    if bridge.app is not None:
        liquidity.record_equity(bridge.app, bridge.proposal.ticker, qty, scope=_liq_scope(bridge),
                                day=_liq_day(bridge, t))


async def _capital_refuses(bridge: Bridge, broker: Broker, rec: dict, add_notional: float | None,
                           add_margin: float | None = None) -> bool:
    if bridge.app is None:
        return False
    sandbox = bridge._sandboxed()
    px = bridge.last_under_px
    sandbox_gross = max(0.0, bridge.broker_hedge) * px if (sandbox and px) else 0.0
    if sandbox and bridge.division == "opportunity":
        sandbox_gross = abs(bridge.opt_pos) * bridge.opt_risk_per_unit
    margin = add_margin if add_margin is not None or add_notional is None else \
        capital_budget.REG_T_INITIAL * add_notional
    try:
        chk = await capital.check(bridge.app, broker=broker, event=capital.event_key(bridge.market),
                                  add_notional=add_notional, add_margin=margin,
                                  scope="replay_sandbox" if sandbox else "account", sandbox_gross=sandbox_gross)
    except Exception as e:
        chk = {"ok": sandbox, "enforced": not sandbox, "checked": False, "scope": "account",
               "breaches": [{"kind": "check_failed", "detail": f"capital check failed ({type(e).__name__})"}]}
    capital.tag(rec, chk)
    if capital.refused(chk):
        bridge.capital_refused += 1
        bridge.reasons[capital_budget.CAPITAL_BUDGET] += 1
        rec.update(status="held", reject_reason=capital.refusal_text(chk), filled_qty=0.0)
        return True
    return False


def _equity_px(bridge: Bridge, t: Tick | None = None) -> float | None:
    px = _positive(t.fields.get("under_px")) if t is not None else None
    if px is None:
        px = _positive(bridge.last_under_px)
    if px is None and bridge.app is not None:
        from .liquidity.service import service_for
        raw, _ = service_for(bridge.app).cached_equity(bridge.proposal.ticker)
        px = _positive((raw or {}).get("price"))
    return px


async def _equity_gates(bridge: Bridge, broker: Broker, rec: dict, side: str, qty: float,
                        t: Tick | None = None) -> float | None:
    qty = _equity_liquidity(bridge, rec, qty, t)
    if qty <= 1e-9:
        rec.update(status="held", filled_qty=0.0,
                   reject_reason=f"liquidity_capped: {rec['liquidity'].get('rule')} (limit "
                                 f"{rec['liquidity'].get('limit_qty'):g} shares left)")
        return None
    if side == "sell":
        px = _equity_px(bridge, t)
        if px is None and bridge.app is not None:
            px, src = await capital.order_price(bridge.app, broker, bridge.proposal.ticker)
            if px is not None:
                rec["capital_price_source"] = src
        if await _capital_refuses(bridge, broker, rec, qty * px if px else None):
            return None
    return qty


def _track_unconfirmed(bridge: Bridge, broker: Broker, req: OrderRequest, instrument: str) -> None:
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
    f = t.fields
    return {"ts_ns": t.ts_ns, "p": t.p, "venue": "kalshi" if t.venue == 1 else "poly",
            "yes_bid": _fin(f.get("yes_bid")), "yes_ask": _fin(f.get("yes_ask")),
            "p_other_venue": _fin(f.get("p_other_venue")), "under_px": _fin(f.get("under_px")),
            "depth": sum(1 for i in range(5) if _fin(f.get(f"bid_px_{i}")) is not None)}


def adverse_p(oriented: dict, t: Tick, direction: str) -> float:
    b, a = _fin(oriented.get("yes_bid")), _fin(oriented.get("yes_ask"))
    if b is not None and a is not None:
        return (b + a) / 2.0
    return t.p if direction != "up_on_yes" else 1.0 - t.p


def engine_tick(oriented: dict, ts_ns: int, venue: int) -> dict:
    d: dict[str, Any] = {k: (v if (v := _fin(oriented.get(k))) is not None else math.nan) for k in TICK_FIELDS}
    d["ts_ns"], d["venue"] = int(ts_ns), int(venue)
    return d


async def _closed_tick(bridge: Bridge, t: Tick, oriented: dict) -> tuple[dict | None, list[tuple[str, dict]]]:
    if bridge.effective_source == "replay":
        rts = getattr(t, "recorded_ts_ns", None)
        if rts is not None:
            bridge.last_replay_ts_ns = int(rts)
    px = _positive(t.fields.get("under_px"))
    if px is not None:
        bridge.last_under_px = px
    cm = bridge.closed
    if cm is None:
        return None, []
    try:
        return await cm.on_tick(t, oriented, engine_tick)
    except Exception as e:
        bridge.closed_errors += 1
        if bridge.closed_errors <= 3:
            return None, [("error", {"message": f"closed-market step failed: {type(e).__name__}: {e}",
                                     "source": "closed"})]
        return None, []


SESSION_CLOSED = "session_closed"


HOLD_NOTE_EQUITY = ("equities closed: the equity algo holds until the regular session; the staged plan (hedge B) "
                    "covers the open")
HOLD_NOTE_OPTIONS = ("options closed: the order broker takes option orders only in the regular session (09:30-16:00 "
                     "ET), so the options algo holds until it opens")


async def _hold_closed(bridge: Bridge, fields: dict, note: str = HOLD_NOTE_EQUITY) -> None:
    bridge.closed.holds += 1
    bridge.reasons[SESSION_CLOSED] += 1
    sess = bridge.closed.sess
    await bridge.emit("decision", {**fields, "action": "hold", "reason": SESSION_CLOSED,
                                   "phase": sess.phase if sess is not None else None, "note": note})


async def _run_source(bridge: Bridge, engine, hc, source) -> None:
    async for raw in source:
        t = as_tick(raw)
        bridge.ticks += 1
        oriented = orient_to_adverse(t.fields, bridge.direction)
        view, extra = await _closed_tick(bridge, t, oriented)
        ev = _tick_event(t)
        if view is not None:
            ev["closed"] = view
        await bridge.emit("tick", ev)
        for kind, data in extra:
            await bridge.emit(kind, data)
        if bridge.closed is not None and bridge.closed.hold:
            await _hold_closed(bridge, {"engine": "legacy", "family": None, "preset": None, "signal": None,
                                        "qty": 0.0, "order_qty": 0.0, "target_hedge": None,
                                        "current_hedge": bridge.hedge, "latency_ns": None})
            continue
        d = engine.on_tick(ts_ns=t.ts_ns, p=adverse_p(oriented, t, bridge.direction), now_ns=time.time_ns())
        bridge.latencies.append(d.latency_ns)
        bridge.reasons[d.reason] += 1
        await bridge.emit("decision", {"action": d.action, "reason": d.reason, "order_qty": d.order_qty,
                                       "target_hedge": d.target_hedge, "current_hedge": d.current_hedge,
                                       "latency_ns": d.latency_ns, "engine": "legacy", "family": None,
                                       "preset": None, "signal": None})
        if d.action == "order":
            engine.on_fill(d.order_qty)
            bridge.orders += 1
            bridge.hedge = engine.current_hedge
            fill = await _send_to_broker(bridge, d.order_qty)
            if fill is not None:
                bridge.fills.append(fill)
                del bridge.fills[:-MAX_FILLS]
                await bridge.emit("fill", fill)
            shares = bridge.proposal.shares_held
            await bridge.emit("position", {"hedge": bridge.hedge, "coverage": bridge.hedge / shares,
                                           "hedge_basis": "engine_intent",
                                           "broker_hedge": bridge.broker_hedge,
                                           "broker_coverage": bridge.broker_hedge / shares if shares else 0.0,
                                           "broker": bridge.broker_name or getattr(bridge.broker, "name", None)})


EQUITY_TTL_S = 15.0
STALE_QUOTE_SOURCES = ("massive_prev_close",)


def _equity_quote(bridge: Bridge, app):
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


RECORDED_SOURCE = "recorded"
REPLAY_RECORDED_NOTE = "replay: recorded price (no current quote), not a live fill"
REPLAY_RECORDED_PRICE_NOTE = ("recorded price: no current market quote (offline or no Massive key), so the fill is "
                              "priced at the replayed under_px, not today's market")


def recorded_prices_only() -> bool:
    return os.environ.get("POLYBRIDGE_REPLAY_PRICES", "").strip().lower() == "recorded"


async def _broker_can_price(bridge: Bridge, broker: Broker) -> bool:
    sim = broker if isinstance(broker, SimBroker) else None
    if sim is None:
        return True
    if recorded_prices_only():
        return False
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
                             broker: Broker | None = None, inherited: bool = False) -> None:
    filled = float(getattr(o, "filled_qty", 0.0) or 0.0)
    hedged = applied if hedged is None else hedged
    if filled - hedged > 1e-9:
        d = filled - hedged
        signed = d if side == "sell" else -d
        src = broker or bridge.resting_broker
        if src is not None and src is not bridge.replay_broker:
            bridge.account_hedge += signed
        if not (inherited and bridge._sandboxed()):
            bridge.broker_hedge += signed
            if bridge.closed is not None and instrument == "equity":
                if bridge.effective_source == "replay":
                    px = _positive(ref_px) or bridge.last_under_px
                else:
                    px = (_positive(getattr(o, "fill_px", None)) or _positive(getattr(o, "limit_px", None))
                          or _positive(ref_px))
                bridge.closed.on_equity_fill(signed, px)
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
    if inherited:
        keep["inherited"] = True
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
    else:
        if o.status == "rejected":
            bridge.broker_rejects += 1
        bridge.resting = bridge.resting_broker = None
        if algo is not None:
            algo.on_reject(instrument)


async def _lookup(broker: Broker, order_id: str, client_order_id: str | None = None):
    ids = {order_id, client_order_id} - {None}

    async def read():
        rows = await broker.orders()
        hit = next((o for o in rows if o.id in ids or getattr(o, "client_order_id", None) in ids), None)
        find = getattr(broker, "find_order", None)
        if hit is None and find is not None:
            hit = await find(client_order_id or order_id)
        return hit

    return await asyncio.wait_for(read(), BROKER_TIMEOUT_S)


async def _settle_resting(bridge: Bridge, algo, broker: Broker | None, why: str, ref_px: float | None = None) -> bool:
    r = bridge.resting
    broker = bridge.resting_broker or broker
    if r is None or broker is None:
        return r is None
    cid = r.get("client_order_id")
    inherited = bool(r.get("inherited"))
    if inherited:
        algo = None
    rec: dict = {"order_id": r["order_id"], "reason": why, "broker": broker.name}
    try:
        current = await _lookup(broker, r["order_id"], cid)
        if current is not None and current.status == "open":
            try:
                current = await asyncio.wait_for(broker.cancel(current.id), BROKER_TIMEOUT_S)
            except Exception:
                current = await _lookup(broker, r["order_id"], cid)
    except Exception as e:
        bridge.broker_errors += 1
        rec.update(status="error", error=type(e).__name__, kept_resting=True)
        await bridge.emit("cancel", rec)
        return False
    applied, hedged = float(r.get("applied") or 0.0), float(r.get("hedged", r.get("applied")) or 0.0)
    if current is None:
        bridge.resting = bridge.resting_broker = None
        if algo is not None:
            algo.on_reject(r["instrument"])
        rec["status"] = "unknown"
    elif current.status == "open":
        await _apply_order_state(bridge, algo, current, r["side"], r["instrument"], applied, hedged, ref_px, broker,
                                 inherited)
        rec.update(status="cancel_failed", kept_resting=True, filled_qty=current.filled_qty)
        await bridge.emit("cancel", rec)
        return False
    else:
        if current.status == "cancelled":
            bridge.cancels += 1
        await _apply_order_state(bridge, algo, current, r["side"], r["instrument"], applied, hedged, ref_px, broker,
                                 inherited)
        rec.update(status=current.status, filled_qty=current.filled_qty, fill_px=current.fill_px)
        if bridge.resting is not None:
            rec["kept_resting"] = True
            await bridge.emit("cancel", rec)
            return False
    await bridge.emit("cancel", rec)
    return True


def _coverage_room(bridge: Bridge) -> float:
    cap = math.floor(bridge.proposal.target_coverage * bridge.proposal.shares_held + 1e-9)
    reserved = pm = 0.0
    app = getattr(bridge, "app", None)
    if app is not None:
        clock = "replay" if bridge.effective_source == "replay" else "wall"
        try:
            reserved = staged_book.reserved_sell_qty(app, bridge.proposal_id, clock)
        except Exception:
            reserved = 0.0
    cm = getattr(bridge, "closed", None)
    if cm is not None:
        pm = cm.pm_leg_shares()
    return max(0.0, cap - bridge.broker_hedge - reserved - pm)


async def _send_intent(bridge: Bridge, algo, intent: dict, t: Tick) -> dict:
    instrument = str(intent.get("instrument") or "equity")
    side, qty = _side(intent), float(intent.get("qty") or 0.0)
    rec: dict = {"side": side, "qty": qty, "symbol": bridge.proposal.ticker, "instrument": instrument,
                 "family": bridge.algo["family"], "preset": bridge.algo.get("preset_index"),
                 "reason": intent.get("reason")}
    broker = bridge.order_broker()
    if instrument != "equity" or not (qty > 0 and math.isfinite(qty)):
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
        algo.on_reject(instrument)
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
    gated = await _equity_gates(bridge, broker, rec, side, qty, t)
    if gated is None:
        algo.on_reject(instrument)
        return rec
    qty = gated
    bridge.broker_name = broker.name
    limit = _fin(intent.get("limit_px"))
    limit = limit if limit is not None and limit > 0 else None
    note = ref = ref_source = None
    if bridge.effective_source == "replay":
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
        recorded = _fin(t.fields.get("under_px"))
        if recorded is not None and recorded > 0 and not await _broker_can_price(bridge, broker):
            ref, ref_source, note = recorded, RECORDED_SOURCE, REPLAY_RECORDED_NOTE
            rec["price_note"] = REPLAY_RECORDED_PRICE_NOTE
        else:
            note = REPLAY_NOTE
            rec["price_note"] = "priced at the current market, not the replayed time"
    else:
        ref = _fin(t.fields.get("under_px"))
        ref = ref if ref is not None and ref > 0 else None
    try:
        req = OrderRequest(symbol=bridge.proposal.ticker, asset="equity", side=side, qty=qty,
                           type="limit" if limit is not None else "market", limit_px=limit, ref_px=ref,
                           ref_source=ref_source, client_order_id=f"{bridge.id}-{bridge.orders}", tag=bridge.id,
                           note=note)
    except Exception as e:
        bridge.broker_errors += 1
        algo.on_reject(instrument)
        rec.update(status="error", error=type(e).__name__, filled_qty=0.0)
        return rec
    _record_participation(bridge, qty, t)
    try:
        o = await asyncio.wait_for(broker.place_order(req), BROKER_TIMEOUT_S)
    except Exception as e:
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
            bridge.quote_check = (time.monotonic(), False)
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
        if opp:
            rts = getattr(t, "recorded_ts_ns", None)
            if rts is not None:
                bridge.last_replay_ts_ns = int(rts)
            if getattr(t, "legs", None):
                bridge.last_legs = dict(t.legs)
                bridge.last_legs_ts_ns = int(rts) if rts is not None else None
                bridge.last_legs_settled = bool(getattr(t, "settled", False))
            bridge.opt_last = pm_vs_options(t.fields)
            ev["options"] = bridge.opt_last
            if bridge.opt_last["opt_implied_prob"] is not None and bridge.option_data == "none":
                bridge.option_data = "live_chain" if bridge.effective_source == "live" else "recorded"
        else:
            ev["under_source"] = bridge.equity_source if bridge.effective_source == "live" else (
                "recorded" if ev["under_px"] is not None else None)
        oriented = opp_engine_fields(bridge, t.fields) if opp else orient_to_adverse(t.fields, bridge.direction)
        adverse = oriented if not opp else orient_to_adverse(t.fields, bridge.direction)
        view, extra = await _closed_tick(bridge, t, adverse)
        if view is not None:
            ev["closed"] = view
        await bridge.emit("tick", ev)
        for kind, data in extra:
            await bridge.emit(kind, data)
        if bridge.closed is not None and bridge.closed.hold:
            await _hold_closed(bridge, {"engine": "algo", "family": fam, "preset": preset, "signal": None,
                                        "instrument": None, "side": None, "qty": 0.0, "limit_px": None,
                                        "order_qty": 0.0, "target_hedge": None, "current_hedge": bridge.hedge,
                                        "latency_ns": None}, HOLD_NOTE_OPTIONS if opp else HOLD_NOTE_EQUITY)
            continue
        i = algo.on_tick(engine_tick(oriented, t.ts_ns, t.venue), time.time_ns())
        reason = str(i.get("reason"))
        bridge.latencies.append(int(i.get("latency_ns") or 0))
        is_order = i.get("action") == "order"
        side = _side(i)
        qty = float(i.get("qty") or 0.0) if is_order else 0.0
        bridge.reasons[reason] += 1
        await bridge.emit("decision", {
            "engine": "algo", "family": fam, "preset": preset, "action": i.get("action"), "reason": reason,
            "reason_code": i.get("reason_code"), "reason_block": i.get("reason_block"), "signal": i.get("signal"),
            "instrument": i.get("instrument"), "side": side if is_order else None, "qty": qty,
            "limit_px": i.get("limit_px"),
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
                "broker": fill.get("broker"), "simulated": fill.get("simulated", True)})
            continue
        await bridge.emit("position", {"hedge": bridge.hedge, "coverage": bridge.hedge / shares if shares else 0.0,
                                       "hedge_basis": "broker_fill", "broker_hedge": bridge.broker_hedge,
                                       "broker_coverage": bridge.broker_hedge / shares if shares else 0.0,
                                       "resting_order": bridge.resting["order_id"] if bridge.resting else None,
                                       "broker": bridge.broker_name or getattr(bridge.broker, "name", None)})


OPTION_FILLS_LABEL = ("simulated option fills: Massive option quote mid +/- half the quoted spread, per-contract fee "
                      "(SimBroker; Webull paper does not take options here)")
OPTION_FILLS_LABEL_BROKER = ("Webull paper option fills: each structure is one net limit order at the quoted mids +/- "
                             "half-spreads, filled (or not) by the Webull paper account (WEBULL_OPTIONS=1; paper "
                             "money, Webull's own fill model)")
ROUTED_SIM = "simulator (Webull paper takes equities only unless WEBULL_OPTIONS=1)"
ROUTED_BROKER = "Webull paper (WEBULL_OPTIONS=1: option combos are placed at the Webull paper account)"
OPTIONS_SESSION_CLOSED = ("session_closed: the order broker takes option orders only in the regular session "
                          "(09:30-16:00 ET); nothing is sent until it opens")


def _options_at_broker(broker: Broker | None) -> bool:
    return broker is not None and not isinstance(broker, SimBroker) and bool(getattr(broker, "options_supported",
                                                                                     False))


def _options_closed_at_broker(bridge: Bridge, broker: Broker | None) -> bool:
    if not _options_at_broker(broker) or not getattr(broker, "regular_session_only", False):
        return False
    try:
        now = bridge_mode.live_now(bridge.app) if bridge.app is not None else bridge_mode.now_utc()
        return bridge_mode.session_at(now).closed
    except (ValueError, AttributeError):
        return True
OPTION_MULT = 100.0
RECORDED_OPTION_NOTE = "replay: option legs priced at the recorded bar closes (no current chain lists them)"
RECORDED_OPTION_PRICE_NOTE = ("recorded leg closes: no current option chain lists these contracts (expired, or offline), "
                              "so each leg is priced at its Massive bar close as of the replayed time, +/- the "
                              "simulator's default half-spread (2% of the price; the real spread is unknown)")
NO_FRESH_LEGS = ("replay: no fresh recorded option closes at this replayed time (the recording keeps leg closes only in "
                 "the regular session once both legs have printed) and no current chain lists these contracts")
END_LEGS_MAX_AGE_NS = (3600 + 300) * 1_000_000_000
SETTLED_OPTION_PRICE_NOTE = ("expiry settlement: the contracts expired, so each leg is valued at its intrinsic value from "
                             "the underlying's official close on the expiry date (recorded with the replay), with no "
                             "spread; the simulator's per-contract fee still applies")
SETTLED_OPENS = ("replay: the recorded legs are the expiry settlement (the contracts have expired), not a tradable quote: "
                 "only an open structure is closed at it")
SETTLE_MIN_PX = 0.0001


def stale_end_legs(age_ns: int | None) -> str:
    if age_ns is None:
        return ("replay: the bridge-end close cannot tell when the last recorded leg closes were seen, so it does not "
                "price the close at them (the structure stays open in option_structure)")
    return (f"replay: the last recorded leg closes are {age_ns / 3.6e12:.1f} h older than the end of the replay (no "
            "fresh closes overnight, on weekends or after expiry, and no recorded settlement), so the bridge-end close "
            "is not priced at a stale close (the structure stays open in option_structure)")


def recorded_context(struct: dict, legs: dict[str, float], settled: bool = False) -> dict:
    from .options.chain import Chain, OptionQuote
    chain = Chain(underlying=struct["underlying"], fetched_at=time.time(), source="recording")
    for lg in struct["legs"]:
        px = legs.get(lg["ticker"])
        if px is not None:
            extra = {"bid": px, "ask": px, "mark_source": "expiry_settlement"} if settled else {
                "mark_source": "recorded_bar_close"}
            chain.quotes.append(OptionQuote(ticker=lg["ticker"], kind=lg["kind"], strike=lg["strike"],
                                            expiry=struct["expiry"], mid=px, **extra))
    return {"underlying": struct["underlying"], "strike": struct.get("strike"), "expiry": struct["expiry"],
            "k_lo": struct["k_lo"], "k_hi": struct["k_hi"], "above": struct["direction"] == "above", "chain": chain,
            "available": True, "recorded": True}


def _options_brief(enricher: OptionsEnricher | None) -> dict | None:
    if enricher is None:
        return None
    d = enricher.detail or {}
    keep = ("supported", "available", "reason", "underlying_used", "strike_used", "expiry", "k_lo", "k_hi",
            "method", "direction", "expiry_gap_days", "notes", "eightk_coverage")
    return {k: (None if isinstance(d[k], float) and not math.isfinite(d[k]) else d[k]) for k in keep if k in d}


def opp_engine_fields(bridge: Bridge, fields: dict) -> dict:
    qdir = (bridge.options.detail or {}).get("direction") if bridge.options is not None else None
    return orient_for_family(fields, bridge.algo["family"], qdir)


def pm_vs_options(fields: dict) -> dict:
    b, a = _fin(fields.get("yes_bid")), _fin(fields.get("yes_ask"))
    pm = (b + a) / 2.0 if b is not None and a is not None else None
    op = _fin(fields.get("opt_implied_prob"))
    return {"pm_mid": pm, "opt_implied_prob": op, "gap": (pm - op) if pm is not None and op is not None else None,
            "opt_mid": _fin(fields.get("opt_mid")), "opt_iv": _fin(fields.get("opt_iv")),
            "opt_delta": _fin(fields.get("opt_delta")), "eightk_score": _fin(fields.get("eightk_score")),
            "label": "PM price measured; options-implied probability is a risk-neutral estimate"}


def option_structure(family: str, ctx: dict, side: int) -> dict | None:
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
    fam = bridge.algo["family"]
    side = 1 if int(intent.get("side") or 0) > 0 else -1
    qty = float(intent.get("qty") or 0.0)
    broker = bridge.order_broker()
    at_broker = _options_at_broker(broker)
    rec: dict = {"instrument": "option", "side": "buy" if side > 0 else "sell", "qty": qty, "family": fam,
                 "preset": bridge.algo.get("preset_index"), "reason": intent.get("reason"), "symbol": None,
                 "simulated": not at_broker, "fill_model": OPTION_FILLS_LABEL_BROKER if at_broker
                 else OPTION_FILLS_LABEL}
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
    if _options_closed_at_broker(bridge, broker):
        bridge.reasons[SESSION_CLOSED] += 1
        rec.update(status="held", reject_reason=OPTIONS_SESSION_CLOSED, filled_qty=0.0)
        return rec
    ctx = bridge.options.context() if bridge.options is not None else None
    recorded = settled = False
    closing = bridge.opt_pos != 0 and side * bridge.opt_pos < 0
    if ctx is None and bridge.effective_source == "replay" and bridge.recorded_options is not None:
        if t is None:
            legs_px, settled = bridge.last_legs, bridge.last_legs_settled
            if legs_px:
                age = (None if bridge.last_legs_ts_ns is None or bridge.last_replay_ts_ns is None
                       else bridge.last_replay_ts_ns - bridge.last_legs_ts_ns)
                if age is None or age > END_LEGS_MAX_AGE_NS:
                    return refuse("rejected", stale_end_legs(age))
        else:
            legs_px, settled = getattr(t, "legs", None), bool(getattr(t, "settled", False))
        if not legs_px:
            return refuse("rejected", NO_FRESH_LEGS)
        if settled and not closing:
            return refuse("rejected", SETTLED_OPENS)
        ctx, recorded = recorded_context(bridge.recorded_options, legs_px, settled), True
        rec["price_source"] = RECORDED_SOURCE
    if closing and bridge.opt_open is not None:
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
    if not closing:
        p = bridge.proposal
        room_c = max(0.0, float(p.max_contracts or 0) - abs(bridge.opt_pos)) if p.max_contracts else qty
        risk = unit_risk(struct, side, net_mid, net_half)
        if risk is None:
            return refuse("rejected", "no option quote to size the max_notional cap")
        if risk <= 0:
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
    lq = liquidity.option_check([_quote_by_ticker(chain, tk) if chain is not None else None for _s, tk, *_r in priced],
                                qty)
    liquidity.tag(rec, lq)
    if lq["status"] == "capped":
        bridge.liquidity_capped += 1
        bridge.reasons[liquidity.LIQUIDITY_CAPPED] += 1
        rec.setdefault("capped_from", qty)
        qty = float(lq["allowed"])
        rec["qty"] = qty
        if qty <= 0:
            return refuse("held", f"liquidity_capped: {lq['rule']} (leg {lq.get('leg')} allows {lq['limit_qty']:g})")
    if not closing:
        mode = capital_budget.limits(bridge.app)["short_put_mode"] if bridge.app is not None else "cash_secured"
        spot = _positive(bridge.last_under_px) or _fin((ctx or {}).get("spot"))
        req_usd = capital_budget.option_requirement(struct.get("kind", ""), side, qty, net_mid, net_half,
                                                    width=struct.get("width"), strike=struct.get("strike"),
                                                    spot=spot, mode=mode)
        opt_acct = getattr(broker, "sim", None) if not isinstance(broker, SimBroker) and not at_broker else None
        if await _capital_refuses(bridge, opt_acct or broker, rec, req_usd, req_usd):
            algo.on_reject("option")
            return rec
    note = None
    if bridge.effective_source == "replay":
        note = RECORDED_OPTION_NOTE if recorded else "replay: option legs priced at the current chain snapshot, not the replayed time"
        rec["price_note"] = (SETTLED_OPTION_PRICE_NOTE if settled else RECORDED_OPTION_PRICE_NOTE) if recorded else note
        if settled:
            rec["settlement"] = (bridge.recorded_options or {}).get("settlement") or {"rule": "intrinsic value at expiry"}
        rec["scope"] = "account" if bridge.replay_to_account else "replay_sandbox"
    if at_broker:
        rec["routed"] = ROUTED_BROKER
    elif not isinstance(bridge.broker, SimBroker):
        rec["routed"] = ROUTED_SIM
    cid = f"{bridge.id}-{bridge.orders}"
    try:
        if settled:
            priced = [(sign, tk, max(mid, SETTLE_MIN_PX) if mid is not None else None, 0.0, src)
                      for sign, tk, mid, _half, src in priced]
        reqs = [OrderRequest(symbol=tk, asset="option", side="buy" if sign * side > 0 else "sell", qty=qty,
                             type="market", ref_px=mid if mid is not None and mid > 0 else None,
                             ref_half_spread=half if mid is not None and mid > 0 else None,
                             ref_source=RECORDED_SOURCE if recorded and mid is not None and mid > 0 else None,
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
        if recorded:
            bridge.recorded_option_fills += 1
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
        position = ({"option": 0.0} if bridge.division == "opportunity"
                    else {"shares_held": float(bridge.proposal.shares_held)})
        try:
            engine = hc.Algo(bridge.algo["family"], dict(bridge.algo["params"]), position)
        except Exception as e:
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
    bridge.engine = engine
    try:
        bridge.broker = get_broker(app)
    except Exception:
        bridge.broker = None
        await bridge.emit("error", {"message": "broker unavailable", "source": "broker"})
    if bridge.options is not None and bridge.effective_source == "replay":
        await bridge.options({"ts_ns": time.time_ns()}, time.time_ns())
    if bridge.options is not None:
        await bridge.emit("status", {"status": "running", "options": bridge.options_brief()
                                     if bridge.options.detail or bridge.recorded_options else
                                     {"supported": None, "reason": "resolving"}})
    try:
        try:
            await loop(source)
        except (SourceError, OSError) as e:
            await bridge.emit("error", {"message": str(e), "source": bridge.effective_source})
            if bridge.effective_source == "live" and fallback is not None and fallback.is_file():
                await _finish_orders(bridge, engine)
                bridge.effective_source = "replay"
                bridge.set_replay(fallback)
                await bridge.emit("status", {"status": "running", "source": "replay", "note": "live failed; replaying"})
                bars = _bars(bridge.proposal.ticker)
                bridge.equity_price = _replay_equity_price(fallback, bars)
                await loop(ReplaySource(fallback, speed=_replay_speed(app, fallback), bars=bars))
            else:
                await _finish_orders(bridge, engine)
                await bridge.emit("status", {"status": "stopped", "reason": "source_failed"}, status="stopped")
                return
        await _finish_orders(bridge, engine)
        await bridge.emit("status", {"status": "finished"}, status="finished")
    except asyncio.CancelledError:
        await bridge.emit("status", {"status": "stopped", "reason": "cancelled"}, status="stopped")
        raise
    except Exception as e:
        await bridge.emit("error", {"message": type(e).__name__})
        await bridge.emit("status", {"status": "stopped", "reason": "internal_error"}, status="stopped")


OPTION_CLOSE_LABEL = ("simulated close at bridge end: the open option structure is bought/sold back on its own legs "
                      "at the Massive quote mid +/- half the spread (SimBroker), so no option position outlives the "
                      "bridge")
OPTION_CLOSE_LABEL_BROKER = ("close at bridge end: the open option structure is bought/sold back on its own legs as "
                             "one net limit order at the Webull paper account (WEBULL_OPTIONS=1); outside 09:30-16:00 "
                             "ET nothing is sent and the structure stays open (reported)")


async def _finish_orders(bridge: Bridge, engine) -> None:
    if bridge.resting is not None:
        await _settle_resting(bridge, engine if bridge.algo else None, bridge.order_broker(), "bridge_end")
    if bridge.algo and bridge.division == "opportunity" and bridge.opt_pos != 0 and bridge.opt_open is not None:
        bridge.orders += 1
        intent = {"action": "order", "instrument": "option", "side": -1 if bridge.opt_pos > 0 else 1,
                  "qty": abs(bridge.opt_pos), "reason": "bridge_end"}
        fill = await _send_option_intent(bridge, engine, intent, None)
        fill.update(close_reason="bridge_end",
                    close_label=OPTION_CLOSE_LABEL if fill.get("simulated", True) else OPTION_CLOSE_LABEL_BROKER)
        bridge.fills.append(fill)
        del bridge.fills[:-MAX_FILLS]
        await bridge.emit("fill", fill)
        await bridge.emit("position", {
            "option_position": bridge.opt_pos, "option_structure": bridge.opt_open,
            "risk_used": abs(bridge.opt_pos) * bridge.opt_risk_per_unit,
            "max_contracts": bridge.proposal.max_contracts, "max_notional": bridge.proposal.max_notional,
            "broker": fill.get("broker"), "simulated": fill.get("simulated", True), "close_reason": "bridge_end"})


def _replay_equity_price(path: Path, bars: list[tuple[int, float]]) -> str:
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
    try:
        m = normalize_manifest(hc.catalog())
        if m["families"]:
            return m
    except Exception:
        pass
    from .pipeline.engine_adapter import EngineAdapter
    return EngineAdapter(module=None).library()[0]


def _asked_algo(body: BridgeIn) -> AlgoChoice | None:
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
    if opp:
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
    prior: Bridge | None = None
    if existing is not None and existing.status != "running":
        _history(request)[existing.id] = existing
        prior, existing = existing, None
    if existing is not None:
        if existing.requested_source != body.source:
            raise HTTPException(409, f"Bridge {existing.id} already started for proposal {prop.id} with source {existing.requested_source}.")
        asked = _asked_algo(body)
        if asked is not None and (existing.choice is None or not _same_algo(asked, existing.choice)):
            raise HTTPException(409, f"Bridge {existing.id} for proposal {prop.id} already runs "
                                     f"{_algo_label(existing.choice)}; it cannot switch algos.")
        response.status_code = 200
        return {"bridge_id": existing.id}
    market, direction = _resolve(prop, body)
    evid = evidence_gate.signal_status(market.source, market.id, market.token_id, prop.ticker)
    if not evid["validated"] and not prop.ack_unvalidated:
        raise HTTPException(409, f"EVIDENCE_UNVALIDATED: {prop.ticker} on {market.source}:{market.id} is an "
                                 f"unvalidated estimate ({evid['evidence']}) and proposal {prop.id} was approved "
                                 "without ack_unvalidated; propose again and approve with ack_unvalidated: true.")
    if prop.algo is not None and prop.algo.source == "ai_fit" and not prop.ack_unvalidated:
        raise HTTPException(409, f"GENERIC_FIT_UNVALIDATED: proposal {prop.id} runs {prop.algo.family} chosen by the "
                                 "generic AI fit, which is unvalidated (its walk-forward test failed), and was approved "
                                 "without ack_unvalidated; the fit acts only behind the acknowledgement gate, even on a "
                                 "market whose gap evidence is validated. Propose again and approve with "
                                 "ack_unvalidated: true.")
    if body.act_on_unvalidated and prop.family != "hedge":
        raise HTTPException(422, "act_on_unvalidated (the closed-market staged-hedge override) applies to hedge "
                                 "bridges only.")
    hc = _load_engine()
    if hc is None:
        raise HTTPException(503, NO_ENGINE)

    algo, choice = _algo_for(prop, body, hc)
    to_account, broker_note = _replay_scope(request.app, body)
    bridge = Bridge(prop, body.source, market, body.gap_per_share, direction, to_account, algo)
    bridge.broker_note = broker_note
    bridge.choice = choice
    bridge.app = request.app
    bridge.session_hold = body.session_hold
    bridge.evidence = evid
    bridge.evidence_label = (evidence_gate.LABEL_VALIDATED if evid["validated"]
                             else evidence_gate.LABEL_ACKNOWLEDGED)
    bridge.act_on_unvalidated = bool(body.act_on_unvalidated or prop.act_on_unvalidated) and not evid["validated"]
    if prop.family == "hedge":
        from .liquidity.service import service_for
        service_for(request.app).warm_equity(prop.ticker)
    if prior is not None:
        _carry_account_exposure(prior, bridge)
    bridge.closed = bridge_mode.ClosedMode(bridge, request.app, hc,
                                           hedge_a=bool(getattr(prop, "closed_pm_hedge", False)))

    fallback = _fallback_path(request.app, market)
    if body.source == "replay":
        path = _replay_path(request, market, body.market, replay_file=body.replay_file)
        if path is None or not path.is_file():
            raise HTTPException(422, "No replay file configured (set POLYBRIDGE_REPLAY_PATH or add replays/<market id>.jsonl).")
        bridge.set_replay(path)
        bars = _bars(prop.ticker)
        source: Any = ReplaySource(path, speed=_replay_speed(request.app, path), bars=bars)
        bridge.equity_price = _replay_equity_price(path, bars)
        if bridge.division == "opportunity":
            bridge.options = _options_enricher(request, market)
    else:
        primary, mid = _live_primary(market)
        twin = _twin(body.twin, primary)
        origin = "request" if twin else None
        if twin is None and body.twin is None:
            twin = _mapped_twin(market)
            origin = "twin_map" if twin else None
        bridge.twin = {"source": twin[0], "id": twin[1], "origin": origin} if twin else None
        factory = getattr(request.app.state, "live_source_factory", None) or LiveSource
        if bridge.division == "opportunity":
            bridge.options = _options_enricher(request, market)
            source = factory(mid, primary=primary, twin=twin, equity=None, options=bridge.options)
        else:
            source = factory(mid, primary=primary, twin=twin,
                             equity=_equity_quote(bridge, request.app) if algo else None)

    reg[prop.id] = bridge
    store.mark_bridge_started(prop.id)
    bridge.task = asyncio.create_task(_run(bridge, request.app, hc, source, fallback))
    return {"bridge_id": bridge.id}


def _regular_session_only(app) -> bool:
    try:
        return bool(getattr(get_broker(app), "regular_session_only", False))
    except Exception:
        return False


def _wall_closed(app) -> bool:
    try:
        return bridge_mode.session_at(bridge_mode.live_now(app)).closed
    except ValueError:
        return False


def _replay_scope(app, body: BridgeIn) -> tuple[bool, str | None]:
    if not _regular_session_only(app) or not _wall_closed(app):
        return body.replay_to_account, None
    if body.source == "replay":
        note = ("Webull paper accepts orders 09:30-16:00 ET and the market is closed: this replay trades its "
                "in-memory sandbox")
        return False, note + (" (replay_to_account ignored)" if body.replay_to_account else "")
    return False, ("Webull paper accepts orders 09:30-16:00 ET and the market is closed: the equity algo holds and "
                   "only approved staged orders go to Webull, executing at the 09:30 ET open")


def _carry_account_exposure(old: Bridge, new: Bridge) -> None:
    new.account_hedge = old.account_hedge
    if not new._sandboxed():
        new.broker_hedge = old.account_hedge
        if new.algo:
            new.hedge = new.broker_hedge
    r, rb = old.resting, old.resting_broker
    if r is not None and rb is not None and rb is not old.replay_broker:
        new.resting, new.resting_broker = {**r, "inherited": True}, rb


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
        seen = 0
        while True:
            batch: list = []
            done = heartbeat = False
            async with bridge.cond:
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
