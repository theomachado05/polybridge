from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.markets import polymarket_midpoint


async def record(token_id: str, out: Path, minutes: float, interval: float) -> tuple[int, int]:
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + minutes * 60
    ok = fail = 0
    with out.open("w") as f:
        async with httpx.AsyncClient() as http:
            nxt = time.monotonic()
            while time.monotonic() < deadline:
                try:
                    p = await polymarket_midpoint(http, token_id)
                except Exception as e:
                    p = None
                    print(f"poll failed: {type(e).__name__}", flush=True)
                if p is None:
                    fail += 1
                else:
                    f.write(f'{{"ts_ns": {time.time_ns()}, "p": {p}}}\n')
                    f.flush()
                    ok += 1
                nxt += interval
                await asyncio.sleep(max(0.0, nxt - time.monotonic()))
    return ok, fail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()
    ok, fail = asyncio.run(record(a.token_id, a.out, a.minutes, a.interval))
    print(f"done: {ok} ticks, {fail} failed polls -> {a.out}")


if __name__ == "__main__":
    main()
