"""Any-stock lookup: 8-K filings with verdict badges, live implied move, related prediction markets."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import httpx
import pandas as pd
from fastapi import APIRouter, Request
from polybridge_research.schema import normalize_ticker
from polybridge_research.parity import implied_move
from pydantic import BaseModel

from . import chain
from .cache import TTLCache
from .markets import TIMEOUT, Market, search_all
from .verdicts import Evidence, TagVerdict, load_verdicts, results_dir

NAMES: dict[str, str] = json.loads((Path(__file__).parent / "data" / "names.json").read_text())
DISCLOSURES = "/stocks/filings/8-K/vX/disclosures"
FILING_DAYS = 180
SNAP_TTL = 600


class ImpliedMove(BaseModel):
    value: float
    expiry: str
    spot: float
    as_of: str


class Filing(BaseModel):
    date: str
    accession: str | None = None
    url: str | None = None
    tags: list[str]
    verdict: TagVerdict | None = None


class EquityCard(BaseModel):
    ticker: str
    name: str | None = None
    implied_move: ImpliedMove | None = None
    filings: list[Filing]
    markets: list[Market]
    notes: list[str]


def implied_card(snap: dict) -> ImpliedMove | None:
    legs = snap["legs"]
    c, p = legs["C_K"]["mark"], legs["P_K"]["mark"]
    if c is None or p is None:
        return None
    v = implied_move(c, p, snap["spot"])
    if not math.isfinite(v):
        return None
    return ImpliedMove(value=v, expiry=snap["expiry"], spot=snap["spot"], as_of=snap["as_of"])


def _row_tags(r: dict) -> list[str]:
    tags = r.get("tags")
    if isinstance(tags, list):
        return [str(t) for t in tags]
    t = r.get("tertiary_category") or r.get("tag")
    return [str(t)] if t else []


def _verdict(book, tag: str) -> TagVerdict:
    try:
        return book.for_tag(tag)
    except KeyError:  # tag absent from the atlas (never tested)
        return TagVerdict(tag=tag, family=None, kind="none", label="no_edge", evidence=Evidence(), note="not tested")


def _headline(vs: list[TagVerdict]) -> TagVerdict | None:
    """One badge per filing: an edge label beats no_edge; confirmatory beats exploratory."""
    if not vs:
        return None
    return sorted(vs, key=lambda v: (v.label == "no_edge", v.kind != "confirmatory"))[0]


def fetch_filings(client, ticker: str, today: pd.Timestamp, book) -> list[Filing]:
    rows = client.get_all(DISCLOSURES, {"tickers": ticker,
                                        "filing_date.gte": (today - pd.Timedelta(days=FILING_DAYS)).strftime("%Y-%m-%d"),
                                        "filing_date.lte": today.strftime("%Y-%m-%d"),
                                        "limit": 1000, "sort": "filing_date.desc"})
    want = normalize_ticker(ticker)
    groups: dict[str, dict] = {}
    for r in rows:
        tk = r.get("tickers")
        if not isinstance(tk, list) or want not in {normalize_ticker(t) for t in tk}:
            continue  # the API may ignore its filter; never show another company's filing
        acc = r.get("accession_number")
        key = acc or f"{r.get('filing_date')}-{len(groups)}"  # internal grouping key only
        g = groups.setdefault(key, {"date": str(r.get("filing_date"))[:10], "url": r.get("filing_url"), "tags": [],
                                    "acc": acc})
        for t in _row_tags(r):
            if t not in g["tags"]:
                g["tags"].append(t)
    out = [Filing(date=g["date"], accession=g["acc"], url=g["url"], tags=sorted(g["tags"]),
                  verdict=_headline([_verdict(book, t) for t in sorted(g["tags"])])) for k, g in groups.items()]
    return sorted(out, key=lambda f: f.date, reverse=True)


router = APIRouter()


def _cache(request: Request, name: str, ttl: float) -> TTLCache:
    key = f"cache_{name}"
    if not hasattr(request.app.state, key):
        setattr(request.app.state, key, TTLCache(ttl))
    return getattr(request.app.state, key)


def _http(request: Request) -> httpx.AsyncClient:
    if not hasattr(request.app.state, "http"):
        request.app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    return request.app.state.http


_BOOK: dict = {"key": None, "book": None}


def _book_sync():
    d = results_dir()
    key = (str(d), tuple(sorted((str(f), f.stat().st_mtime_ns) for f in d.rglob("*") if f.suffix in (".txt", ".csv"))))
    if _BOOK["key"] != key:
        _BOOK.update(key=key, book=load_verdicts(d))
    return _BOOK["book"]


def get_client(request: Request):
    """Massive client; tests set app.state.massive (a fake) or app.state.massive = None for 'no key'."""
    if not hasattr(request.app.state, "massive"):
        request.app.state.massive = chain.make_client()
    return request.app.state.massive


def today_of(request: Request) -> pd.Timestamp:
    return pd.Timestamp(getattr(request.app.state, "today", None) or pd.Timestamp.today().normalize())


async def get_snapshot(request: Request, client, ticker: str) -> tuple[dict | None, str | None]:
    today = today_of(request)
    session = str(chain.calendar().before(today).date())
    value, _ = await _cache(request, "snap", SNAP_TTL).get_or_set(
        (ticker, session), lambda: asyncio.to_thread(chain.snapshot, client, ticker, today))
    return value


@router.get("/equities/{ticker}", response_model=EquityCard)
async def equity(ticker: str, request: Request) -> EquityCard:
    ticker = ticker.strip().upper()
    name = NAMES.get(ticker)
    notes: list[str] = []
    client = get_client(request)
    today = today_of(request)
    move, filings = None, []
    if client is None:
        notes.append("Massive key not configured")
    else:
        try:
            snap, note = await get_snapshot(request, client, ticker)
            if snap is None:
                notes.append(note or "no listed options")
            else:
                move = implied_card(snap)
                notes.extend(snap.get("notes", []))
                if move is None:
                    notes.append("ATM pair did not trade on the last session")
        except Exception:
            notes.append("options data unavailable")
        try:
            book = await asyncio.to_thread(_book_sync)
            filings = await asyncio.to_thread(fetch_filings, client, ticker, today, book)
            if not filings:
                notes.append("no 8-K filings in the last 180 days")
        except Exception:
            notes.append("filings unavailable")
    markets: list[Market] = []
    try:
        http = _http(request)
        seen: set[tuple[str, str]] = set()
        for q in dict.fromkeys(x for x in (name, ticker) if x):
            res, _ = await _cache(request, "search", 60).get_or_set(q.lower(), lambda q=q: search_all(http, q))
            for m in res:
                if (m.source, m.id) not in seen:
                    seen.add((m.source, m.id))
                    markets.append(m)
        markets.sort(key=lambda m: m.volume_24h, reverse=True)
    except Exception:
        notes.append("prediction-market search unavailable")
    return EquityCard(ticker=ticker, name=name, implied_move=move, filings=filings, markets=markets, notes=notes)
