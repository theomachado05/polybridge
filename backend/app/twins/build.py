from __future__ import annotations

from collections import Counter
from typing import Callable

import httpx

from .claims import from_kalshi, from_polymarket
from .matcher import Pair, match_all, utcnow_iso
from .sources import fetch_kalshi, fetch_polymarket, universe_ids

SCHEMA = 1
MAX_AMBIGUOUS = 150


def _poly_ref(c) -> dict:
    r = c.ref
    return {"id": r["id"], "token_id": r.get("token_id"), "question": r["question"], "end_date": r.get("end_date"),
            "deadline_et": c.deadline.isoformat() if c.deadline else None, "slug": r.get("slug"),
            "event_slug": r.get("event_slug")}


def _kalshi_ref(c) -> dict:
    r = c.ref
    return {"ticker": r["ticker"], "event_ticker": r.get("event_ticker"), "question": r["question"],
            "close_time": r.get("close_time"), "deadline_et": c.deadline.isoformat() if c.deadline else None}


def _entry(x: Pair, verified_at: str) -> dict:
    v = x.verdict
    return {"polymarket": _poly_ref(x.poly), "kalshi": _kalshi_ref(x.kalshi), "direction": "same",
            "score": round(v.score, 3),
            "verification": {"verified_at": verified_at, "checks": {c.name: c.as_dict() for c in v.checks},
                             "note": v.note}}


def _ambiguous(x: Pair) -> dict:
    v = x.verdict
    return {"polymarket": _poly_ref(x.poly), "kalshi": _kalshi_ref(x.kalshi), "score": round(v.score, 3),
            "reasons": v.reasons, "note": v.note, "used": False}


def build_map(poly_markets: list[dict], kalshi_markets: list[dict], verified_at: str | None = None,
              stats: dict | None = None) -> dict:
    polys = [c for c in (from_polymarket(m) for m in poly_markets) if c]
    kals = [c for c in (from_kalshi(m) for m in kalshi_markets) if c]
    pairs = match_all(polys, kals)
    when = verified_at or utcnow_iso()
    verified = sorted((x for x in pairs if x.verdict.status == "verified"),
                      key=lambda x: (x.poly.id, x.kalshi.id))
    amb = sorted((x for x in pairs if x.verdict.status == "ambiguous"), key=lambda x: -x.verdict.score)
    reasons = Counter(r for x in amb for r in x.verdict.reasons)
    return {
        "schema": SCHEMA, "generated_at": when,
        "about": ("Verified Polymarket<->Kalshi twins: the same question on both venues (same event, threshold, "
                  "direction, deadline within 1 day, compatible resolution source). `direction` is always 'same': "
                  "inverted pairs are refused. Only `pairs` is used by the backend; `ambiguous` is for humans."),
        "stats": {"polymarket_markets": len(polys), "kalshi_markets": len(kals), "verified": len(verified),
                  "ambiguous": len(amb), "ambiguous_reasons": dict(reasons), **(stats or {})},
        "pairs": [_entry(x, when) for x in verified],
        "ambiguous": [_ambiguous(x) for x in amb[:MAX_AMBIGUOUS]],
    }


async def run(http: httpx.AsyncClient, *, top_n: int = 2000, log: Callable[[str], None] = print,
              verified_at: str | None = None) -> dict:
    poly = await fetch_polymarket(http, universe_ids(), top_n=top_n, log=log)
    kal = await fetch_kalshi(http, log=log)
    if not poly or not kal:
        raise RuntimeError(f"a venue returned nothing (polymarket={len(poly)}, kalshi={len(kal)}); "
                           "refusing to overwrite the map")
    return build_map(poly, kal, verified_at=verified_at)
