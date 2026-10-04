from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-flash-lite-latest"
RETRY_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_BASE_S = 1.5
RETRY_MAX_WAIT_S = 4.0
TIMEOUT_S = 8.0
MODELS_TTL_S = 3600.0
BACKEND = Path(__file__).resolve().parents[2]
log = logging.getLogger("polybridge.llm")


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str: ...

    async def explain(self, result: dict) -> str: ...


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
    cls, fam, div = r.get("event_class"), r.get("family"), r.get("division")
    if not fam and r.get("question_unresolved"):
        return ("The market's question could not be resolved (it is not in the bundled universe and could not be "
                "fetched), so it was not classified and no algo was fitted. Pass the question text with the request "
                "to fit it.")
    if not fam:
        reason = r.get("reason") or "no algo family in the library covers this event class"
        by = r.get("llm") or "rules"
        by = f"Gemini ({by.split(':', 1)[1]})" if by.startswith("gemini:") else ("keyword rules" if by == "rules" else by)
        return (f"Classified as {cls} by {by}. No algo was fitted: {reason}. "
                f"Try a market about rates, elections, trade, energy, housing, banks, tech regulation, crypto or a company.")
    ticker = r.get("ticker") or "the position"
    first = f"Classified as {cls}; {r.get('n_shortlisted', 0)} {div} families in the library cover it, and {fam} was chosen for {ticker}."
    if r.get("scored") and r.get("score") is not None:
        metric = ("hedge variance reduction beyond a static hedge of the same average size"
                  if div == "hedge" else "P&L net of fees per unit of drawdown")
        extra = ""
        if div == "hedge" and r.get("score_raw") is not None:
            extra = f"; raw variance reduction {r['score_raw']:.3f}"
            if r.get("avg_hedge_ratio") is not None:
                extra += f" at an average hedge ratio of {r['avg_hedge_ratio']:.2f}"
        second = (f"Preset #{r.get('preset_index')} ({_fmt_params(r.get('params') or {})}) scored best on {metric} "
                  f"({r['score']:.3f}{extra}) over {r.get('n_ticks', 0)} replayed ticks from {r.get('ticks_source')} "
                  "price history.")
    else:
        why = r.get("unscored_reason") or "the compiled engine is not available"
        second = (f"Preset #{r.get('preset_index')} ({_fmt_params(r.get('params') or {})}) is the family's default, picked by "
                  f"event-class rules without a replay score because {why}.")
    alts = [a.get("family") for a in (r.get("alternatives") or []) if a.get("family")]
    third = f" Alternatives considered: {', '.join(dict.fromkeys(alts))}." if alts else ""
    return f"{first} {second}{third}"


class RulesProvider:
    name = "rules"
    label = "rules"
    model = None
    fell_back_reason = None

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str:
        return rules_classify(question, allowed)

    async def explain(self, result: dict) -> str:
        return template_rationale(result)


def classify_request(question: str, allowed: list[str], ticker: str | None = None) -> tuple[str, dict]:
    prompt = ("Classify this prediction-market question into exactly one event class for an equity-hedging "
              "system. Use 'unsupported' when no class fits (sports, entertainment, weather...).\n"
              f"Allowed classes: {', '.join(allowed)}.\n"
              f"Question: {question!r}\n" + (f"Equity the user holds: {ticker}\n" if ticker else "") +
              'Answer as JSON: {"event_class": "<one allowed class>"}')
    schema = {"type": "OBJECT", "properties": {"event_class": {"type": "STRING", "enum": list(allowed)}},
              "required": ["event_class"]}
    return prompt, schema


def explain_request(result: dict) -> tuple[str, dict]:
    prompt = ("Write a 2-3 sentence rationale for an investor explaining why this algo and preset were chosen. "
              "Use ONLY the facts in the JSON below; do not add numbers, events, or claims that are not in it. "
              "If 'scored' is false, say plainly that the preset was picked by rules without a replay score. "
              "For a hedge, 'score' is the variance reduction BEYOND a static hedge of the same average size "
              "(what the market signal adds); 'score_raw' is plain variance reduction, which any static short "
              "earns, so never present score_raw as the hedge's edge. "
              "Say 'replay' for replayed history, never 'live performance'.\n"
              "Write scores as percentages with one decimal (0.2459 -> 24.6%).\n"
              f"{json.dumps(_round_floats(result), default=str, sort_keys=True)}\n"
              'Answer as JSON: {"rationale": "<2-3 sentences>"}')
    schema = {"type": "OBJECT", "properties": {"rationale": {"type": "STRING"}}, "required": ["rationale"]}
    return prompt, schema


def map_request(question: str, universe: list[dict], max_items: int = 6) -> tuple[str, dict]:
    tickers = [u["ticker"] for u in universe]
    lines = "\n".join(f"{u['ticker']}: {u.get('name') or u['ticker']}" for u in universe)
    prompt = ("You map a prediction-market question to the US-listed stocks or ETFs whose price would move if the "
              "question resolved YES. Choose ONLY tickers from the list below; never invent a ticker. "
              f"Return at most {max_items}, most affected first, and an empty list when no listed ticker has a "
              "clear, direct link (do not stretch). For each: direction 'down_on_yes' if the stock would fall on "
              "YES, 'up_on_yes' if it would rise; impact_pct = your estimate of the stock's move in percent "
              "(a positive number, at most 20) if YES became certain; rationale = one plain sentence, no numbers "
              "that are not in the question.\n"
              f"Question: {question!r}\nTickers:\n{lines}\n"
              'Answer as JSON: {"mappings": [{"ticker": "...", "direction": "down_on_yes|up_on_yes", '
              '"impact_pct": 1.5, "rationale": "..."}]}')
    item = {"type": "OBJECT", "properties": {
        "ticker": {"type": "STRING", "enum": tickers},
        "direction": {"type": "STRING", "enum": ["down_on_yes", "up_on_yes"]},
        "impact_pct": {"type": "NUMBER"},
        "rationale": {"type": "STRING"}}, "required": ["ticker", "direction", "impact_pct", "rationale"]}
    schema = {"type": "OBJECT", "properties": {"mappings": {"type": "ARRAY", "items": item}},
              "required": ["mappings"]}
    return prompt, schema


def strict_json_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [strict_json_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out[k] = v.lower()
        elif k == "properties" and isinstance(v, dict):
            out[k] = {name: strict_json_schema(sub) for name, sub in v.items()}
        elif k == "items":
            out[k] = strict_json_schema(v)
        else:
            out[k] = v
    if out.get("type") == "object":
        out["required"] = list((out.get("properties") or {}).keys())
        out["additionalProperties"] = False
    return out


class JSONProvider:
    display = "LLM"

    async def _generate(self, prompt: str, schema: dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    async def classify(self, question: str, allowed: list[str], ticker: str | None = None) -> str:
        out = await self._generate(*classify_request(question, allowed, ticker))
        cls = str(out.get("event_class", "")).strip()
        if cls not in allowed:
            raise LLMError(f"{self.display} returned a class outside the allowed set")
        return cls

    async def explain(self, result: dict) -> str:
        out = await self._generate(*explain_request(result))
        text = str(out.get("rationale", "")).strip()
        if not text:
            raise LLMError(f"{self.display} returned an empty rationale")
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return " ".join(sentences[:3])[:800]

    async def map_tickers(self, question: str, universe: list[dict], max_items: int = 6) -> list:
        out = await self._generate(*map_request(question, universe, max_items))
        rows = out.get("mappings")
        if not isinstance(rows, list):
            raise LLMError(f"{self.display} returned no mappings list")
        return rows


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


def parse_json_text(text: str, vendor: str = "Gemini") -> dict:
    t = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        v = json.loads(t)
    except ValueError as e:
        raise LLMError(f"{vendor} returned malformed JSON") from e
    if not isinstance(v, dict):
        raise LLMError(f"{vendor} JSON was not an object")
    return v


_SPECIAL = re.compile(r"(tts|image|audio|live|embedding|vision|robotics|computer-use|thinking|learnlm|aqa)")
_FLASH = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash(?:-(.*))?$")
_models_cache: dict[str, tuple[float, list[dict]]] = {}
_resolved: dict[str, str] = {}


def _key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def newest_flash(models: list[dict]) -> str | None:
    best: tuple | None = None
    best_id: str | None = None
    for m in models or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("name") or "").removeprefix("models/")
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        hit = _FLASH.match(mid)
        if not hit or _SPECIAL.search(mid):
            continue
        version = tuple(int(x) for x in hit.group(1).split("."))
        suffix = hit.group(2) or ""
        stable = not re.search(r"(preview|exp)", suffix)
        full = "lite" not in suffix
        rank = (version, stable, full, suffix == "", -len(mid))
        if best is None or rank > best:
            best, best_id = rank, mid
    return best_id


async def list_models(api_key: str, http: httpx.AsyncClient | None = None, timeout_s: float = TIMEOUT_S,
                      use_cache: bool = True) -> list[dict]:
    kid = _key_id(api_key)
    hit = _models_cache.get(kid)
    if use_cache and hit and time.monotonic() - hit[0] < MODELS_TTL_S:
        return hit[1]
    own = http is None
    client = http or httpx.AsyncClient()
    models: list[dict] = []
    try:
        token = None
        for _ in range(10):
            params = {"pageSize": 1000, **({"pageToken": token} if token else {})}
            r = await client.get(MODELS_URL, params=params, headers={"x-goog-api-key": api_key},
                                 timeout=httpx.Timeout(timeout_s))
            if r.status_code >= 400:
                raise LLMError(f"Gemini model list failed: HTTP {r.status_code}")
            body = r.json()
            models.extend(m for m in body.get("models") or [] if isinstance(m, dict))
            token = body.get("nextPageToken")
            if not token:
                break
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"Gemini model list failed: {type(e).__name__}") from None
    finally:
        if own:
            await client.aclose()
    _models_cache[kid] = (time.monotonic(), models)
    return models


def _round_floats(x: Any, nd: int = 4) -> Any:
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _round_floats(v, nd) for k, v in x.items()}
    if isinstance(x, list):
        return [_round_floats(v, nd) for v in x]
    return x


class GeminiProvider(JSONProvider):
    name = "gemini"
    display = "Gemini"

    def __init__(self, api_key: str, model: str | None = None, http: httpx.AsyncClient | None = None,
                 timeout_s: float = TIMEOUT_S) -> None:
        self.api_key = api_key
        self.configured_model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self.model = self.configured_model
        self.fell_back_reason: str | None = None
        if self.configured_model in _resolved:
            self.model = _resolved[self.configured_model]
            self.fell_back_reason = (f"configured model {self.configured_model} returned 404; "
                                     f"using {self.model}, the newest flash model this key lists")
        self._http, self.timeout_s = http, timeout_s

    @property
    def label(self) -> str:
        return f"gemini:{self.model}"

    def info(self, live: bool) -> dict:
        return {"provider": "gemini", "model": self.model, "live": live, "fell_back_reason": self.fell_back_reason}

    async def _fallback_model(self, http: httpx.AsyncClient) -> str | None:
        try:
            new = newest_flash(await list_models(self.api_key, http, self.timeout_s))
        except LLMError:
            return None
        if not new or new == self.model:
            return None
        log.warning("Gemini model %s returned 404; falling back to %s (newest flash model listed for this key)",
                    self.model, new)
        _resolved[self.configured_model] = new
        self.fell_back_reason = (f"configured model {self.model} returned 404; using {new}, the newest flash model "
                                 "this key lists")
        self.model = new
        return new

    async def _generate(self, prompt: str, schema: dict) -> dict:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                                     "temperature": 0.0}}
        headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        http = self._http or httpx.AsyncClient()
        try:
            fell_back, retries = False, 0
            while True:
                try:
                    r = await http.post(GEMINI_URL.format(model=self.model), json=body, headers=headers,
                                        timeout=httpx.Timeout(self.timeout_s))
                except (httpx.TimeoutException, httpx.TransportError):
                    if retries + 1 < RETRY_ATTEMPTS:
                        retries += 1
                        await asyncio.sleep(RETRY_BASE_S * retries)
                        continue
                    raise
                if r.status_code == 404 and not fell_back and await self._fallback_model(http):
                    fell_back = True
                    continue
                if r.status_code in RETRY_STATUS and retries + 1 < RETRY_ATTEMPTS:
                    retries += 1
                    try:
                        wait = float(r.headers.get("retry-after", ""))
                    except ValueError:
                        wait = RETRY_BASE_S * retries
                    await asyncio.sleep(min(max(wait, 0.5), RETRY_MAX_WAIT_S))
                    continue
                r.raise_for_status()
                return parse_json_text(_response_text(r.json()))
        except LLMError:
            raise
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Gemini call failed: HTTP {e.response.status_code}") from None
        except Exception as e:
            raise LLMError(f"Gemini call failed: {type(e).__name__}") from None
        finally:
            if self._http is None:
                await http.aclose()


NO_KEY_REASON = "no OPENAI_API_KEY or GEMINI_API_KEY: keyword rules and templates, no LLM call"
PROVIDER_CHOICES = ("auto", "openai", "gemini", "rules")


def rules_info(reason: str | None = None) -> dict:
    return {"provider": "rules", "model": None, "live": False, "fell_back_reason": reason}


def ai_label(provider: object) -> str:
    return getattr(provider, "label", None) or "rules"


def provider_choice() -> str:
    v = (os.environ.get("LLM_PROVIDER") or "auto").strip().lower()
    return v if v in PROVIDER_CHOICES else "auto"


class _Rules(RulesProvider):

    def __init__(self, reason: str) -> None:
        self.fell_back_reason = reason


def no_llm_reason(provider: object) -> str:
    return getattr(provider, "fell_back_reason", None) or NO_KEY_REASON


def default_provider(http: httpx.AsyncClient | None = None) -> LLMProvider:
    choice = provider_choice()
    if choice == "rules":
        return _Rules("LLM_PROVIDER=rules: keyword rules and templates, no LLM call")
    from .openai_llm import ChainProvider, OpenAIProvider, openai_key
    chain: list = []
    if choice in ("auto", "openai") and (okey := openai_key()):
        chain.append(OpenAIProvider(okey))
    if choice in ("auto", "gemini") and (gkey := gemini_key()):
        chain.append(GeminiProvider(gkey, http=http))
    if not chain:
        if choice == "openai":
            return _Rules("LLM_PROVIDER=openai but no OPENAI_API_KEY: keyword rules and templates, no LLM call")
        if choice == "gemini":
            return _Rules("LLM_PROVIDER=gemini but no GEMINI_API_KEY: keyword rules and templates, no LLM call")
        return RulesProvider()
    if len(chain) == 1 and isinstance(chain[0], GeminiProvider):
        return chain[0]
    return ChainProvider(chain)
