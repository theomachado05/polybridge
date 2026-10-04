"""Record live Polymarket order books (top 5 levels per side) to replay JSONL, for the demo.

One row per poll, in the shape ReplaySource reads (every MarketTick field a row carries is kept):

    {"ts_ns", "p" (book mid), "yes_bid", "yes_ask", "no_bid", "no_ask",
     "bid_px_0".."bid_px_4", "bid_qty_0".."bid_qty_4", "ask_px_0".."ask_qty_4", "under_px"?}

``--equity TICKER`` also stamps ``under_px`` (the Massive last trade, refreshed every ``--equity-every`` seconds) so the
hedge families can price an order while replaying. When the equity market is closed that quote is the last session's
last trade and stays constant: the README beside the recording says so. Without MASSIVE_API_KEY ``under_px`` is simply
left out (NaN on replay, never invented). Book depth missing on a side is left out too. Polls that fail are skipped.

    cd backend && uv run --env-file ../.env python scripts/record_book.py \\
        --market indiana-datacenter-2027=5126779 --market iran-invasion-2026=665374 \\
        --equity VRT --equity SPY --outdir ../replays --minutes 10 --interval 1

``--market slug=ID`` takes a Polymarket gamma market id (resolved to its YES token) or a long YES token id.
``--equity`` is matched to ``--market`` by position. Several markets are recorded concurrently.
``--list`` prints the highest 24h-volume open non-sports markets (with YES token ids) and exits.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.ticks import book_fields, book_mid, polymarket_book  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com/markets"
SPORTS = re.compile(r"\b(nba|nfl|mlb|nhl|ncaa|fifa|ufc|mma|tennis|counter-strike|valorant|lol|league of legends|dota|"
                    r"vs\.?|o/u|spread|open:|win on)\b", re.I)


def row_for(bids, asks, ts_ns: int, under_px: float | None) -> dict | None:
    mid = book_mid(bids, asks)
    if mid is None:
        return None
    f = book_fields(bids, asks)
    row: dict = {"ts_ns": ts_ns, "p": round(mid, 6)}
    for k, v in f.items():
        if k == "eightk_score" or not math.isfinite(v):
            continue
        row[k] = v
    if under_px is not None:
        row["under_px"] = under_px
    return row


async def resolve(http: httpx.AsyncClient, spec: str) -> tuple[str, str, str]:
    slug, _, ident = spec.partition("=")
    if not ident:
        raise SystemExit(f"--market needs slug=ID, got {spec!r}")
    if ident.isdigit() and len(ident) >= 30:
        return slug, ident, ""
    r = await http.get(f"{GAMMA}/{ident}", timeout=15)
    r.raise_for_status()
    m = r.json()
    toks = json.loads(m.get("clobTokenIds") or "[]")
    if not toks:
        raise SystemExit(f"market {ident} has no CLOB token")
    return slug, str(toks[0]), m.get("question", "")


async def list_top(http: httpx.AsyncClient, n: int) -> None:
    r = await http.get(GAMMA, params=dict(active="true", closed="false", limit=100, order="volume24hr", ascending="false"), timeout=20)
    r.raise_for_status()
    shown = 0
    for m in r.json():
        if SPORTS.search(m.get("question", "")):
            continue
        toks = json.loads(m.get("clobTokenIds") or "[]")
        if not toks:
            continue
        print(f"{float(m.get('volume24hr') or 0):>10,.0f}  id={m['id']:<8} yes_token={toks[0]}  {m['question'][:80]}")
        shown += 1
        if shown >= n:
            break


async def equity_loop(ticker: str, every: float, state: dict, stop: asyncio.Event) -> None:
    from app.broker.quotes import MassiveQuotes
    q = MassiveQuotes()
    while not stop.is_set():
        quote = await q.equity(ticker)
        if quote is not None:
            state["px"], state["src"] = quote.mid, quote.source
        try:
            await asyncio.wait_for(stop.wait(), every)
        except asyncio.TimeoutError:
            pass


async def record_one(http: httpx.AsyncClient, slug: str, token: str, out: Path, deadline: float, interval: float,
                     equity: dict | None) -> tuple[int, int]:
    ok = fail = 0
    nxt = time.monotonic()
    with out.open("w") as f:
        while time.monotonic() < deadline:
            try:
                bids, asks = await polymarket_book(http, token)
                row = row_for(bids, asks, time.time_ns(), equity.get("px") if equity else None)
            except Exception as e:
                row = None
                print(f"[{slug}] poll failed: {type(e).__name__}", flush=True)
            if row is None:
                fail += 1
            else:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
                f.flush()
                ok += 1
            nxt += interval
            await asyncio.sleep(max(0.0, nxt - time.monotonic()))
    return ok, fail


async def main_async(a: argparse.Namespace) -> int:
    async with httpx.AsyncClient() as http:
        if a.list:
            await list_top(http, a.list)
            return 0
        if not a.market:
            raise SystemExit("give --market slug=ID (or --list)")
        specs = [await resolve(http, m) for m in a.market]
        a.outdir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + a.minutes * 60
        stop = asyncio.Event()
        states: list[dict | None] = []
        tasks = []
        for i, (slug, token, question) in enumerate(specs):
            ticker = a.equity[i] if i < len(a.equity) else None
            st: dict | None = {} if ticker else None
            states.append(st)
            if ticker:
                tasks.append(asyncio.create_task(equity_loop(ticker, a.equity_every, st, stop)))
            print(f"[{slug}] YES token {token[:12]}...  {question}  equity={ticker}", flush=True)
        await asyncio.sleep(2 if a.equity else 0)
        results = await asyncio.gather(*[record_one(http, slug, token, a.outdir / f"{slug}-book.jsonl", deadline, a.interval, st)
                                         for (slug, token, _), st in zip(specs, states)])
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        for (slug, _, _), (ok, fail), st in zip(specs, results, states):
            extra = f", under_px {st.get('px')} ({st.get('src')})" if st else ""
            print(f"[{slug}] {ok} rows, {fail} skipped polls{extra} -> {a.outdir / (slug + '-book.jsonl')}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--market", action="append", default=[], metavar="SLUG=ID")
    ap.add_argument("--equity", action="append", default=[], metavar="TICKER", help="stamp under_px from this ticker (by position)")
    ap.add_argument("--outdir", type=Path, default=BACKEND.parent / "replays")
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--equity-every", type=float, default=15.0)
    ap.add_argument("--list", type=int, nargs="?", const=15, default=0, metavar="N", help="list the top N markets by 24h volume and exit")
    a = ap.parse_args()
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
