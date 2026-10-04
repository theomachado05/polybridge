"""Fit the market universe offline so the stage demo is instant (spec section 4, batch precompute).

    cd backend && uv run python scripts/precompute_fits.py --limit 3            # live APIs, first 3 mapped markets
    cd backend && uv run python scripts/precompute_fits.py --offline            # recorded replays only, no network
    cd backend && uv run --group engine --env-file ../.env python scripts/precompute_fits.py \
        --provider rules --log data_logs/precompute_fits.log                    # the committed run: real engine

Each market is fitted against the first ticker mapped to it in app/data/ai_map.json (markets without a mapping are
skipped). Writes app/data/fits.json keyed "source:id", plus a "summary" block: how many fits were scored by the
compiled engine, and which markets fell back to a recorded replay or had no price history at all. Without the
compiled engine the fits are unscored (scored=false) and say so. Every fit is bounded by --fit-timeout (the network
chain inside a fit is bounded too); a fit that overruns is recorded as unfitted, never retried in a loop.
Do not run it live against the whole universe during the event (rate limits).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.pipeline.engine_adapter import EngineAdapter  # noqa: E402
from app.pipeline.llm import RulesProvider, default_provider  # noqa: E402
from app.pipeline.service import Deps, FitRequest, MarketRef, fit  # noqa: E402

DATA = BACKEND / "app" / "data"
FIT_TIMEOUT_S = 60.0


def load_jobs(universe: Path, ai_map: Path, limit: int | None = None, only: list[str] | None = None) -> list[dict]:
    markets = json.loads(universe.read_text()).get("markets", [])
    items = json.loads(ai_map.read_text()).get("items", {})
    jobs = []
    for m in markets:
        key = f"{m.get('source')}:{m.get('id')}"
        if only and key not in only and str(m.get("id")) not in only:
            continue
        maps = (items.get(key) or {}).get("mappings") or []
        if not maps or not maps[0].get("ticker"):
            continue
        jobs.append({"key": key, "source": m["source"], "id": str(m["id"]), "question": m.get("question"),
                     "token_id": m.get("token_id"), "ticker": maps[0]["ticker"],
                     "direction": maps[0].get("direction") or "down_on_yes"})
        if limit and len(jobs) >= limit:
            break
    return jobs


def _unfitted(req: FitRequest, why: str) -> dict:
    return {"event_class": "unsupported", "division": None, "family": None, "preset_index": None, "params": {},
            "score": None, "alternatives": [], "rationale": f"No fit: {why}.", "llm": "rules", "ticks_source": "none",
            "n_ticks": 0}


async def run(jobs: list[dict], deps: Deps, shares: float, fit_timeout_s: float = FIT_TIMEOUT_S,
              log=None) -> dict:
    fits = {}
    for j in jobs:
        try:
            req = FitRequest(market=MarketRef(source=j["source"], id=j["id"], token_id=j.get("token_id")),
                             question=j.get("question"), ticker=j["ticker"],
                             direction=j["direction"] if j["direction"] in ("down_on_yes", "up_on_yes") else "down_on_yes",
                             shares_held=shares)
        except Exception as e:
            print(f"skip {j['key']}: {type(e).__name__}", file=sys.stderr)
            continue
        t0 = time.monotonic()
        timed_out = False
        try:
            res = (await asyncio.wait_for(fit(req, deps), fit_timeout_s)).model_dump()
        except asyncio.TimeoutError:
            res, timed_out = _unfitted(req, f"the fit took over {fit_timeout_s:g} s"), True
        fits[j["key"]] = {"question": j.get("question"), "ticker": req.ticker, "direction": req.direction,
                          "shares_held": shares, **res, "scored": res["score"] is not None,
                          "timed_out": timed_out, "elapsed_s": round(time.monotonic() - t0, 2)}
        line = (f"{j['key']:>24} {req.ticker:<6} {res['event_class']:<18} {res['family'] or '-':<22} "
                f"preset={res['preset_index'] if res['preset_index'] is not None else '-':<4} "
                f"scored={res['score'] is not None!s:<5} ticks={res['ticks_source']}:{res['n_ticks']}"
                f"{_score_text(res)}{' TIMEOUT' if timed_out else ''}")
        print(line, file=sys.stderr)
        if log is not None:
            log.append(line)
    return fits


def _score_text(res: dict) -> str:
    if res.get("score") is None:
        return ""
    if res.get("score_basis") == "hedge_var_reduction_vs_static":
        raw, h = res.get("score_raw"), res.get("avg_hedge_ratio")
        return (f" vs_static={res['score']:+.3f} raw={raw:.3f}" if raw is not None else f" vs_static={res['score']:+.3f}") \
            + (f" h={h:.2f}" if h is not None else "")
    return f" score={res['score']:+.3f}"


def hedge_score_stats(fits: dict) -> dict:
    """Distribution of the hedge ranking score (variance cut beyond a same-size static hedge) over scored fits."""
    v = sorted(f["score"] for f in fits.values()
               if f.get("score") is not None and f.get("score_basis") == "hedge_var_reduction_vs_static")
    if not v:
        return {"n": 0}
    mid = len(v) // 2
    median = v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
    return {"n": len(v), "gt0": sum(1 for x in v if x > 0), "le0": sum(1 for x in v if x <= 0),
            "median": round(median, 4), "max": round(v[-1], 4), "min": round(v[0], 4)}


def summarize(fits: dict) -> dict:
    by_source = Counter(f["ticks_source"] for f in fits.values())
    return {
        "n": len(fits),
        "scored": sum(1 for f in fits.values() if f["scored"]),
        "fitted": sum(1 for f in fits.values() if f["family"]),
        "ticks_source": dict(by_source),
        "fell_back_to_replay": sorted(k for k, f in fits.items() if f["ticks_source"] == "replay"),
        "no_history": sorted(k for k, f in fits.items() if f["ticks_source"] == "none"),
        "timed_out": sorted(k for k, f in fits.items() if f.get("timed_out")),
        "families": dict(Counter(f["family"] or "-" for f in fits.values()).most_common()),
        "event_classes": dict(Counter(f["event_class"] for f in fits.values()).most_common()),
        # score_vs_static: hedge variance cut beyond a static short of the same average size (the ranking score)
        "score_vs_static": hedge_score_stats(fits),
        # rules picks because no preset had a defined vs-static score (never ranked on raw variance reduction)
        "no_static_benchmark": sorted(k for k, f in fits.items()
                                      if not f["scored"] and f.get("no_static_benchmark")),
    }


async def amain(argv: list[str] | None = None, deps: Deps | None = None, universe: Path = DATA / "market_universe.json",
                ai_map: Path = DATA / "ai_map.json") -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None, help="fit at most N mapped markets")
    ap.add_argument("--markets", nargs="*", default=None, help="only these ids or source:id keys")
    ap.add_argument("--offline", action="store_true", help="no network: recorded replays only")
    ap.add_argument("--shares", type=float, default=1000.0, help="shares held for the hedge division (default 1000)")
    ap.add_argument("--provider", choices=("auto", "rules"), default="auto",
                    help="auto: the provider factory (OpenAI -> Gemini -> rules, LLM_PROVIDER); rules: keyword rules only")
    ap.add_argument("--fit-timeout", type=float, default=FIT_TIMEOUT_S, help="seconds per market (default 60)")
    ap.add_argument("--log", type=Path, default=None, help="also write the per-market lines and the summary here")
    ap.add_argument("--out", type=Path, default=DATA / "fits.json")
    a = ap.parse_args(argv)

    jobs = load_jobs(universe, ai_map, a.limit, a.markets)
    own_http = None
    if deps is None:
        from app import chain
        own_http = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        client_box: list = []

        def massive():
            if not client_box:
                client_box.append(chain.make_client())
            return client_box[0]

        provider = RulesProvider() if a.provider == "rules" else default_provider(own_http)
        deps = Deps(adapter=EngineAdapter(), provider=provider, http=own_http, massive=massive, offline=a.offline)
    lines: list[str] = []
    started = datetime.now(timezone.utc)
    try:
        fits = await run(jobs, deps, a.shares, a.fit_timeout, lines)
    finally:
        if own_http is not None:
            await own_http.aclose()
    _, lib_source = deps.adapter.library()
    summary = summarize(fits)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "generator": "scripts/precompute_fits.py", "library_source": lib_source,
           "can_score": deps.adapter.can_score, "offline": bool(deps.offline),
           "provider": getattr(deps.provider, "name", type(deps.provider).__name__),
           "n": len(fits), "summary": summary, "fits": fits}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=1))
    tmp.replace(a.out)
    print(f"wrote {len(fits)} fits to {a.out}", file=sys.stderr)
    if a.log is not None:
        head = [f"# precompute_fits run {started.isoformat(timespec='seconds')} -> {out['generated_at']}",
                f"# library={lib_source} can_score={out['can_score']} provider={out['provider']} "
                f"offline={out['offline']} shares={a.shares:g} fit_timeout={a.fit_timeout:g}s jobs={len(jobs)}", ""]
        tail = ["", "# summary", json.dumps(summary, indent=1)]
        a.log.parent.mkdir(parents=True, exist_ok=True)
        a.log.write_text("\n".join(head + lines + tail) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    asyncio.run(amain(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
