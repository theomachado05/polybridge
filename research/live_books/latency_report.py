"""Latency report from the recorder's decision logs. Writes results/live_books/LATENCY.md.

    cd research && .venv/bin/python -m live_books.latency_report
"""
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


def read(dec_dir: Path):
    tot, parse, dec = array("q"), array("q"), array("q")
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
                    tot.append(t2 - t0)
                    parse.append(t1 - t0)
                    dec.append(t2 - t1)
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
    return tot, parse, dec, len(t0s), c, flagged_mk, tmin, tmax


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
    a = ap.parse_args(argv)
    tot, parse, dec, n_msg_dec, c, flagged_mk, tmin, tmax = read(a.out / "decisions")
    if not c["decisions"]:
        raise SystemExit("no decisions logged yet")
    span = (tmax - tmin) / 1e9
    n_raw = raw_messages(a.out / "raw", tmin, tmax)
    cpp = call_cost(detector.decide_cpp) if detector.decide_cpp else None
    py = call_cost(detector.decide_py)
    rows = [("receive to decision (t2 - t0)", pct(tot)), ("receive to parsed (t1 - t0)", pct(parse)),
            ("parsed to decision (t2 - t1)", pct(dec))]
    impl = ", ".join(f"{k[5:]} {v:,}" for k, v in sorted(c.items()) if k.startswith("impl_"))
    L = ["# Live book recorder: detector latency", "",
         f"Window: {fmt(tmin)} to {fmt(tmax)} ({span / 60:.1f} min). Detector implementation in the logged decisions: {impl}.",
         "",
         "**These decisions use a stale reference.** Outside the US regular session the reference probability is the option-implied "
         "probability at the last regular-session close, and every such decision is flagged `reference_stale=true`. Weekend "
         "numbers are a latency demonstration of the recorder and detector, not a trading result. No order is ever sent.", "",
         "## Latency per book update (microseconds)", "",
         "| stage | p50 | p90 | p99 | p99.9 | mean |", "|---|---:|---:|---:|---:|---:|"]
    L += [f"| {name} | " + " | ".join(f"{v:,.1f}" for v in vals) + " |" for name, vals in rows]
    L += ["",
          "t0 is `time.time_ns()` when the websocket frame is handed to the handler, t1 after `json.loads`, t2 after the book update "
          "and the detector call for that asset. A frame that carries several book events is parsed once, so its later events "
          "include the earlier events' processing. Network latency from Polymarket to this machine is not included.", "",
          "## Detector call cost (isolated, one book touch, nanoseconds per call)", "",
          "| implementation | ns per call |", "|---|---:|",
          f"| C++ `hedgecore::stale_quote` through the pybind11 module `hedgecore_stale` | {cpp:,.0f} |" if cpp else
          "| C++ binding | not built |",
          f"| pure-Python twin `live_books.detector.decide_py` | {py:,.0f} |", "",
          "The C++ figure includes the pybind11 call and tuple return; the hot path inside C++ does no allocation. Most of the "
          "receive-to-decision time is Python JSON parsing and book bookkeeping, not the decision itself.", "",
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
