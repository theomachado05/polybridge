from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.keys import env_key  # noqa: E402
from app.pipeline import llm, openai_llm  # noqa: E402
from app.pipeline.engine_adapter import EVENT_CLASSES  # noqa: E402
from gemini_check import CLASSIFY_Q, MAP_Q, sample_fit  # noqa: E402

NEWEST = 5


async def run(key: str, client=None, out=print) -> int:
    configured = (os.environ.get("OPENAI_MODEL") or "").strip() or None
    t0 = time.perf_counter()
    try:
        models = await openai_llm.list_models(key, client or openai_llm.make_client(key), use_cache=False)
    except llm.LLMError as e:
        status = str(e)
        if any(f"HTTP {c}" in status for c in (401, 403)):
            out(f"FAIL  OPENAI_API_KEY was rejected ({status}). Check the key in .env (platform.openai.com API key).")
        else:
            out(f"FAIL  could not list models: {status}")
        return 1
    ids = sorted(str(m["id"]) for m in models)
    want = configured or "gpt"
    matching = [i for i in ids if want in i]
    newest = [m["id"] for m in sorted(openai_llm.general_models(models), key=lambda m: -int(m.get("created") or 0))]
    out(f"OK    key accepted: {len(models)} models listed ({(time.perf_counter() - t0) * 1000:.0f} ms)")
    out(f"      ids containing {want!r}: {', '.join(matching[:20]) or 'none'}"
        + (f" (+{len(matching) - 20} more)" if len(matching) > 20 else ""))
    out(f"      newest general text models: {', '.join(newest[:NEWEST]) or 'none'}")
    model, reason = openai_llm.pick_model(models, configured)
    if not model:
        out(f"FAIL  {reason}. The app will not substitute another model: fits and /map use Gemini (when "
            "GEMINI_API_KEY is set) or keyword rules. Set OPENAI_MODEL to one of the ids above, or leave it unset.")
        return 1
    out(f"      OPENAI_MODEL: {configured or '(unset)'} -> the app uses {model}"
        + ("" if configured else " (newest general text model listed; set OPENAI_MODEL to pin one)"))

    p = openai_llm.OpenAIProvider(key, model=model, client=client)
    failures, slow = 0, []

    def timed(name: str, t: float) -> str:
        ms = (time.perf_counter() - t) * 1000
        if ms > p.timeout_s * 1000 * 0.75:
            slow.append(f"{name} {ms:.0f} ms")
        return f"model={p.model} latency={ms:.0f} ms"

    t = time.perf_counter()
    try:
        cls = await p.classify(CLASSIFY_Q, list(EVENT_CLASSES) + ["unsupported"])
        out(f"OK    classify  {timed('classify', t)}  {CLASSIFY_Q!r} -> {cls}")
    except llm.LLMError as e:
        failures += 1
        out(f"FAIL  classify  {timed('classify', t)}: {e}")

    t = time.perf_counter()
    fit = sample_fit()
    try:
        text = await p.explain(fit)
        out(f"OK    explain   {timed('explain', t)}  ({fit.get('family')} #{fit.get('preset_index')} for "
            f"{fit.get('ticker')}):")
        out(f"      {text}")
    except llm.LLMError as e:
        failures += 1
        out(f"FAIL  explain   {timed('explain', t)}: {e}")

    from app.mapping import LIVE_MAX_ITEMS, ticker_universe, validate_mappings
    universe = ticker_universe()
    t = time.perf_counter()
    try:
        rows = await p.map_tickers(MAP_Q, universe, LIVE_MAX_ITEMS)
        items, dropped = validate_mappings(rows, {u["ticker"] for u in universe})
        out(f"OK    map       {timed('map', t)}  {MAP_Q!r} -> {len(items)} valid of {len(rows)} rows "
            f"(universe {len(universe)} tickers)")
        for i in items:
            out(f"      {i['ticker']:<6} {i['direction']:<12} ~{i['impact_pct']:g}%  {i['rationale']}")
        for d in dropped:
            out(f"      dropped: {d}")
    except llm.LLMError as e:
        failures += 1
        out(f"FAIL  map       {timed('map', t)}: {e}")

    if slow:
        out(f"WARN  close to the {p.timeout_s:g} s per-call timeout: {', '.join(slow)}")
    if failures:
        out(f"FAIL  {failures} of 3 OpenAI calls failed")
        return 1
    out(f"OK    OpenAI is live: fit responses will report llm \"openai:{p.model}\"")
    return 0


def main() -> int:
    key = env_key("OPENAI_API_KEY")
    if not key:
        print("FAIL  OPENAI_API_KEY is missing: add a line OPENAI_API_KEY=<key> to the repo-root .env "
              "(never commit it), then rerun make openai-check.")
        return 2
    return asyncio.run(run(key))


if __name__ == "__main__":
    sys.exit(main())
