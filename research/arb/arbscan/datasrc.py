"""Network layer: cached, counted HTTP for Polymarket / Kalshi, plus the Massive option helpers."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from .implied import Quote

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
RETRY = {429, 500, 502, 503, 504}


class CountingSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.counts: Counter = Counter()
        self.errors: list[str] = []

    def get(self, url, **kw):
        self.counts[requests.utils.urlparse(url).netloc] += 1
        return super().get(url, **kw)


class Http:
    """JSON GET with an on-disk cache (sha1 of the full URL), retries, and a per-host request counter.
    `cache=False` is for live data: those responses are never reused."""

    def __init__(self, cache_dir: Path, session: requests.Session | None = None, sleep=time.sleep, max_attempts: int = 6):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or CountingSession()
        self._sleep = sleep
        self.max_attempts = max_attempts
        self.failures: list[str] = []

    def get_json(self, url: str, params: dict | None = None, cache: bool = True, allow_status: tuple = ()) -> dict | list | None:
        full = requests.Request("GET", url, params=params).prepare().url
        cf = self.cache_dir / (hashlib.sha1(full.encode()).hexdigest() + ".json")
        if cache and cf.exists():
            return json.loads(cf.read_text())
        resp = None
        for attempt in range(self.max_attempts):
            try:
                resp = self.session.get(full, timeout=30)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt == self.max_attempts - 1:
                    self.failures.append(f"conn-error {url}")
                    return None
                self._sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code not in RETRY:
                break
            ra = str(resp.headers.get("Retry-After", ""))
            self._sleep(min(float(ra), 60) if ra.isdigit() else min(2 ** attempt, 20))
        if resp is None or resp.status_code in RETRY or (resp.status_code >= 400 and resp.status_code not in allow_status):
            self.failures.append(f"{getattr(resp, 'status_code', '?')} {url}")
            return None
        if resp.status_code >= 400:
            payload = {"_status": resp.status_code}
        else:
            payload = resp.json()
        if cache:
            tmp = cf.with_name(f"{cf.stem}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(payload))
            os.replace(tmp, cf)
        return payload


# ---------------- Polymarket ----------------

def gamma_equity_events(http: Http, end_min: str, end_max: str, tag_id: int = 102676) -> list[dict]:
    out: dict[str, dict] = {}
    for closed in ("true", "false"):
        offset = 0
        while True:
            rows = http.get_json(f"{GAMMA}/events", {"tag_id": tag_id, "closed": closed, "limit": 100, "offset": offset,
                                                       "end_date_min": end_min, "end_date_max": end_max,
                                                       "order": "endDate", "ascending": "true"},
                                 cache=(closed == "true"))
            if not rows:
                break
            for e in rows:
                out[str(e.get("id"))] = e
            if len(rows) < 100:
                break
            offset += 100
    return list(out.values())


def clob_history(http: Http, token: str, start_ts: int, end_ts: int, fidelity: int = 1) -> list[tuple[int, float]]:
    d = http.get_json(f"{CLOB}/prices-history", {"market": token, "startTs": int(start_ts), "endTs": int(end_ts), "fidelity": fidelity},
                      allow_status=(400,))
    if not d or "history" not in d:
        return []
    return [(int(h["t"]), float(h["p"])) for h in d["history"]]


def clob_book(http: Http, token: str) -> dict | None:
    d = http.get_json(f"{CLOB}/book", {"token_id": token}, cache=False)
    if not d:
        return None
    bids = sorted(((float(x["price"]), float(x["size"])) for x in d.get("bids", [])), reverse=True)
    asks = sorted((float(x["price"]), float(x["size"])) for x in d.get("asks", []))
    return {"bids": bids, "asks": asks, "ts": float(d.get("timestamp", 0)) / 1000.0}


def book_touch(book: dict) -> dict:
    """Best bid/ask and the size sitting at exactly that price (shares)."""
    bb, bq = (book["bids"][0] if book["bids"] else (None, None))
    ba, aq = (book["asks"][0] if book["asks"] else (None, None))
    return {"bid": bb, "bid_size": bq, "ask": ba, "ask_size": aq}


# ---------------- Kalshi ----------------

def kalshi_markets(http: Http, series: str, status: str, min_close_ts: int | None = None, max_close_ts: int | None = None) -> list[dict]:
    out, cursor = [], None
    while True:
        p = {"series_ticker": series, "status": status, "limit": 1000}
        if min_close_ts:
            p["min_close_ts"] = min_close_ts
        if max_close_ts:
            p["max_close_ts"] = max_close_ts
        if cursor:
            p["cursor"] = cursor
        d = http.get_json(f"{KALSHI}/markets", p, cache=(status == "settled"))
        if not d:
            break
        out.extend(d.get("markets", []))
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    return out


def kalshi_candles(http: Http, series: str, ticker: str, start_ts: int, end_ts: int, period: int = 1) -> list[dict]:
    d = http.get_json(f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks",
                      {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": period}, allow_status=(400, 404))
    return (d or {}).get("candlesticks", []) if isinstance(d, dict) else []


def _f(x) -> float | None:
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def kalshi_bid_ask_at(candles: list[dict], snapshot_ts: float, max_age: float = 900) -> dict | None:
    """Last 1-minute candle ending at or before the snapshot that carries both yes_bid and yes_ask (closes)."""
    best = None
    for c in candles:
        t = c.get("end_period_ts")
        if t is None or t > snapshot_ts:
            continue
        bid = _f((c.get("yes_bid") or {}).get("close_dollars"))
        ask = _f((c.get("yes_ask") or {}).get("close_dollars"))
        if bid is None or ask is None:
            continue
        if best is None or t > best["t"]:
            best = {"t": float(t), "bid": bid, "ask": ask}
    if best and snapshot_ts - best["t"] <= max_age:
        return best
    return None


# ---------------- Massive options ----------------

class OptionSource:
    """Listed strikes (per underlying and expiry) and NBBO quotes at an instant, through MassiveClient."""

    def __init__(self, client, today: date):
        self.client = client
        self.today = today
        self._contracts: dict[tuple[str, str], dict[float, str]] = {}
        self._quotes: dict[tuple[str, str], Quote | None] = {}
        self.failures: list[str] = []

    def _safe(self, path: str, params: dict) -> dict | None:
        try:
            return self.client.get(path, params)
        except Exception as e:  # network/HTTP error: degrade, never crash the scan
            self.failures.append(f"{path} {str(e)[:80]}")
            return None

    def contracts(self, und: str, expiry: str) -> dict[float, str]:
        key = (und, expiry)
        if key not in self._contracts:
            p = {"underlying_ticker": und, "expiration_date": expiry, "contract_type": "call", "limit": 1000}
            if date.fromisoformat(expiry) < self.today:
                p["expired"] = "true"
            rows: list[dict] = []
            payload = self._safe("/v3/reference/options/contracts", p)
            while payload:
                rows.extend(payload.get("results") or [])
                nxt = payload.get("next_url")
                payload = self._safe(nxt, {}) if nxt else None
            self._contracts[key] = {float(r["strike_price"]): r["ticker"] for r in rows if r.get("shares_per_contract", 100) == 100}
        return self._contracts[key]

    def nearest_expiry(self, und: str, on_or_after: date, max_days: int = 10) -> tuple[str, dict[float, str]] | None:
        for n in range(max_days + 1):
            d = (on_or_after + timedelta(days=n))
            if d.weekday() >= 5:
                continue
            c = self.contracts(und, d.isoformat())
            if c:
                return d.isoformat(), c
        return None

    def quote(self, opt_ticker: str, at_utc: datetime) -> Quote | None:
        iso = at_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        key = (opt_ticker, iso)
        if key not in self._quotes:
            r = self._safe(f"/v3/quotes/{opt_ticker}", {"limit": 1, "timestamp.lte": iso, "order": "desc", "sort": "timestamp"})
            res = (r or {}).get("results") or []
            if not res:
                self._quotes[key] = None
            else:
                x = res[0]
                self._quotes[key] = Quote(bid=float(x.get("bid_price") or 0), ask=float(x.get("ask_price") or 0),
                                          bid_size=float(x.get("bid_size") or 0), ask_size=float(x.get("ask_size") or 0),
                                          ts=float(x.get("sip_timestamp") or 0) / 1e9)
        return self._quotes[key]
