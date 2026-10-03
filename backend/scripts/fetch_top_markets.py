"""Rebuild app/data/market_universe.json: top open Polymarket + Kalshi markets by 24h volume.
Documentation-grade; not run in tests. Usage: uv run python scripts/fetch_top_markets.py"""
import json
import re
from datetime import datetime
from pathlib import Path

import httpx

GAMMA = "https://gamma-api.polymarket.com/markets"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/events"
CATS = ["Economics", "Companies", "Financials", "Politics", "Science and Technology"]
SPORTS = re.compile(
    r"\b(nba|nfl|mlb|nhl|ncaa|fifa|world cup|premier league|la liga|ufc|mma|tennis|golf|f1|grand prix|"
    r"super bowl|stanley cup|champions league|esports?|counter-strike|cs2|dota|valorant|league of legends|"
    r"vs\.?|o/u|spread)\b", re.I)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _get(c, url, params):
    try:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        print(f"warning: skipping failing request {url} {params}: {e}")
        return [] if url == GAMMA else None


def polymarket(c):
    for off in (0, 100, 200):
        p = dict(active="true", closed="false", limit=100, offset=off, order="volume24hr", ascending="false")
        for m in _get(c, GAMMA, p):
            prices = json.loads(m.get("outcomePrices") or "[]")
            yield dict(source="polymarket", id=str(m["id"]), question=m["question"],
                       yes_price=num(prices[0]) if prices else None,
                       volume_24h=num(m.get("volume24hr")), end_date=m.get("endDate"))


def kalshi(c):
    for cat in CATS:
        p = dict(status="open", limit=60, with_nested_markets="true", category=cat)
        for e in (_get(c, KALSHI, p) or {}).get("events", []):
            if e.get("markets"):
                m = e["markets"][0]  # first market per event
                yield dict(source="kalshi", id=m["ticker"], question=m.get("title") or e["title"],
                           yes_price=num(m.get("last_price_dollars") or m.get("last_price")),
                           volume_24h=num(m.get("volume_24h")), end_date=m.get("close_time"))


def main():
    with httpx.Client(timeout=15) as c:
        rows = list(polymarket(c)) + list(kalshi(c))
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: -r["volume_24h"]):
        key = re.sub(r"\W+", " ", r["question"].lower()).strip()
        if SPORTS.search(r["question"]) or key in seen:
            continue
        seen.add(key)
        out.append(r)
    path = Path(__file__).parents[1] / "app" / "data" / "market_universe.json"
    path.write_text(json.dumps({"fetched_at": datetime.now().isoformat(),
                                "filter": "sports/esports removed by keyword; duplicates removed",
                                "markets": out}, indent=1))


if __name__ == "__main__":
    main()
