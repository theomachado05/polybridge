"""Live Polymarket books for the PM half-spread assumption (METHOD.md section 6)."""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone

import requests

from .config import CLOB, GAMMA, PARAMS


def _tokens(m: dict) -> list[str]:
    t = m.get("clobTokenIds")
    if isinstance(t, str):
        try:
            t = json.loads(t)
        except ValueError:
            return []
    return list(t or [])


def pick_markets(markets: list[dict], n: int = PARAMS.n_books) -> list[dict]:
    """First n markets (already ordered by lifetime volume) that have an order book and token ids."""
    out = []
    for m in markets:
        if m.get("enableOrderBook") and _tokens(m) and m.get("active") and not m.get("closed"):
            out.append(m)
        if len(out) >= n:
            break
    return out


def half_spread_pp(book: dict, lo: float = PARAMS.mid_lo, hi: float = PARAMS.mid_hi) -> float | None:
    """(best ask - best bid)/2 in pp for a two-sided book with mid in [lo, hi]; None otherwise."""
    bids = [float(x["price"]) for x in (book or {}).get("bids", [])]
    asks = [float(x["price"]) for x in (book or {}).get("asks", [])]
    if not bids or not asks:
        return None
    bb, ba = max(bids), min(asks)
    mid = (bb + ba) / 2
    if not (lo <= mid <= hi) or ba < bb:
        return None
    return 100.0 * (ba - bb) / 2


def summarise(halves: list[float], min_books: int = PARAMS.min_books, fallback: float = PARAMS.hs_fallback_pp) -> dict:
    if len(halves) >= min_books:
        return {"hs_pp": float(statistics.median(halves)), "n": len(halves), "fallback": False}
    return {"hs_pp": fallback, "n": len(halves), "fallback": True}


def fetch_live(session: requests.Session | None = None, n: int = PARAMS.n_books) -> tuple[dict, dict]:
    """Returns (summary, raw). Network: one gamma page (up to 3 if needed) + one CLOB /book per market."""
    s = session or requests.Session()
    counts = {"gamma": 0, "clob": 0}
    markets: list[dict] = []
    for offset in (0, 200, 400):
        r = s.get(f"{GAMMA}/markets", params={"active": "true", "closed": "false", "order": "volumeNum",
                                              "ascending": "false", "limit": 200, "offset": offset}, timeout=60)
        counts["gamma"] += 1
        r.raise_for_status()
        page = r.json()
        markets.extend(page)
        if len(pick_markets(markets, n)) >= n or not page:
            break
    picked = pick_markets(markets, n)
    raw, halves = [], []
    for m in picked:
        tok = _tokens(m)[0]
        try:
            r = s.get(f"{CLOB}/book", params={"token_id": tok}, timeout=30)
            counts["clob"] += 1
            book = r.json() if r.status_code == 200 else None
        except requests.RequestException:
            book = None
        h = half_spread_pp(book) if book else None
        if h is not None:
            halves.append(h)
        raw.append({"slug": m.get("slug"), "question": m.get("question"), "volumeNum": m.get("volumeNum"),
                    "token": tok, "half_spread_pp": h,
                    "bids": (book or {}).get("bids", [])[-5:], "asks": (book or {}).get("asks", [])[-5:]})
    summ = summarise(halves)
    summ.update(fetched_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), n_markets=len(picked),
                requests=counts)
    return summ, {"summary": summ, "books": raw}
