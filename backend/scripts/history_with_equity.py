"""A month of real Polymarket price history as a replay JSONL that also carries the equity price, so the demo replay
can hedge without any other file: each row is ``{"ts_ns", "p", "under_px"}``.

``under_px`` is the close of the last Massive bar that had already ENDED at the row's time (bar start + span: no
look-ahead, same rule as app.pipeline.ticks). Rows before the first finished bar carry no ``under_px`` (NaN on replay).
Needs MASSIVE_API_KEY (read by the client, never printed). Price history is a mid-price series: the true spread
and the book depth at those times are unknown and are not invented (see record_book.py for depth).

    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py \\
        --market indiana-datacenter-2027=5126779 --equity VRT --out ../replays/indiana-datacenter-2027-history.jsonl

Replay it at the demo speed: POLYBRIDGE_REPLAY_SPEED=36000 (hourly points, ten ticks per second).
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from history_to_replay import fetch as fetch_history  # noqa: E402
from record_book import resolve  # noqa: E402
from record_equity_bars import fetch as fetch_bars  # noqa: E402

from app.pipeline.ticks import BAR_SPAN_S  # noqa: E402


def join(rows: list[dict], span_s: int, bars: list[dict]) -> list[dict]:
    """Stamp each row with the close of the last bar already finished at its time."""
    known = [b["t"] + span_s for b in bars]
    out = []
    for r in rows:
        j = bisect.bisect_right(known, r["ts_ns"] // 1_000_000_000) - 1
        out.append({**r, "under_px": bars[j]["c"]} if j >= 0 else dict(r))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--market", required=True, metavar="SLUG=ID")
    ap.add_argument("--equity", required=True, metavar="TICKER")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    slug, token, question = asyncio.run(_resolve(a.market))
    with httpx.Client() as http:
        rows = fetch_history(token, http)
    from app import chain
    client = chain.make_client()
    if client is None:
        print("MASSIVE_API_KEY is not set: writing the history without under_px", file=sys.stderr)
        joined = rows
    else:
        lo, hi = rows[0]["ts_ns"] // 1_000_000_000, rows[-1]["ts_ns"] // 1_000_000_000
        span, bars = fetch_bars(client, a.equity, lo, hi)
        if not bars:
            print(f"no Massive bars for {a.equity.upper()}: writing the history without under_px", file=sys.stderr)
            joined = rows
        else:
            joined = join(rows, BAR_SPAN_S[span], bars)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in joined))
    ps = [r["p"] for r in joined]
    n_eq = sum(1 for r in joined if "under_px" in r)
    print(f"{question or slug}: {len(joined)} points, p {min(ps):.4f}..{max(ps):.4f}, {n_eq} with under_px -> {a.out}")
    return 0


async def _resolve(spec: str):
    async with httpx.AsyncClient() as http:
        return await resolve(http, spec)


if __name__ == "__main__":
    raise SystemExit(main())
