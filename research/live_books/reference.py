from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import requests

from arbscan import implied
from arbscan.implied import Quote
from forward_monday import config as FC
from forward_monday import core as FM
from pm_taker import config as PC
from pm_taker import core as P
from polybridge_research.massive import BASE_URL

UTC = timezone.utc
ET = FM.ET
OPEN_HM, CLOSE_HM = (9, 30), (16, 0)


@dataclass
class Ref:
    p: float
    p_lo: float
    p_hi: float
    basis: str
    computed_ns: int
    quote_ts: float
    status: str


def in_session(now: datetime, sess: set[date]) -> bool:
    e = now.astimezone(ET)
    return e.date() in sess and P.et(e.date(), OPEN_HM) <= e < P.et(e.date(), CLOSE_HM)


def last_close(now: datetime, sess: set[date]) -> date:
    d = now.astimezone(ET).date()
    if d in sess and now >= P.et(d, CLOSE_HM):
        return d
    d -= timedelta(days=1)
    while d not in sess:
        d -= timedelta(days=1)
    return d


def from_spread(sp, basis: str) -> Ref:
    st = P.spread_status(sp)
    if sp is None:
        return Ref(float("nan"), float("nan"), float("nan"), basis, time.time_ns(), float("nan"), st)
    qts = min(sp.q1.ts, sp.q2.ts)
    p = sp.p_mid if st == "ok" else float("nan")
    return Ref(p, sp.p_lo, sp.p_hi, basis, time.time_ns(), qts, st)


def close_ref(opts, row: dict, d: date) -> Ref:
    t = int(P.et(d, CLOSE_HM).timestamp()) - 1
    chain = opts.contracts(row["tk"], row["res_date"])
    sp = P.option_spread(chain, float(row["k"]), lambda tkr, s: opts.quote(tkr, datetime.fromtimestamp(s, UTC)), t,
                         int(row["exp_close"]))
    return from_spread(sp, f"close_{d}")


class LiveQuotes:

    def __init__(self, api_key: str, ttl: float = 3.0):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {api_key}"
        self.ttl = ttl
        self.cache: dict[str, tuple[float, Quote | None]] = {}
        self.calls = self.errors = 0

    def quote(self, tkr: str) -> Quote | None:
        now = time.time()
        hit = self.cache.get(tkr)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        q = None
        try:
            self.calls += 1
            r = self.s.get(f"{BASE_URL}/v3/quotes/{tkr}", params={"limit": 1, "order": "desc", "sort": "timestamp"}, timeout=10)
            r.raise_for_status()
            res = r.json().get("results") or []
            if res:
                x = res[0]
                q = Quote(bid=float(x.get("bid_price") or 0), ask=float(x.get("ask_price") or 0),
                          bid_size=float(x.get("bid_size") or 0), ask_size=float(x.get("ask_size") or 0),
                          ts=float(x.get("sip_timestamp") or 0) / 1e9)
        except Exception:
            self.errors += 1
        self.cache[tkr] = (now, q)
        return q


def live_ref(opts, live: LiveQuotes, row: dict) -> Ref:
    now = time.time()
    chain = opts.contracts(row["tk"], row["res_date"])
    if not chain:
        return from_spread(None, "live")
    t_years = max((int(row["exp_close"]) - now) / (365.0 * 86400.0), 0.0)
    sp = implied.pick_spread(sorted(chain), float(row["k"]), lambda s: live.quote(chain[s]), t_years, snapshot_ts=now,
                             max_age=PC.LEG_MAX_AGE, rate=PC.RATE)
    return from_spread(sp, "live")


TAU = FC.TAU
