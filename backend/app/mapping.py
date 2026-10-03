"""Serve the precomputed AI event -> stock mapping library (no runtime LLM calls)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

MAP_PATH = Path(__file__).parent / "data" / "ai_map.json"
LABEL = "AI estimate (precomputed)"
NO_MATCH = "no precomputed mapping; pick stocks manually"
THRESHOLD = 0.5
STOP = frozenset(
    "a an the of in on at to by for or and will be is are was do does did with from as this that it its "
    "before after than then any".split()
)
# Direction words are never stopwords; two questions carrying different ones are opposites.
DIRECTION = frozenset("cut increase hike above below yes no not".split())
MIN_JACCARD, MIN_SHARED, MARGIN = 0.5, 3, 0.15
_cache: dict | None = None
_cache_mtime: float | None = None


def _load() -> dict:
    """Cache a good library by mtime; error states are re-checked on every call."""
    global _cache, _cache_mtime
    try:
        mtime = MAP_PATH.stat().st_mtime
        if _cache is not None and _cache_mtime == mtime:
            return _cache
        data = json.loads(MAP_PATH.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return {"items": {}, "error": "malformed"}
        _cache, _cache_mtime = data, mtime
        return data
    except (OSError, ValueError):
        return {"items": {}, "error": "missing"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP}


def _score(a: set[str], b: set[str]) -> tuple[float, int]:
    """(Jaccard, shared count), or (0, 0) if the pair is disqualified."""
    shared = a & b
    if not shared:
        return 0.0, 0
    da, db = a & DIRECTION, b & DIRECTION
    if da and db and da != db:
        return 0.0, 0
    na, nb = {t for t in a if t.isdigit()}, {t for t in b if t.isdigit()}
    if na and nb and not (na & nb):
        return 0.0, 0
    j = len(shared) / len(a | b)
    return (j, len(shared)) if j >= MIN_JACCARD and len(shared) >= MIN_SHARED else (0.0, 0)


class MapRequest(BaseModel):
    question: str | None = None
    source: str | None = None
    market_id: str | None = None


router = APIRouter()


@router.post("/map")
def map_event(req: MapRequest) -> dict:
    has_id = bool(req.source and req.market_id)
    if not (req.question and req.question.strip()) and not has_id:
        raise HTTPException(422, "provide question or source+market_id")
    lib = _load()
    items: dict = {k: v for k, v in lib["items"].items() if isinstance(v, dict)}
    base = {"label": LABEL, "generated_at": lib.get("generated_at")}

    def hit(entry: dict, match_type: str, score: float) -> dict:
        return {**base, "source": "precomputed", "match_type": match_type, "score": score,
                "items": _items(entry), "matched_question": entry.get("question"), "candidates": [], "note": None}

    def miss(note: str, cands: list | None = None) -> dict:
        if "error" in lib:
            note += f" (mapping library {lib['error']})"
        return {**base, "source": "none", "match_type": None, "score": None, "items": [],
                "matched_question": None, "candidates": cands or [], "note": note}

    if has_id and (e := items.get(f"{req.source}:{req.market_id}")):
        return hit(e, "exact", 1.0)
    if not (req.question and req.question.strip()):
        return miss(NO_MATCH)
    qt = _tokens(req.question)
    scored = []
    for key, e in items.items():
        sc, n = _score(qt, _tokens(str(e.get("question", ""))))
        if sc:
            scored.append((sc, n, key, e))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    if not scored:
        return miss(NO_MATCH)
    cands = [{"source_key": k, "matched_question": e.get("question"), "score": round(sc, 3),
              "items": _items(e)} for sc, _, k, e in scored[:3]]
    if len(scored) == 1 or scored[0][0] - scored[1][0] >= MARGIN:
        return hit(scored[0][3], "fuzzy", round(scored[0][0], 3))
    return miss("several close markets — pick one", cands)


def _items(entry: dict) -> list:
    m = entry.get("mappings")
    return m if isinstance(m, list) else []
