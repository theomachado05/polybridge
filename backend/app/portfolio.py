from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from . import chain
from . import equities as eq
from .mapping import SOURCE_PRECOMPUTED, MapRequest, lookup_precomputed
from .markets import Market, offline_search, search_all
from .models import Proposal

PORTFOLIO_PATH = Path(__file__).parent / "data" / "portfolio.json"
TOP_MARKETS = 5
router = APIRouter()


class Exposure(BaseModel):
    market: Market
    direction: str
    impact_pct: float
    rationale: str | None = None
    remaining_usd: float
    label: str
    match_type: str | None = None
    matched_question: str | None = None
    score: float | None = None


class HedgeStatus(BaseModel):
    status: str
    proposal_id: str | None = None
    bridge_id: str | None = None


class BrokerBook(BaseModel):
    broker: str | None = None
    label: str
    available: bool = True
    error: str | None = None
    account: dict | None = None
    positions: list[dict] = []
    options_supported: bool | None = None
    note: str | None = None


class Holding(BaseModel):
    ticker: str
    name: str | None = None
    shares: float
    spot: float | None = None
    value: float | None = None
    markets: list[Market]
    filings: list[eq.Filing]
    exposure: Exposure | None = None
    hedge: HedgeStatus
    notes: list[str]
    broker_qty: float | None = None
    can_short: bool | None = None
    short_reason: str | None = None


class PortfolioOut(BaseModel):
    holdings_label: str = "demo holdings"
    holdings: list[Holding]
    broker_account: BrokerBook | None = None
    total_value: float | None = None
    total_exposure: float | None = None
    total_includes_fuzzy: bool = False
    stale: bool = False


def remaining_exposure(shares: float, spot: float | None, impact_pct: float | None, p: float | None,
                       direction: str | None = "down_on_yes") -> float | None:
    vals = (shares, spot, impact_pct, p)
    if any(v is None or not math.isfinite(v) for v in vals) or shares <= 0 or spot <= 0:
        return None
    pc = min(max(p, 0.0), 1.0)
    if direction == "down_on_yes":
        adverse = 1 - pc
    elif direction == "up_on_yes":
        adverse = pc
    else:
        return None
    return shares * spot * abs(impact_pct) / 100 * adverse


def load_holdings() -> list[dict]:
    try:
        rows = json.loads(PORTFOLIO_PATH.read_text()).get("holdings", [])
        out = []
        for r in rows:
            h = {"ticker": str(r["ticker"]).upper(), "shares": float(r["shares"])}
            ev = r.get("event_market")
            if isinstance(ev, dict) and ev.get("source") and ev.get("id"):
                h["event_market"] = {"source": str(ev["source"]), "id": str(ev["id"]), "query": str(ev.get("query") or "")}
            out.append(h)
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return []


def hedge_status(ticker: str, proposals: list[Proposal], bridges: dict | None = None) -> HedgeStatus:
    mine = [p for p in proposals if p.ticker == ticker]
    if not mine:
        return HedgeStatus(status="none")
    p = max(mine, key=lambda x: x.created_at)
    if p.status == "approved" and p.bridge_started_at is not None:
        b = (bridges or {}).get(p.id)
        return HedgeStatus(status="bridging", proposal_id=p.id, bridge_id=getattr(b, "id", None))
    return HedgeStatus(status=p.status, proposal_id=p.id)


def find_exposure(ticker: str, shares: float, spot: float | None, markets: list[Market]) -> Exposure | None:
    for m in markets[:TOP_MARKETS]:
        try:
            res = lookup_precomputed(MapRequest(question=m.question, source=m.source, market_id=m.id))
        except Exception:
            continue
        if res.get("source") != SOURCE_PRECOMPUTED:
            continue
        item = next((i for i in res["items"] if isinstance(i, dict) and str(i.get("ticker", "")).upper() == ticker), None)
        if item is None:
            continue
        try:
            impact = float(item.get("impact_pct"))
        except (TypeError, ValueError):
            continue
        rem = remaining_exposure(shares, spot, impact, m.yes_price, item.get("direction"))
        if rem is None:
            continue
        return Exposure(market=m, direction=str(item.get("direction", "")), impact_pct=impact,
                        rationale=item.get("rationale"), remaining_usd=rem, label=res["label"],
                        match_type=res["match_type"], matched_question=res["matched_question"], score=res["score"])
    return None


async def _pinned_market(request: Request, ev: dict) -> tuple[Market | None, bool]:
    want = (ev["source"], ev["id"])
    q = ev.get("query") or ""
    if q:
        try:
            http = eq._http(request)
            res, st = await eq._cache(request, "search", 60).get_or_set(q.lower(), lambda: search_all(http, q))
            m = next((m for m in res if (m.source, m.id) == want), None)
            if m is not None:
                return m, bool(st)
        except Exception:
            pass
    m = next((m for m in offline_search(q) if (m.source, m.id) == want), None) if q else None
    return m, m is not None


async def _holding(request: Request, h: dict, proposals: list[Proposal], bridges: dict) -> tuple[Holding, bool]:
    ticker, shares = h["ticker"], h["shares"]
    name = eq.NAMES.get(ticker)
    notes: list[str] = []
    stale = False
    spot, filings = None, []
    client = eq.get_client(request)
    if client is None:
        notes.append("Massive key not configured")
    else:
        try:
            snap, _ = await eq.get_snapshot(request, client, ticker)
            spot = snap["spot"] if snap and math.isfinite(snap["spot"]) else None
            if snap is None:
                notes.append("no listed options")
        except Exception:
            notes.append("options data unavailable")
        try:
            book = await chain.bounded(eq._book_sync)
            filings = await chain.bounded(eq.fetch_filings, client, ticker, eq.today_of(request), book)
        except Exception:
            notes.append("filings unavailable")
    markets: list[Market] = []
    try:
        http = eq._http(request)
        q = name or ticker
        markets, st = await eq._cache(request, "search", 60).get_or_set(q.lower(), lambda: search_all(http, q))
        markets = list(markets)
        stale = bool(st)
    except Exception:
        notes.append("prediction-market search unavailable")
    markets.sort(key=lambda m: m.volume_24h, reverse=True)
    if h.get("event_market"):
        pinned, st = await _pinned_market(request, h["event_market"])
        if pinned is not None:
            markets = [pinned] + [m for m in markets if (m.source, m.id) != (pinned.source, pinned.id)]
            stale = stale or st
    exposure = find_exposure(ticker, shares, spot, markets)
    return Holding(ticker=ticker, name=name, shares=shares, spot=spot, value=spot * shares if spot is not None and math.isfinite(spot) else None,
                   markets=markets[:TOP_MARKETS], filings=filings[:3], exposure=exposure,
                   hedge=hedge_status(ticker, proposals, bridges), notes=notes), stale


BROKER_TIMEOUT_S = 10.0


async def broker_book(request: Request, tickers: list[str]) -> tuple[BrokerBook, dict[str, dict]]:
    from .broker import get_broker
    from .broker.routes import _short

    try:
        b = get_broker(request.app)
    except Exception as e:
        return BrokerBook(label="unavailable", available=False, error=type(e).__name__), {}
    label = "Webull paper account" if b.name == "webull-paper" else "Simulated account"
    book = BrokerBook(broker=b.name, label=label, options_supported=getattr(b, "options_supported", None))
    try:
        acct = await asyncio.wait_for(b.account(), BROKER_TIMEOUT_S)
        book.account = acct.model_dump(exclude_none=True)
        book.note = acct.note
    except Exception as e:
        book.available, book.error = False, getattr(e, "message", None) or type(e).__name__
    try:
        book.positions = [p.model_dump() for p in await asyncio.wait_for(b.positions(), BROKER_TIMEOUT_S)]
    except Exception as e:
        book.available = False
        book.error = book.error or getattr(e, "message", None) or type(e).__name__
    try:
        shorts = await asyncio.wait_for(_short(b, tickers), BROKER_TIMEOUT_S) if tickers else {}
    except Exception:
        shorts = {}
    return book, shorts


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(request: Request) -> PortfolioOut:
    proposals = request.app.state.store.list()
    rows = load_holdings()
    bridges = getattr(request.app.state, "bridges", {})
    book_task = asyncio.ensure_future(broker_book(request, [h["ticker"] for h in rows]))
    results = await asyncio.gather(*(_holding(request, h, proposals, bridges) for h in rows), return_exceptions=True)
    book, shorts = await book_task
    holdings: list[Holding] = []
    stale = False
    for h, r in zip(rows, results):
        if isinstance(r, Exception):
            holdings.append(Holding(ticker=h["ticker"], name=eq.NAMES.get(h["ticker"]), shares=h["shares"], markets=[],
                                    filings=[], hedge=hedge_status(h["ticker"], proposals, bridges),
                                    notes=["holding data unavailable"]))
        else:
            holdings.append(r[0])
            stale = stale or r[1]
    held = {}
    for p in book.positions:
        if p.get("asset") == "equity":
            held[p["symbol"]] = held.get(p["symbol"], 0.0) + float(p.get("qty") or 0.0)
    for x in holdings:
        x.broker_qty = held.get(x.ticker, 0.0) if book.available else None
        sh = shorts.get(x.ticker) or {}
        x.can_short, x.short_reason = sh.get("can_short"), sh.get("reason")
    vals = [x.value for x in holdings if x.value is not None]
    exps = [x.exposure.remaining_usd for x in holdings if x.exposure]
    fuzzy = any(x.exposure and x.exposure.match_type == "fuzzy" for x in holdings)
    return PortfolioOut(holdings=holdings, broker_account=book, total_value=sum(vals) if vals else None,
                        total_exposure=sum(exps) if exps else None, total_includes_fuzzy=fuzzy, stale=stale)
