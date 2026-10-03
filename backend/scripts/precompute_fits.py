"""Fit the market universe offline so the stage demo is instant (spec section 4, batch precompute).

    cd backend && uv run python scripts/precompute_fits.py --limit 3            # live APIs, first 3 mapped markets
    cd backend && uv run python scripts/precompute_fits.py --offline            # recorded replays only, no network
    cd backend && uv run --group engine python scripts/precompute_fits.py ...   # with replay scores from hedgecore

Each market is fitted against the first ticker mapped to it in app/data/ai_map.json (markets without a mapping are
skipped). Writes app/data/fits.json keyed "source:id". Without the compiled engine the fits are unscored
(scored=false) and say so. Do not run it live against the whole universe during the event (rate limits).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.pipeline.engine_adapter import EngineAdapter  # noqa: E402
from app.pipeline.llm import default_provider  # noqa: E402
from app.pipeline.service import Deps, FitRequest, MarketRef, fit  # noqa: E402

DATA = BACKEND / "app" / "data"


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


async def run(jobs: list[dict], deps: Deps, shares: float) -> dict:
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
        res = await fit(req, deps)
        fits[j["key"]] = {"question": j.get("question"), "ticker": req.ticker, "direction": req.direction,
                          "shares_held": shares, **res.model_dump(), "scored": res.score is not None}
        print(f"{j['key']:>24} {req.ticker:<6} {res.event_class:<18} {res.family or '-':<22} "
              f"scored={res.score is not None} ticks={res.ticks_source}:{res.n_ticks}", file=sys.stderr)
    return fits


async def amain(argv: list[str] | None = None, deps: Deps | None = None, universe: Path = DATA / "market_universe.json",
                ai_map: Path = DATA / "ai_map.json") -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None, help="fit at most N mapped markets")
    ap.add_argument("--markets", nargs="*", default=None, help="only these ids or source:id keys")
    ap.add_argument("--offline", action="store_true", help="no network: recorded replays only")
    ap.add_argument("--shares", type=float, default=1000.0, help="shares held for the hedge division (default 1000)")
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

        deps = Deps(adapter=EngineAdapter(), provider=default_provider(own_http), http=own_http,
                    massive=massive, offline=a.offline)
    try:
        fits = await run(jobs, deps, a.shares)
    finally:
        if own_http is not None:
            await own_http.aclose()
    _, lib_source = deps.adapter.library()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "generator": "scripts/precompute_fits.py", "library_source": lib_source,
           "can_score": deps.adapter.can_score, "offline": bool(deps.offline), "n": len(fits), "fits": fits}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=1))
    tmp.replace(a.out)
    print(f"wrote {len(fits)} fits to {a.out}", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    asyncio.run(amain(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
