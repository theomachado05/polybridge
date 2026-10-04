"""Replay recorded raw frames through the original Python path and the C++ BookEngine, check the decisions match, and
report per-frame latency percentiles. The newest raw file is skipped because the recorder may still be writing it.

    cd research && .venv/bin/python -m live_books.bench_replay
"""
from __future__ import annotations

import argparse
import gc
import gzip
import json
import math
import random
import time
from pathlib import Path

import numpy as np

import live_books  # noqa: F401

from . import reference as R
from .pybook import PyBookEngine
from .recorder import OUT

QS = (50, 90, 99, 99.9)
EXACT = (0, 1, 2, 3, 4, 5, 6, 13)
CLOSE = (10, 11)


def frames(f: Path):
    try:
        with gzip.open(f, "rb") as fh:
            for line in fh:
                j = line.find(b',"m":')
                if line.startswith(b'{"t":') and j > 0 and line.endswith(b"}\n"):
                    yield int(line[5:j]), line[j + 5:-2]
    except EOFError:
        return


def universe(files: list[Path]) -> dict[str, list[str]]:
    mk: dict[str, list[str]] = {}
    for f in files:
        for _, raw in frames(f):
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            for ev in (msg if isinstance(msg, list) else [msg]):
                if not isinstance(ev, dict) or not isinstance(ev.get("market"), str):
                    continue
                ids = [ev.get("asset_id")] + [c.get("asset_id") for c in ev.get("price_changes") or [] if isinstance(c, dict)]
                for a in ids:
                    if isinstance(a, str) and a not in mk.setdefault(ev["market"], []):
                        mk[ev["market"]].append(a)
    return mk


def ref_draw(rng: random.Random) -> float:
    u = rng.random()
    if u < 0.08:
        return float("nan")
    if u < 0.14:
        return rng.choice([0.01, 0.99, 0.03, 0.97])
    return rng.uniform(0.03, 0.97)


def same(a: tuple, b: tuple) -> bool:
    for i in EXACT:
        if a[i] != b[i]:
            return False
    for i in (9, 12):
        if not (a[i] == b[i] or (math.isnan(a[i]) and math.isnan(b[i]))):
            return False
    return all(abs(a[i] - b[i]) <= 1e-9 for i in CLOSE)


def pct(x) -> list[float]:
    x = np.asarray(x, dtype=np.float64) / 1e3
    return [float(np.percentile(x, q)) for q in QS] + [float(x.mean())]


def run(files: list[Path], seed: int = 7, churn_every: int = 20000):
    from .hedgecore_book import BookEngine

    mk = universe(files)
    rng = random.Random(seed)
    old, new = PyBookEngine(R.TAU), BookEngine(R.TAU)
    pairs = []
    for i, (m, ids) in enumerate(sorted(mk.items())):
        ids = sorted(ids)
        pairs.append(ids)
        p, fees = ref_draw(rng), rng.random() < 0.6
        for e in (old, new):
            e.set_market(i, p, fees)
        for j, a in enumerate(ids):
            if old.add_asset(a, i, j == 0) != new.add_asset(a, i, j == 0):
                raise SystemExit("slot numbering differs")
    t_old, t_new, t_new_dec, t_new_int = [], [], [], []
    n_msg = n_dec = n_flag = mism = bad_old = bad_new = 0
    first_mism = None
    gc.disable()
    try:
        for f in files:
            for k, (_, raw) in enumerate(frames(f)):
                if raw == b'"PONG"' or raw == b"PONG":
                    continue
                n_msg += 1
                if churn_every and n_msg % churn_every == 0:
                    for _ in range(20):
                        i = rng.randrange(len(pairs))
                        p = ref_draw(rng)
                        old.set_p(i, p)
                        new.set_p(i, p)
                    i = rng.randrange(len(pairs))
                    for e in (old, new):
                        for j, a in enumerate(pairs[i]):
                            e.remove_asset(a)
                            e.add_asset(a, i, j == 0)
                s = raw.decode()
                a0 = time.perf_counter_ns()
                no = old.process(s, 0)
                a1 = time.perf_counter_ns()
                t_old.append(a1 - a0)
                t0 = time.time_ns()
                b0 = time.perf_counter_ns()
                nn = new.process(raw, t0, b0)
                b1 = time.perf_counter_ns()
                t_new.append(b1 - b0)
                bad_old += no < 0
                bad_new += nn < 0
                do, dn = old.decisions() if no > 0 else [], new.decisions() if nn > 0 else []
                if nn > 0:
                    t_new_dec.append(b1 - b0)
                    t_new_int.extend(d[15] - t0 for d in dn)
                n_dec += len(do)
                n_flag += sum(d[2] != 0 for d in do)
                if len(do) != len(dn) or not all(same(x, y) for x, y in zip(do, dn)):
                    mism += 1
                    if first_mism is None:
                        first_mism = (f.name, k, raw[:300], do[:3], dn[:3])
    finally:
        gc.enable()
    return dict(n_msg=n_msg, n_dec=n_dec, n_flag=n_flag, mism=mism, first_mism=first_mism, bad_old=bad_old,
                bad_new=bad_new, n_assets=sum(len(p) for p in pairs), n_markets=len(pairs), old=pct(t_old),
                new=pct(t_new), new_dec=pct(t_new_dec), new_int=pct(t_new_int))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=OUT / "raw")
    ap.add_argument("--all", action="store_true", help="include the newest raw file")
    ap.add_argument("--max-files", type=int, default=0)
    a = ap.parse_args(argv)
    files = sorted(a.raw.glob("raw_*.jsonl.gz"))
    if not a.all:
        files = files[:-1]
    if a.max_files:
        files = files[:a.max_files]
    r = run(files)
    print(f"files: {', '.join(f.name for f in files)}")
    print(f"frames {r['n_msg']:,}, decisions {r['n_dec']:,} (flagged {r['n_flag']:,}), {r['n_markets']} markets / "
          f"{r['n_assets']} tokens; bad frames old {r['bad_old']} new {r['bad_new']}")
    print(f"decision mismatches (frames): {r['mism']}")
    if r["first_mism"]:
        print("first mismatch:", r["first_mism"])
    print("| path | p50 | p90 | p99 | p99.9 | mean |\n|---|---:|---:|---:|---:|---:|")
    for name, k in (("old: json.loads + dict books + C++ detector, per frame", "old"),
                    ("new: one C++ call (simdjson + books + detector), per frame", "new"),
                    ("new, frames with at least one decision", "new_dec"),
                    ("new, receive to decision inside C++ (t2 - t0), per decision", "new_int")):
        print(f"| {name} | " + " | ".join(f"{v:,.2f}" for v in r[k]) + " |")


if __name__ == "__main__":
    main()
