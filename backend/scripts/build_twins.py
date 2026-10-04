from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.twins.build import build_map, run  # noqa: E402
from app.twins.sources import DATA, fetch_kalshi, fetch_polymarket, universe_ids  # noqa: E402


async def main(args: argparse.Namespace) -> int:
    out = Path(args.out)
    async with httpx.AsyncClient(headers={"User-Agent": "polybridge-twins/1"}) as http:
        if args.cache and Path(args.cache).is_file():
            raw = json.loads(Path(args.cache).read_text())
            doc = build_map(raw["polymarket"], raw["kalshi"])
        elif args.cache:
            poly = await fetch_polymarket(http, universe_ids(), top_n=args.top, log=print)
            kal = await fetch_kalshi(http, log=print)
            if not poly or not kal:
                print("a venue returned nothing; map not written", file=sys.stderr)
                return 1
            Path(args.cache).write_text(json.dumps({"polymarket": poly, "kalshi": kal}))
            doc = build_map(poly, kal)
        else:
            try:
                doc = await run(http, top_n=args.top)
            except RuntimeError as e:
                print(str(e), file=sys.stderr)
                return 1
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    s = doc["stats"]
    print(f"wrote {out}: {s['verified']} verified, {s['ambiguous']} ambiguous "
          f"({s['polymarket_markets']} polymarket x {s['kalshi_markets']} kalshi markets)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "kalshi_twins.json"))
    ap.add_argument("--top", type=int, default=2000, help="top-N live Polymarket markets by 24h volume")
    ap.add_argument("--cache", help="raw-fetch cache file: reused if present, else written after fetching")
    sys.exit(asyncio.run(main(ap.parse_args())))
