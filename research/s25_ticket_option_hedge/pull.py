"""S25 pull: the two legs' NBBO at Monday 09:35, the underlying's daily closes (unadjusted and adjusted), the splits, and
(for capacity only) each leg's daily volume on the hedge day. Massive only (METHOD.md 9).

One worker, at most 2 requests a second, one small cache line per request, resumable. The recorder's log is read only.
S21's result files are read; S21's cache is not touched.

Run from `research/`:  python -m s25_ticket_option_hedge.pull
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
S18 = RESEARCH / "results" / "s18_price_market_calibration"
S21 = RESEARCH / "results" / "s21_options_anchor"
RECORDER_LOG = RESEARCH / "forward" / "recorder.log"
ET = ZoneInfo("America/New_York")
RETRY = {429, 500, 502, 503, 504}


class NotPulled(Exception):
    pass


class StopPull(Exception):
    pass


class FetchError(Exception):
    pass


def recorder_failures() -> int:
    """Lines of the recorder's log that say `fetch failed` (read only)."""
    try:
        with open(RECORDER_LOG, "rb") as f:
            return sum(1 for line in f if b"fetch failed" in line)
    except OSError:
        return -1


class Src:
    """Cache first; the network only when `offline` is False. (S21's source, copied; its own cache folder.)"""

    def __init__(self, offline: bool = True, stop_epoch: float | None = None):
        self.offline, self.stop_epoch = offline, stop_epoch
        CACHE.mkdir(parents=True, exist_ok=True)
        self.file = CACHE / "cache.jsonl"
        self.cache: dict[str, object] = {}
        if self.file.exists():
            for line in self.file.read_text().splitlines():
                if line.strip():
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue          # a line cut by an interrupted write
                    self.cache[d["k"]] = d["v"]
        self.requests, self.errors, self.events = 0, [], []
        self.rps, self._last = cfg.MAX_RPS, 0.0
        self.rec0 = self.rec_last = None
        self._session = self._out = None

    def note(self, msg: str):
        line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
        self.events.append(line)
        with open(CACHE / "pull.log", "a") as f:
            f.write(line + "\n")

    def _open(self):
        if self._session is None:
            sys.path.insert(0, str(RESEARCH))
            from polybridge_research.massive import BASE_URL, load_api_key
            self._base = BASE_URL
            self._session = requests.Session()
            self._session.headers["Authorization"] = f"Bearer {load_api_key(search_from=RESEARCH)}"
            self._out = open(self.file, "a")
            self.rec0 = self.rec_last = recorder_failures()
            self.note(f"recorder `fetch failed` lines before the pull: {self.rec0}")

    def _get(self, url: str, params: dict | None) -> dict:
        self._open()
        if not url.startswith("http"):
            url = self._base + url
        resp, err = None, ""
        for attempt in range(6):
            if self.stop_epoch and time.time() >= self.stop_epoch:
                raise StopPull()
            wait = self._last + 1.0 / self.rps - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.requests += 1
            if self.requests % cfg.RECORDER_CHECK_EVERY == 0:
                self.rec_last = recorder_failures()
                if self.rps > cfg.SLOW_RPS and self.rec0 is not None and self.rec_last - self.rec0 > cfg.RECORDER_TOLERANCE:
                    self.rps = cfg.SLOW_RPS
                    self.note(f"recorder failures grew from {self.rec0} to {self.rec_last}: dropping to {self.rps} request a second")
            try:
                resp = self._session.get(url, params=params, timeout=30)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                resp, err = None, type(e).__name__
                time.sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code not in RETRY:
                break
            time.sleep(min(2 ** attempt, 20))
        path = url.split("?")[0].replace(getattr(self, "_base", ""), "")
        if resp is None:
            self.errors.append(f"{path} {err}")
            raise FetchError(f"{path}: {err}")
        if resp.status_code != 200:
            msg = f"{path} HTTP {resp.status_code} {resp.text[:200]}"
            self.errors.append(msg)
            raise FetchError(msg)
        return resp.json()

    def _put(self, k: str, v):
        self.cache[k] = v
        self._out.write(json.dumps({"k": k, "v": v}) + "\n")
        self._out.flush()

    def quote(self, opt: str, at: float) -> dict | None:
        """The last NBBO at or before `at` (epoch seconds): {"bid", "ask", "bsz", "asz", "ts"}, or None when there is none."""
        iso = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        k = f"q|{opt}|{iso}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            raise NotPulled(k)
        res = self._get(f"/v3/quotes/{opt}", {"limit": 1, "timestamp.lte": iso, "order": "desc", "sort": "timestamp"}).get("results") or []
        v = None
        if res:
            x = res[0]
            v = {"bid": float(x.get("bid_price") or 0), "ask": float(x.get("ask_price") or 0), "bsz": float(x.get("bid_size") or 0),
                 "asz": float(x.get("ask_size") or 0), "ts": float(x.get("sip_timestamp") or 0) / 1e9}
        self._put(k, v)
        return v

    def daily(self, ticker: str, start: str, end: str, adjusted: bool) -> dict[str, list[float]]:
        """{day: [close, volume]} of daily bars from `start` to `end` (New York days)."""
        k = f"d|{ticker}|{start}|{end}|{'adj' if adjusted else 'raw'}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            raise NotPulled(k)
        rows: list[dict] = []
        payload = self._get(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                            {"adjusted": "true" if adjusted else "false", "sort": "asc", "limit": 50000})
        while payload:
            rows.extend(payload.get("results") or [])
            nxt = payload.get("next_url")
            payload = self._get(nxt, None) if nxt else None
        out = {datetime.fromtimestamp(float(r["t"]) / 1000.0, ET).strftime("%Y-%m-%d"): [float(r["c"]), float(r.get("v") or 0)] for r in rows}
        self._put(k, out)
        return out

    def splits(self, ticker: str) -> list[dict]:
        """Every listed split of the ticker: execution_date, split_from, split_to."""
        k = f"s|{ticker}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            raise NotPulled(k)
        rows: list[dict] = []
        payload = self._get("/v3/reference/splits", {"ticker": ticker, "limit": 1000})
        while payload:
            rows.extend(payload.get("results") or [])
            nxt = payload.get("next_url")
            payload = self._get(nxt, None) if nxt else None
        out = [{"execution_date": r["execution_date"], "split_from": float(r["split_from"]), "split_to": float(r["split_to"])}
               for r in rows if r.get("ticker") == ticker]
        self._put(k, out)
        return out


# ---------------------------------------------------------------- the plan

def session_days() -> list[str]:
    from s4_linked_assets import engine as en
    return list(en.sessions_from(np.load(RESEARCH / "s5_big_moves" / ".cache" / "eq_SPY.npz")["t"]).day)


def epoch(day: str, hhmm: str) -> float:
    return pd.Timestamp(f"{day} {hhmm}", tz=ET).timestamp()


def plan() -> pd.DataFrame:
    """One row per market of the study: S21's anchored markets with a first-weekend taker sale, with S21's legs, S18's
    ticket leg and the hedge instant."""
    a = pd.read_csv(S21 / "anchors.csv", dtype={"market": str, "event": str})
    a = a[a.status == "ok"].copy()
    pm = pd.read_csv(S18 / "prints_markets.csv", dtype={"market": str, "event": str})
    cols = ["market", "outcome", "sell_prints", "sell_size", "sell_price", "sell_pnl_points", "sell_pnl_points_2x_fee"]
    d = a.merge(pm[cols], on="market", how="inner")
    d = d[d.sell_pnl_points.notna()].copy()
    days = session_days()
    d["hedge_day"] = [min(x for x in days if x > f) for f in d.anchor_day]
    d["hedge_epoch"] = [epoch(x, cfg.HEDGE_TIME_ET) for x in d.hedge_day]
    d["open_epoch"] = [epoch(x, cfg.SESSION_OPEN_ET) for x in d.hedge_day]
    d["expiry_epoch"] = [epoch(x, cfg.EXPIRY_CLOSE_ET) for x in d.expiry]
    d["rule"] = 100.0 * (d.sell_price - d.anchor_central) >= cfg.RULE_THRESHOLD_POINTS - 1e-9
    d["agg_ticker"] = [cfg.INDEX_AGG_TICKER.get(t, t) for t in d.ticker]
    return d.sort_values(["anchor_day", "ticker", "market"]).reset_index(drop=True)


def pull_order(d: pd.DataFrame) -> pd.DataFrame:
    events = sorted(set(d.event))
    random.Random(cfg.PULL_ORDER_SEED).shuffle(events)
    rank = {e: i for i, e in enumerate(events)}
    return d.assign(_r=d.event.map(rank)).sort_values(["_r", "market"]).drop(columns="_r")


def main() -> int:
    t0 = time.time()
    d = plan()
    stop = pd.Timestamp(cfg.PULL_STOP_ET, tz=ET).timestamp()
    src = Src(offline=False, stop_epoch=stop)
    src._open()
    src.note(f"pull started: {len(d)} markets, {d.event.nunique()} events, {d.agg_ticker.nunique()} tickers")
    stopped = False

    # 1. the underlying's closes and splits (42 requests)
    for tk in sorted(set(d.agg_ticker)):
        for what in ("raw", "adj", "splits"):
            try:
                if what == "splits":
                    if not tk.startswith("I:"):
                        src.splits(tk)
                else:
                    src.daily(tk, cfg.CLOSE_FROM, cfg.CLOSE_TO, adjusted=(what == "adj"))
            except FetchError as e:
                src.note(f"error ({tk} {what}): {str(e)[:200]}")
            except StopPull:
                stopped = True
    src.note(f"closes and splits done: {src.requests} requests, {len(src.errors)} errors")

    # 2. the two legs at the hedge instant, events in a seeded random order
    done = fails = 0
    order = pull_order(d)
    for r in order.itertuples():
        if stopped:
            break
        for leg in (r.leg_lo, r.leg_hi):
            try:
                src.quote(leg, r.hedge_epoch)
                done += 1
            except FetchError as e:
                fails += 1
                if done == 0 and fails >= 6:
                    src.note(f"STOP: Monday quotes are not available: {str(e)[:300]}")
                    print(f"STOP: Monday quotes are not available. Exact error: {e}", flush=True)
                    return 2
            except StopPull:
                stopped = True
                break
        if (done + fails) % 100 < 2:
            print(f"quotes {done} ok, {fails} failed, {src.requests} requests, {src.rps} rps", flush=True)
    src.note(f"leg quotes done: {done} served, {fails} failed, {src.requests} requests, {len(src.errors)} errors, stopped early: {stopped}")

    # 3. for capacity.md only: each leg's daily bar on the hedge day (its volume)
    vol = 0
    for r in order.itertuples():
        if stopped:
            break
        for leg in (r.leg_lo, r.leg_hi):
            try:
                src.daily(leg, r.hedge_day, r.hedge_day, adjusted=False)
                vol += 1
            except FetchError:
                pass
            except StopPull:
                stopped = True
                break
    src.note(f"pull finished: {src.requests} requests in {time.time() - t0:.0f}s, {len(src.errors)} errors, final rate {src.rps} rps, "
             f"leg volumes {vol}, stopped early: {stopped}, recorder `fetch failed` lines now {recorder_failures()} (before: {src.rec0})")
    for e in sorted(set(src.errors))[:10]:
        src.note(f"error: {e}")
    print(json.dumps({"requests": src.requests, "errors": len(src.errors), "quotes": done, "quote_failures": fails, "leg_volumes": vol,
                      "stopped_early": stopped, "rps": src.rps}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
