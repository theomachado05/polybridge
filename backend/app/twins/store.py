"""Read side of the twin map: ``twin_of(source, market_id, token_id)`` -> the same question on the OTHER venue.

Only entries under ``pairs`` with ``direction == "same"`` and a complete verification record are served. A missing,
unreadable or malformed file is an empty map (never an exception): twins are an enrichment, not a requirement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "kalshi_twins.json"


@dataclass(frozen=True)
class Twin:
    """The counterpart market on the other venue. ``id`` is what the venue's book is keyed by in ``MarketRef``:
    a Kalshi ticker, or a Polymarket gamma market id (``token_id`` is its YES token)."""
    source: str                 # venue of the twin: "polymarket" | "kalshi"
    id: str
    token_id: str | None = None
    note: str = ""

    def as_market_ref(self) -> dict:
        d = {"source": self.source, "id": self.id}
        if self.token_id:
            d["token_id"] = self.token_id
        return d


_cache: dict[str, Any] = {}


def _load(path: Path) -> dict[tuple[str, str], Twin]:
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    index: dict[tuple[str, str], Twin] = {}
    try:
        doc = json.loads(path.read_text())
        pairs = doc.get("pairs") or []
    except (OSError, ValueError, AttributeError):
        pairs = []
    for e in pairs if isinstance(pairs, list) else []:
        try:
            p, k = e["polymarket"], e["kalshi"]
            pid, tok, ticker = str(p["id"]), p.get("token_id"), str(k["ticker"])
            ver = e.get("verification") or {}
            if e.get("direction") != "same" or not tok or not ver.get("note") or not ver.get("verified_at"):
                continue  # inverted, untradable on Polymarket, or without a verification record: never served
        except (KeyError, TypeError):
            continue
        note = str(ver["note"])
        as_kalshi = Twin("kalshi", ticker, None, note)
        as_poly = Twin("polymarket", pid, str(tok), note)
        for ident in (pid, str(tok)):
            index.setdefault(("polymarket", ident), as_kalshi)
        index.setdefault(("kalshi", ticker), as_poly)
    _cache[key] = (mtime, index)
    return index


def twin_of(source: str, market_id: str | None = None, token_id: str | None = None,
            path: Path | None = None) -> Twin | None:
    """The verified twin of a market, or None. Polymarket markets are found by gamma id or YES token id."""
    index = _load(path or DEFAULT_PATH)
    if not index:
        return None
    for ident in (market_id, token_id):
        if ident and (hit := index.get((source, str(ident)))):
            return hit
    return None
