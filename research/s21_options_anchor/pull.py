"""S21 pull and anchor builder: option contracts and NBBO quotes at the anchor instant from Massive (METHOD.md 3, 8).

One worker, at most 2 requests a second, one small cache line per request, resumable. The recorder's log is read only.

Run from `research/`:  python -m s21_options_anchor.pull
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from . import config as cfg
from . import engine as eg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
S18 = RESEARCH / "results" / "s18_price_market_calibration"
UNIVERSES = (RESEARCH / "s9_weekend_price_markets" / "universe.json", RESEARCH / "s15_weekend_scare" / "universe.json")
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
    """Cache first; the network only when `offline` is False."""

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

    def contracts(self, und: str, expiry: str) -> dict[str, str]:
        """{strike: call ticker} of one underlying and one expiry (standard 100-share contracts of the right root)."""
        k = f"c|{und}|{expiry}"
        if k in self.cache:
            return self.cache[k]
        if self.offline:
            raise NotPulled(k)
        root = cfg.INDEX_ROOT.get(und, f"O:{und}")
        pat = re.compile(rf"^{re.escape(root)}\d{{6}}C\d{{8}}$")
        p = {"underlying_ticker": und, "expiration_date": expiry, "contract_type": "call", "limit": 1000}
        if date.fromisoformat(expiry) < date.fromisoformat(cfg.TODAY):
            p["expired"] = "true"
        rows: list[dict] = []
        payload = self._get("/v3/reference/options/contracts", p)
        while payload:
            rows.extend(payload.get("results") or [])
            nxt = payload.get("next_url")
            payload = self._get(nxt, None) if nxt else None
        out = {f"{float(r['strike_price']):.4f}": r["ticker"] for r in rows
               if r.get("shares_per_contract", 100) == 100 and pat.match(r.get("ticker", ""))}
        self._put(k, out)
        return out

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


# ---------------------------------------------------------------- the plan

def anchor_epoch(entry_epoch: float, session_close: dict[str, float]) -> tuple[str, float]:
    """(anchor day, anchor instant): 15:55 New York on the day of S18's entry instant; 12:55 on a half session."""
    day = datetime.fromtimestamp(entry_epoch, ET).strftime("%Y-%m-%d")
    close = session_close.get(day)
    half = close is not None and datetime.fromtimestamp(close, ET).hour < 15
    return day, pd.Timestamp(f"{day} {'12:55' if half else '15:55'}", tz=ET).timestamp()


def plan() -> tuple[list[dict], dict[str, int]]:
    """One record per stock or S&P market of S18's prints file, parsed; and the count of markets dropped by reason."""
    from s4_linked_assets import engine as en
    sess = en.sessions_from(np.load(RESEARCH / "s5_big_moves" / ".cache" / "eq_SPY.npz")["t"])
    close = {d: float(c) for d, c in zip(sess.day, sess.close)}
    uni: dict[str, dict] = {}
    for f in UNIVERSES:
        for m in json.loads(f.read_text())["markets"]:
            uni.setdefault(str(m["id"]), m)
    pm = pd.read_csv(S18 / "prints_markets.csv", dtype={"market": str, "event": str})
    pm = pm[pm.asset_class.isin(cfg.ASSET_CLASSES)]
    ent = pd.read_csv(S18 / "entries.csv", dtype={"market": str}).drop_duplicates("market").set_index("market")
    out, dropped = [], {}
    for r in pm.itertuples():
        m = uni.get(r.market)
        if m is None or r.market not in ent.index:
            dropped["no universe record or S18 entry"] = dropped.get("no universe record or S18 entry", 0) + 1
            continue
        p, why = eg.parse_market(m)
        if p is None:
            dropped[why] = dropped.get(why, 0) + 1
            continue
        e = ent.loc[r.market]
        day, at = anchor_epoch(float(e.entry_epoch), close)
        if date.fromisoformat(p["end_session"]) < date.fromisoformat(day):
            dropped["the window was over before the first weekend"] = dropped.get("the window was over before the first weekend", 0) + 1
            continue
        out.append({"market": r.market, "event": r.event, "segment": r.segment, "asset_class": r.asset_class, "question": r.question, **p,
                    "anchor_day": day, "anchor_epoch": at, "entry_epoch": float(e.entry_epoch), "result_epoch": float(e.result_epoch)})
    return out, dropped


def pull_order(markets: list[dict]) -> list[dict]:
    events = sorted({m["event"] for m in markets})
    random.Random(cfg.PULL_ORDER_SEED).shuffle(events)
    rank = {e: i for i, e in enumerate(events)}
    return sorted(markets, key=lambda m: (rank[m["event"]], m["market"]))


# ---------------------------------------------------------------- one anchor

def build_anchor(src: Src, m: dict) -> dict:
    """The anchor of one market, or the reason there is none. Raises NotPulled / StopPull / FetchError from the source."""
    und, at, up = m["ticker"], m["anchor_epoch"], m["direction"] > 0
    d0, a_day = date.fromisoformat(m["end_session"]), date.fromisoformat(m["anchor_day"])
    tried, last = 0, "no listed expiry within 45 days of the window's end"
    for n in range(cfg.MAX_EXPIRY_GAP_DAYS + 1):
        d = d0 + timedelta(days=n)
        if d.weekday() >= 5:
            continue
        calls = src.contracts(und, d.isoformat())
        if not calls:
            continue
        tried += 1
        strikes = {float(k): v for k, v in calls.items()}
        legs: dict[float, dict | None] = {}

        def get_quote(strike: float):
            tk = strikes[strike] if up else eg.put_ticker(strikes[strike])
            q = src.quote(tk, at)
            legs[strike] = None if q is None else {**q, "ticker": tk}
            return None if q is None else eg.Quote(bid=q["bid"], ask=q["ask"], bid_size=q["bsz"], ask_size=q["asz"], ts=q["ts"])

        sp = eg.finish_beyond(sorted(strikes), m["level"], m["direction"], get_quote, (d - a_day).days / 365.0, at)
        if sp is None:
            if eg.bracket_indices(sorted(strikes), m["level"]) is None:
                last = "no listed strikes bracket the level"
            elif all(v is None for v in legs.values()):
                last = "no quote at or before the instant on the bracketing strikes"
            else:
                last = "no usable pair of leg quotes (stale, or no offer)"
            if tried >= cfg.MAX_EXPIRY_TRIES:
                break
            continue
        lower, central = eg.anchors(sp.p_mid)
        lo_leg, hi_leg = legs[sp.k1], legs[sp.k2]
        return {"status": "ok", "expiry": d.isoformat(), "expiry_rank": tried, "days_expiry_after_end": (d - d0).days,
                "days_to_expiry": (d - a_day).days, "option_type": "call" if up else "put", "k_lo": sp.k1, "k_hi": sp.k2,
                "width_pct_of_level": 100.0 * (sp.k2 - sp.k1) / m["level"], "stepped": sp.stepped,
                "leg_lo": lo_leg["ticker"], "leg_lo_bid": lo_leg["bid"], "leg_lo_ask": lo_leg["ask"], "leg_lo_age_s": at - lo_leg["ts"],
                "leg_hi": hi_leg["ticker"], "leg_hi_bid": hi_leg["bid"], "leg_hi_ask": hi_leg["ask"], "leg_hi_age_s": at - hi_leg["ts"],
                "zero_bid_leg": bool(lo_leg["bid"] <= 0 or hi_leg["bid"] <= 0), "raw_mid": sp.raw_mid, "noarb_violation": bool(sp.noarb_violation),
                "p_lo": sp.p_lo, "p_mid": sp.p_mid, "p_hi": sp.p_hi, "anchor_lower": lower, "anchor_central": central,
                "central_lo": min(1.0, cfg.CENTRAL_MULTIPLE * sp.p_lo), "central_hi": min(1.0, cfg.CENTRAL_MULTIPLE * sp.p_hi)}
    return {"status": last, "expiries_tried": tried}


def build(src: Src, markets: list[dict], verbose: bool = False) -> list[dict]:
    rows, bad = [], {}
    for i, m in enumerate(pull_order(markets)):
        try:
            if bad.get(m["ticker"], 0) >= 3:
                a = {"status": "fetch error (underlying skipped after three failures)"}
            else:
                a = build_anchor(src, m)
        except NotPulled:
            a = {"status": "not pulled"}
        except StopPull:
            a = {"status": "not pulled"}
            src.offline = True                      # the stop time has passed: finish from the cache only
        except FetchError as e:
            bad[m["ticker"]] = bad.get(m["ticker"], 0) + 1
            a = {"status": f"fetch error: {str(e)[:160]}"}
        rows.append({**m, **a})
        if verbose and (i + 1) % 25 == 0:
            ok = sum(r["status"] == "ok" for r in rows)
            print(f"{i + 1}/{len(markets)} markets, {ok} anchored, {src.requests} requests, {len(src.errors)} errors, {src.rps} rps", flush=True)
    return rows


def main() -> int:
    t0 = time.time()
    markets, dropped = plan()
    stop = pd.Timestamp(cfg.PULL_STOP_ET, tz=ET).timestamp()
    src = Src(offline=False, stop_epoch=stop)
    src._open()
    src.note(f"pull started: {len(markets)} markets parsed, dropped in parsing: {dropped}")
    rows = build(src, markets, verbose=True)
    st = pd.Series([r["status"] for r in rows]).value_counts().to_dict()
    src.note(f"pull finished: {src.requests} requests in {time.time() - t0:.0f}s, {len(src.errors)} errors, final rate {src.rps} rps, "
             f"recorder `fetch failed` lines now {recorder_failures()} (before: {src.rec0}); status {st}")
    for e in src.errors[:10]:
        src.note(f"error: {e}")
    print(json.dumps(st, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
