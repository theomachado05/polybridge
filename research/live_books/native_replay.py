from __future__ import annotations

import argparse
import asyncio
import json
import random
import threading
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.server import serve

import live_books  # noqa: F401

from . import bench_replay as B
from . import reference as R
from .recorder import OUT


def setup(engines, mk: dict[str, list[str]], seed: int):
    rng = random.Random(seed)
    for i, (_, ids) in enumerate(sorted(mk.items())):
        p, fees = B.ref_draw(rng), rng.random() < 0.6
        for e in engines:
            e.set_market(i, p, fees)
            for j, a in enumerate(sorted(ids)):
                e.add_asset(a, i, j == 0)


def serve_frames(msgs: list, pause_every: int, ready: threading.Event, port: list, done: threading.Event):
    async def handler(ws):
        await ws.recv()
        for k, m in enumerate(msgs):
            if m is None:
                await ws.ping()
            else:
                await ws.send(m)
            if pause_every and k % pause_every == pause_every - 1:
                await asyncio.sleep(0.002)
        await ws.send("PONG")
        await asyncio.sleep(0.5)

    async def main():
        async with serve(handler, "127.0.0.1", 0, compression=None, max_size=2 ** 24) as srv:
            port.append(srv.sockets[0].getsockname()[1])
            ready.set()
            while not done.is_set():
                await asyncio.sleep(0.05)

    asyncio.run(main())


def run(msgs: list, mk: dict[str, list[str]], seed: int = 7, spin: bool = True, warm_us: int = 50,
        pause_every: int = 500, timeout: float = 600.0) -> dict:
    from .hedgecore_book import BookEngine, WsFeed

    ref, nat = BookEngine(R.TAU), BookEngine(R.TAU)
    setup((ref, nat), mk, seed)
    sent = [m if isinstance(m, (bytes, type(None))) else m.encode() if isinstance(m, str) else b"".join(
        x.encode() for x in m) for m in msgs]
    expect = [m for m in sent if m is not None and m != b"PONG"]
    ready, done, port = threading.Event(), threading.Event(), []
    th = threading.Thread(target=serve_frames, args=(msgs, pause_every, ready, port, done), daemon=True)
    th.start()
    ready.wait(10)
    feed = WsFeed(nat, "127.0.0.1", port[0], "/", False, "", spin, 10, warm_us)
    feed.start([json.dumps({"assets_ids": [], "type": "market"})])
    got, lat_sock, lat_t0 = [], [], []
    t_end = time.time() + timeout
    try:
        while len(got) < len(expect) and time.time() < t_end:
            time.sleep(0.005)
            frames, _ = feed.drain()
            got.extend(frames)
    finally:
        feed.stop()
        done.set()
    mism = raw_mism = n_dec = 0
    first = None
    for k, (fr, raw) in enumerate(zip(got, expect)):
        _, n, ts, tv, tr, t0, graw, dn = fr
        if graw != raw:
            raw_mism += 1
        nr = ref.process(raw, 0, 0)
        dr = ref.decisions() if nr > 0 else []
        n_dec += len(dr)
        lat_sock.extend(d[15] - ts for d in dn)
        lat_t0.extend(d[15] - t0 for d in dn)
        if n != nr or len(dr) != len(dn) or not all(B.same(x, y) for x, y in zip(dr, dn)):
            mism += 1
            if first is None:
                first = (k, raw[:200], dr[:2], dn[:2])
    return dict(sent=len(expect), got=len(got), raw_mism=raw_mism, mism=mism, first=first, n_dec=n_dec,
                sock=B.pct(lat_sock) if lat_sock else None, t0=B.pct(lat_t0) if lat_t0 else None)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=OUT / "raw")
    ap.add_argument("--all", action="store_true", help="include the newest raw file")
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--no-spin", action="store_true")
    ap.add_argument("--warm-us", type=int, default=50)
    a = ap.parse_args(argv)
    files = sorted(a.raw.glob("raw_*.jsonl.gz"))
    if not a.all:
        files = files[:-1]
    if a.max_files:
        files = files[:a.max_files]
    msgs = [raw.decode() for f in files for _, raw in B.frames(f) if raw not in (b"PONG", b'"PONG"')]
    r = run(msgs, B.universe(files), spin=not a.no_spin, warm_us=a.warm_us)
    print(f"files: {', '.join(f.name for f in files)}")
    print(f"frames sent {r['sent']:,}, received by the native client {r['got']:,}, raw bytes differing {r['raw_mism']}, "
          f"decisions {r['n_dec']:,}; frames whose decisions differ from BookEngine.process: {r['mism']}")
    if r["first"]:
        print("first mismatch:", r["first"])
    for name, k in (("loopback socket to decision (t2 - ts)", "sock"), ("frame decoded to decision (t2 - t0)", "t0")):
        if r[k]:
            print(f"| {name} | " + " | ".join(f"{v:,.2f}" for v in r[k]) + " |")


if __name__ == "__main__":
    main()
