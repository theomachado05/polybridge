"""POST /map: which stocks a prediction-market event moves.

Three answers, always labelled by ``source``:

- ``"ai_precomputed"``: the bundled library ``data/ai_map.json`` (generated ahead of time, see its ``generator``),
  matched exactly by market id or by a confident fuzzy match on the question.
- ``"ai_live:gemini:<model>"``: the question is not in the library and Gemini is available. Gemini picks tickers
  ONLY from the candidate universe (``ticker_universe``) under a strict JSON schema; every row is validated
  (``validate_mappings``: ticker in the universe, direction known, move bounded, one sentence) before it is served,
  and the answer is cached by question hash.
- ``"none"``: nothing matched and no live answer was possible; ``note`` says why (no key, Gemini failed, ...).
  A fake AI answer is never served.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

DATA = Path(__file__).parent / "data"
MAP_PATH = DATA / "ai_map.json"
UNIVERSE_PATH = DATA / "market_universe.json"
NAMES_PATH = DATA / "names.json"
PORTFOLIO_PATH = DATA / "portfolio.json"
MANIFEST_PATH = DATA / "manifest_fallback.json"
LABEL = "AI estimate (precomputed)"
NO_MATCH = "no precomputed mapping; pick stocks manually"
SOURCE_PRECOMPUTED = "ai_precomputed"
THRESHOLD = 0.5
STOP = frozenset(
    "a an the of in on at to by for or and will be is are was do does did with from as this that it its "
    "before after than then any".split()
)
# Direction words are never stopwords; two questions carrying different ones are opposites.
DIRECTION = frozenset("cut increase hike above below yes no not".split())
MIN_JACCARD, MIN_SHARED, MARGIN = 0.5, 3, 0.15
# Live mapping bounds.
LIVE_MAX_ITEMS = 6
LIVE_MAX_MOVE_PCT = 20.0
LIVE_BUDGET_S = 20.0          # covers one Gemini call plus a one-off model fallback
LIVE_CACHE_TTL_S = 6 * 3600.0
LIVE_CACHE_MAX = 512
DIRECTIONS = ("down_on_yes", "up_on_yes")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_cache: dict | None = None
_cache_mtime: float | None = None
_universe: list[dict] | None = None


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


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def ticker_universe() -> list[dict]:
    """The candidate tickers live mapping may choose from: [{ticker, name}], sorted.

    Union of the named stock list (names.json), the demo portfolio's holdings, the library families' proxy ETFs and
    every ticker the precomputed map already uses for the market universe's questions. Built once per process."""
    global _universe
    if _universe is not None:
        return _universe
    names = {str(k).upper(): str(v) for k, v in (_read_json(NAMES_PATH, {}) or {}).items()}
    out: dict[str, str | None] = dict(names)
    for h in (_read_json(PORTFOLIO_PATH, {}) or {}).get("holdings") or []:
        if isinstance(h, dict) and h.get("ticker"):
            out.setdefault(str(h["ticker"]).upper(), None)
    for f in (_read_json(MANIFEST_PATH, {}) or {}).get("families") or []:
        for t in (f or {}).get("proxies") or []:
            out.setdefault(str(t).upper(), None)
    for e in ((_read_json(MAP_PATH, {}) or {}).get("items") or {}).values():
        if not isinstance(e, dict):
            continue
        for m in e.get("mappings") or []:
            if isinstance(m, dict) and m.get("ticker"):
                out.setdefault(str(m["ticker"]).upper(), None)
    _universe = [{"ticker": t, "name": n} for t, n in sorted(out.items()) if TICKER_RE.match(t)]
    return _universe


def _universe_question(source: str | None, market_id: str | None) -> str | None:
    for m in (_read_json(UNIVERSE_PATH, {}) or {}).get("markets") or []:
        if isinstance(m, dict) and m.get("source") == source and str(m.get("id")) == str(market_id):
            return m.get("question")
    return None


def _first_sentence(text: str, limit: int = 240) -> str:
    t = " ".join(str(text or "").split())
    m = re.match(r"^(.+?[.!?])(\s|$)", t)
    t = m.group(1) if m else t
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def validate_mappings(rows: object, universe: set[str], max_items: int = LIVE_MAX_ITEMS) -> tuple[list[dict], list[str]]:
    """(valid items, reasons for each dropped row). Pure: the only gate between Gemini's output and the response.

    A row is kept only when its ticker is in ``universe``, its direction is down_on_yes / up_on_yes, its
    ``impact_pct`` is a finite number in (0, LIVE_MAX_MOVE_PCT] and its rationale is non-empty. Duplicate tickers keep
    the first row; at most ``max_items`` rows are kept."""
    items: list[dict] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            dropped.append("not an object")
            continue
        t = str(row.get("ticker") or "").strip().upper()
        if t not in universe:
            dropped.append(f"{t or '?'}: not in the candidate universe")
            continue
        if t in seen:
            dropped.append(f"{t}: duplicate")
            continue
        d = row.get("direction")
        if d not in DIRECTIONS:
            dropped.append(f"{t}: bad direction")
            continue
        raw = row.get("impact_pct")
        try:
            pct = float("nan") if isinstance(raw, bool) else float(raw)
        except (TypeError, ValueError):
            pct = float("nan")
        if not math.isfinite(pct) or not 0 < pct <= LIVE_MAX_MOVE_PCT:
            dropped.append(f"{t}: move outside (0, {LIVE_MAX_MOVE_PCT:g}] %")
            continue
        why = _first_sentence(row.get("rationale") or "")
        if not why:
            dropped.append(f"{t}: no rationale")
            continue
        if len(items) >= max_items:
            dropped.append(f"{t}: over {max_items} items")
            continue
        seen.add(t)
        items.append({"ticker": t, "direction": d, "impact_pct": round(pct, 2), "rationale": why})
    return items, dropped


def question_hash(question: str) -> str:
    norm = " ".join(re.findall(r"[a-z0-9$%.]+", (question or "").lower()))
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


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


def _provider(request: Request):
    """Tests set app.state.pipeline_provider; otherwise Gemini when GEMINI_API_KEY is set, else rules (no live map)."""
    from .pipeline.llm import default_provider
    p = getattr(request.app.state, "pipeline_provider", None)
    if p is not None:
        return p
    from .markets import _http
    return default_provider(_http(request))


def _live_cache(request: Request):
    from .pipeline.router import FitCache
    c = getattr(request.app.state, "map_live_cache", None)
    if not isinstance(c, FitCache):
        c = request.app.state.map_live_cache = FitCache(ttl_s=LIVE_CACHE_TTL_S, max_entries=LIVE_CACHE_MAX)
    return c


def _precomputed_ai(lib: dict) -> dict:
    return {"provider": "precomputed", "model": None, "live": False, "cached": False,
            "generator": lib.get("generator"), "fell_back_reason": None}


def _miss(lib: dict, note: str, cands: list | None = None, ai: dict | None = None) -> dict:
    if "error" in lib:
        note += f" (mapping library {lib['error']})"
    return {"label": LABEL, "generated_at": lib.get("generated_at"), "source": "none", "match_type": None,
            "score": None, "items": [], "matched_question": None, "candidates": cands or [], "note": note,
            "ai": ai or {**_precomputed_ai(lib), "provider": "none"}}


def _resolve(req: MapRequest) -> tuple[dict, dict | None]:
    """(precomputed answer, live-lookup arguments or None). The live arguments are set when the question is not in
    the precomputed library (no exact id, no confident fuzzy match)."""
    lib = _load()
    items: dict = {k: v for k, v in lib["items"].items() if isinstance(v, dict)}

    def hit(entry: dict, match_type: str, score: float) -> dict:
        return {"label": LABEL, "generated_at": lib.get("generated_at"), "source": SOURCE_PRECOMPUTED,
                "match_type": match_type, "score": score, "items": _items(entry),
                "matched_question": entry.get("question"), "candidates": [], "note": None,
                "ai": _precomputed_ai(lib)}

    if req.source and req.market_id and (e := items.get(f"{req.source}:{req.market_id}")):
        return hit(e, "exact", 1.0), None
    question = (req.question or "").strip() or (_universe_question(req.source, req.market_id) or "").strip()
    if not question:
        return _miss(lib, NO_MATCH), None
    qt = _tokens(question)
    scored = []
    for key, e in items.items():
        sc, n = _score(qt, _tokens(str(e.get("question", ""))))
        if sc:
            scored.append((sc, n, key, e))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    cands = [{"source_key": k, "matched_question": e.get("question"), "score": round(sc, 3),
              "items": _items(e)} for sc, _, k, e in scored[:3]]
    if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= MARGIN):
        return hit(scored[0][3], "fuzzy", round(scored[0][0], 3)), None
    note = "several close markets — pick one" if scored else NO_MATCH
    return _miss(lib, note, cands), {"question": question, "cands": cands, "fallback_note": note, "lib": lib}


def lookup_precomputed(req: MapRequest) -> dict:
    """The precomputed library only (no network, no LLM): what the portfolio's exposure view uses."""
    return _resolve(req)[0]


@router.post("/map")
async def map_event(req: MapRequest, request: Request) -> dict:
    if not (req.question and req.question.strip()) and not (req.source and req.market_id):
        raise HTTPException(422, "provide question or source+market_id")
    answer, live = _resolve(req)
    if live is None:
        return answer
    return await _live(request, **live)


async def _live(request: Request, question: str, cands: list, fallback_note: str, lib: dict) -> dict:
    """Not in the precomputed library: ask Gemini (validated, cached), or say plainly why there is no AI answer."""
    from .pipeline.llm import NO_KEY_REASON, LLMError, RulesProvider, rules_info

    def miss(note: str, c: list, ai: dict) -> dict:
        return _miss(lib, note, c, ai)

    err = None
    try:
        provider = _provider(request)
    except Exception as e:  # never a 500
        provider, err = RulesProvider(), f"provider error: {type(e).__name__}"
    if isinstance(provider, RulesProvider) or not hasattr(provider, "map_tickers"):
        reason = err or NO_KEY_REASON
        return miss(f"{fallback_note}; live AI mapping unavailable ({reason})", cands, rules_info(reason))
    qh = question_hash(question)
    cache = _live_cache(request)
    if (cached := cache.get(qh)) is not None:
        return {**cached, "candidates": cands, "ai": {**cached["ai"], "cached": True}}
    universe = ticker_universe()
    allowed = {u["ticker"] for u in universe}
    try:
        rows = await asyncio.wait_for(provider.map_tickers(question, universe, LIVE_MAX_ITEMS), LIVE_BUDGET_S)
    except asyncio.TimeoutError:
        reason = f"Gemini took over {LIVE_BUDGET_S:g} s"
        return miss(f"{fallback_note}; live AI mapping failed ({reason})", cands, rules_info(reason))
    except LLMError as e:
        return miss(f"{fallback_note}; live AI mapping failed ({e})", cands, rules_info(str(e)))
    except Exception as e:
        reason = f"provider error: {type(e).__name__}"
        return miss(f"{fallback_note}; live AI mapping failed ({reason})", cands, rules_info(reason))
    valid, dropped = validate_mappings(rows, allowed)
    n_rows = len(rows) if isinstance(rows, list) else 0
    if n_rows and not valid:  # Gemini answered, but nothing survived validation: no AI answer, say so
        reason = f"all {n_rows} rows failed validation: " + "; ".join(dropped[:3])
        return miss(f"{fallback_note}; live AI mapping rejected ({reason})", cands,
                    {**rules_info(reason), "model": getattr(provider, "model", None)})
    model = getattr(provider, "model", None) or "unknown"
    note = None
    if not valid:
        note = "Gemini found no stock in the candidate universe with a clear link to this question."
    elif dropped:
        note = f"{len(dropped)} of {n_rows} rows dropped by validation: " + "; ".join(dropped[:3])
    out = {"label": f"AI estimate (live, Gemini {model})",
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source": f"ai_live:gemini:{model}", "match_type": "live", "score": None, "items": valid,
           "matched_question": question, "candidates": cands, "note": note, "question_hash": qh,
           "universe_size": len(universe),
           "ai": {**provider.info(True), "cached": False}}
    cache.put(qh, out)
    return out


def _items(entry: dict) -> list:
    m = entry.get("mappings")
    return m if isinstance(m, list) else []
