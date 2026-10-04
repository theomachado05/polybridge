from __future__ import annotations

import argparse
import json

import requests

GAMMA = "https://gamma-api.polymarket.com"


def search_events(query: str, closed: bool = True, limit: int = 10) -> list[dict]:
    params = {"q": query, "limit_per_type": limit}
    if closed:
        params["events_status"] = "closed"
    r = requests.get(f"{GAMMA}/public-search", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("events", [])


def event_by_slug(slug: str) -> dict | None:
    r = requests.get(f"{GAMMA}/events", params={"slug": slug}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def market_by_slug(slug: str) -> dict | None:
    for closed in ("false", "true"):
        r = requests.get(f"{GAMMA}/markets", params={"slug": slug, "closed": closed}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if rows:
            return rows[0]
    return None


def token_ids(market: dict) -> list[str]:
    raw = market.get("clobTokenIds") or "[]"
    return json.loads(raw) if isinstance(raw, str) else list(raw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--open", action="store_true", help="include open events")
    ap.add_argument("--markets", action="store_true", help="list each event's markets")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    for e in search_events(a.query, closed=not a.open, limit=a.limit):
        print(f"{e['slug']}  vol={float(e.get('volume') or 0):,.0f}  {str(e.get('startDate'))[:10]}..{str(e.get('endDate'))[:10]}  {e.get('title')}")
        if a.markets:
            for m in e.get("markets", []):
                print(f"    {m['slug']}  vol={float(m.get('volume') or 0):,.0f}  {m.get('question')}")


if __name__ == "__main__":
    main()
