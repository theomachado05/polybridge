"""Step 1: question -> event class (the LLM provider first: OpenAI, then Gemini; keyword rules on any failure), and the four contract types.

Two classifiers live here:

- ``classify_contract`` (what the product acts on): ``ladder_rung``, ``touch_ticket``, ``close_above_ticket`` or
  ``other``, with structured fields and link checks. The rule parser (``research/linker/link_map.classify``) decides;
  Gemini may read the same text into the same fields and is checked against it (``app.contracts.classify``).
- ``classify`` (the generic AI fit, unvalidated: its walk-forward test failed): question -> event class.
"""
from __future__ import annotations

from ..contracts.classify import TYPES as CONTRACT_TYPES, classify_contract, rules_classify as rules_classify_contract  # noqa: F401

from .engine_adapter import EVENT_CLASSES
from .llm import LLMError, LLMProvider, RulesProvider


async def classify(question: str, provider: LLMProvider, allowed: list[str] | None = None,
                   ticker: str | None = None, trace: dict | None = None) -> tuple[str, str]:
    """Returns (event_class, label of what produced it: 'openai:<model>' | 'gemini:<model>' | 'rules').

    ``trace`` (optional) receives ``error`` when an LLM provider was tried and the rules answered instead."""
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
            err = f"{getattr(provider, 'display', 'Gemini')} returned a class outside the allowed set"
        except LLMError as e:
            err = str(e)
        except Exception as e:  # a provider bug must not break the fit
            err = f"provider error: {type(e).__name__}"
        if trace is not None:
            trace["error"] = err
    return await RulesProvider().classify(question, allowed, ticker), "rules"
