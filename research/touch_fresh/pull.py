"""touch_fresh pull: first-weekend prints and results (Polymarket), option legs and underlying quotes (Massive).
Streamed one market at a time, cached, resumable.

Run from `research/`:  python -m touch_fresh.pull
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from s1_twin_spread import data as ds
from s21_options_anchor import engine as eg
from s21_options_anchor import pull as p21

from . import config as cfg

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
ET = ZoneInfo("America/New_York")


def anchor_epoch(day: str) -> float:
    return pd.Timestamp(f"{day} {'12:55' if day in cfg.HALF_DAYS else '15:55'}", tz=ET).timestamp()


def expiry_order(d0: date, a_day: date) -> list[date]:
    out = []
    for n in range(cfg.MAX_EXPIRY_GAP_DAYS + 1):
        for d in ((d0 + timedelta(days=n), d0 - timedelta(days=n)) if n else (d0,)):
            if d.weekday() < 5 and (d - a_day).days >= cfg.MIN_DAYS_TO_EXPIRY and d not in out:
                out.append(d)
    return out


def build_anchor(src: p21.Src, m: dict) -> dict:
    und, up = m["ticker"], m["direction"] > 0
    a_day, d0 = date.fromisoformat(m["entry_day"]), date.fromisoformat(m["end_session"])
    at = anchor_epoch(m["entry_day"])
    tried, last = 0, "no listed expiry within 45 days of the window's end"
    for d in expiry_order(d0, a_day):
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
        lo_leg, hi_leg = legs[sp.k1], legs[sp.k2]
        return {"status": "ok", "expiry": d.isoformat(), "expiry_rank": tried, "days_expiry_minus_end": (d - d0).days,
                "T_days": (d - a_day).days, "tau_days": (d0 - a_day).days, "k_lo": sp.k1, "k_hi": sp.k2, "stepped": sp.stepped,
                "leg_lo": lo_leg["ticker"], "leg_lo_bid": lo_leg["bid"], "leg_lo_ask": lo_leg["ask"], "leg_lo_age_s": at - lo_leg["ts"],
                "leg_hi": hi_leg["ticker"], "leg_hi_bid": hi_leg["bid"], "leg_hi_ask": hi_leg["ask"], "leg_hi_age_s": at - hi_leg["ts"],
                "zero_bid_leg": bool(lo_leg["bid"] <= 0 or hi_leg["bid"] <= 0), "p_lo": sp.p_lo, "p_mid": sp.p_mid, "p_hi": sp.p_hi}
    return {"status": last, "expiries_tried": tried}


def stock_quote(src: p21.Src, ticker: str, at: float) -> dict | None:
    iso = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    k = f"sq|{ticker}|{iso}"
    if k in src.cache:
        return src.cache[k]
    res = src._get(f"/v3/quotes/{ticker}", {"limit": 1, "timestamp.lte": iso, "order": "desc", "sort": "timestamp"}).get("results") or []
    v = None
    if res:
        x = res[0]
        v = {"bid": float(x.get("bid_price") or 0), "ask": float(x.get("ask_price") or 0), "ts": float(x.get("sip_timestamp") or 0) / 1e9}
    src._put(k, v)
    return v


def daily_closes(src: p21.Src, ticker: str) -> dict[str, float]:
    k = f"d|{ticker}"
    if k in src.cache:
        return src.cache[k]
    tk = "I:SPX" if ticker == "SPX" else ticker
    res = src._get(f"/v2/aggs/ticker/{tk}/range/1/day/2026-03-01/2026-10-02", {"adjusted": "false", "limit": 50000}).get("results") or []
    v = {datetime.fromtimestamp(r["t"] / 1000, ET).strftime("%Y-%m-%d"): float(r["c"]) for r in res}
    src._put(k, v)
    return v


def pm_record(m: dict, pt: ds.Throttle) -> dict:
    f = CACHE / f"pm_{m['id']}.json"
    if f.exists():
        return json.loads(f.read_text())
    rec: dict = {"reach_oldest": None, "served": 0, "prints": []}
    try:
        raw = ds.pm_trades(m["condition"], m["entry_epoch"], pt, max_pages=cfg.PRINT_PAGES)
        ts = [float(t.get("timestamp", 0)) for t in raw]
        keep = [t for t, s in zip(raw, ts) if m["entry_epoch"] <= s <= m["entry_epoch"] + cfg.PRINT_WINDOW_S]
        rec = {"reach_oldest": min(ts) if ts else None, "served": len(raw),
               "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]}
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)[:200]
    g = ds.get_json(f"{ds.GAMMA}/markets/{m['id']}", throttle=pt)
    prices = json.loads(g["outcomePrices"]) if g.get("outcomePrices") else []
    yes = float(prices[0]) if prices else float("nan")
    rec["outcome"] = yes if g.get("closed") and yes in (0.0, 1.0) else None
    rec["closed_time"] = g.get("closedTime")
    f.write_text(json.dumps(rec))
    return rec


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    p21.CACHE = CACHE
    u = json.loads((HERE / "universe.json").read_text())["markets"]
    stop = pd.Timestamp(cfg.PULL_STOP_ET, tz=ET).timestamp()
    src = p21.Src(offline=False, stop_epoch=stop)
    src._open()
    pt, t0 = ds.Throttle(cfg.PM_RPS), time.time()
    out = []
    for i, m in enumerate(u):
        pm = pm_record(m, pt)
        row = {"id": m["id"]}
        try:
            row.update(build_anchor(src, m))
            at = anchor_epoch(m["entry_day"])
            if m["ticker"] != "SPX":
                q = stock_quote(src, m["ticker"], at)
                row["stock_quote"] = q
            daily_closes(src, m["ticker"])
        except (p21.StopPull, p21.NotPulled):
            row["status"] = "not pulled"
            src.offline = True
        except p21.FetchError as e:
            row["status"] = f"fetch error: {str(e)[:160]}"
        out.append(row)
        with open(CACHE / "anchors.jsonl", "a") as fh:
            fh.write(json.dumps(row) + "\n")
        if (i + 1) % 10 == 0:
            ok = sum(r.get("status") == "ok" for r in out)
            print(f"{i + 1}/{len(u)} markets, {ok} anchored, {src.requests} massive requests, {len(src.errors)} errors, {time.time() - t0:.0f}s", flush=True)
    st = pd.Series([r.get("status") for r in out]).value_counts().to_dict()
    src.note(f"touch_fresh pull finished: {src.requests} requests in {time.time() - t0:.0f}s, {len(src.errors)} errors; status {st}")
    for e in src.errors[:10]:
        src.note(f"error: {e}")
    print(json.dumps(st, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
