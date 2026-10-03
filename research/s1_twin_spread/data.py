"""S1 data: pair metadata, Kalshi 1-minute candles (real bid/ask), Polymarket 1-minute price history and trade prints.

Nothing here is committed: arrays go to `.cache/` as compressed npz. Run from `research/`:
    python -m s1_twin_spread.data
"""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests

from .config import LOOKBACK_DAYS, UTC

ROOT = Path(__file__).resolve().parents[2]
TWINS = ROOT / "backend" / "app" / "data" / "kalshi_twins.json"
CACHE = Path(__file__).resolve().parent / ".cache"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com/trades"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WINDOW_S = 4990 * 60          # the API serves at most 5000 candles per request
PM_WINDOW_S = 14 * 86400             # prices-history refuses 1-minute ranges much longer than 15 days
RETRY = {429, 500, 502, 503, 504}


class Throttle:
    """At most `rate` calls per second across threads."""

    def __init__(self, rate: float):
        self.gap, self.lock, self.next = 1.0 / rate, threading.Lock(), 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        time.sleep(max(0.0, at - now))


_local = threading.local()


def _http() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = "polybridge-research/1.0"
    return _local.s


def get_json(url: str, params=None, throttle: Throttle | None = None, allow: tuple = (), attempts: int = 7):
    for i in range(attempts):
        if throttle:
            throttle.wait()
        try:
            r = _http().get(url, params=params, timeout=40)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            time.sleep(min(2 ** i, 20))
            continue
        if r.status_code in RETRY:
            time.sleep(min(2 ** i, 20))
            continue
        if r.status_code >= 400:
            if r.status_code in allow:
                return {"_status": r.status_code, "_text": r.text[:300]}
            raise RuntimeError(f"{r.status_code} {url} {r.text[:200]}")
        return r.json()
    raise RuntimeError(f"gave up on {url}")


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def load_pairs() -> list[dict]:
    return json.loads(TWINS.read_text())["pairs"]


def pair_meta(pair: dict, kt: Throttle, pt: Throttle) -> dict:
    """Dates, fee terms and ids of one pair, from the venues' own market records (no prices are kept)."""
    tk = pair["kalshi"]["ticker"]
    m = get_json(f"{KALSHI}/markets/{tk}", throttle=kt)["market"]
    ev = get_json(f"{KALSHI}/events/{m['event_ticker']}", throttle=kt)["event"]
    se = get_json(f"{KALSHI}/series/{ev['series_ticker']}", throttle=kt)["series"]
    g = get_json(f"{GAMMA}/markets/{pair['polymarket']['id']}", throttle=pt)
    sched = g.get("feeSchedule") or {}
    k_end, p_end = _iso(m["close_time"]), _iso(g["endDate"])
    return {
        "ticker": tk, "series": ev["series_ticker"], "pm_id": str(pair["polymarket"]["id"]),
        "token": pair["polymarket"]["token_id"], "condition_id": g.get("conditionId"),
        "question": pair["polymarket"]["question"],
        "kalshi_open": m["open_time"], "kalshi_close": m["close_time"], "kalshi_status": m.get("status"),
        "kalshi_fee_type": se.get("fee_type"), "kalshi_fee_multiplier": float(se.get("fee_multiplier") or 1.0),
        "pm_start": g.get("startDate") or g.get("createdAt"), "pm_end": g["endDate"], "pm_closed": bool(g.get("closed")),
        "pm_fees_enabled": bool(g.get("feesEnabled")), "pm_fee_rate": float(sched.get("rate", 0.0) or 0.0),
        "pm_fee_exponent": float(sched.get("exponent", 1.0) or 1.0),
        "pm_min_size": g.get("orderMinSize"), "pm_tick": g.get("orderPriceMinTickSize"), "pm_neg_risk": bool(g.get("negRisk")),
        "deadline": max(k_end, p_end).isoformat(),
    }


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def kalshi_candles(meta: dict, start: datetime, end: datetime, kt: Throttle) -> dict[str, np.ndarray]:
    t, bid, ask, vol = [], [], [], []
    s, e = int(start.timestamp()), int(end.timestamp())
    url = f"{KALSHI}/series/{meta['series']}/markets/{meta['ticker']}/candlesticks"
    while s < e:
        w = min(s + KALSHI_WINDOW_S, e)
        d = get_json(url, {"start_ts": s, "end_ts": w, "period_interval": 1}, throttle=kt, allow=(400, 404))
        for c in d.get("candlesticks", []) if isinstance(d, dict) else []:
            t.append(int(c["end_period_ts"]))
            bid.append(_f((c.get("yes_bid") or {}).get("close_dollars")))
            ask.append(_f((c.get("yes_ask") or {}).get("close_dollars")))
            vol.append(_f(c.get("volume_fp")))
        s = w
    o = np.argsort(np.array(t, dtype=np.int64), kind="stable")
    return {"t": np.array(t, dtype=np.int64)[o], "bid": np.array(bid, dtype=np.float32)[o],
            "ask": np.array(ask, dtype=np.float32)[o], "vol": np.array(vol, dtype=np.float32)[o]}


def pm_history(meta: dict, start: datetime, end: datetime, pt: Throttle) -> dict[str, np.ndarray]:
    t, p = [], []
    s, e = int(start.timestamp()), int(end.timestamp())
    while s < e:
        w = min(s + PM_WINDOW_S, e)
        d = get_json(f"{CLOB}/prices-history", {"market": meta["token"], "startTs": s, "endTs": w, "fidelity": 1},
                     throttle=pt, allow=(400,))
        for h in d.get("history", []) if isinstance(d, dict) else []:
            t.append(int(h["t"]))
            p.append(float(h["p"]))
        s = w
    tt, idx = np.unique(np.array(t, dtype=np.int64), return_index=True)
    return {"t": tt, "p": np.array(p, dtype=np.float32)[idx]}


def pm_trades(condition_id: str, oldest_needed: float, pt: Throttle, page: int = 500, max_pages: int = 40) -> list[dict]:
    """Public trade prints, newest first, paged back until `oldest_needed` (epoch s) or until the API stops serving."""
    out: list[dict] = []
    for i in range(max_pages):
        d = get_json(DATA_API, {"market": condition_id, "limit": page, "offset": i * page}, throttle=pt, allow=(400, 404))
        if not isinstance(d, list) or not d:
            break
        out.extend(d)
        if len(d) < page or float(d[-1].get("timestamp", 0)) < oldest_needed:
            break
    return out


def pull_pair(pair: dict, t1: datetime, kt: Throttle, pt: Throttle) -> dict:
    meta = pair_meta(pair, kt, pt)
    start = max(t1 - timedelta(days=LOOKBACK_DAYS), _iso(meta["kalshi_open"]), _iso(meta["pm_start"]))
    start = start.replace(second=0, microsecond=0)
    meta["hist_start"] = start.isoformat()
    k = kalshi_candles(meta, start, t1, kt)
    p = pm_history(meta, start, t1, pt)
    np.savez_compressed(CACHE / f"k_{meta['ticker']}.npz", **k)
    np.savez_compressed(CACHE / f"p_{meta['pm_id']}.npz", **p)
    meta["kalshi_candles"], meta["pm_points"] = int(len(k["t"])), int(len(p["t"]))
    return meta


def main() -> int:
    """No argument: pull every pair up to now. With tickers: re-pull only those, up to the first pull's cut-off, slowly
    (the forward recorder shares Kalshi's rate limit)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    prior = json.loads((CACHE / "pull_meta.json").read_text()) if only else None
    t1 = _iso(prior["t1"]) if prior else datetime.now(UTC).replace(second=0, microsecond=0)
    kt, pt = (Throttle(3.0), Throttle(3.0)) if only else (Throttle(9.0), Throttle(5.0))
    pairs = [p for p in load_pairs() if not only or p["kalshi"]["ticker"] in only]
    metas, failures = [], []
    t0 = time.time()

    def job(pair):
        try:
            m = pull_pair(pair, t1, kt, pt)
            print(f"{time.time() - t0:6.0f}s {m['ticker']}: {m['kalshi_candles']} candles, {m['pm_points']} PM points "
                  f"from {m['hist_start'][:10]}", flush=True)
            return m
        except Exception as e:  # reported, never hidden
            failures.append({"ticker": pair["kalshi"]["ticker"], "error": repr(e)[:300]})
            print(f"FAILED {pair['kalshi']['ticker']}: {e!r}", flush=True)
            return None

    with ThreadPoolExecutor(max_workers=1 if only else 6) as ex:
        metas = [m for m in ex.map(job, pairs) if m]
    seconds = round(time.time() - t0, 1)
    if prior:
        done = {m["ticker"] for m in metas}
        metas = [m for m in prior["pairs"] if m["ticker"] not in done] + metas
        failures = [f for f in prior["failures"] if f["ticker"] not in done] + failures
        seconds += prior.get("seconds", 0)
    order = {p["kalshi"]["ticker"]: i for i, p in enumerate(load_pairs())}
    metas.sort(key=lambda m: order[m["ticker"]])
    (CACHE / "pull_meta.json").write_text(json.dumps({"t1": t1.isoformat(), "pairs": metas, "failures": failures,
                                                      "seconds": seconds}, indent=1))
    print(f"done: {len(metas)} pairs, {len(failures)} failures, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
