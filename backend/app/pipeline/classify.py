"""Step 1: question -> event class (Gemini first, keyword rules on any failure)."""
from __future__ import annotations

from .engine_adapter import EVENT_CLASSES
from .llm import LLMError, LLMProvider, RulesProvider


async def classify(question: str, provider: LLMProvider, allowed: list[str] | None = None,
                   ticker: str | None = None, trace: dict | None = None) -> tuple[str, str]:
    """Returns (event_class, label of what produced it: 'gemini:<model>' | 'rules').

    ``trace`` (optional) receives ``error`` when a Gemini provider was tried and the rules answered instead."""
    allowed = list(allowed or EVENT_CLASSES)
    if "unsupported" not in allowed:
        allowed.append("unsupported")
    if not (question or "").strip():
        return "unsupported", "rules"
    if not isinstance(provider, RulesProvider):
        try:
            cls = await provider.classify(question, allowed, ticker)
            if cls in allowed:
                return cls, getattr(provider, "label", None) or getattr(provider, "name", "gemini")
            err = "Gemini returned a class outside the allowed set"
        except LLMError as e:
            err = str(e)
        except Exception as e:  # a provider bug must not break the fit
            err = f"provider error: {type(e).__name__}"
        if trace is not None:
            trace["error"] = err
    return await RulesProvider().classify(question, allowed, ticker), "rules"
