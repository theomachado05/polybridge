from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json
import logging
import os
import signal
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import websockets
from websockets.asyncio.client import ClientConnection

import live_books  # noqa: F401
from arbscan import datasrc as ds
from forward_monday import config as FC
from forward_monday import core as FM
from forward_monday.run import listing, sessions, universe
from polybridge_research.massive import MassiveClient, load_api_key

from . import detector, reference as R
from .pybook import PyBookEngine

try:
    from .hedgecore_book import BookEngine, keep_warm, set_interactive_qos
    BOOK_IMPL = "cpp_book"
except ImportError:
    BookEngine, BOOK_IMPL = PyBookEngine, "python_book"
    keep_warm = set_interactive_qos = None
try:
    from .hedgecore_book import WsFeed
except ImportError:
    WsFeed = None

UTC = timezone.utc
WS_HOST, WS_PATH = "ws-subscriptions-clob.polymarket.com", "/ws/market"
WS_URL = f"wss://{WS_HOST}{WS_PATH}"
CA_FILES = ("/opt/homebrew/etc/openssl@3/cert.pem", "/usr/local/etc/openssl@3/cert.pem", "/etc/ssl/cert.pem")
DRAIN_SEC = 0.002
OUT = FC.RESEARCH_DIR / "results" / "live_books"
SNAPSHOT = FC.PKG_DIR / f"snapshot_{FC.SNAPSHOT_DATE}.csv"
CHUNK = 200
UNIVERSE_SEC = 1800
REF_MIN_SEC = 5.0
REF_FRESH_SEC = 60.0
PING_SEC = 10
FLUSH_SEC = 30
DISK_SEC = 60
RAW_CAP = 5 * 1024 ** 3
UNTIL = "2026-10-05T10:30:00-04:00"
KINDS = ("book", "price_change")


class HourlyGz:
    def __init__(self, d: Path, prefix: str, binary: bool = False):
        self.d, self.prefix, self.mode = d, prefix, "ab" if binary else "at"
        d.mkdir(parents=True, exist_ok=True)
        self.hour, self.f, self.path = None, None, None

    def write(self, t_ns: int, line: str | bytes) -> Path | None:
        h = t_ns // 3_600_000_000_000
        closed = None
        if h != self.hour:
            closed = self.close()
            self.hour = h
            stamp = datetime.fromtimestamp(h * 3600, UTC).strftime("%Y%m%dT%H")
            self.path = self.d / f"{self.prefix}_{stamp}.jsonl.gz"
            self.f = gzip.open(self.path, self.mode, compresslevel=5)
        self.f.write(line)
        return closed

    def flush(self):
        if self.f:
            self.f.flush()

    def close(self) -> Path | None:
        if self.f:
            self.f.close()
            self.f = None
            return self.path
        return None


def dir_bytes(d: Path) -> int:
    return sum(p.stat().st_size for p in d.glob("*.jsonl.gz"))


def yes_no(meta: dict) -> tuple[str, str]:
    toks, outs = FM._jl(meta.get("clobTokenIds")), [str(o).lower() for o in FM._jl(meta.get("outcomes"))]
    if len(toks) != 2:
        return "", ""
    if outs == ["no", "yes"]:
        return toks[1], toks[0]
    return toks[0], toks[1]


class StampedConnection(ClientConnection):
    t_read = 0

    def data_received(self, data: bytes) -> None:
        self.t_read = time.perf_counter_ns()
        super().data_received(data)


class Recorder:
    def __init__(self, out: Path, until: datetime, raw_cap: int, warm: bool = True, native: bool = True,
                 spin: bool = True, warm_us: int = 200):
        self.out, self.until, self.raw_cap = out, until, raw_cap
        self.native = native and WsFeed is not None and BOOK_IMPL == "cpp_book"
        self.spin = self.native and spin
        self.warm_us = warm_us if self.spin else 0
        self.impl = ("native_ws_spin" if self.spin else "native_ws") if self.native else BOOK_IMPL
        self.warm = warm and keep_warm is not None and not self.spin
        self.raw = HourlyGz(out / "raw", "raw", binary=True)
        self.dec = HourlyGz(out / "decisions", "decisions")
        self.gaps = (out / "gaps.jsonl").open("a")
        self.log = logging.getLogger("live_books")
        self.sess = sessions()
        self.http = ds.Http(out / ".cache" / "http")
        key = load_api_key(search_from=FC.RESEARCH_DIR, interactive=False)
        self.opts = ds.OptionSource(MassiveClient(key, cache_dir=out / ".cache" / "massive"), datetime.now(UTC).date())
        self.live = R.LiveQuotes(key)
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.markets: dict[str, dict] = {}
        self.assets: dict[str, tuple[str, bool]] = {}
        self.engine = BookEngine(R.TAU, 0.04, 1.0)
        self.mid_idx: dict[str, int] = {}
        self.slot_info: dict[int, tuple[str, bool]] = {}
        self.refs: dict[str, R.Ref] = {}
        self.snapshot_ids = {r["id"] for r in csv.DictReader(SNAPSHOT.open())}
        self.raw_on = True
        self.raw_bytes = dir_bytes(out / "raw")
        self.in_sess = R.in_session(datetime.now(UTC), self.sess)
        self.counts: Counter = Counter()
        self.stop = asyncio.Event()
        self.resub = asyncio.Event()

    def build_universe(self) -> dict[str, dict]:
        today = datetime.now(R.ET).date()
        reo = [d for d in FM.reopenings(self.sess) if FM.week_end(d, self.sess) >= today]
        if not reo:
            return {}
        meta = listing(self.http, reo[0], FM.week_end(reo[-1], self.sess), closed_states=("false",))
        by_id = {str(m["id"]): m for m in meta}
        scope: Counter = Counter()
        out = {}
        for d in reo:
            for r in universe(meta, d, self.sess, self.opts, scope):
                y, n = yes_no(by_id[r["id"]])
                if y and n and r["id"] not in out:
                    out[r["id"]] = {**r, "yes": y, "no": n, "in_snapshot": r["id"] in self.snapshot_ids}
        missing = sorted(self.snapshot_ids - set(out))
        self.log.info("universe: %d markets (%d in snapshot, %d new), %d snapshot ids not open or not eligible now; drops %s",
                      len(out), sum(m["in_snapshot"] for m in out.values()), sum(not m["in_snapshot"] for m in out.values()),
                      len(missing), dict(scope))
        return out

    def close_refs(self, mids: list[str]):
        d = R.last_close(datetime.now(UTC), self.sess)
        basis = f"close_{d}"
        todo = [m for m in mids if self.refs.get(m) is None or self.refs[m].basis != basis]
        for mid, ref in zip(todo, self.pool.map(lambda m: R.close_ref(self.opts, self.markets[m], d), todo)):
            self.set_ref(mid, ref)
        if todo:
            ok = sum(self.refs[m].status == "ok" for m in todo)
            self.log.info("close references (%s): %d computed, %d usable", basis, len(todo), ok)

    def live_refs(self):
        now = time.time_ns()
        due = [m for m in self.markets if (r := self.refs.get(m)) is None or r.basis != "live"
               or now - r.computed_ns > REF_MIN_SEC * 1e9]
        for mid, ref in zip(due, self.pool.map(lambda m: R.live_ref(self.opts, self.live, self.markets[m]), due)):
            self.set_ref(mid, ref)

    def set_ref(self, mid: str, ref: R.Ref):
        self.refs[mid] = ref
        i = self.mid_idx.get(mid)
        if i is not None:
            self.engine.set_p(i, ref.p)

    async def universe_loop(self):
        while not self.stop.is_set():
            try:
                new = await asyncio.to_thread(self.build_universe)
                if new:
                    old = set(self.assets)
                    self.markets.update(new)
                    for mid in [m for m in self.markets if m not in new]:
                        self.markets.pop(mid)
                        self.refs.pop(mid, None)
                        if mid in self.mid_idx:
                            self.engine.set_p(self.mid_idx[mid], float("nan"))
                    self.assets = {}
                    for mid, m in self.markets.items():
                        self.assets[m["yes"]] = (mid, True)
                        self.assets[m["no"]] = (mid, False)
                    for a in old - set(self.assets):
                        self.engine.remove_asset(a)
                    for mid, m in self.markets.items():
                        i = self.mid_idx.setdefault(mid, len(self.mid_idx))
                        ref = self.refs.get(mid)
                        self.engine.set_market(i, ref.p if ref is not None else float("nan"), bool(m["fees_listing"]))
                    for a, (mid, is_yes) in self.assets.items():
                        self.slot_info[self.engine.add_asset(a, self.mid_idx[mid], is_yes)] = (mid, is_yes)
                    if not self.in_sess:
                        await asyncio.to_thread(self.close_refs, list(self.markets))
                    if set(self.assets) != old:
                        self.resub.set()
            except Exception as e:
                self.log.exception("universe refresh failed: %s", e)
            try:
                await asyncio.wait_for(self.stop.wait(), UNIVERSE_SEC)
            except asyncio.TimeoutError:
                pass

    async def ref_loop(self):
        while not self.stop.is_set():
            try:
                if self.markets:
                    if self.in_sess:
                        await asyncio.to_thread(self.live_refs)
                    else:
                        await asyncio.to_thread(self.close_refs, list(self.markets))
            except Exception as e:
                self.log.exception("reference refresh failed: %s", e)
            await asyncio.sleep(2.0)

    def on_message(self, raw: bytes, t0: int, t0m: int, tr: int | None = None):
        if raw == b"PONG":
            return
        n = self.engine.process(raw, t0, t0m)
        self.on_frame(raw, n, t0, None, tr, self.engine.decisions() if n > 0 else ())

    def on_frame(self, raw: bytes, n: int, t0: int, ts: int | None, tr: int | None, decs, tv: int | None = None):
        self.counts["msgs"] += 1
        if n < 0:
            self.counts["bad_json"] += 1
        if self.raw_on:
            raw = raw.rstrip()
            if b"\n" in raw:
                raw = raw.replace(b"\n", b" ")
            closed = self.raw.write(t0, b'{"t":%d,"m":%b}\n' % (t0, raw))
            if closed:
                self.log.info("raw hour closed %s: %.1f MB, raw dir %.1f MB", closed.name, closed.stat().st_size / 1e6,
                              dir_bytes(closed.parent) / 1e6)
        for d in decs:
            self.log_decision(t0, d, ts, tr, tv)

    def log_decision(self, t0: int, d: tuple, ts: int | None = None, tr: int | None = None, tv: int | None = None):
        slot, kind, side, yb, ybs, ya, yas, bdep, adep, p, edge, net, px, sz, t1, t2 = d
        mid, is_yes = self.slot_info[slot]
        ref = self.refs.get(mid)
        m = self.markets[mid]
        stale = not (self.in_sess and ref is not None and ref.basis == "live" and t2 - ref.computed_ns <= REF_FRESH_SEC * 1e9)
        self.counts["decisions"] += 1
        if side:
            self.counts["flagged"] += 1
            if not stale:
                self.counts["flagged_fresh"] += 1
        row = {"ts": ts, "tv": tv, "tr": tr, "t0": t0, "t1": t1, "t2": t2, "kind": KINDS[kind], "mid": mid, "tok": "yes" if is_yes else "no", "tk": m["tk"],
               "k": m["k"], "res": m["res_date"], "bid": yb, "bid_sz": ybs, "ask": ya, "ask_sz": yas,
               "bid_depth_2c": bdep, "ask_depth_2c": adep,
               "p_ref": None if p != p else round(p, 5), "ref_basis": ref.basis if ref else None,
               "ref_age_s": None if ref is None else round((t2 - ref.computed_ns) / 1e9, 1),
               "quote_age_s": None if ref is None or ref.quote_ts != ref.quote_ts else round(t2 / 1e9 - ref.quote_ts, 1),
               "reference_stale": stale, "in_window": t2 // 1_000_000_000 >= int(m["w0"]) and t2 // 1_000_000_000 <= int(m["w1"])
               and str(datetime.fromtimestamp(t2 / 1e9, R.ET).date()) == m["reopening"],
               "decision": detector.SIDES[side], "edge_pt": round(edge, 3), "net_edge_pt": round(net, 3),
               "price": None if px != px else round(px, 4), "size": sz, "impl": self.impl, "warm": self.warm or self.warm_us > 0}
        self.dec.write(t2, json.dumps(row, separators=(",", ":")) + "\n")

    async def pinger(self, ws):
        while True:
            await asyncio.sleep(PING_SEC)
            await ws.send("PING")

    async def conn(self, cid: int, assets: list[str]):
        backoff, down_since, err = 1.0, None, ""
        while not self.stop.is_set():
            try:
                async with websockets.connect(WS_URL, ping_interval=None, max_size=2 ** 24, open_timeout=20,
                                              create_connection=StampedConnection) as ws:
                    await ws.send(json.dumps({"assets_ids": assets, "type": "market"}))
                    if down_since is not None:
                        now = time.time()
                        self.gaps.write(json.dumps({"conn": cid, "gap_start": down_since, "gap_end": now,
                                                    "dur_s": round(now - down_since, 2), "err": err}) + "\n")
                        self.gaps.flush()
                        self.log.warning("conn %d reconnected after %.1fs gap (%s)", cid, now - down_since, err)
                        down_since = None
                    self.log.info("conn %d subscribed to %d assets", cid, len(assets))
                    backoff = 1.0
                    ping = asyncio.create_task(self.pinger(ws))
                    try:
                        while True:
                            try:
                                raw = await ws.recv(decode=False)
                            except websockets.ConnectionClosedOK:
                                break
                            t0m = time.perf_counter_ns()
                            t0 = time.time_ns()
                            self.on_message(raw, t0, t0m, t0 - (t0m - ws.t_read))
                    finally:
                        ping.cancel()
                    err = "closed by server"
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:120]}"
            if down_since is None:
                down_since = time.time()
                self.log.warning("conn %d down: %s", cid, err)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def native_supervisor(self):
        ca = next((c for c in CA_FILES if os.path.exists(c)), "")
        feed = WsFeed(self.engine, WS_HOST, 443, WS_PATH, True, ca, self.spin, PING_SEC, self.warm_us)
        down: dict[int, tuple[float, str]] = {}
        try:
            while not self.stop.is_set():
                if self.resub.is_set():
                    self.resub.clear()
                    al = sorted(self.assets)
                    subs = [json.dumps({"assets_ids": al[j:j + CHUNK], "type": "market"}) for j in range(0, len(al), CHUNK)]
                    await asyncio.to_thread(feed.stop)
                    self.drain(feed, down)
                    down.clear()
                    if subs:
                        await asyncio.to_thread(feed.start, subs)
                    self.log.info("subscribing %d assets (%d markets) over %d native connections (spin %s)", len(al),
                                  len(self.markets), len(subs), self.spin)
                try:
                    self.drain(feed, down)
                except Exception as e:
                    self.log.exception("native drain failed: %s", e)
                await asyncio.sleep(DRAIN_SEC)
        finally:
            await asyncio.to_thread(feed.stop)
            self.drain(feed, down)

    def drain(self, feed, down: dict[int, tuple[float, str]]):
        frames, events = feed.drain()
        for cid, kind, t, msg in events:
            if kind == 1:
                down.setdefault(cid, (t, msg))
                if msg != "stopped":
                    self.log.warning("conn %d down: %s", cid, msg)
            elif cid in down:
                t_down, err = down.pop(cid)
                self.gaps.write(json.dumps({"conn": cid, "gap_start": t_down, "gap_end": t, "dur_s": round(t - t_down, 2),
                                            "err": err}) + "\n")
                self.gaps.flush()
                self.log.warning("conn %d reconnected after %.1fs gap (%s)", cid, t - t_down, err)
            else:
                self.log.info("conn %d connected", cid)
        for cid, n, ts, tv, tr, t0, raw, decs in frames:
            self.on_frame(raw, n, t0, ts, tr, decs, tv)

    async def ws_supervisor(self):
        if self.native:
            return await self.native_supervisor()
        tasks: list[asyncio.Task] = []
        while not self.stop.is_set():
            await self.resub.wait()
            self.resub.clear()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            al = sorted(self.assets)
            tasks = [asyncio.create_task(self.conn(i, al[j:j + CHUNK])) for i, j in enumerate(range(0, len(al), CHUNK))]
            self.log.info("subscribing %d assets (%d markets) over %d connections", len(al), len(self.markets), len(tasks))
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def housekeeping(self):
        last_flush = last_disk = time.time()
        last_counts = Counter(self.counts)
        while not self.stop.is_set():
            await asyncio.sleep(1.0)
            now = time.time()
            self.in_sess = R.in_session(datetime.now(UTC), self.sess)
            if now - last_flush >= FLUSH_SEC:
                self.raw.flush()
                self.dec.flush()
                last_flush = now
            if now - last_disk >= DISK_SEC:
                self.raw_bytes = dir_bytes(self.out / "raw")
                if self.raw_on and self.raw_bytes > self.raw_cap:
                    self.raw_on = False
                    self.raw.close()
                    self.log.error("raw size %.2f GB above cap %.2f GB: raw writing stopped, decisions continue",
                                   self.raw_bytes / 1024 ** 3, self.raw_cap / 1024 ** 3)
                d = {k: self.counts[k] - last_counts[k] for k in ("msgs", "decisions", "flagged")}
                self.log.info("last %ds: %.2f msg/s, %d decisions, %d flagged; raw %.1f MB, decisions %.1f MB; in_session=%s; "
                              "live quote calls %d errors %d", now - last_disk, d["msgs"] / (now - last_disk), d["decisions"],
                              d["flagged"], self.raw_bytes / 1e6, dir_bytes(self.out / "decisions") / 1e6, self.in_sess,
                              self.live.calls, self.live.errors)
                last_counts, last_disk = Counter(self.counts), now
            if datetime.now(UTC) >= self.until:
                self.log.info("reached --until %s, stopping", self.until.isoformat())
                self.stop.set()
                self.resub.set()

    async def run(self):
        loop = asyncio.get_running_loop()
        for s in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(s, lambda: (self.stop.set(), self.resub.set()))
        if self.warm:
            set_interactive_qos()
            keep_warm(True)
        self.log.info("start pid %d, frame path %s, detector impl %s, keep-warm %s, rerun-warm %d us, until %s", os.getpid(),
                      self.impl, detector.IMPL, self.warm, self.warm_us, self.until.isoformat())
        tasks = [asyncio.create_task(c) for c in (self.universe_loop(), self.ref_loop(), self.ws_supervisor(), self.housekeeping())]
        await self.stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.raw.close()
        self.dec.close()
        self.gaps.close()
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.warm:
            keep_warm(False)
        self.log.info("stopped; counts %s; engine bad frames %d, other events %d", dict(self.counts), self.engine.bad_frames,
                      self.engine.other_events)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--until", default=UNTIL)
    ap.add_argument("--raw-cap-gb", type=float, default=RAW_CAP / 1024 ** 3)
    ap.add_argument("--keep-warm", action=argparse.BooleanOptionalAction, default=True,
                    help="interactive QoS on the event loop thread and one native thread spinning to keep the P cores awake")
    ap.add_argument("--native", action=argparse.BooleanOptionalAction, default=True,
                    help="native C++ websocket and TLS client thread calling the book engine with no Python in the hot path")
    ap.add_argument("--spin", action=argparse.BooleanOptionalAction, default=True,
                    help="native client busy-polls its sockets instead of blocking in poll(); replaces keep-warm")
    ap.add_argument("--warm-us", type=int, default=200,
                    help="with --spin, rerun the last frame on the engine after this many idle microseconds to keep it in cache")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=a.out / "recorder.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    pid = a.out / "recorder.pid"
    pid.write_text(str(os.getpid()))
    try:
        asyncio.run(Recorder(a.out, datetime.fromisoformat(a.until), int(a.raw_cap_gb * 1024 ** 3), a.keep_warm, a.native,
                             a.spin, a.warm_us).run())
    finally:
        if pid.exists() and pid.read_text().strip() == str(os.getpid()):
            pid.unlink()


if __name__ == "__main__":
    main()
