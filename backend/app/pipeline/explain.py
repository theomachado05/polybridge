from __future__ import annotations

from .llm import LLMProvider, RulesProvider, template_rationale

FACT_KEYS = ("event_class", "division", "family", "preset_index", "params", "score", "score_basis", "score_raw",
             "avg_hedge_ratio", "scored", "unscored_reason",
             "ticks_source", "n_ticks", "ticker", "direction", "shares_held", "n_shortlisted", "family_idea",
             "proxies", "llm", "reason", "question_unresolved")


def facts(result: dict) -> dict:
    out = {k: result.get(k) for k in FACT_KEYS if result.get(k) is not None}
    out["alternatives"] = [{k: a.get(k) for k in ("family", "preset_index", "score")}
                           for a in result.get("alternatives") or []]
    return out


async def explain(result: dict, provider: LLMProvider, trace: dict | None = None) -> tuple[str, bool]:
    f = facts(result)
    if not isinstance(provider, RulesProvider):
        try:
            text = await provider.explain(f)
            if text:
                return text, True
            err = "Gemini returned an empty rationale"
        except Exception as e:
            err = str(e) if str(e).startswith("Gemini") else f"provider error: {type(e).__name__}"
        if trace is not None:
            trace["error"] = err
    return template_rationale(f), False
