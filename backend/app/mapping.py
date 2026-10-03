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
    "before after than then not no yes any".split()
)
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            data = json.loads(MAP_PATH.read_text())
            _cache = data if isinstance(data.get("items"), dict) else {"items": {}, "error": "malformed"}
        except (OSError, ValueError, AttributeError):
            _cache = {"items": {}, "error": "missing"}
    return _cache


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP}


def _score(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


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
    items: dict = lib["items"]

    def hit(entry: dict) -> dict:
        return {
            "source": "precomputed", "label": LABEL, "generated_at": lib.get("generated_at"),
            "items": entry.get("mappings", []), "matched_question": entry.get("question"), "note": None,
        }

    if has_id and (e := items.get(f"{req.source}:{req.market_id}")):
        return hit(e)
    best, best_score = None, 0.0
    qt = _tokens(req.question or "")
    for e in items.values():
        s = _score(qt, _tokens(e.get("question", "")))
        if s > best_score:
            best, best_score = e, s
    if best is not None and best_score >= THRESHOLD:
        return hit(best)
    note = NO_MATCH if "error" not in lib else f"{NO_MATCH} (mapping library {lib['error']})"
    return {"source": "none", "label": LABEL, "generated_at": lib.get("generated_at"),
            "items": [], "matched_question": None, "note": note}
