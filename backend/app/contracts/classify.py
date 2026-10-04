"""The four-type contract classifier: rule parser first, an LLM (OpenAI or Gemini) as a checked second reader.

Types: ``ladder_rung``, ``touch_ticket``, ``close_above_ticket``, ``other`` (``research/linker/link_map.classify``).
Gemini may read the question and rule text into the same fields, and compare two rungs' rules. Every Gemini field is
checked against the rule parser: on any disagreement the rule parser's value is served and the item is flagged.
Gemini never decides a trade; without a key (or on any Gemini failure) the rule parser answers alone.
"""
from __future__ import annotations

import math
from typing import Any

from ..pipeline.llm import LLMError, RulesProvider
from . import research

TYPES = ("ladder_rung", "touch_ticket", "close_above_ticket", "other")
GEMINI_NOTE = "The LLM (OpenAI or Gemini) reads text into fields only; every field is checked against the rule parser, which wins; it never decides a trade."
_COMPARED = {"touch_ticket": ("underlying", "level", "direction", "window_end"),
             "close_above_ticket": ("underlying", "level", "direction", "window_end"),
             "ladder_rung": ("date",), "other": ()}


def rules_classify(question: str, rules: str | None = None, market: dict | None = None) -> dict:
    """The rule parser's answer, or type ``other`` with the reason when the research code cannot load."""
    try:
        return research.link_map().classify(question or "", rules, market or {})
    except RuntimeError as e:
        return {"type": "other", "mechanism": "none", "fields": {}, "linkable": False,
                "checks": [{"check": "rule parser available", "ok": False, "detail": str(e)}], "reasons": [str(e)]}


def _is_gemini(provider: Any) -> bool:
    return provider is not None and not isinstance(provider, RulesProvider) and hasattr(provider, "_generate")


async def gemini_fields(provider: Any, question: str, rules: str | None, created: str | None) -> dict:
    """Gemini's reading of the text into the parser's fields. Raises LLMError."""
    prompt = ("Read this prediction-market question and its rules into fields. Do not judge prices or trades.\n"
              "type: ladder_rung (\"X by <date>\" where an earlier date implies a later one), touch_ticket (a stock or "
              "the S&P 500 hitting, reaching or dipping to a $ level within a window), close_above_ticket (a stock or the "
              "S&P 500 closing above/below a $ level on a date), other.\n"
              "underlying: the stock ticker for tickets (as written, e.g. NVDA, SPY, SPX), else empty. level: the $ level "
              "for tickets, else 0. direction: up, down, or none. date: YYYY-MM-DD for a rung's deadline or a ticket's "
              "window end (a missing year is the first year on or after the creation date), else empty.\n"
              f"Created: {created or 'unknown'}\nQuestion: {question!r}\nRules: {(rules or '')[:1500]!r}\n")
    schema = {"type": "OBJECT", "properties": {
        "type": {"type": "STRING", "enum": list(TYPES)}, "underlying": {"type": "STRING"}, "level": {"type": "NUMBER"},
        "direction": {"type": "STRING", "enum": ["up", "down", "none"]}, "date": {"type": "STRING"}},
        "required": ["type", "underlying", "level", "direction", "date"]}
    out = await provider._generate(prompt, schema)
    if not isinstance(out, dict) or out.get("type") not in TYPES:
        raise LLMError("Gemini returned no usable type")
    return out


def _gem_value(g: dict, field: str) -> Any:
    if field in ("window_end", "date"):
        return str(g.get("date") or "")[:10] or None
    if field == "level":
        try:
            v = float(g.get("level") or 0)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) and v > 0 else None
    if field == "direction":
        d = str(g.get("direction") or "").lower()
        return d if d in ("up", "down") else None
    return str(g.get(field) or "").strip().upper() or None


def compare(rule: dict, gem: dict) -> list[dict]:
    """Fields where Gemini disagrees with the rule parser (empty = agreement)."""
    out = []
    if gem.get("type") != rule["type"]:
        out.append({"field": "type", "rules": rule["type"], "gemini": gem.get("type")})
        return out
    for f in _COMPARED.get(rule["type"], ()):
        rv, gv = rule["fields"].get(f), _gem_value(gem, f)
        same = (rv is not None and gv is not None and abs(float(rv) - float(gv)) < 1e-6) if f == "level" else rv == gv
        if not same:
            out.append({"field": f, "rules": rv, "gemini": gv})
    return out


async def classify_contract(question: str, rules: str | None = None, market: dict | None = None,
                            provider: Any = None) -> dict:
    """Rule parser result plus ``gemini_agreement``. The served type and fields are always the rule parser's."""
    res = rules_classify(question, rules, market)
    agreement: dict = {"used": False, "provider": "rules", "agree": None, "disagreements": [], "error": None, "note": GEMINI_NOTE}
    if _is_gemini(provider) and (question or "").strip():
        agreement.update(used=True, provider=getattr(provider, "label", "gemini"))
        m = market or {}
        try:
            gem = await gemini_fields(provider, question, rules if rules is not None else m.get("description"),
                                      str(m.get("createdAt") or m.get("startDate") or "")[:10] or None)
            dis = compare(res, gem)
            agreement.update(agree=not dis, disagreements=dis)
        except LLMError as e:
            agreement["error"] = str(e)
        except Exception as e:  # a provider bug must not break classification
            agreement["error"] = f"provider error: {type(e).__name__}"
        agreement["provider"] = getattr(provider, "label", "gemini")  # after the call: who answered (or failed) last
    res = dict(res, gemini_agreement=agreement, flagged=bool(agreement["disagreements"]))
    return res


async def gemini_same_rules(provider: Any, rules_a: str, rules_b: str) -> bool:
    """Gemini's reading of whether two rungs' rules define the same event with the same source. Raises LLMError."""
    prompt = ("Two prediction-market rungs of one ladder differ only by their deadline. Ignoring the deadline itself, do "
              "their rules define the same event, the same resolution source and the same window start? Answer only "
              "from the text.\n" f"Rules A: {rules_a[:1500]!r}\nRules B: {rules_b[:1500]!r}\n")
    schema = {"type": "OBJECT", "properties": {"same": {"type": "BOOLEAN"}}, "required": ["same"]}
    out = await provider._generate(prompt, schema)
    if not isinstance(out, dict) or not isinstance(out.get("same"), bool):
        raise LLMError("Gemini returned no same/different answer")
    return out["same"]


async def check_pair_with_gemini(provider: Any, pair: dict, rich: dict, cheap: dict) -> dict:
    """Adds ``gemini`` to a ladder pair: Gemini's same-rules reading against the rule verdict (rule wins; flagged on
    disagreement). The pair's ``nested`` verdict is never changed."""
    if not _is_gemini(provider):
        return pair
    rule_same = all(c["ok"] for c in pair["checks"][1:])
    try:
        same = await gemini_same_rules(provider, rich.get("description") or "", cheap.get("description") or "")
        g = {"used": True, "same_rules": same, "agree": same == rule_same, "error": None}
    except LLMError as e:
        g = {"used": True, "same_rules": None, "agree": None, "error": str(e)}
    g["provider"] = getattr(provider, "label", "gemini")  # the provider that answered (or failed) last
    return {**pair, "gemini": g, "flagged": g["agree"] is False}
