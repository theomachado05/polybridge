import gzip
import json
import logging
import random
import time
from collections import Counter

import pytest

import live_books  # noqa: F401
from live_books import bench_replay as B
from live_books.recorder import OUT
from live_books.tests.test_book import N1, N2, Y1, Y2, book, pc

hb = pytest.importorskip("live_books.hedgecore_book", reason="hedgecore_book not built (engine/hedgecore/scripts/build_stale.sh)")
if not hasattr(hb, "WsFeed"):
    pytest.skip("hedgecore_book built without WsFeed", allow_module_level=True)

from live_books import native_replay as NR  # noqa: E402

MK = {"m1": [Y1, N1], "m2": [Y2, N2]}


def stream(seed: int, n: int) -> list:
    rng = random.Random(seed)
    toks = [Y1, N1, Y2, N2, "999"]
    out = []
    for k in range(n):
        if rng.random() < 0.1:
            f = book(rng.choice(toks), [(f"{rng.randint(1, 99) / 100:.2f}", str(rng.choice([0, 1, 5.5]))) for _ in range(rng.randint(0, 6))],
                     [(f"{rng.randint(1, 99) / 100:.2f}", str(rng.choice([0, 2, 7.25]))) for _ in range(rng.randint(0, 6))])
        else:
            f = pc(*[(rng.choice(toks), f"{rng.randint(1, 999) / 1000:.3f}".rstrip("0"), rng.choice(["0", "3", "12.5"]),
                      rng.choice(["BUY", "SELL"])) for _ in range(rng.randint(1, 4))])
        if rng.random() < 0.05:
            f = [f, pc((Y2, "0.5", "1", "BUY"))]
        s = json.dumps(f, separators=(",", ":"))
        u = rng.random()
        if u < 0.03:
            out.append(None)
        if u < 0.06:
            out.append(s[: len(s) // 2] + "[")
        elif u < 0.12:
            out.append([s[: len(s) // 3], s[len(s) // 3: 2 * len(s) // 3], s[2 * len(s) // 3:]])
        elif u < 0.14:
            out.append(s + " " * 70000)
        else:
            out.append(s)
    return out


@pytest.mark.parametrize("spin,warm_us", [(True, 20), (True, 0), (False, 0)])
def test_native_feed_matches_book_engine(spin, warm_us):
    msgs = stream(5, 3000)
    r = NR.run(msgs, MK, spin=spin, warm_us=warm_us, pause_every=50, timeout=60)
    assert r["got"] == r["sent"] == sum(m is not None for m in msgs)
    assert r["raw_mism"] == 0 and r["mism"] == 0 and r["n_dec"] > 1000, r["first"]


def test_rerun_leaves_books_and_decisions_unchanged():
    a, b = hb.BookEngine(0.05), hb.BookEngine(0.05)
    NR.setup((a, b), MK, 3)
    for m in stream(9, 2000):
        if m is None:
            continue
        raw = ("".join(m) if isinstance(m, list) else m).encode()
        na, nb = a.process(raw, 0, 0), b.process(raw, 0, 0)
        da, db = a.decisions() if na > 0 else [], b.decisions() if nb > 0 else []
        assert na == nb and all(B.same(x, y) for x, y in zip(da, db))
        if na >= 0:
            bad, other = a.bad_frames, a.other_events
            a.rerun(raw)
            assert (a.bad_frames, a.other_events) == (bad, other)
        for t in (Y1, N1, Y2, N2):
            for side in (True, False):
                assert a.book_levels(a.slot_of(t), side) == b.book_levels(b.slot_of(t), side)
    e0 = a.epoch
    a.remove_asset(Y1)
    a.add_asset(Y1, 0, True)
    assert a.epoch == e0 + 2


def test_recorded_frames_through_native_client():
    files = sorted((OUT / "raw").glob("raw_*.jsonl.gz"))[:-1]
    if not files:
        pytest.skip("no closed raw files")
    msgs = [raw.decode() for _, raw in B.frames(files[0]) if raw not in (b"PONG", b'"PONG"')][:20000]
    r = NR.run(msgs, B.universe(files[:1]), timeout=120)
    assert r["got"] == r["sent"] and r["raw_mism"] == 0 and r["mism"] == 0 and r["n_dec"] > 0


def test_recorder_drain_rows_and_gaps(tmp_path):
    from live_books import recorder as RC
    from live_books import reference as R

    r = RC.Recorder.__new__(RC.Recorder)
    r.out, r.raw_on, r.in_sess, r.counts, r.warm, r.impl, r.warm_us = tmp_path, True, False, Counter(), False, "native_ws_spin", 200
    r.raw, r.dec = RC.HourlyGz(tmp_path / "raw", "raw", binary=True), RC.HourlyGz(tmp_path / "decisions", "decisions")
    r.gaps = (tmp_path / "gaps.jsonl").open("a")
    r.log = logging.getLogger("test")
    r.engine = RC.BookEngine(R.TAU)
    r.markets = {"m1": {"yes": Y1, "no": N1, "tk": "SPY", "k": 500.0, "res_date": "2026-10-09", "fees_listing": True,
                        "w0": 0, "w1": 0, "reopening": "2026-10-05"}}
    r.slot_info = {r.engine.add_asset(Y1, 0, True): ("m1", True)}
    r.engine.set_market(0, 0.46, True)
    r.refs = {"m1": R.Ref(0.46, 0.45, 0.47, "close_2026-10-02", time.time_ns(), float("nan"), "ok")}
    frame = json.dumps(book(Y1, [("0.38", "100")], [("0.40", "50")]), separators=(",", ":")).encode()
    t0 = time.time_ns()
    n = r.engine.process(frame, t0, time.perf_counter_ns())
    decs = r.engine.decisions()

    class Feed:
        def drain(self):
            return [(0, n, t0 - 3000, t0 - 2000, t0 - 1000, t0, frame, decs)], [(1, 1, 10.0, "tls read error"), (1, 0, 12.5, "connected")]

    down = {}
    r.drain(Feed(), down)
    r.raw.close()
    r.dec.close()
    r.gaps.close()
    row = json.loads(gzip.open(next((tmp_path / "decisions").glob("*.gz")), "rb").read())
    assert row["ts"] == t0 - 3000 and row["tv"] == t0 - 2000 and row["tr"] == t0 - 1000 and row["t0"] == t0
    assert row["decision"] == "buy_yes" and row["impl"] == "native_ws_spin" and row["warm"]
    gap = json.loads((tmp_path / "gaps.jsonl").read_text())
    assert gap["conn"] == 1 and gap["dur_s"] == 2.5 and gap["err"] == "tls read error" and not down
