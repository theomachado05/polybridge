"""Step 5: a 2-3 sentence rationale written from the structured result only (OpenAI or Gemini, else a template)."""
from __future__ import annotations

from .llm import LLMError, LLMProvider, RulesProvider, template_rationale

FACT_KEYS = ("event_class", "division", "family", "preset_index", "params", "score", "score_basis", "score_raw",
             "avg_hedge_ratio", "scored", "unscored_reason",
             "ticks_source", "n_ticks", "ticker", "direction", "shares_held", "n_shortlisted", "family_idea",
             "proxies", "llm", "reason", "question_unresolved")


def facts(result: dict) -> dict:
    """The only data the LLM may see: the structured result, alternatives reduced to family/preset/score."""
    out = {k: result.get(k) for k in FACT_KEYS if result.get(k) is not None}
    out["alternatives"] = [{k: a.get(k) for k in ("family", "preset_index", "score")}
                           for a in result.get("alternatives") or []]
    return out


async def explain(result: dict, provider: LLMProvider, trace: dict | None = None) -> tuple[str, bool]:
    """(rationale, written_by_llm). ``trace`` (optional) receives ``error`` when an LLM was tried and failed."""
    f = facts(result)
    if not isinstance(provider, RulesProvider):
        try:
            text = await provider.explain(f)
            if text:
                return text, True
            err = f"{getattr(provider, 'display', 'Gemini')} returned an empty rationale"
        except Exception as e:
            err = str(e) if isinstance(e, LLMError) or str(e).startswith("Gemini") else f"provider error: {type(e).__name__}"
        if trace is not None:
            trace["error"] = err
    return template_rationale(f), False
