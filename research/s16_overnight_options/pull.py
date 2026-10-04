"""S16 pull: option contracts, NBBO quotes at the instants and day volumes from Massive (METHOD.md sections 3, 4, 10).

One worker, at most 2 requests a second, one small cache line per request, resumable. The recorder's log is read only.

Run from `research/`:  python -m s16_overnight_options.pull
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import config as cfg
from . import engine as eg
from .plan import CACHE, RESEARCH, Ctx, build_plan

NOT_PULLED = "NOT_PULLED"
RETRY = {429, 500, 502, 503, 504}
RECORDER_LOG = RESEARCH / "forward" / "recorder.log"
ORDER_PRIMARY = ("0935", "close")
ORDER_REST = ("0931", "0945", "1000", "1030")


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
    """Cache first; the network only when `offline` is False."""

    def __init__(self, offline: bool = True, stop_epoch: float | None = None):
        self.offline = offline
        self.stop_epoch = stop_epoch
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
        self.requests = 0
        self.errors: list[str] = []
        self.rps = cfg.MAX_RPS
        self._last = 0.0
        self.rec0 = None
        self.rec_last = None
        self.events: list[str] = []
        self._session = None
        self._out = None

    # ---- network
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

    def note(self, msg: str):
        line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
        self.events.append(line)
        with open(CACHE / "pull.log", "a") as f:
            f.write(line + "\n")

    def _get(self, path: str, params: dict) -> dict:
        self._open()
        resp = None
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
                resp = self._session.get(self._base + path, params=params, timeout=30)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                resp = None
                err = type(e).__name__
                time.sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code not in RETRY:
                break
            time.sleep(min(2 ** attempt, 20))
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

    # ---- the three lookups
    def contracts(self, tk: str, day: str, spot: float):
        """{"expiry": ..., "strikes": {strike: call ticker}} of the nearest listed expiry 7 to 45 days after `day`."""
        k = f"c|{tk}|{day}|{spot:.4f}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            return NOT_PULLED
        d0 = date.fromisoformat(day)
        lo, hi = d0 + timedelta(days=cfg.EXPIRY_MIN_DAYS), d0 + timedelta(days=cfg.EXPIRY_MAX_DAYS)
        today = date.fromisoformat(cfg.TODAY)
        pat = re.compile(rf"^O:{re.escape(tk)}\d{{6}}C\d{{8}}$")
        out = {"expiry": None, "strikes": {}}
        for expired in ([True, False] if lo < today else [False]):
            if expired is False and hi < today:
                continue
            p = {"underlying_ticker": tk, "contract_type": "call", "expiration_date.gte": lo.isoformat(), "expiration_date.lte": hi.isoformat(),
                 "strike_price.gte": round(spot * (1 - cfg.STRIKE_BAND), 4), "strike_price.lte": round(spot * (1 + cfg.STRIKE_BAND), 4),
                 "sort": "expiration_date", "order": "asc", "limit": 250}
            if expired:
                p["expired"] = "true"
            rows = [r for r in (self._get("/v3/reference/options/contracts", p).get("results") or [])
                    if r.get("shares_per_contract", 100) == 100 and pat.match(r.get("ticker", ""))]
            if rows:
                exp = min(r["expiration_date"] for r in rows)
                out = {"expiry": exp, "strikes": {f"{float(r['strike_price']):.4f}": r["ticker"] for r in rows if r["expiration_date"] == exp}}
                break
        self._put(k, out)
        return out

    def quote(self, opt: str, at: int):
        """The last NBBO at or before `at` (epoch seconds): {"bid", "ask", "bsz", "asz", "ts"} or None when there is none."""
        iso = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        k = f"q|{opt}|{iso}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            return NOT_PULLED
        res = self._get(f"/v3/quotes/{opt}", {"limit": 1, "timestamp.lte": iso, "order": "desc", "sort": "timestamp"}).get("results") or []
        v = None
        if res:
            x = res[0]
            v = {"bid": float(x.get("bid_price") or 0), "ask": float(x.get("ask_price") or 0), "bsz": float(x.get("bid_size") or 0),
                 "asz": float(x.get("ask_size") or 0), "ts": float(x.get("sip_timestamp") or 0) / 1e9}
        self._put(k, v)
        return v

    def volume(self, opt: str, day: str):
        """The contract's volume and number of trades on `day`: {"v", "n"}."""
        k = f"v|{opt}|{day}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            return NOT_PULLED
        res = self._get(f"/v2/aggs/ticker/{opt}/range/1/day/{day}/{day}", {"adjusted": "true"}).get("results") or []
        v = {"v": float(sum(r.get("v", 0) for r in res)), "n": float(sum(r.get("n", 0) for r in res))}
        self._put(k, v)
        return v

    def bars_5m(self, tk: str, start: str, end: str) -> Path:
        """Regular-session five-minute bars of a ticker that is not in the S5 or S4 cache, as `eq_<TICKER>.npz`."""
        f = CACHE / f"eq_{tk}.npz"
        if f.exists() or self.offline:
            return f
        rows = []
        cur, last = pd.Timestamp(start), pd.Timestamp(end)
        while cur <= last:
            nxt = (cur + pd.offsets.MonthBegin(1)).normalize()
            b = min(nxt - pd.Timedelta(days=1), last)
            rows += self._get(f"/v2/aggs/ticker/{tk}/range/5/minute/{cur.strftime('%Y-%m-%d')}/{b.strftime('%Y-%m-%d')}",
                              {"adjusted": "true", "sort": "asc", "limit": 50000}).get("results") or []
            cur = nxt
        df = pd.DataFrame(rows).drop_duplicates("t").sort_values("t")
        local = pd.to_datetime(df.t, unit="ms", utc=True).dt.tz_convert("America/New_York")
        mins = local.dt.hour * 60 + local.dt.minute
        df = df[(mins >= 570) & (mins < 960)]
        np.savez_compressed(f, t=(df.t.to_numpy() // 1000).astype(np.int64), o=df.o.to_numpy(float), c=df.c.to_numpy(float),
                            v=df.v.to_numpy(float), vw=df.get("vw", df.c).to_numpy(float))
        return f


def observe(src: Src, it: dict, ctx: Ctx) -> dict:
    """One ticker-day: contract, quotes at every instant asked for, underlying prices. Status says why it is dropped."""
    tk, i = it["ticker"], it["i"]
    rec = {k: it[k] for k in ("tier", "sample", "kind", "ticker", "day", "event_day", "segment", "weekend", "x", "direction", "market", "question")}
    rec["status"] = "ok"
    spot = ctx.first_price(tk, i)
    if spot is None:
        return {**rec, "status": "no opening bar"}
    rec["spot_open"] = spot
    c = src.contracts(tk, it["day"], spot)
    if c == NOT_PULLED:
        return {**rec, "status": "not pulled"}
    if not c["strikes"]:
        return {**rec, "status": "no listed expiry"}
    strike = min((float(s) for s in c["strikes"]), key=lambda s: (abs(s - spot), s))
    call = c["strikes"][f"{strike:.4f}"]
    put = eg.put_ticker(call)
    rec.update({"expiry": c["expiry"], "strike": strike, "call": call, "put": put,
                "dte": (date.fromisoformat(c["expiry"]) - date.fromisoformat(it["day"])).days})
    at = ctx.instants(i)
    floor = float(ctx.op[i])
    keys = list(ORDER_PRIMARY) + (list(ORDER_REST) + (["prev"] if it["need_prev"] else []) if it["full"] else [])
    for key in keys:
        morning = key not in ("close", "prev")
        okk = True
        for leg, tkr in (("c", call), ("p", put)):
            q = src.quote(tkr, at[key])
            if q == NOT_PULLED:
                if key in ORDER_PRIMARY:
                    return {**rec, "status": "not pulled"}
                rec["partial"] = True
                okk = False
                continue
            if eg.valid_quote(q, at[key], cfg.MORNING_QUOTE_MAX_AGE_S if morning else cfg.CLOSE_QUOTE_MAX_AGE_S, floor if morning else None):
                rec.update({f"{leg}_bid_{key}": q["bid"], f"{leg}_ask_{key}": q["ask"], f"{leg}_bsz_{key}": q["bsz"], f"{leg}_asz_{key}": q["asz"],
                            f"{leg}_age_{key}": at[key] - q["ts"]})
            else:
                okk = False
                rec[f"{leg}_why_{key}"] = "no quote" if not q else ("bid or ask not valid" if not (q["bid"] > 0 and q["ask"] >= q["bid"]) else "stale")
        if key in ORDER_PRIMARY and not okk:
            return {**rec, "status": f"no valid quote at {'09:35' if key == '0935' else '15:55'}"}
    for key, t in at.items():
        rec[f"u_{key}"] = ctx.price_at(tk, t)
    return rec


def main() -> int:
    stop = pd.Timestamp(cfg.PULL_HARD_STOP_ET, tz="America/New_York").timestamp()
    plan, ctx, meta = build_plan()
    src = Src(offline=False, stop_epoch=stop)
    t0 = time.time()
    done: dict[int, int] = {}
    state = {"finished_tiers": [], "stopped": None}
    src.note(f"pull start: {len(plan)} plan items " + json.dumps({t: sum(1 for p in plan if p['tier'] == t) for t in (1, 2, 4, 5)}))

    def run_tier(tier: int) -> None:
        items = [p for p in plan if p["tier"] == tier]
        fails = 0
        for n_, it in enumerate(items):
            try:
                observe(src, it, ctx)
                fails = 0
            except FetchError as e:
                fails += 1
                src.note(f"request failed: {str(e)[:300]}")
                if fails >= 10:
                    raise
            done[tier] = n_ + 1
            if (n_ + 1) % 25 == 0:
                src.note(f"tier {tier}: {n_ + 1}/{len(items)} items, {src.requests} requests, {time.time() - t0:.0f}s, "
                         f"rps {src.rps}, recorder {src.rec_last}")
        state["finished_tiers"].append(tier)
        src.note(f"tier {tier} finished: {len(items)} items, {src.requests} requests so far")

    try:
        run_tier(1)
        run_tier(2)
        # tier 3: the day's volume of the two entry legs of each main event with valid primary quotes, most recent first
        off = Src(offline=True)
        ok = [r for r in (observe(off, p, ctx) for p in plan if p["tier"] == 1 and p["kind"] == "event") if r["status"] == "ok"]
        for r in sorted(ok, key=lambda r: r["day"], reverse=True):
            try:
                src.volume(r["call"], r["day"])
                src.volume(r["put"], r["day"])
            except FetchError as e:
                src.note(f"request failed: {str(e)[:300]}")
        state["finished_tiers"].append(3)
        src.note(f"tier 3 finished: {len(ok)} events, {src.requests} requests so far")
        for tk in ("XLF", "KRE"):          # not cached for the whole window by S4 or S5 (amendment 2)
            src.bars_5m(tk, ctx.days[0], ctx.days[-1])
            ctx._bars.pop(tk, None)
        run_tier(4)
        run_tier(5)
    except StopPull:
        state["stopped"] = "hard stop " + cfg.PULL_HARD_STOP_ET
        src.note("hard stop reached")
    except FetchError as e:
        state["stopped"] = f"ten requests in a row failed: {str(e)[:300]}"
        src.note(state["stopped"])
    rec_end = recorder_failures()
    state.update({"requests": src.requests, "errors": len(src.errors), "first_errors": src.errors[:5], "seconds": round(time.time() - t0, 1),
                  "items_done_by_tier": done, "recorder_before": src.rec0, "recorder_after": rec_end, "final_rps": src.rps, "plan_meta": meta,
                  "ended_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    prev = []
    f = CACHE / "pull_state.json"
    if f.exists():
        prev = json.loads(f.read_text())
    f.write_text(json.dumps(prev + [state], indent=1))
    src.note("pull end " + json.dumps({k: state[k] for k in ("finished_tiers", "stopped", "requests", "errors", "recorder_before", "recorder_after")}))
    print(json.dumps(state, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
