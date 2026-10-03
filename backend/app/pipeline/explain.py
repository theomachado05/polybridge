"""Step 5: a 2-3 sentence rationale written from the structured result only (Gemini, else a template)."""
from __future__ import annotations

from .llm import LLMProvider, RulesProvider, template_rationale

FACT_KEYS = ("event_class", "division", "family", "preset_index", "params", "score", "scored", "unscored_reason",
             "ticks_source", "n_ticks", "ticker", "direction", "shares_held", "n_shortlisted", "family_idea",
             "proxies", "llm", "reason")


def facts(result: dict) -> dict:
    """The only data the LLM may see: the structured result, alternatives reduced to family/preset/score."""
    out = {k: result.get(k) for k in FACT_KEYS if result.get(k) is not None}
    out["alternatives"] = [{k: a.get(k) for k in ("family", "preset_index", "score")}
                           for a in result.get("alternatives") or []]
    return out


async def explain(result: dict, provider: LLMProvider) -> tuple[str, bool]:
    """(rationale, written_by_llm)."""
    f = facts(result)
    if not isinstance(provider, RulesProvider):
        try:
            text = await provider.explain(f)
            if text:
                return text, True
        except Exception:
            pass
    return template_rationale(f), False
