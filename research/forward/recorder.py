from __future__ import annotations

import argparse
import gzip
import json
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "arb"))
from arbscan.parse import KALSHI_UNDERLYING, kalshi_is_close, parse_pm_question  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
TWINS = ROOT / "backend" / "app" / "data" / "kalshi_twins.json"
OUT = Path(__file__).resolve().parent
END_UTC = datetime(2026, 10, 4, 13, 30, tzinfo=timezone.utc)
DEPTH = 5
PM_CHUNK = 100
KALSHI_CHUNK = 50
SERIES_KALSHI = ["KXINXU", "KXNASDAQ100U", "INXU", "NASDAQ100U", "KXINXAB", "INXAB"]
EQUITY_TAG = 102676
THRESHOLD_HORIZON_DAYS = 21
RETRY = {429, 500, 502, 503, 504}


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}", flush=True)


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "polybridge-forward-recorder/1.0"
    return s


def _levels(raw, best_high: bool) -> list[list[float]]:
    out = []
    for x in raw or []:
        p, s = (x["price"], x["size"]) if isinstance(x, dict) else (x[0], x[1])
        out.append([round(float(p), 4), round(float(s), 2)])
    out.sort(key=lambda l: l[0], reverse=best_high)
    return out[:DEPTH]


def pm_row(book: dict, t0: float, t1: float) -> dict:
    return {"t0": round(t0, 3), "t": round(t1, 3), "v": "pm", "id": str(book.get("asset_id")),
            "vts": int(book["timestamp"]) if str(book.get("timestamp", "")).isdigit() else None,
            "b": _levels(book.get("bids"), True), "a": _levels(book.get("asks"), False),
            "ltp": book.get("last_trade_price"), "h": book.get("hash")}


def kalshi_row(ob: dict, t0: float, t1: float) -> dict:
    fp = ob.get("orderbook_fp") or {}
    no_bids = _levels(fp.get("no_dollars"), True)
    return {"t0": round(t0, 3), "t": round(t1, 3), "v": "k", "id": ob.get("ticker"),
            "b": _levels(fp.get("yes_dollars"), True), "a": [[round(1.0 - p, 4), s] for p, s in no_bids]}


def _request(http: requests.Session, method: str, url: str, **kw):
    for attempt in range(3):
        t0 = time.time()
        r = http.request(method, url, timeout=10, **kw)
        t1 = time.time()
        if r.status_code not in RETRY or attempt == 2:
            break
        time.sleep(1.0 + attempt)
    r.raise_for_status()
    return r, t0, t1


def fetch_pm(http: requests.Session, tokens: list[str]) -> list[dict]:
    rows = []
    for i in range(0, len(tokens), PM_CHUNK):
        chunk = tokens[i:i + PM_CHUNK]
        r, t0, t1 = _request(http, "POST", f"{CLOB}/books", json=[{"token_id": t} for t in chunk])
        rows.extend(pm_row(b, t0, t1) for b in r.json())
    return rows


def fetch_kalshi(http: requests.Session, tickers: list[str]) -> list[dict]:
    rows = []
    for i in range(0, len(tickers), KALSHI_CHUNK):
        chunk = tickers[i:i + KALSHI_CHUNK]
        r, t0, t1 = _request(http, "GET", f"{KALSHI}/markets/orderbooks", params=[("tickers", t) for t in chunk])
        rows.extend(kalshi_row(ob, t0, t1) for ob in r.json().get("orderbooks", []))
    return rows


def twins_universe(http: requests.Session) -> dict:
    pairs = json.loads(TWINS.read_text())["pairs"]
    return {"pm": [{"token": p["polymarket"]["token_id"], "id": p["polymarket"]["id"],
                    "question": p["polymarket"]["question"], "twin": p["kalshi"]["ticker"]} for p in pairs],
            "kalshi": [{"ticker": p["kalshi"]["ticker"], "question": p["kalshi"]["question"],
                        "twin": p["polymarket"]["id"]} for p in pairs]}


def _jl(x) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def thresholds_universe(http: requests.Session) -> dict:
    now = datetime.now(timezone.utc)
    pm, offset = [], 0
    while True:
        r = http.get(f"{GAMMA}/events", params={
            "tag_id": EQUITY_TAG, "closed": "false", "limit": 100, "offset": offset, "order": "endDate",
            "ascending": "true", "end_date_min": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date_max": (now + timedelta(days=THRESHOLD_HORIZON_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")}, timeout=20)
        r.raise_for_status()
        events = r.json()
        for ev in events:
            for m in ev.get("markets") or []:
                th, _ = parse_pm_question(m.get("question") or "", ev.get("title") or "")
                tokens = [str(t) for t in _jl(m.get("clobTokenIds"))]
                if th is None or not tokens or m.get("closed"):
                    continue
                pm.append({"token": tokens[0], "id": str(m.get("id")), "question": m.get("question"),
                           "underlying": th.ticker, "strike": th.strike, "kind": th.kind, "end_date": m.get("endDate"),
                           "event": ev.get("slug"), "fees_enabled": m.get("feesEnabled"),
                           "fee_schedule": m.get("feeSchedule")})
        if len(events) < 100:
            break
        offset += 100
    kalshi = []
    for ser in SERIES_KALSHI:
        cursor = None
        while True:
            params = {"series_ticker": ser, "status": "open", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = http.get(f"{KALSHI}/markets", params=params, timeout=20)
            r.raise_for_status()
            d = r.json()
            for m in d.get("markets", []):
                if not kalshi_is_close(m.get("event_ticker", "")):
                    continue
                if m.get("strike_type") not in ("greater", "greater_or_equal") or m.get("floor_strike") is None:
                    continue
                kalshi.append({"ticker": m["ticker"], "question": m.get("title"), "underlying": KALSHI_UNDERLYING[ser],
                               "strike": float(m["floor_strike"]), "close_time": m.get("close_time"),
                               "event": m.get("event_ticker")})
            cursor = d.get("cursor")
            if not cursor or not d.get("markets"):
                break
    return {"pm": pm, "kalshi": kalshi}


class Sink:

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def write(self, rows: list[dict]) -> None:
        if not rows:
            return
        path = self.folder / f"{datetime.now(timezone.utc):%Y%m%dT%H}.jsonl.gz"
        with gzip.open(path, "ab") as f:
            f.write(("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n").encode())


def record(name: str, interval: float, universe_fn, refresh_s: float | None, end: datetime) -> None:
    http, sink = session(), Sink(OUT / "raw" / name)
    uni, uni_at = None, 0.0
    stats = {"cycles": 0, "rows": 0, "errors": 0, "started": time.time()}
    nxt = time.time()
    while datetime.now(timezone.utc) < end:
        if uni is None or (refresh_s and time.time() - uni_at > refresh_s):
            try:
                new = universe_fn(http)
                if new["pm"] or new["kalshi"]:
                    uni, uni_at = new, time.time()
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    (OUT / "raw" / name / f"universe_{stamp}.json").write_text(json.dumps(uni, indent=1))
                    log(f"[{name}] universe: {len(uni['pm'])} polymarket, {len(uni['kalshi'])} kalshi")
            except Exception as e:
                uni_at = time.time() - (refresh_s or 0) + 120
                log(f"[{name}] universe refresh failed: {e!r}")
            if uni is None:
                time.sleep(10)
                continue
        rows = []
        for venue, fn, ids in (("pm", fetch_pm, [m["token"] for m in uni["pm"]]),
                               ("k", fetch_kalshi, [m["ticker"] for m in uni["kalshi"]])):
            if not ids:
                continue
            try:
                rows.extend(fn(http, ids))
            except Exception as e:
                stats["errors"] += 1
                rows.append({"t": round(time.time(), 3), "v": venue, "err": repr(e)[:200]})
                log(f"[{name}] {venue} fetch failed: {e!r}")
        try:
            sink.write(rows)
        except Exception:
            log(f"[{name}] write failed:\n{traceback.format_exc()}")
        stats["cycles"] += 1
        stats["rows"] += len(rows)
        stats["last_cycle"] = time.time()
        if stats["cycles"] % 20 == 1:
            (OUT / f"heartbeat_{name}.json").write_text(json.dumps(stats))
        nxt += interval
        if nxt < time.time():
            nxt = time.time()
        time.sleep(max(0.0, nxt - time.time()))
    (OUT / f"heartbeat_{name}.json").write_text(json.dumps(stats))
    log(f"[{name}] done: {stats}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--twins-interval", type=float, default=15.0)
    ap.add_argument("--thresholds-interval", type=float, default=30.0)
    ap.add_argument("--only", choices=["twins", "thresholds"])
    ap.add_argument("--end", default=END_UTC.isoformat())
    a = ap.parse_args()
    end = datetime.fromisoformat(a.end)
    jobs = []
    if a.only != "thresholds":
        jobs.append(threading.Thread(target=record, args=("twins", a.twins_interval, twins_universe, None, end)))
    if a.only != "twins":
        jobs.append(threading.Thread(target=record, args=("thresholds", a.thresholds_interval, thresholds_universe,
                                                          1800.0, end)))
    log(f"recorder start, end {end.isoformat()}")
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
