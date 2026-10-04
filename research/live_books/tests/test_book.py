import json
import math
import random
import time

import pytest

import live_books  # noqa: F401
from live_books import bench_replay as B
from live_books.pybook import PyBookEngine
from live_books.recorder import OUT

hb = pytest.importorskip("live_books.hedgecore_book", reason="hedgecore_book not built (engine/hedgecore/scripts/build_stale.sh)")

Y1, N1, Y2, N2 = "111", "222", "333", "444"


def engines(p1=0.46, p2=0.50, fees=(True, False)):
    out = []
    for e in (PyBookEngine(0.05), hb.BookEngine(0.05)):
        e.set_market(0, p1, fees[0])
        e.set_market(1, p2, fees[1])
        for a, m, y in ((Y1, 0, True), (N1, 0, False), (Y2, 1, True), (N2, 1, False)):
            e.add_asset(a, m, y)
        out.append(e)
    return out


def book(a, bids, asks):
    return {"event_type": "book", "asset_id": a, "market": "0x1", "bids": [{"price": p, "size": s} for p, s in bids],
            "asks": [{"price": p, "size": s} for p, s in asks]}


def pc(*changes):
    return {"event_type": "price_change", "market": "0x1",
            "price_changes": [{"asset_id": a, "price": p, "size": s, "side": sd, "hash": "h"} for a, p, s, sd in changes]}


def run_both(old, new, frame):
    raw = json.dumps(frame, separators=(",", ":"))
    t0 = time.time_ns()
    no, nn = old.process(raw, t0), new.process(raw.encode(), t0, time.perf_counter_ns())
    return no, nn, (old.decisions() if no > 0 else []), (new.decisions() if nn > 0 else [])


def check(old, new, frame):
    no, nn, do, dn = run_both(old, new, frame)
    assert no == nn
    assert len(do) == len(dn) and all(B.same(x, y) for x, y in zip(do, dn)), (do, dn)
    return dn


def test_book_and_changes_match_python():
    old, new = engines()
    d = check(old, new, book(Y1, [("0.38", "100"), ("0.30", "5")], [("0.40", "50"), ("0.45", "7")]))
    assert d[0][2] == 1 and d[0][12] == 0.40 and d[0][13] == 50.0
    d = check(old, new, book(N1, [("0.55", "10")], [("0.62", "20")]))
    assert d[0][3] == pytest.approx(0.38) and d[0][4] == 20.0 and d[0][5] == pytest.approx(0.45) and d[0][6] == 10.0
    check(old, new, pc((Y1, "0.40", "0", "SELL"), (Y1, "0.39", "3", "BUY"), (N1, "0.62", "0", "SELL"), ("999", "0.5", "1", "BUY")))
    check(old, new, pc((Y2, "0.47", "4", "BUY"), (Y2, "0.58", "4", "SELL")))
    check(old, new, [book(Y2, [("0.61", "1"), ("0.61", "9")], [("0.70", "0")]), pc((Y2, "0.61", "0", "BUY"))])
    check(old, new, {"event_type": "price_change", "asset_id": N2, "changes": [{"price": "0.3", "size": "2", "side": "BUY"}]})
    check(old, new, {"event_type": "last_trade_price", "asset_id": Y1, "price": "0.5", "size": "1"})
    check(old, new, book("999", [("0.1", "1")], []))
    check(old, new, pc((Y1, "0.385", "11", "BUY"), (Y1, "0.3851", "2", "BUY")))


def test_reference_updates_and_removal():
    old, new = engines(p1=float("nan"))
    assert check(old, new, book(Y1, [("0.38", "100")], [("0.40", "50")]))[0][2] == 0
    for e in (old, new):
        e.set_p(0, 0.30)
    assert check(old, new, pc((Y1, "0.381", "1", "BUY")))[0][2] == 2
    for e in (old, new):
        e.remove_asset(Y1)
    assert check(old, new, pc((Y1, "0.39", "1", "BUY"))) == []
    for e in (old, new):
        e.add_asset(Y1, 0, True)
    d = check(old, new, pc((Y1, "0.39", "1", "BUY")))
    assert d[0][3] == 0.39 and d[0][5] == 0.0


def test_depth_within_two_cents_in_yes_terms():
    e = engines()[1]
    e.process(json.dumps(book(N1, [("0.55", "10"), ("0.54", "1"), ("0.53", "2"), ("0.52", "100")],
                              [("0.60", "3"), ("0.62", "4"), ("0.63", "5")])).encode(), 0, 0)
    d = e.decisions()[0]
    assert d[7] == pytest.approx(7.0) and d[8] == pytest.approx(13.0)
    assert e.book_levels(e.slot_of(N1), True) == 4


def test_bad_frames_and_timestamps():
    e = engines()[1]
    assert e.process(b'{"event_type":"book","asset_id":"111","bids":[{"price":"0.1"', 0, 0) == -1
    assert e.process(b"[1,2,", 0, 0) == -1 and e.bad_frames == 2
    assert e.process(b'"x"', 0, 0) == 0
    t0 = time.time_ns()
    n = e.process(json.dumps(book(Y1, [("0.38", "1")], [("0.40", "1")])).encode(), t0, time.perf_counter_ns())
    d = e.decisions()[0]
    assert n == 1 and t0 <= d[14] <= d[15] < t0 + 10_000_000


def test_random_streams_match_python():
    rng = random.Random(3)
    for trial in range(20):
        old, new = engines(p1=rng.uniform(0.03, 0.97), p2=rng.choice([float("nan"), rng.uniform(0, 1)]))
        for _ in range(300):
            toks = [Y1, N1, Y2, N2, "999"]
            if rng.random() < 0.1:
                frame = book(rng.choice(toks), [(f"{rng.randint(1, 99) / 100:.2f}", str(rng.choice([0, 1, 5.5]))) for _ in
                                                range(rng.randint(0, 6))],
                             [(f"{rng.randint(1, 99) / 100:.2f}", str(rng.choice([0, 2, 7.25]))) for _ in range(rng.randint(0, 6))])
            else:
                frame = pc(*[(rng.choice(toks), f"{rng.randint(1, 999) / 1000:.3f}".rstrip("0"), rng.choice(["0", "3", "12.5"]),
                              rng.choice(["BUY", "SELL"])) for _ in range(rng.randint(1, 4))])
            if rng.random() < 0.05:
                frame = [frame, pc((Y2, "0.5", "1", "BUY"))]
            check(old, new, frame)
            if rng.random() < 0.02:
                m, p = rng.randint(0, 1), rng.uniform(0, 1)
                for e in (old, new):
                    e.set_p(m, p)


def test_recorded_frames_match_python():
    files = sorted((OUT / "raw").glob("raw_*.jsonl.gz"))[:-1]
    if not files:
        pytest.skip("no closed raw files")
    r = B.run(files[:1])
    assert r["n_dec"] > 0 and r["mism"] == 0 and r["bad_old"] == r["bad_new"]
    assert not math.isnan(r["new"][0])


def test_recorder_raw_and_decision_rows(tmp_path):
    import asyncio
    import gzip
    import logging
    from collections import Counter

    from live_books import recorder as RC
    from live_books import reference as R

    r = RC.Recorder.__new__(RC.Recorder)
    r.out, r.raw_on, r.in_sess, r.counts, r.warm = tmp_path, True, False, Counter(), False
    r.raw, r.dec = RC.HourlyGz(tmp_path / "raw", "raw", binary=True), RC.HourlyGz(tmp_path / "decisions", "decisions")
    r.log = logging.getLogger("test")
    r.engine, r.mid_idx, r.slot_info, r.refs = RC.BookEngine(R.TAU), {}, {}, {}
    r.markets = {"m1": {"yes": Y1, "no": N1, "tk": "SPY", "k": 500.0, "res_date": "2026-10-09", "fees_listing": True,
                        "w0": 0, "w1": 0, "reopening": "2026-10-05"}}
    r.assets = {}
    r.resub = asyncio.Event()
    r.stop = asyncio.Event()
    r.build_universe = lambda: (r.stop.set(), dict(r.markets))[1]
    r.close_refs = lambda mids: None
    r.set_ref("m1", R.Ref(0.46, 0.45, 0.47, "close_2026-10-02", time.time_ns(), float("nan"), "ok"))

    asyncio.run(RC.Recorder.universe_loop(r))
    frame = json.dumps(book(Y1, [("0.38", "100")], [("0.40", "50")]), separators=(",", ":")).encode()
    t0 = time.time_ns()
    r.on_message(frame + b"\n", t0, time.perf_counter_ns())
    r.on_message(b"PONG", t0, 0)
    r.raw.close()
    r.dec.close()
    raw = gzip.open(next((tmp_path / "raw").glob("*.gz")), "rb").read()
    assert raw == f'{{"t":{t0},"m":{frame.decode()}}}\n'.encode()
    row = json.loads(gzip.open(next((tmp_path / "decisions").glob("*.gz")), "rb").read())
    assert row["decision"] == "buy_yes" and row["price"] == 0.4 and row["p_ref"] == 0.46 and row["impl"] == RC.BOOK_IMPL
    assert row["t0"] == t0 <= row["t1"] <= row["t2"] and row["reference_stale"] and row["bid_depth_2c"] == 100.0
    assert r.counts["decisions"] == 1 and r.counts["msgs"] == 1
