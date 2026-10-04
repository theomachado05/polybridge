from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.keys import env_key  # noqa: E402
from app.pipeline import llm  # noqa: E402
from app.pipeline.engine_adapter import EVENT_CLASSES  # noqa: E402
from app.pipeline.explain import facts  # noqa: E402

CLASSIFY_Q = "Will the Fed cut interest rates at the December 2026 meeting?"
MAP_Q = "Will the US ban short-term rentals such as Airbnb nationwide by 2027?"
FITS = Path(__file__).resolve().parents[1] / "app" / "data" / "fits.json"


def sample_fit() -> dict:
    try:
        fits = json.loads(FITS.read_text())["fits"]
        for f in fits.values():
            if f.get("score") is not None and f.get("family"):
                return facts(f)
    except (OSError, ValueError, KeyError):
        pass
    return facts({"event_class": "macro_fed", "division": "hedge", "family": "macro_fed_hedge", "preset_index": 0,
                  "params": {}, "score": None, "scored": False, "ticker": "TLT"})


async def run(key: str, http: httpx.AsyncClient | None = None, out=print) -> int:
    own = http is None
    http = http or httpx.AsyncClient()
    try:
        t0 = time.perf_counter()
        try:
            models = await llm.list_models(key, http, use_cache=False)
        except llm.LLMError as e:
            status = str(e)
            if any(f"HTTP {c}" in status for c in (400, 401, 403)):
                out(f"FAIL  GEMINI_API_KEY was rejected ({status}). Check the key in .env (AI Studio key, "
                    "Generative Language API enabled).")
            else:
                out(f"FAIL  could not list models: {status}")
            return 1
        gen = sorted(str(m.get("name", "")).removeprefix("models/") for m in models
                     if "generateContent" in (m.get("supportedGenerationMethods") or []))
        flash = [m for m in gen if "flash" in m]
        newest = llm.newest_flash(models)
        out(f"OK    key accepted: {len(models)} models listed, {len(gen)} support generateContent "
            f"({(time.perf_counter() - t0) * 1000:.0f} ms)")
        out(f"      flash models: {', '.join(flash) or 'none'}")
        if not newest:
            out("FAIL  no general-purpose flash generateContent model is available to this key")
            return 1
        configured = os.environ.get("GEMINI_MODEL") or llm.DEFAULT_MODEL
        listed = configured in gen
        out(f"      newest flash: {newest}; configured model: {configured} "
            + ("(listed)" if listed else "(NOT listed: the app falls back to the newest flash model on its first 404)"))

        p = llm.GeminiProvider(key, model=configured if listed else newest, http=http)
        failures = 0

        t = time.perf_counter()
        try:
            cls = await p.classify(CLASSIFY_Q, list(EVENT_CLASSES) + ["unsupported"])
            out(f"OK    classify  model={p.model} latency={(time.perf_counter() - t) * 1000:.0f} ms  "
                f"{CLASSIFY_Q!r} -> {cls}")
        except llm.LLMError as e:
            failures += 1
            out(f"FAIL  classify  model={p.model}: {e}")

        t = time.perf_counter()
        fit = sample_fit()
        try:
            text = await p.explain(fit)
            out(f"OK    explain   model={p.model} latency={(time.perf_counter() - t) * 1000:.0f} ms  "
                f"({fit.get('family')} #{fit.get('preset_index')} for {fit.get('ticker')}):")
            out(f"      {text}")
        except llm.LLMError as e:
            failures += 1
            out(f"FAIL  explain   model={p.model}: {e}")

        from app.mapping import LIVE_MAX_ITEMS, ticker_universe, validate_mappings
        universe = ticker_universe()
        t = time.perf_counter()
        try:
            rows = await p.map_tickers(MAP_Q, universe, LIVE_MAX_ITEMS)
            items, dropped = validate_mappings(rows, {u["ticker"] for u in universe})
            out(f"OK    map       model={p.model} latency={(time.perf_counter() - t) * 1000:.0f} ms  "
                f"{MAP_Q!r} -> {len(items)} valid of {len(rows)} rows (universe {len(universe)} tickers)")
            for i in items:
                out(f"      {i['ticker']:<6} {i['direction']:<12} ~{i['impact_pct']:g}%  {i['rationale']}")
            for d in dropped:
                out(f"      dropped: {d}")
        except llm.LLMError as e:
            failures += 1
            out(f"FAIL  map       model={p.model}: {e}")

        if failures:
            out(f"FAIL  {failures} of 3 Gemini calls failed")
            return 1
        out(f"OK    Gemini is live: fit responses will report llm \"gemini:{p.model}\"")
        return 0
    finally:
        if own:
            await http.aclose()


def main() -> int:
    key = env_key("GEMINI_API_KEY")
    if not key:
        print("FAIL  GEMINI_API_KEY is missing: add a line GEMINI_API_KEY=<key> to the repo-root .env "
              "(never commit it), then rerun make gemini-check.")
        return 2
    return asyncio.run(run(key))


if __name__ == "__main__":
    sys.exit(main())
