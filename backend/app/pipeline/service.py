"""POST /pipeline/fit orchestration: classify -> shortlist -> build ticks -> tune -> explain. Never raises."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from .classify import classify
from .engine_adapter import EngineAdapter
from .explain import explain
from .llm import LLMProvider, RulesProvider, rules_classify
from .shortlist import shortlist, unmet_requirements
from .options_join import join_options
from .ticks import (TickSet, _universe_entry, available_requirements, build_ticks, kalshi_series, orient_to_adverse,
                    resolve_polymarket)
from .tune import tune

Direction = Literal["down_on_yes", "up_on_yes"]
TICKS_BUDGET_S = 15.0
OPTIONS_BUDGET_S = 12.0


def _has_options(ts: TickSet) -> bool:
    import numpy as np
    v = (ts.ticks or {}).get("opt_implied_prob")
    return v is not None and bool(np.isfinite(v).any())


class MarketRef(BaseModel):
    source: Literal["polymarket", "kalshi"]
    id: str = Field(min_length=1, max_length=120)
    token_id: str | None = Field(default=None, max_length=120)


class FitRequest(BaseModel):
    market: MarketRef | None = None
    question: str | None = Field(default=None, max_length=1000)
    ticker: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,11}$")
    direction: Direction = "down_on_yes"
    shares_held: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Optional (request only; the response keys are unchanged): fit this division instead of the default choice
    # (hedge when shares are held, else opportunity) -- the Build screen asks for both to offer Hedge vs Opportunity.
    division: Literal["hedge", "opportunity"] | None = None
    # The market's resolution date (ISO), used to read a threshold question without a date; else the universe's.
    end_date: str | None = Field(default=None, max_length=40)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _need_market_or_question(self) -> "FitRequest":
        if self.market is None and not (self.question or "").strip():
            raise ValueError("give a market or a question")
        return self


class Alternative(BaseModel):
    family: str
    preset_index: int
    params: dict[str, float]
    score: float | None = None
    stats: dict[str, float] | None = None


class FitResponse(BaseModel):
    event_class: str
    division: Literal["hedge", "opportunity"] | None
    family: str | None
    preset_index: int | None
    params: dict[str, float]
    score: float | None
    alternatives: list[Alternative]
    rationale: str
    llm: Literal["gemini", "rules"]
    ticks_source: Literal["live_history", "replay", "none"]
    n_ticks: int
    # Exactly the spec §4 keys. An unscored (rules) pick is visible as score == null; `scored` stays internal.


@dataclass
class Deps:
    adapter: EngineAdapter
    provider: LLMProvider = field(default_factory=RulesProvider)
    http: httpx.AsyncClient | None = None
    massive: Callable[[], Any] | None = None
    offline: bool = False


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


async def _question_for(req: FitRequest, deps: Deps) -> tuple[str, str | None]:
    """(question, token_id). Uses the request, then the bundled universe, then Gamma (Polymarket) or the Kalshi API."""
    q = (req.question or "").strip()
    token = req.market.token_id if req.market else None
    if q or req.market is None:
        return q, token
    entry = _universe_entry(req.market.source, req.market.id)
    if entry.get("question"):
        return entry["question"], token or entry.get("token_id")
    if req.market.source == "polymarket" and deps.http is not None and not deps.offline:
        try:
            tok, question = await resolve_polymarket(deps.http, req.market.id)
            return (question or ""), token or tok
        except Exception:
            pass
    if req.market.source == "kalshi" and deps.http is not None and not deps.offline:
        try:
            _, question = await kalshi_series(deps.http, req.market.id)
            return (question or ""), token
        except Exception:
            pass
    return "", token


def choose_division(lists: dict[str, list[dict]], shares_held: float | None, asked: str | None = None) -> str | None:
    """Hedge when the user holds shares (hedge variance is defined only then); otherwise opportunity.
    Falls back to the other division when the preferred one has no family for this class. An explicitly asked
    division is honoured without fallback (None when it has no eligible family)."""
    if asked is not None:
        return asked if lists.get(asked) else None
    preferred = "hedge" if (shares_held or 0) > 0 else "opportunity"
    other = "opportunity" if preferred == "hedge" else "hedge"
    if lists.get(preferred):
        return preferred
    return other if lists.get(other) else None


async def run_fit(req: FitRequest, deps: Deps) -> dict:
    question, token = await _question_for(req, deps)
    manifest, _ = deps.adapter.library()
    market = None
    if req.market:
        market = {"source": req.market.source, "id": req.market.id, "token_id": token}

    end_date = req.end_date or (_universe_entry(req.market.source, req.market.id).get("end_date")
                                if req.market else None)

    async def ticks() -> TickSet:
        try:  # bound the whole network chain (Gamma + CLOB + Massive); on overrun use recorded data only
            ts = await asyncio.wait_for(
                build_ticks(market, req.ticker, http=deps.http, massive=deps.massive, offline=deps.offline),
                TICKS_BUDGET_S)
        except asyncio.TimeoutError:
            ts = await build_ticks(market, req.ticker, http=None, massive=None, offline=True)
            ts.notes.append(f"live history took over {TICKS_BUDGET_S:g} s")
            return ts
        if ts.ticks is not None and not _has_options(ts):  # threshold questions: options-implied history
            try:
                joined, info = await asyncio.wait_for(
                    join_options(ts.ticks, question or ts.question, end_date, massive=deps.massive,
                                 offline=deps.offline), OPTIONS_BUDGET_S)
                ts.ticks = joined
                ts.notes.extend(info.get("notes") or [])
            except asyncio.TimeoutError:
                ts.notes.append(f"options history took over {OPTIONS_BUDGET_S:g} s")
        return ts

    (event_class, llm), ts = await asyncio.gather(
        classify(question, deps.provider, manifest.get("event_classes"), req.ticker), ticks())

    question_unresolved = req.market is not None and not question
    # Families whose data needs this market cannot meet (second venue, listed options) are left out entirely.
    available = available_requirements(ts)
    lists = {d: [f for f in fams if not unmet_requirements(f, available)]
             for d, fams in shortlist(manifest, event_class, available).items()}
    division = choose_division(lists, req.shares_held, req.division)
    families = lists.get(division, []) if division else []
    # §3.3 Position fields only. The direction reaches the engine through the ticks: for a hedge, YES is re-oriented
    # to the outcome that hurts the held equity (see ticks.orient_to_adverse), so every family sees one convention.
    position = {"shares_held": float(req.shares_held or 0.0), "equity": 0.0, "pred_yes": 0.0, "pred_no": 0.0,
                "option": 0.0}
    if division == "hedge" and ts.ticks is not None:
        ts = TickSet(orient_to_adverse(ts.ticks, req.direction), ts.source, ts.n, ts.has_underlying, ts.quote_model,
                     ts.notes, ts.token_id, ts.question)
    t = tune(deps.adapter, families, division or "hedge", position, ts)

    fam = next((f for f in families if f["id"] == t["family"]), None)
    result = {
        "event_class": event_class, "division": division if t["family"] else None, "family": t["family"],
        "preset_index": t["preset_index"], "params": t["params"], "score": t["score"] if t["scored"] else None,
        "alternatives": t["alternatives"], "llm": llm, "ticks_source": ts.source if ts.ticks is not None else "none",
        "n_ticks": ts.n, "scored": bool(t["scored"]),
        # facts for the rationale only (not part of the response):
        "ticker": req.ticker, "direction": req.direction, "shares_held": req.shares_held,
        "n_shortlisted": len(families), "unscored_reason": t.get("unscored_reason"),
        "family_idea": (fam or {}).get("idea"), "proxies": (fam or {}).get("proxies"),
        "question_unresolved": question_unresolved or None,
        "reason": None if t["family"] else _no_fit_reason(event_class, question_unresolved, t),
    }
    result["rationale"], _ = await explain(result, deps.provider)
    return result


def _no_fit_reason(event_class: str, question_unresolved: bool, t: dict) -> str | None:
    if question_unresolved:
        return "the market's question could not be resolved"
    if event_class == "unsupported":
        return "the question is outside every supported event class"
    return t.get("unscored_reason")


def degraded(req: FitRequest | None, err: Exception) -> dict:
    """Last-resort answer when something unexpected broke: honest, rules-only, never a 500."""
    q = (req.question or "") if req else ""
    return {"event_class": rules_classify(q) if q else "unsupported", "division": None, "family": None,
            "preset_index": None, "params": {}, "score": None, "alternatives": [], "llm": "rules",
            "ticks_source": "none", "n_ticks": 0,
            "rationale": f"The fit pipeline hit an internal error ({type(err).__name__}), so no algo was fitted. "
                         "Nothing here is a recommendation; retry in a moment."}


async def fit(req: FitRequest, deps: Deps) -> FitResponse:
    try:
        r = await run_fit(req, deps)
    except Exception as e:  # never a 500
        r = degraded(req, e)
    try:
        return FitResponse(**{k: r[k] for k in FitResponse.model_fields})
    except Exception as e:
        r = degraded(req, e)
        return FitResponse(**{k: r[k] for k in FitResponse.model_fields})
