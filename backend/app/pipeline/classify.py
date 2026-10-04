from __future__ import annotations

from ..contracts.classify import TYPES as CONTRACT_TYPES, classify_contract, rules_classify as rules_classify_contract  # noqa: F401

from .engine_adapter import EVENT_CLASSES
from .llm import LLMError, LLMProvider, RulesProvider


async def classify(question: str, provider: LLMProvider, allowed: list[str] | None = None,
                   ticker: str | None = None, trace: dict | None = None) -> tuple[str, str]:
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
        except Exception as e:
            err = f"provider error: {type(e).__name__}"
        if trace is not None:
            trace["error"] = err
    return await RulesProvider().classify(question, allowed, ticker), "rules"
