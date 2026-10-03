"""Step 1: question -> event class (Gemini first, keyword rules on any failure)."""
from __future__ import annotations

from .engine_adapter import EVENT_CLASSES
from .llm import LLMError, LLMProvider, RulesProvider


async def classify(question: str, provider: LLMProvider, allowed: list[str] | None = None,
                   ticker: str | None = None) -> tuple[str, str]:
    """Returns (event_class, provider name that produced it: 'gemini' | 'rules')."""
    allowed = list(allowed or EVENT_CLASSES)
    if "unsupported" not in allowed:
        allowed.append("unsupported")
    if not (question or "").strip():
        return "unsupported", "rules"
    if not isinstance(provider, RulesProvider):
        try:
            cls = await provider.classify(question, allowed, ticker)
            if cls in allowed:
                return cls, getattr(provider, "name", "gemini")
        except LLMError:
            pass
        except Exception:  # a provider bug must not break the fit
            pass
    return await RulesProvider().classify(question, allowed, ticker), "rules"
