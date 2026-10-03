"""Demo portfolio exposure map: seeded holdings joined with open markets, recent filings + verdicts,
remaining event exposure (from the precomputed AI mapping) and hedge status. Never 500s on a failing source."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from . import equities as eq
from .mapping import MapRequest, map_event
from .markets import Market, search_all
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
    status: str  # none | proposed | approved | bridging | rejected
    proposal_id: str | None = None
    bridge_id: str | None = None


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


class PortfolioOut(BaseModel):
    holdings: list[Holding]
    total_value: float | None = None
    total_exposure: float | None = None
    stale: bool = False


def remaining_exposure(shares: float, spot: float | None, impact_pct: float | None, p: float | None) -> float | None:
    """N x spot x impact_pct/100 x (1 - p); None when an input is missing or not finite."""
    vals = (shares, spot, impact_pct, p)
    if any(v is None or not math.isfinite(v) for v in vals) or shares <= 0 or spot <= 0:
        return None
    return shares * spot * abs(impact_pct) / 100 * (1 - min(max(p, 0.0), 1.0))


def load_holdings() -> list[dict]:
    try:
        rows = json.loads(PORTFOLIO_PATH.read_text()).get("holdings", [])
        return [{"ticker": str(r["ticker"]).upper(), "shares": float(r["shares"])} for r in rows]
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
            res = map_event(MapRequest(question=m.question, source=m.source, market_id=m.id))
        except Exception:
            continue
        if res.get("source") != "precomputed":
            continue
        item = next((i for i in res["items"] if isinstance(i, dict) and str(i.get("ticker", "")).upper() == ticker), None)
        if item is None:
            continue
        try:
            impact = float(item.get("impact_pct"))
        except (TypeError, ValueError):
            continue
        rem = remaining_exposure(shares, spot, impact, m.yes_price)
        if rem is None:
            continue
        return Exposure(market=m, direction=str(item.get("direction", "")), impact_pct=impact,
                        rationale=item.get("rationale"), remaining_usd=rem, label=res["label"],
                        match_type=res["match_type"], matched_question=res["matched_question"], score=res["score"])
    return None


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
            spot = snap["spot"] if snap else None
            if snap is None:
                notes.append("no listed options")
        except Exception:
            notes.append("options data unavailable")
        try:
            book = await asyncio.to_thread(eq._book_sync)
            filings = await asyncio.to_thread(eq.fetch_filings, client, ticker, eq.today_of(request), book)
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
    exposure = find_exposure(ticker, shares, spot, markets)
    return Holding(ticker=ticker, name=name, shares=shares, spot=spot, value=None if spot is None else spot * shares,
                   markets=markets[:TOP_MARKETS], filings=filings[:3], exposure=exposure,
                   hedge=hedge_status(ticker, proposals, bridges), notes=notes), stale


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(request: Request) -> PortfolioOut:
    proposals = request.app.state.store.list()
    rows = load_holdings()
    bridges = getattr(request.app.state, "bridges", {})
    results = await asyncio.gather(*(_holding(request, h, proposals, bridges) for h in rows), return_exceptions=True)
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
    vals = [x.value for x in holdings if x.value is not None]
    exps = [x.exposure.remaining_usd for x in holdings if x.exposure]
    return PortfolioOut(holdings=holdings, total_value=sum(vals) if vals else None,
                        total_exposure=sum(exps) if exps else None, stale=stale)
