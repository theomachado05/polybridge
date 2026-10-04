from __future__ import annotations

import datetime as dt
import os
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import OPP_DEFAULT_MAX_CONTRACTS, OPP_DEFAULT_MAX_NOTIONAL
from . import opportunity as opp
from . import session as sc

router = APIRouter(prefix="/closed/opportunity", tags=["closed"])
TIMEOUT = httpx.Timeout(5.0)


class SnapshotIn(BaseModel):
    market_source: Literal["polymarket", "kalshi"] | None = None
    market_id: str | None = Field(default=None, min_length=1, max_length=128)
    question: str | None = Field(default=None, min_length=1, max_length=500)
    end_date: str | None = Field(default=None, max_length=40)
    pm_yes: float | None = Field(default=None, gt=0, lt=1, allow_inf_nan=False)


class StageIn(BaseModel):
    snapshot_id: str = Field(min_length=1, max_length=64)
    contracts: int = Field(default=opp.DEFAULT_CONTRACTS, ge=1, le=OPP_DEFAULT_MAX_CONTRACTS)
    max_contracts: int = Field(default=OPP_DEFAULT_MAX_CONTRACTS, ge=1, le=OPP_DEFAULT_MAX_CONTRACTS)
    max_notional: float = Field(default=OPP_DEFAULT_MAX_NOTIONAL, gt=0, le=OPP_DEFAULT_MAX_NOTIONAL,
                                allow_inf_nan=False)
    pm_yes: float | None = Field(default=None, gt=0, lt=1, allow_inf_nan=False)
    ack_unvalidated: bool = False


class PriceIn(BaseModel):
    pm_yes: float | None = Field(default=None, gt=0, lt=1, allow_inf_nan=False)


def book(request: Request) -> opp.OpportunityBook:
    st = request.app.state
    if getattr(st, "opportunity_book", None) is None:
        st.opportunity_book = opp.OpportunityBook(os.environ.get("CLOSED_OPPORTUNITY_PATH") or opp.DEFAULT_PATH)
    return st.opportunity_book


def now(request: Request) -> dt.datetime:
    clock = getattr(request.app.state, "closed_clock", None)
    return sc.to_utc(clock()) if clock is not None else sc.now_utc()


def _http(request: Request) -> httpx.AsyncClient:
    if not hasattr(request.app.state, "http"):
        request.app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    return request.app.state.http


def _local_price(request: Request, pm_yes: float | None) -> float | None:
    return None if getattr(request.state, "remote", False) else pm_yes


async def _resolve(request: Request, market: dict) -> dict:
    from ..options.router import resolve_market
    if market.get("source") and market.get("id"):
        return await resolve_market(_http(request), market["source"], str(market["id"]))
    return {"question": market.get("question"), "end_date": market.get("end_date"), "yes_price": None,
            "origin": "request"}


DECISION_ORIGINS = ("live",)


def decision_price(found: dict) -> float | None:
    return opp._fin(found.get("yes_price")) if found.get("origin") in DECISION_ORIGINS else None


async def pm_now(request: Request, market: dict, override: float | None) -> tuple[float | None, str | None]:
    if (p := _local_price(request, override)) is not None:
        return p, "supplied"
    if not (market.get("source") and market.get("id")):
        return None, None
    found = await _resolve(request, market)
    return decision_price(found), found.get("origin")


async def open_chain(snap: dict, t: dt.datetime):
    client = opp.make_client()
    if client is None or not snap.get("match"):
        return None, False
    m = snap["match"]
    got = await opp.fetch_chain(snap["underlying_used"], float(snap["strike_used"]), m["expiry"], None,
                                float(m.get("level") or 0), as_of=t.astimezone(sc.ET).date(), client=client)
    return (got[0], got[1]) if got else (None, False)


def _snap(request: Request, snapshot_id: str | None = None, source: str | None = None,
          mid: str | None = None) -> dict:
    b = book(request)
    s = b.snapshots.get(snapshot_id) if snapshot_id else b.latest_for(f"{source}:{mid}") if source and mid else None
    if s is None:
        raise HTTPException(404, {"reason_code": "no_snapshot", "reason": opp.REASONS["no_snapshot"]})
    return s


def _trade(request: Request, tid: str) -> dict:
    t = book(request).trades.get(tid)
    if t is None:
        raise HTTPException(404, f"No opportunity trade {tid}.")
    return t


def _close_supported(s: dict) -> bool:
    return bool(s.get("available")) and opp._fin(s.get("pm_yes")) is not None


@router.get("")
async def status(request: Request) -> dict:
    b = book(request)
    t = now(request)
    snaps = sorted(b.snapshots.values(), key=lambda s: s.get("taken_at") or "", reverse=True)
    trades = sorted(b.trades.values(), key=lambda x: x.get("created_at") or "", reverse=True)
    research = opp.research_status()
    supported = any(_close_supported(s) for s in snaps)
    s = sc.session_at(t)
    return {"label": opp.LABEL, "research": research,
            "supported": supported,
            "display": "research_supported" if supported and research["supports_claim"] else
                       "estimate" if supported else "hidden",
            "session": {"phase": s.phase, "label": s.label, "next_open": sc._iso(s.next_open),
                        "last_close": sc._iso(s.last_close)},
            "book": {"max_notional": opp.BOOK_MAX_NOTIONAL, "exposure": b.exposure(t), "room": b.book_room(t)},
            "snapshots": [{**x, "supported": _close_supported(x)} for x in snaps], "trades": trades}


@router.post("/snapshot")
async def snapshot(body: SnapshotIn, request: Request) -> dict:
    if not body.question and not (body.market_source and body.market_id):
        raise HTTPException(422, "Give market_source and market_id, or question.")
    t = now(request)
    market: dict[str, Any] = {"source": body.market_source, "id": body.market_id, "question": body.question,
                              "end_date": body.end_date, "origin": "request" if body.question else None}
    yes = found_origin = None
    if body.market_source and body.market_id:
        found = await _resolve(request, market)
        found_origin = found.get("origin")
        market.update(question=body.question or found.get("question"),
                      end_date=body.end_date or found.get("end_date"),
                      origin="request" if body.question else found_origin)
        yes = decision_price(found)
    supplied = _local_price(request, body.pm_yes)
    rec = await opp.take_snapshot(market, now=t, pm_yes=supplied if supplied is not None else yes,
                                  client=opp.make_client())
    if rec.get("key") is None:
        return {**rec, "stored": False, "research": opp.research_status()}
    rec["pm_source"] = "supplied" if supplied is not None else found_origin if yes is not None else None
    if supplied is None and yes is None and found_origin not in (None, *DECISION_ORIGINS):
        rec.setdefault("notes", []).append(f"no live PM price (lookup fell back to {found_origin}); no close price "
                                           "recorded")
    b = book(request)
    async with b.lock:
        try:
            stored = b.put_snapshot(rec, pm_explicit=supplied is not None)
        except ValueError as e:
            code = str(e)
            sid = b.snapshot_id(rec["key"], rec["close_day"])
            cur = b.in_use(sid) or {}
            raise HTTPException(409, {"reason_code": code, "reason": opp.REASONS.get(code, code),
                                      "snapshot_id": sid, "trade_id": cur.get("id")})
    return {**stored, "stored": True, "supported": _close_supported(stored), "research": opp.research_status()}


@router.get("/compare")
async def compare(request: Request, snapshot_id: str | None = None, market_source: str | None = None,
                  market_id: str | None = None, refresh_options: bool = False, pm_yes: float | None = None) -> dict:
    if pm_yes is not None and not 0 < pm_yes < 1:
        raise HTTPException(422, "pm_yes must be in (0, 1).")
    s = _snap(request, snapshot_id, market_source, market_id)
    t = now(request)
    price, origin = await pm_now(request, s["market"], pm_yes)
    opt_now = None
    if refresh_options and sc.to_utc(s["next_open"]) <= t:
        chain, stale = await open_chain(s, t)
        opt_now = opp.implied_now(s, chain, now=t, cache_stale=stale)
    dec = opp.evaluate(s, price, opt_now)
    active = book(request).active_trade(s["id"])
    return {"snapshot_id": s["id"], "market": s["market"], "label": opp.LABEL, "supported": dec["supported"],
            "comparison": dec, "pm_source": origin, "opt_now": opt_now, "active_trade": active,
            "research": opp.research_status(), "snapshot": s}


@router.post("/trades", status_code=201)
async def stage(body: StageIn, request: Request) -> dict:
    b = book(request)
    s = _snap(request, body.snapshot_id)
    t = now(request)
    if t >= sc.to_utc(s["next_open"]) + dt.timedelta(seconds=opp.EXEC_WINDOW_S):
        raise HTTPException(409, {"reason_code": "missed_open_window", "reason": opp.REASONS["missed_open_window"]})
    research = opp.research_status()
    validated = bool(research.get("supports_claim"))
    if not validated and not body.ack_unvalidated:
        raise HTTPException(409, {"reason_code": "evidence_unvalidated", "reason": opp.REASONS["evidence_unvalidated"],
                                  "research": research})
    price, _ = await pm_now(request, s["market"], body.pm_yes)
    dec = opp.evaluate(s, price)
    async with b.lock:
        if (cur := b.active_trade(s["id"])) is not None:
            raise HTTPException(409, {"reason_code": "already_staged", "reason": f"trade {cur['id']} is already "
                                      f"{cur['status']} for this snapshot", "trade_id": cur["id"]})
        try:
            trade = opp.stage_trade(s, dec, now=t, contracts=body.contracts, max_contracts=body.max_contracts,
                                    max_notional=body.max_notional, book_room=b.book_room(t))
        except ValueError as e:
            code = str(e)
            raise HTTPException(409, {"reason_code": code, "reason": opp.REASONS.get(code, code), "comparison": dec})
        trade["ack_unvalidated"] = bool(body.ack_unvalidated)
        trade["evidence"] = "validated" if validated else opp.EVIDENCE_LABEL
        return b.put_trade(trade)


@router.get("/trades")
async def list_trades(request: Request) -> list[dict]:
    return sorted(book(request).trades.values(), key=lambda x: x.get("created_at") or "", reverse=True)


@router.get("/trades/{tid}")
async def get_trade(tid: str, request: Request) -> dict:
    return _trade(request, tid)


@router.post("/trades/{tid}/approve")
async def approve(tid: str, request: Request) -> dict:
    b = book(request)
    t = now(request)
    async with b.lock:
        tr = _trade(request, tid)
        if tr["status"] != "staged":
            raise HTTPException(409, f"Trade {tid} is {tr['status']}; only a staged trade can be approved.")
        if t >= sc.to_utc(tr["window_end"]):
            tr["status"] = "expired"
            opp._event(tr, t, "expired", "not_approved_in_window")
            b.put_trade(tr)
            raise HTTPException(409, {"reason_code": "not_approved_in_window",
                                      "reason": opp.REASONS["not_approved_in_window"]})
        tr["status"] = "approved"
        tr["approved_at"] = sc._iso(t)
        opp._event(tr, t, "approved", "approved")
        return b.put_trade(tr)


@router.post("/trades/{tid}/cancel")
async def cancel(tid: str, request: Request) -> dict:
    b = book(request)
    async with b.lock:
        tr = _trade(request, tid)
        if tr["status"] not in opp.ACTIVE:
            raise HTTPException(409, f"Trade {tid} is {tr['status']}; only a staged or approved trade can be cancelled.")
        tr["status"] = "cancelled"
        opp._event(tr, now(request), "cancelled", "cancelled_by_user")
        return b.put_trade(tr)


async def _execute(request: Request, tr: dict, override: float | None) -> dict:
    from ..broker import get_broker
    b = book(request)
    t = now(request)
    s = b.snapshots.get(tr["snapshot_id"])
    if s is None:
        tr["status"] = "rejected"
        opp._event(tr, t, "rejected", "no_snapshot")
        b.put_trade(tr)
        return {"outcome": "rejected", "reason_code": "no_snapshot", "reason": opp.REASONS["no_snapshot"],
                "trade_id": tr["id"]}
    chain = stale = price = None
    if tr["status"] == "approved" and sc.to_utc(tr["not_before"]) <= t < sc.to_utc(tr["window_end"]):
        chain, stale = await open_chain(s, t)
        price, _ = await pm_now(request, s["market"], override)
    res = await opp.execute_trade(tr, s, now=t, pm_now=price, chain=chain, broker=get_broker(request.app),
                                  cache_stale=bool(stale), book_room=b.book_room(t, exclude=tr["id"]),
                                  app=request.app)
    b.put_trade(tr)
    return res


@router.post("/trades/{tid}/execute")
async def execute(tid: str, request: Request, body: PriceIn | None = None) -> dict:
    b = book(request)
    async with b.lock:
        tr = _trade(request, tid)
        res = await _execute(request, tr, body.pm_yes if body else None)
    if res["outcome"] == "refused":
        raise HTTPException(409, {k: res[k] for k in ("reason_code", "reason", "trade_id")})
    return {**res, "trade": tr}


@router.post("/execute-due")
async def execute_due(request: Request) -> dict:
    b = book(request)
    t = now(request)
    out = []
    async with b.lock:
        for tr in list(b.trades.values()):
            due = tr["status"] == "approved" and sc.to_utc(tr["not_before"]) <= t
            overdue = tr["status"] in opp.ACTIVE and t >= sc.to_utc(tr["window_end"])
            if due or overdue:
                out.append(await _execute(request, tr, None))
    return {"at": sc._iso(t), "results": out}


@router.post("/review")
async def review(request: Request) -> dict:
    b = book(request)
    t = now(request)
    out = []
    async with b.lock:
        for tr in list(b.trades.values()):
            if tr["status"] not in opp.ACTIVE:
                continue
            s = b.snapshots.get(tr["snapshot_id"])
            price, _ = await pm_now(request, (s or {}).get("market") or {}, None)
            dec = opp.review_trade(tr, s, price, now=t)
            b.put_trade(tr)
            out.append({"trade_id": tr["id"], "status": tr["status"], "comparison": dec})
    return {"at": sc._iso(t), "results": out}
