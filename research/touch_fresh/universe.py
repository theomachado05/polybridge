"""Fresh "will it hit" universe from Polymarket catalogue metadata only (METHOD.md section 2). No price and no
result is read: `outcomePrices` is dropped from every record before anything is kept.

Run from `research/`:  python -m touch_fresh.universe
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from s21_options_anchor import engine as eg

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ET = ZoneInfo("America/New_York")


def frozen_ids() -> set[str]:
    ids: set[str] = set()
    for f in cfg.FROZEN_UNIVERSES:
        ids |= {str(m["id"]) for m in json.loads((RESEARCH / f).read_text())["markets"]}
    for f in cfg.FROZEN_CSVS:
        with open(RESEARCH / f) as fh:
            ids |= {str(r["market"]) for r in csv.DictReader(fh)}
    return ids


def asset_class(title: str) -> str | None:
    if re.search(cfg.EXCLUDE_TITLE_RE, title, re.I):
        return None
    if "S&P 500" in title:
        return "sp500"
    sym = re.findall(r"\(([A-Z]{1,5})\)", title)
    if len(sym) != 1 or sym[0] in cfg.NOT_STOCK:
        return None
    return "stock"


def last_session_before_weekend(d: date) -> date:
    """The Friday of d's week, stepped back over holidays."""
    f = d + timedelta(days=(4 - d.weekday()) % 7)
    while f.isoformat() in cfg.HOLIDAYS or f.weekday() >= 5:
        f -= timedelta(days=1)
    return f


def entry_instant(start_iso: str) -> tuple[date, float]:
    """The first weekend start (20:00 New York on the last session day before a weekend) strictly after the listing."""
    t0 = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp()
    d = datetime.fromtimestamp(t0, ET).date()
    while True:
        f = last_session_before_weekend(d)
        at = datetime(f.year, f.month, f.day, 20, 0, tzinfo=ET).timestamp()
        if at > t0:
            return f, at
        d = f + timedelta(days=3)


def fetch_events() -> list[dict]:
    out, off, s = [], 0, requests.Session()
    while True:
        r = s.get(f"{cfg.GAMMA}/events", params={"tag_slug": cfg.TAG, "closed": "true", "limit": 100, "offset": off}, timeout=30)
        r.raise_for_status()
        d = r.json()
        if not d:
            return out
        out += d
        off += 100
        time.sleep(0.3)


def main() -> int:
    seen = frozen_ids()
    events = fetch_events()
    counts: dict[str, int] = {"events_served": len(events)}
    markets = []

    def drop(why: str):
        counts[why] = counts.get(why, 0) + 1

    for e in events:
        cls = asset_class(e["title"])
        if cls is None or not re.search(r"\bhit\b", e["title"], re.I) or re.search(r"all time high", e["title"], re.I):
            continue
        ev_vol = float(e.get("volume") or 0)
        for m in e.get("markets") or []:
            m.pop("outcomePrices", None)
            if str(m["id"]) in seen:
                drop("in a frozen S9/S15/S18/S19/S21 list")
                continue
            if not m.get("closed"):
                drop("not closed")
                continue
            if ev_vol < cfg.RELAXED_MIN_EVENT_VOLUME:
                drop("event volume below the relaxed floor")
                continue
            if float(m.get("volume") or 0) < cfg.MIN_MARKET_VOLUME:
                drop("market volume below the floor")
                continue
            tokens = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else []
            if not tokens or not m.get("startDate") or not m.get("conditionId"):
                drop("no token, listing time or condition")
                continue
            label = m.get("groupItemTitle") or ""
            text = f"{m['question']} {label}"
            sign = 1 if ("(HIGH)" in text or "↑" in text) else -1 if ("(LOW)" in text or "↓" in text) else 0
            if sign == 0:
                sign = 1 if re.search(r"\breach\b", m["question"]) else -1 if re.search(r"\bdip\b", m["question"]) else 0
            rec = {"id": str(m["id"]), "event": str(e["id"]), "event_title": e["title"], "asset_class": cls, "question": m["question"],
                   "label": label, "sign": sign, "volume": float(m.get("volume") or 0), "event_volume": ev_vol, "start": m["startDate"], "strict": ev_vol >= cfg.MIN_EVENT_VOLUME,
                   "closed_time": m.get("closedTime"), "end_date": m.get("endDate"), "token": tokens[0], "condition": m["conditionId"]}
            fs = m.get("feeSchedule") or {}
            fee_on = bool(m.get("feesEnabled")) and bool(fs)
            rec["fee_rate"] = float(fs.get("rate", 0.0)) if fee_on else 0.0
            rec["fee_exponent"] = float(fs.get("exponent", 1)) if fee_on else 1.0
            p, why = eg.parse_market(rec)
            if p is None:
                drop(f"parse: {why}")
                continue
            day, at = entry_instant(rec["start"])
            if date.fromisoformat(p["end_session"]) <= day:
                drop("the window ends on or before the first weekend's Friday")
                continue
            ct = rec["closed_time"]
            if ct:
                cte = pd.Timestamp(ct).timestamp()
                if cte <= at:
                    drop("closed before the first weekend")
                    continue
            if day.isoformat() < cfg.FIRST_ENTRY_DAY:
                drop("first weekend before the fixed start")
                continue
            markets.append({**rec, **p, "entry_day": day.isoformat(), "entry_epoch": at})
    counts["markets_kept"] = len(markets)
    counts["events_kept"] = len({m["event"] for m in markets})
    counts["strict_markets"] = sum(m["strict"] for m in markets)
    counts["strict_events"] = len({m["event"] for m in markets if m["strict"]})
    out = {"built_utc": datetime.now(timezone.utc).isoformat(), "counts": counts, "markets": markets}
    (HERE / "universe.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(counts, indent=1))
    by: dict[str, int] = {}
    for m in markets:
        by[m["ticker"]] = by.get(m["ticker"], 0) + 1
    print(dict(sorted(by.items(), key=lambda x: -x[1])))
    print("entry days:", sorted({m["entry_day"] for m in markets}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
