"""S20 pull: the public prints inside D1 and W2 of every S18 market that was still open at its D1 start (METHOD.md section 7).

One worker, at most one request a second, cached per market and resumable. Read-only guard on the live recorder's log.

Run from `research/`:  python -m s20_closed_vs_open.pull
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s9_weekend_price_markets.run import calendar

from . import config as cfg
from . import windows as wn

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
S18_RESULTS = RESEARCH / "results" / "s18_price_market_calibration"
S18_CACHE = RESEARCH / "s18_price_market_calibration" / ".cache"
SOURCES = (RESEARCH / "s9_weekend_price_markets", RESEARCH / "s15_weekend_scare")
RECORDER_LOG = RESEARCH / "forward" / "recorder.log"
KEEP = ("timestamp", "price", "side", "outcome", "size")


def plan() -> list[dict]:
    """S18's markets, each with its three windows."""
    sess = en.sessions_from(np.load(S5_CACHE / "eq_SPY.npz")["t"])
    spans, starts = wn.session_spans(sess), wn.weekend_starts(calendar(), sess)
    entries = pd.read_csv(S18_RESULTS / "entries.csv")
    return [{**r._asdict(), "market": str(r.market), "event": str(r.event), "windows": wn.market_windows(float(r.entry_epoch), starts, spans)}
            for r in entries.itertuples(index=False)]


def conditions() -> dict[str, str]:
    return {str(m["id"]): m["condition"] for root in SOURCES for m in json.loads((root / "universe.json").read_text())["markets"]}


def recorder_failures() -> int:
    """`fetch failed` lines in the live recorder's log. Read only."""
    try:
        with open(RECORDER_LOG, "r", errors="ignore") as f:
            return sum("fetch failed" in line for line in f)
    except OSError:
        return -1


def fetch(condition: str, oldest_needed: float, throttle: ds.Throttle) -> tuple[list[dict], int]:
    """S18's request (`s1_twin_spread.data.pm_trades`), page by page, counting the requests."""
    out: list[dict] = []
    n = 0
    for i in range(cfg.PAGES):
        d = ds.get_json(ds.DATA_API, {"market": condition, "limit": cfg.PAGE, "offset": i * cfg.PAGE}, throttle=throttle, allow=(400, 404))
        n += 1
        if not isinstance(d, list) or not d:
            break
        out.extend(d)
        if len(d) < cfg.PAGE or float(d[-1].get("timestamp", 0)) < oldest_needed:
            break
    return out, n


def split(raw: list[dict], windows: dict) -> dict:
    """Only the prints stamped inside D1 and W2 are kept."""
    ts = [float(t.get("timestamp", 0)) for t in raw]
    rec = {"reach_oldest": min(ts) if ts else None, "served": len(raw), "d1": [], "w2": []}
    for t, s in zip(raw, ts):
        for key, name in (("d1", "D1"), ("w2", "W2")):
            if wn.inside(s, windows[name]):
                rec[key].append({k: t.get(k) for k in KEEP})
    return rec


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    cond = conditions()
    meta_f = CACHE / "pull_meta.json"
    meta = json.loads(meta_f.read_text()) if meta_f.exists() else {"started": time.time(), "recorder_failures_before": recorder_failures(), "guard_trips": []}
    meta_f.write_text(json.dumps(meta))
    todo = [m for m in plan() if m["windows"]["D1"] and m["result_epoch"] > m["windows"]["D1"][0][0]]
    throttle, base = ds.Throttle(cfg.REQUESTS_PER_S), recorder_failures()
    t0, requests, since_check, done, kept, failed = time.time(), 0, 0, 0, 0, []
    log = open(CACHE / "pull.log", "a")

    def say(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    say(f"start: {len(todo)} markets to hold, recorder failures now {base}, rate {cfg.REQUESTS_PER_S}/s")
    for attempt in (1, 2):
        pending = [m for m in todo if not (CACHE / f"prints_{m['market']}.json").exists()]
        for m in pending:
            f = CACHE / f"prints_{m['market']}.json"
            try:
                raw, n = fetch(cond[m["market"]], m["windows"]["D1"][0][0], throttle)
                rec = split(raw, m["windows"])
                rec["requests"], rec["pulled_at"] = n, time.time()
                f.write_text(json.dumps(rec))
                kept += len(rec["d1"]) + len(rec["w2"])
            except Exception as e:  # noqa: BLE001
                n = 1
                failed.append(m["market"])
                say(f"market {m['market']}: {str(e)[:160]}")
                if attempt == 2:
                    f.write_text(json.dumps({"reach_oldest": None, "served": 0, "d1": [], "w2": [], "requests": 0, "pulled_at": time.time(), "error": str(e)[:200]}))
            requests, since_check, done = requests + n, since_check + n, done + 1
            if since_check >= cfg.GUARD_EVERY_REQUESTS:
                since_check, now_f = 0, recorder_failures()
                if now_f - base > cfg.GUARD_GROWTH:
                    say(f"GUARD: recorder failures {base} -> {now_f}; pausing {cfg.GUARD_PAUSE_S}s, then {cfg.SLOW_REQUESTS_PER_S}/s")
                    meta["guard_trips"].append({"at": time.time(), "from": base, "to": now_f})
                    meta_f.write_text(json.dumps(meta))
                    time.sleep(cfg.GUARD_PAUSE_S)
                    throttle, base = ds.Throttle(cfg.SLOW_REQUESTS_PER_S), recorder_failures()
            if done % 50 == 0:
                say(f"{time.time() - t0:.0f}s: {done} markets, {requests} requests, {kept} prints kept, recorder failures {recorder_failures()}")
        if not failed:
            break
    meta.update({"finished": time.time(), "recorder_failures_after": recorder_failures(), "requests_this_run": requests, "prints_kept_this_run": kept,
                 "seconds_this_run": round(time.time() - t0, 1), "failed_first_pass": failed})
    meta_f.write_text(json.dumps(meta))
    say(f"done: {time.time() - t0:.0f}s, {done} market pulls, {requests} requests, {kept} prints kept, recorder failures {meta['recorder_failures_after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
