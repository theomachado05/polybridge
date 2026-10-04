from __future__ import annotations

import argparse
import gzip
import json
import timeit
from array import array
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import live_books  # noqa: F401

from . import detector
from .recorder import OUT

QS = (50, 90, 99, 99.9)


IMPL_NAMES = {"cpp": "old path: Python json.loads and dict books, C++ detector call per token",
              "python": "old path with the pure-Python detector",
              "cpp_book": "new path: one C++ call per frame (simdjson parse, books, detector)",
              "cpp_book+warm": "new path with keep-warm (interactive QoS, one native thread spinning to keep the P cores awake)",
              "python_book": "fallback path (Python twin of the C++ engine)",
              "native_ws": "native path: C++ websocket and TLS client thread calling the engine, blocking in poll()",
              "native_ws_spin+warm": "native path, busy-polling the sockets, engine kept in cache by rerunning the last frame "
                                     "when idle"}
STAGES = (("socket to decision (t2 - ts)", "ts"), ("recv return to decision (t2 - tv)", "tv"),
          ("after TLS read to decision (t2 - tr)", "tr"))


def read(dec_dir: Path, w0: int = 0, w1: int = 2 ** 63 - 1):
    lat: dict[str, tuple[array, array, array]] = {}
    extra: dict[str, dict[str, array]] = {}
    span: dict[str, list[int]] = {}
    t0s: set[int] = set()
    c: Counter = Counter()
    flagged_mk: set[str] = set()
    tmin = tmax = None
    for f in sorted(dec_dir.glob("decisions_*.jsonl.gz")):
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        c["bad_lines"] += 1
                        continue
                    t0, t1, t2 = r["t0"], r["t1"], r["t2"]
                    if not w0 <= t0 <= w1:
                        continue
                    key = r["impl"] + ("+warm" if r.get("warm") else "")
                    tot, parse, dec = lat.setdefault(key, (array("q"), array("q"), array("q")))
                    w = span.setdefault(key, [t0, t2])
                    w[0], w[1] = min(w[0], t0), max(w[1], t2)
                    tot.append(t2 - t0)
                    parse.append(t1 - t0)
                    dec.append(t2 - t1)
                    for _, k in STAGES:
                        if r.get(k):
                            extra.setdefault(key, {}).setdefault(k, array("q")).append(t2 - r[k])
                    t0s.add(t0)
                    tmin = t0 if tmin is None else min(tmin, t0)
                    tmax = t2 if tmax is None else max(tmax, t2)
                    c["decisions"] += 1
                    c[f"impl_{r['impl']}"] += 1
                    c["stale" if r["reference_stale"] else "fresh"] += 1
                    if r["p_ref"] is None:
                        c["no_ref"] += 1
                    if r["decision"] != "none":
                        c["flagged"] += 1
                        c[f"flagged_{r['decision']}"] += 1
                        c["flagged_stale" if r["reference_stale"] else "flagged_fresh"] += 1
                        if r.get("in_window") and not r["reference_stale"]:
                            c["flagged_fresh_in_window"] += 1
                        flagged_mk.add(r["mid"])
        except EOFError:
            c["truncated_files"] += 1
    return lat, span, len(t0s), c, flagged_mk, tmin, tmax, extra


def raw_messages(raw_dir: Path, tmin: int, tmax: int) -> int:
    n = 0
    for f in sorted(raw_dir.glob("raw_*.jsonl.gz")):
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    if line.startswith(b'{"t":'):
                        j = line.find(b",", 5)
                        if j > 0 and line[5:j].isdigit():
                            n += tmin <= int(line[5:j]) <= tmax
        except EOFError:
            pass
    return n


def call_cost(fn, n: int = 200_000) -> float:
    args = (0.38, 100.0, 0.40, 50.0, 0.46, 0.05, 0.04, 1.0, True)
    return min(timeit.repeat(lambda: fn(*args), number=n, repeat=5)) / n * 1e9


def pct(a: array) -> list[float]:
    x = np.frombuffer(a, dtype=np.int64) / 1e3
    return [float(np.percentile(x, q)) for q in QS] + [float(x.mean())]


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1e9, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-replay", action="store_true")
    ap.add_argument("--ab", nargs="*", default=[], metavar="OUT_DIR",
                    help="recorder output dirs run side by side; their common window is reported as a concurrent A/B")
    a = ap.parse_args(argv)
    lat, spans, n_msg_dec, c, flagged_mk, tmin, tmax, extra = read(a.out / "decisions")
    if not c["decisions"]:
        raise SystemExit("no decisions logged yet")
    span = (tmax - tmin) / 1e9
    n_raw = raw_messages(a.out / "raw", tmin, tmax)
    cpp = call_cost(detector.decide_cpp) if detector.decide_cpp else None
    py = call_cost(detector.decide_py)
    impl = ", ".join(f"{k[5:]} {v:,}" for k, v in sorted(c.items()) if k.startswith("impl_"))
    L = ["# Live book recorder: detector latency", "",
         f"Window: {fmt(tmin)} to {fmt(tmax)} ({span / 60:.1f} min). Detector implementation in the logged decisions: {impl}.",
         "",
         "**These decisions use a stale reference.** Outside the US regular session the reference probability is the option-implied "
         "probability at the last regular-session close, and every such decision is flagged `reference_stale=true`. Weekend "
         "numbers are a latency demonstration of the recorder and detector, not a trading result. No order is ever sent.", "",
         "## Live latency per book update (microseconds)", ""]
    for impl in [k for k in IMPL_NAMES if k in lat] + sorted(k for k in lat if k not in IMPL_NAMES):
        tot, parse, dec = lat[impl]
        w0, w1 = spans[impl]
        L += [f"**{IMPL_NAMES.get(impl, impl)}** (`{impl}`), {fmt(w0)} to {fmt(w1)} ({(w1 - w0) / 6e10:.1f} min), "
              f"{len(tot):,} decisions.", "",
              "| stage | p50 | p90 | p99 | p99.9 | mean |", "|---|---:|---:|---:|---:|---:|"]
        L += [f"| {name} | " + " | ".join(f"{v:,.2f}" for v in pct(x)) + " |" for name, x in
              [(n, extra[impl][k]) for n, k in STAGES if k in extra.get(impl, {})] +
              [("receive to decision (t2 - t0)", tot), ("receive to parsed (t1 - t0)", parse), ("parsed to decision (t2 - t1)", dec)]]
        L += [""]
    L += ["t0 is `time.time_ns()` when the websocket frame is handed to the handler. Old path: t1 after `json.loads` (and after "
          "the gzip write of the raw frame, which came first), t2 after the dict book update and the detector call for that "
          "token, both from `time.time_ns()`. New path: the frame bytes go to `hedgecore_book.BookEngine.process` in one call; "
          "t1 is when that event's book update is done and t2 when its decision is written, both read inside C++ from the "
          "monotonic clock that `time.perf_counter_ns()` uses and placed on t0's wall clock by the offset from a "
          "`perf_counter_ns()` read taken at receive, so sub-microsecond intervals are resolved; the raw gzip write now "
          "happens after the decisions. A frame that carries several book events is handled in one pass, so its later events "
          "include the earlier events' processing. Network latency from Polymarket to this machine is not included.", "",
          "Native path: one C++ thread owns the sockets, the OpenSSL sessions and the websocket framing and calls the engine "
          "directly, so no Python runs between the socket and the decision; Python only drains the finished frames and "
          "decisions for logging. ts is the monotonic clock just before the `SSL_read` call that returned the frame's bytes "
          "(with busy polling this is within one poll iteration, about 0.2 us, of the bytes becoming readable; macOS gives no "
          "kernel receive timestamps for TCP), tv is when the underlying `recv` returned them, tr is after TLS decryption and "
          "t0 is after the websocket frame is decoded, all placed on the wall clock like t1 and t2. On the Python paths tr is "
          "taken in the websockets protocol's `data_received` callback, after asyncio's TLS layer has decrypted the bytes; "
          "the Python paths have no ts or tv. A frame that arrives in the same read as an earlier one shares its ts, tv and tr.",
          ""]
    if a.ab:
        runs = [read(Path(d) / "decisions") for d in a.ab]
        w0, w1 = max(r[5] for r in runs) + 30_000_000_000, min(r[6] for r in runs)
        L += ["## Concurrent A/B (microseconds per book update)", "",
              f"The recorders below ran at the same time on this machine, each with its own connections to the same 400 "
              f"tokens, so they saw the same market traffic and the same machine load. Common window {fmt(w0)} to {fmt(w1)} "
              f"({(w1 - w0) / 6e10:.1f} min), starting 30 s after the later start so that no subscription snapshot is in it.",
              "",
              "| path | stage | n | p50 | p90 | p99 | p99.9 | mean |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for d in a.ab:
            lat2, _, _, _, _, _, _, extra2 = read(Path(d) / "decisions", w0, w1)
            for impl, (tot, _, _) in lat2.items():
                for name, x in [(n, extra2[impl][k]) for n, k in STAGES if k in extra2.get(impl, {})] + [
                        ("receive to decision (t2 - t0)", tot)]:
                    L += [f"| `{impl}` | {name} | {len(x):,} | " + " | ".join(f"{v:,.2f}" for v in pct(x)) + " |"]
        L += [""]
    if not a.no_replay:
        from . import bench_replay as B
        files = sorted((a.out / "raw").glob("raw_*.jsonl.gz"))[:-1]
        if files:
            r = B.run(files)
            L += ["## Replay benchmark on the recorded frames (microseconds per frame)", "",
                  f"Closed raw files {files[0].name} to {files[-1].name}: {r['n_msg']:,} frames, {r['n_dec']:,} decisions "
                  f"against synthetic references (drawn per market so that both sides and the no-reference case occur, with "
                  f"reference changes and token removal and re-adding during the replay). Decisions that differ between the "
                  f"two paths (side, prices and sizes exact, edges to 1e-9): {r['mism']} frames.", "",
                  "| path | p50 | p90 | p99 | p99.9 | mean |", "|---|---:|---:|---:|---:|---:|"]
            L += [f"| {name} | " + " | ".join(f"{v:,.2f}" for v in r[k]) + " |" for name, k in
                  (("old: `json.loads`, dict books, C++ detector call per token", "old"),
                   ("new: one `BookEngine.process` call", "new"),
                   ("new, receive to decision inside C++ (t2 - t0), per decision", "new_int"))]
            L += ["", "Both paths run in one process on the same frames, timed with `time.perf_counter_ns()` around the "
                  "call; the raw gzip write is excluded from both. The per-decision tail of the new path comes from the "
                  "subscription snapshot frames, which carry 200 books each.", ""]
            try:
                from . import native_replay as NR
            except ImportError:
                NR = None
            if NR is not None:
                msgs = [raw.decode() for f in files for _, raw in B.frames(f) if raw not in (b"PONG", b'"PONG"')]
                n = NR.run(msgs, B.universe(files))
                L += ["## Native client on the recorded frames (loopback replay)", "",
                      f"The same closed raw files served over a local plain websocket to the native client (busy polling, "
                      f"rerun warming on): {n['sent']:,} frames sent, {n['got']:,} received, {n['raw_mism']} with different "
                      f"bytes; {n['n_dec']:,} decisions, frames whose decisions differ from `BookEngine.process` on the same "
                      f"bytes: {n['mism']}.", "",
                      "| stage | p50 | p90 | p99 | p99.9 | mean |", "|---|---:|---:|---:|---:|---:|"]
                L += [f"| {name} | " + " | ".join(f"{v:,.2f}" for v in n[k]) + " |" for name, k in
                      (("loopback socket to decision (t2 - ts)", "sock"), ("frame decoded to decision (t2 - t0)", "t0")) if n[k]]
                L += ["", "The server writes frames as fast as it can, so several frames often arrive in one read and "
                      "share its ts; the later ones include the earlier ones' processing.", ""]
    L += [
          "## Detector call cost (isolated, one book touch, nanoseconds per call)", "",
          "| implementation | ns per call |", "|---|---:|",
          f"| C++ `hedgecore::stale_quote` through the pybind11 module `hedgecore_stale` | {cpp:,.0f} |" if cpp else
          "| C++ binding | not built |",
          f"| pure-Python twin `live_books.detector.decide_py` | {py:,.0f} |", "",
          "The C++ figure includes the pybind11 call and tuple return. In the old path most of the receive-to-decision time is "
          "Python JSON parsing and book bookkeeping, not the decision itself; the new path moves the parse, the books and the "
          "decision into one C++ call that does no allocation once its buffers are warm.", "",
          "## Throughput and decisions", "",
          f"- Websocket messages in the window: {n_raw:,} ({n_raw / span:.2f} per second); messages that produced a book decision: "
          f"{n_msg_dec:,}.",
          f"- Book-update decisions: {c['decisions']:,} ({c['decisions'] / span:.2f} per second); with a usable reference: "
          f"{c['decisions'] - c['no_ref']:,}; flagged reference_stale: {c['stale']:,}; fresh: {c['fresh']:,}.",
          f"- Would-trade flags (|book touch - reference| >= 5 pt toward the options): {c['flagged']:,} "
          f"(buy YES {c['flagged_buy_yes']:,}, buy NO {c['flagged_buy_no']:,}) on {len(flagged_mk)} markets; with a fresh "
          f"reference: {c['flagged_fresh']:,}; fresh and inside the forward_monday window: {c['flagged_fresh_in_window']:,}.",
          "", "A flag is counted on every book update while the touch stays through the threshold, so flags are not trades and "
          "repeat for one standing quote."]
    if c["truncated_files"] or c["bad_lines"]:
        L += ["", f"Files still open or truncated when read: {c['truncated_files']}; unreadable lines: {c['bad_lines']}."]
    (a.out / "LATENCY.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
