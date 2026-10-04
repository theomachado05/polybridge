from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import httpx
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from .classify import classify
from .engine_adapter import EngineAdapter
from .explain import explain
from .llm import NO_KEY_REASON, LLMProvider, RulesProvider, rules_classify, rules_info
from .shortlist import shortlist, unmet_requirements
from .options_join import join_options
from .ticks import (TickSet, _universe_entry, available_requirements, build_ticks, kalshi_series, orient_for_family,
                    orient_to_adverse, recording_meta, resolve_polymarket)
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
    division: Literal["hedge", "opportunity"] | None = None
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


class AIInfo(BaseModel):
    provider: Literal["gemini", "rules"]
    model: str | None = None
    live: bool = False
    cached: bool = False
    steps: dict[str, str] = Field(default_factory=dict)
    fell_back_reason: str | None = None


class FitResponse(BaseModel):
    event_class: str
    division: Literal["hedge", "opportunity"] | None
    family: str | None
    preset_index: int | None
    params: dict[str, float]
    score: float | None
    alternatives: list[Alternative]
    rationale: str
    llm: str = Field(pattern=r"^(rules|gemini:[A-Za-z0-9._\-]+)$")
    ticks_source: Literal["live_history", "replay", "none"]
    n_ticks: int
    score_basis: Literal["hedge_var_reduction_vs_static", "net_pnl_per_drawdown"] | None = None
    score_note: str | None = None
    score_raw: float | None = None
    score_vs_static: float | None = None
    avg_hedge_ratio: float | None = None
    no_static_benchmark: bool = False
    ai: AIInfo = Field(default_factory=lambda: AIInfo(**rules_info()))
    _gemini_failed: bool = PrivateAttr(default=False)

    @property
    def gemini_failed(self) -> bool:
        return self._gemini_failed


def ai_block(provider: LLMProvider, classify_by: str, explain_by_llm: bool, errors: list[str]) -> dict:
    steps = {"classify": "gemini" if classify_by.startswith("gemini") else "rules",
             "explain": "gemini" if explain_by_llm else "template"}
    if isinstance(provider, RulesProvider):
        return {**rules_info(NO_KEY_REASON), "steps": steps}
    used = steps["classify"] == "gemini" or explain_by_llm
    reasons = [e for e in errors if e]
    fb = getattr(provider, "fell_back_reason", None)
    if fb:
        reasons.insert(0, fb)
    reason = "; ".join(dict.fromkeys(reasons)) or None
    if not used:
        return {**rules_info(f"Gemini did not answer ({reason or 'unknown error'}); keyword rules and template used"),
                "steps": steps}
    return {"provider": "gemini", "model": getattr(provider, "model", None), "live": True, "steps": steps,
            "fell_back_reason": reason}


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
    meta = recording_meta(req.market.source, req.market.id, token)
    if meta.get("question"):
        return str(meta["question"]), token or meta.get("token_id")
    return "", token


def choose_division(lists: dict[str, list[dict]], shares_held: float | None, asked: str | None = None) -> str | None:
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

    end_date = req.end_date or ((_universe_entry(req.market.source, req.market.id).get("end_date")
                                 or recording_meta(req.market.source, req.market.id, token).get("end_date"))
                                if req.market else None)

    want_options = req.division == "opportunity" or (req.division is None and not (req.shares_held or 0) > 0)
    opt_info: dict = {}

    async def join(ts: TickSet) -> None:
        if ts.ticks is None or _has_options(ts):
            return
        try:
            joined, info = await asyncio.wait_for(
                join_options(ts.ticks, question or ts.question, end_date, massive=deps.massive,
                             offline=deps.offline), OPTIONS_BUDGET_S)
            ts.ticks = joined
            opt_info.update(info)
            ts.notes.extend(info.get("notes") or [])
        except asyncio.TimeoutError:
            ts.notes.append(f"options history took over {OPTIONS_BUDGET_S:g} s")

    async def with_options(ts: TickSet) -> TickSet:
        await join(ts)
        if _has_options(ts) or ts.source != "live_history" or market is None:
            return ts
        rec = await build_ticks(market, req.ticker, http=None, massive=None, offline=True)
        if rec.ticks is None or not _has_options(rec):
            return ts
        why = next((n for n in reversed(ts.notes) if n.startswith("options:")), "options: none joined")
        rec.notes = ts.notes + [f"{why}; the recorded replay of this market carries options-implied history (leg "
                                "bar closes, recorded as of each row), so the fit replays the recording"] + rec.notes
        rec.token_id, rec.question = rec.token_id or ts.token_id, rec.question or ts.question
        return rec

    async def ticks() -> TickSet:
        try:
            ts = await asyncio.wait_for(
                build_ticks(market, req.ticker, http=deps.http, massive=deps.massive, offline=deps.offline),
                TICKS_BUDGET_S)
        except asyncio.TimeoutError:
            ts = await build_ticks(market, req.ticker, http=None, massive=None, offline=True)
            ts.notes.append(f"live history took over {TICKS_BUDGET_S:g} s")
            return ts
        if want_options:
            ts = await with_options(ts)
        return ts

    classify_trace: dict = {}
    (event_class, llm), ts = await asyncio.gather(
        classify(question, deps.provider, manifest.get("event_classes"), req.ticker, classify_trace), ticks())

    def lists_for(ts: TickSet) -> dict[str, list[dict]]:
        available = available_requirements(ts)
        return {d: [f for f in fams if not unmet_requirements(f, available)]
                for d, fams in shortlist(manifest, event_class, available).items()}

    question_unresolved = req.market is not None and not question
    lists = lists_for(ts)
    if not want_options and req.division is None and not lists.get("hedge"):
        ts = await with_options(ts)
        lists = lists_for(ts)
    division = choose_division(lists, req.shares_held, req.division)
    families = lists.get(division, []) if division else []
    position = {"shares_held": float(req.shares_held or 0.0), "equity": 0.0, "pred_yes": 0.0, "pred_no": 0.0,
                "option": 0.0}
    if division == "hedge" and ts.ticks is not None:
        ts = TickSet(orient_to_adverse(ts.ticks, req.direction), ts.source, ts.n, ts.has_underlying, ts.quote_model,
                     ts.notes, ts.token_id, ts.question)
    family_ticks = None
    if division == "opportunity" and ts.ticks is not None:
        qdir = (opt_info.get("match") or {}).get("direction") or _question_direction(question or ts.question, end_date)
        family_ticks = {f["id"]: orient_for_family(ts.ticks, f["id"], qdir) for f in families}
    t = tune(deps.adapter, families, division or "hedge", position, ts, family_ticks)

    fam = next((f for f in families if f["id"] == t["family"]), None)
    result = {
        "event_class": event_class, "division": division if t["family"] else None, "family": t["family"],
        "preset_index": t["preset_index"], "params": t["params"], "score": t["score"] if t["scored"] else None,
        "alternatives": t["alternatives"], "llm": llm, "ticks_source": ts.source if ts.ticks is not None else "none",
        "n_ticks": ts.n, "scored": bool(t["scored"]), "no_static_benchmark": bool(t.get("no_static_benchmark")),
        **{k: (t.get(k) if t["scored"] else None)
           for k in ("score_basis", "score_note", "score_raw", "score_vs_static", "avg_hedge_ratio")},
        "ticker": req.ticker, "direction": req.direction, "shares_held": req.shares_held,
        "n_shortlisted": len(families), "unscored_reason": t.get("unscored_reason"),
        "family_idea": (fam or {}).get("idea"), "proxies": (fam or {}).get("proxies"),
        "question_unresolved": question_unresolved or None,
        "reason": None if t["family"] else _no_fit_reason(event_class, question_unresolved, t),
    }
    explain_trace: dict = {}
    result["rationale"], by_llm = await explain(result, deps.provider, explain_trace)
    errors = []
    if classify_trace.get("error"):
        errors.append(f"classify: {classify_trace['error']}")
    if explain_trace.get("error"):
        errors.append(f"explain: {explain_trace['error']}")
    result["ai"] = ai_block(deps.provider, llm, by_llm, errors)
    result["gemini_failed"] = bool(errors)
    return result


def _question_direction(question: str | None, end_date: Any) -> str | None:
    if not question:
        return None
    try:
        from ..options.match import match_question
        m = match_question(question, end_date)
        return m.direction if m is not None else None
    except Exception:
        return None


def _no_fit_reason(event_class: str, question_unresolved: bool, t: dict) -> str | None:
    if question_unresolved:
        return "the market's question could not be resolved"
    if event_class == "unsupported":
        return "the question is outside every supported event class"
    return t.get("unscored_reason")


def degraded(req: FitRequest | None, err: Exception) -> dict:
    q = (req.question or "") if req else ""
    return {"event_class": rules_classify(q) if q else "unsupported", "division": None, "family": None,
            "preset_index": None, "params": {}, "score": None, "alternatives": [], "llm": "rules",
            "ticks_source": "none", "n_ticks": 0,
            "ai": rules_info(f"internal error ({type(err).__name__}); keyword rules only"),
            "rationale": f"The fit pipeline hit an internal error ({type(err).__name__}), so no algo was fitted. "
                         "Nothing here is a recommendation; retry in a moment."}


async def fit(req: FitRequest, deps: Deps) -> FitResponse:
    try:
        r = await run_fit(req, deps)
    except Exception as e:
        r = degraded(req, e)
    try:
        resp = FitResponse(**{k: r[k] for k in FitResponse.model_fields if k in r})
        resp._gemini_failed = bool(r.get("gemini_failed"))
        return resp
    except Exception as e:
        r = degraded(req, e)
        return FitResponse(**{k: r[k] for k in FitResponse.model_fields if k in r})
