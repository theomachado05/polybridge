"""LLM providers for the fit pipeline: Gemini over REST (JSON mode) and a deterministic rules fallback.

Gemini never sees anything but the question (classify) or the structured fit result (explain). Every Gemini
failure (no key, timeout, HTTP error, malformed JSON, a class outside the allowed set) raises ``LLMError``;
callers then fall back to ``RulesProvider``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_S = 8.0
BACKEND = Path(__file__).resolve().parents[2]


class LLMError(RuntimeError):
    """The provider could not produce a usable answer."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str: ...

    async def explain(self, result: dict) -> str: ...


# ---------------------------------------------------------------- rules (keyword) provider

# (class, weight, patterns). Patterns are regexes matched on the lower-cased question with word boundaries.
RULES: list[tuple[str, list[str]]] = [
    ("macro_fed", [r"fed", r"fomc", r"interest rates?", r"rate (cut|hike|increase|decrease)s?", r"bps", r"basis points?",
                   r"cpi", r"inflation", r"recession", r"gdp", r"unemployment", r"jobs report", r"nonfarm", r"payrolls?",
                   r"powell", r"treasury yields?", r"10-year", r"federal reserve"]),
    ("elections", [r"elections?", r"senate", r"house", r"president(ial)?", r"nominee", r"nomination", r"primary",
                   r"balance of power", r"governor", r"mayor", r"electoral", r"democrats?", r"republicans?",
                   r"midterms?", r"vote share", r"popular vote", r"win the"]),
    ("tariffs_trade", [r"tariffs?", r"trade (deal|war|agreement)", r"imports?", r"exports?", r"customs", r"wto",
                       r"section 301", r"de minimis"]),
    ("geopolitics_energy", [r"war", r"ceasefire", r"invade", r"invasion", r"military", r"airstrikes?", r"strikes? on",
                            r"iran", r"israel", r"russia", r"ukraine", r"taiwan", r"opec", r"oil", r"crude", r"brent",
                            r"wti", r"nato", r"missiles?", r"sanctions?", r"conflict", r"nuclear", r"gaza", r"hezbollah",
                            r"natural gas", r"strait of hormuz"]),
    ("housing", [r"mortgage", r"home prices?", r"housing", r"home sales", r"case-shiller", r"rents?", r"homebuilders?"]),
    ("fig", [r"banks?", r"banking", r"fdic", r"insurers?", r"insurance", r"capital requirements?", r"basel",
             r"bank failures?", r"regional banks?", r"deposits?", r"stress tests?", r"bailout"]),
    ("tech_regulation", [r"antitrust", r"ftc", r"doj", r"ai (regulation|act|bill|safety)", r"data centers?",
                         r"tiktok", r"section 230", r"break ?up", r"chips? export", r"export controls?",
                         r"moratorium", r"monopoly", r"app store"]),
    ("crypto", [r"bitcoin", r"btc", r"ethereum", r"eth", r"crypto(currency)?", r"stablecoins?", r"solana",
                r"coinbase", r"microstrategy", r"spot etf", r"xrp", r"dogecoin"]),
    ("corporate_8k", [r"8-k", r"earnings", r"ceo", r"mergers?", r"acquisitions?", r"acquire[sd]?", r"bankruptcy",
                      r"ipo", r"layoffs?", r"guidance", r"dividends?", r"buybacks?", r"resigns?", r"step down",
                      r"delist(ed|ing)?", r"chapter 11"]),
    ("company_specific", [r"announce[sd]?", r"release[sd]?", r"launch(es|ed)?", r"stock", r"shares", r"market cap",
                          r"largest company", r"valuation", r"products?", r"openai", r"anthropic", r"apple", r"tesla",
                          r"nvidia", r"google", r"microsoft", r"amazon", r"meta"]),
]
UNSUPPORTED = [r"nba", r"nfl", r"mlb", r"nhl", r"fifa", r"world cup", r"super bowl", r"champions league", r"premier league",
               r"tennis", r"golf", r"ufc", r"oscars?", r"grammys?", r"eurovision", r"weather", r"temperature",
               r"esports", r"album", r"box office"]
_COMPILED = [(c, [re.compile(rf"\b{p}\b") for p in pats]) for c, pats in RULES]
_UNSUPPORTED = [re.compile(rf"\b{p}\b") for p in UNSUPPORTED]


def rules_classify(question: str, allowed: list[str] | None = None) -> str:
    """Highest keyword score wins; ties go to the earlier (more market-moving) class in RULES."""
    q = (question or "").lower()
    allowed_set = set(allowed or [c for c, _ in RULES] + ["unsupported"])
    best, best_score = "unsupported", 0
    for cls, pats in _COMPILED:
        if cls not in allowed_set:
            continue
        score = sum(1 for p in pats if p.search(q))
        if score > best_score:
            best, best_score = cls, score
    if any(p.search(q) for p in _UNSUPPORTED) and best_score <= 1:
        return "unsupported"
    return best if best in allowed_set or best == "unsupported" else "unsupported"


def _fmt_params(params: dict) -> str:
    def f(v: Any) -> str:
        return f"{v:g}" if isinstance(v, (int, float)) else str(v)
    return ", ".join(f"{k}={f(v)}" for k, v in (params or {}).items()) or "no parameters"


def template_rationale(r: dict) -> str:
    """2-3 sentences built only from the structured result."""
    cls, fam, div = r.get("event_class"), r.get("family"), r.get("division")
    if not fam:
        reason = r.get("reason") or "no algo family in the library covers this event class"
        return (f"Classified as {cls} by {r.get('llm', 'rules')}. No algo was fitted: {reason}. "
                f"Try a market about rates, elections, trade, energy, housing, banks, tech regulation, crypto or a company.")
    ticker = r.get("ticker") or "the position"
    first = f"Classified as {cls}; {r.get('n_shortlisted', 0)} {div} families in the library cover it, and {fam} was chosen for {ticker}."
    if r.get("scored") and r.get("score") is not None:
        metric = "hedge variance reduction" if div == "hedge" else "P&L net of fees per unit of drawdown"
        second = (f"Preset #{r.get('preset_index')} ({_fmt_params(r.get('params') or {})}) scored best on {metric} "
                  f"({r['score']:.3f}) over {r.get('n_ticks', 0)} replayed ticks from {r.get('ticks_source')} price history.")
    else:
        why = r.get("unscored_reason") or "the compiled engine is not available"
        second = (f"Preset #{r.get('preset_index')} ({_fmt_params(r.get('params') or {})}) is the family's default, picked by "
                  f"event-class rules without a replay score because {why}.")
    alts = [a.get("family") for a in (r.get("alternatives") or []) if a.get("family")]
    third = f" Alternatives considered: {', '.join(dict.fromkeys(alts))}." if alts else ""
    return f"{first} {second}{third}"


class RulesProvider:
    name = "rules"

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str:
        return rules_classify(question, allowed)

    async def explain(self, result: dict) -> str:
        return template_rationale(result)


# ---------------------------------------------------------------- Gemini provider

def gemini_key() -> str | None:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    try:
        from polybridge_research.massive import MissingApiKey, load_api_key
        return load_api_key("GEMINI_API_KEY", search_from=BACKEND, interactive=False)
    except Exception:
        return None


def _response_text(payload: dict) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError("Gemini response had no text") from e


def parse_json_text(text: str) -> dict:
    """Gemini JSON mode returns a JSON string; tolerate a ```json fence just in case."""
    t = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        v = json.loads(t)
    except ValueError as e:
        raise LLMError("Gemini returned malformed JSON") from e
    if not isinstance(v, dict):
        raise LLMError("Gemini JSON was not an object")
    return v


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None, http: httpx.AsyncClient | None = None,
                 timeout_s: float = TIMEOUT_S) -> None:
        self.api_key = api_key
        self.model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self._http, self.timeout_s = http, timeout_s

    async def _generate(self, prompt: str, schema: dict) -> dict:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                                     "temperature": 0.0}}
        url = GEMINI_URL.format(model=self.model)
        headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        http = self._http or httpx.AsyncClient()
        try:
            r = await http.post(url, json=body, headers=headers, timeout=httpx.Timeout(self.timeout_s))
            r.raise_for_status()
            return parse_json_text(_response_text(r.json()))
        except LLMError:
            raise
        except Exception as e:  # timeout, transport, HTTP status, bad JSON body
            raise LLMError(f"Gemini call failed: {type(e).__name__}") from None  # never echo the key-bearing request
        finally:
            if self._http is None:
                await http.aclose()

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str:
        prompt = ("Classify this prediction-market question into exactly one event class for an equity-hedging "
                  "system. Use 'unsupported' when no class fits (sports, entertainment, weather...).\n"
                  f"Allowed classes: {', '.join(allowed)}.\n"
                  f"Question: {question!r}\n" + (f"Equity the user holds: {ticker}\n" if ticker else "") +
                  'Answer as JSON: {"event_class": "<one allowed class>"}')
        schema = {"type": "OBJECT", "properties": {"event_class": {"type": "STRING", "enum": list(allowed)}},
                  "required": ["event_class"]}
        out = await self._generate(prompt, schema)
        cls = str(out.get("event_class", "")).strip()
        if cls not in allowed:
            raise LLMError("Gemini returned a class outside the allowed set")
        return cls

    async def explain(self, result: dict) -> str:
        prompt = ("Write a 2-3 sentence rationale for an investor explaining why this algo and preset were chosen. "
                  "Use ONLY the facts in the JSON below; do not add numbers, events, or claims that are not in it. "
                  "If 'scored' is false, say plainly that the preset was picked by rules without a replay score. "
                  "Say 'replay' for replayed history, never 'live performance'.\n"
                  f"{json.dumps(result, default=str, sort_keys=True)}\n"
                  'Answer as JSON: {"rationale": "<2-3 sentences>"}')
        schema = {"type": "OBJECT", "properties": {"rationale": {"type": "STRING"}}, "required": ["rationale"]}
        out = await self._generate(prompt, schema)
        text = str(out.get("rationale", "")).strip()
        if not text:
            raise LLMError("Gemini returned an empty rationale")
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return " ".join(sentences[:3])[:800]


def default_provider(http: httpx.AsyncClient | None = None) -> LLMProvider:
    key = gemini_key()
    return GeminiProvider(key, http=http) if key else RulesProvider()
