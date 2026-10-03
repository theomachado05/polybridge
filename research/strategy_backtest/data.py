"""Fetch + cache (METHOD.md section 1). Network only here; everything downstream is pure.

PM: Polymarket CLOB prices-history per market x closure (the `leadlag.data` fetcher, cached by URL hash).
SPY: Massive minute bars (month chunks, extended hours), daily bars and cash dividends (MassiveClient cache).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from leadlag.data import CountingSession, fetch_pm_history  # noqa: F401
from leadlag_closed.closures import Closure, build_closures
from polybridge_research.calendar import TradingCalendar

from .config import CACHE_DIR, EVENTS_PATH, MARKETS_PATH, PARAMS, SPAN_START, TICKER

GAMMA = "https://gamma-api.polymarket.com"


# ---------------------------------------------------------------- universe


def _utc(s) -> pd.Timestamp:
    t = pd.Timestamp(s)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def panel_a_markets(session=None) -> list[dict]:
    """The two panel-A markets with life from gamma metadata (startDate, closedTime else endDate). No prices read."""
    import yaml

    doc = yaml.safe_load(open(EVENTS_PATH))["markets"]
    s = session or requests.Session()
    out = []
    for key, m in doc.items():
        cache = CACHE_DIR / "gamma" / f"{m['market_slug']}.json"
        if cache.exists():
            meta = json.loads(cache.read_text())
        else:
            rows = []
            for extra in ({}, {"closed": "true"}):
                r = s.get(f"{GAMMA}/markets", params={"slug": m["market_slug"], **extra}, timeout=60)
                r.raise_for_status()
                rows = r.json()
                if rows:
                    break
            if not rows:
                raise RuntimeError(f"gamma returned no metadata for {m['market_slug']}")
            meta = {k: rows[0].get(k) for k in ("startDate", "createdAt", "closedTime", "endDate", "closed")}
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(meta))
        start = meta.get("startDate") or meta.get("createdAt")
        if not start:
            raise RuntimeError(f"no start date in gamma metadata for {m['market_slug']}")
        end = (meta.get("closedTime") if meta.get("closed") else None) or meta.get("endDate")
        out.append({"market_slug": m["market_slug"], "label": key, "token_id": str(m["token_id"]), "sign": int(m["sign"]),
                    "start": _utc(start).isoformat(), "end": _utc(end).isoformat(), "source": "panel_A"})
    return out


def replication_markets(ranks: range | None = None) -> list[dict]:
    cands = json.loads(MARKETS_PATH.read_text())["candidates"]
    out = []
    for c in cands:
        if ranks is not None and c["rank"] not in ranks:
            continue
        out.append({"market_slug": c["market_slug"], "label": c["market_slug"][:40], "token_id": str(c["token_id"]),
                    "sign": int(c["sign"]), "start": c["start"], "end": c["end"],
                    "source": "panel_B" if c["rank"] <= 10 else "candidate", "rank": c["rank"]})
    return out


def market_closures(m: dict, last_session: pd.Timestamp, cal: TradingCalendar) -> list[Closure]:
    """Closures with close day in [SPAN_START, session before last_session] covered by the market's life."""
    s, e = _utc(m["start"]), _utc(m["end"])
    out = []
    for c in build_closures(SPAN_START, (last_session - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), cal):
        if c.open_day > last_session:
            continue
        if c.nominal_close >= s and c.nominal_open <= e:
            out.append(c)
    return out


def fetch_pm_for(m: dict, closures: list[Closure], session=None, workers: int = 6) -> dict:
    def one(c: Closure):
        a = c.nominal_close - pd.Timedelta(minutes=PARAMS.pm_pad_before_min)
        b = c.nominal_open + pd.Timedelta(minutes=PARAMS.pm_pad_after_min)
        try:
            return c.key, fetch_pm_history(m["token_id"], a, b, CACHE_DIR / "pm", session=session)
        except Exception as exc:  # noqa: BLE001
            return c.key, exc

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, closures))


# ---------------------------------------------------------------- SPY


def _chunks(start: str, end: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out, cur = [], s.replace(day=1)
    while cur <= e:
        nxt = cur + pd.offsets.MonthBegin(1)
        out.append((cur.tz_localize("UTC") - pd.Timedelta(days=1), nxt.tz_localize("UTC") + pd.Timedelta(days=1)))
        cur = nxt
    return out


def fetch_minutes(client, start: str, end: str, ticker: str = TICKER) -> pd.DataFrame:
    parts = []
    for a, b in _chunks(start, end):
        path = f"/v2/aggs/ticker/{ticker}/range/1/minute/{int(a.timestamp() * 1000)}/{int(b.timestamp() * 1000)}"
        rows = client.get_all(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
        if rows:
            df = pd.DataFrame(rows)
            parts.append(pd.DataFrame({"open": df["o"].astype(float).to_numpy(), "close": df["c"].astype(float).to_numpy(),
                                       "volume": df["v"].astype(float).to_numpy()},
                                      index=pd.to_datetime(df["t"], unit="ms", utc=True)))
    if not parts:
        return pd.DataFrame(columns=["open", "close", "volume"], index=pd.DatetimeIndex([], tz="UTC"))
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()


def fetch_daily(client, start: str, end: str, ticker: str = TICKER) -> pd.DataFrame:
    rows = client.get_all(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                          {"adjusted": "true", "sort": "asc", "limit": 50000})
    df = pd.DataFrame(rows)
    idx = pd.DatetimeIndex(pd.to_datetime(df["t"], unit="ms", utc=True)).tz_convert("America/New_York").normalize().tz_localize(None)
    return pd.DataFrame({"open": df["o"].astype(float).to_numpy(), "close": df["c"].astype(float).to_numpy(),
                         "volume": df["v"].astype(float).to_numpy(),
                         "vwap": df.get("vw", df["c"]).astype(float).to_numpy()}, index=idx)


def fetch_dividends(client, start: str, end: str, ticker: str = TICKER) -> pd.Series:
    rows = client.get_all("/v3/reference/dividends", {"ticker": ticker, "ex_dividend_date.gte": start,
                                                      "ex_dividend_date.lte": end, "limit": 1000})
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(r["ex_dividend_date"]): float(r["cash_amount"]) for r in rows
                   if str(r.get("dividend_type", "CD")).upper() in ("CD", "")})
    return s.sort_index()
