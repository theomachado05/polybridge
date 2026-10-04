from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
AI_MAP = RESEARCH.parent / "backend" / "app" / "data" / "ai_map.json"
UTC = timezone.utc
ET = "America/New_York"
BAR_MIN = 5
DAILY_START = "2025-09-01"


def proposer_links() -> list[dict]:
    items = json.loads(AI_MAP.read_text())["items"]
    out = []
    for key, v in items.items():
        if not key.startswith("polymarket:"):
            continue
        for m in v.get("mappings", []):
            out.append({"market": key, "question": v["question"], "ticker": m["ticker"],
                        "direction": 1 if m["direction"] == "up_on_yes" else -1})
    return out


def is_motivating(market: str, question: str) -> bool:
    return market in cfg.MOTIVATING or any(w in question.lower() for w in cfg.MOTIVATING_WORDS)


def _massive_session():
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.massive import BASE_URL, load_api_key

    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {load_api_key(search_from=RESEARCH)}"
    return s, BASE_URL


def massive_rows(s: requests.Session, url: str, params: dict | None = None) -> list[dict]:
    rows: list[dict] = []
    while url:
        for attempt in range(8):
            try:
                r = s.get(url, params=params, timeout=60)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                time.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code in ds.RETRY:
                time.sleep(min(2 ** attempt, 20))
                continue
            break
        r.raise_for_status()
        d = r.json()
        rows.extend(d.get("results") or [])
        url, params = d.get("next_url"), None
    return rows


def month_chunks(start: str, end: str) -> list[tuple[str, str]]:
    out, cur = [], pd.Timestamp(start)
    last = pd.Timestamp(end)
    while cur <= last:
        nxt = (cur + pd.offsets.MonthBegin(1)).normalize()
        out.append((cur.strftime("%Y-%m-%d"), min(nxt - pd.Timedelta(days=1), last).strftime("%Y-%m-%d")))
        cur = nxt
    return out


def equity_bars(s: requests.Session, base: str, ticker: str, start: str = cfg.WINDOW_START,
                end: str = cfg.WINDOW_END) -> dict[str, np.ndarray]:
    rows = []
    for a, b in month_chunks(start, end):
        rows += massive_rows(s, f"{base}/v2/aggs/ticker/{ticker}/range/{BAR_MIN}/minute/{a}/{b}",
                             {"adjusted": "true", "sort": "asc", "limit": 50000})
    if not rows:
        return {k: np.array([]) for k in ("t", "o", "c", "v", "vw")}
    df = pd.DataFrame(rows).drop_duplicates("t").sort_values("t")
    local = pd.to_datetime(df.t, unit="ms", utc=True).dt.tz_convert(ET)
    mins = local.dt.hour * 60 + local.dt.minute
    df = df[(mins >= 570) & (mins < 960)]
    return {"t": (df.t.to_numpy() // 1000).astype(np.int64), "o": df.o.to_numpy(float), "c": df.c.to_numpy(float),
            "v": df.v.to_numpy(float), "vw": df.get("vw", df.c).to_numpy(float)}


def daily_bars(s: requests.Session, base: str, ticker: str, start: str = DAILY_START,
               end: str = cfg.WINDOW_END) -> dict[str, np.ndarray]:
    rows = massive_rows(s, f"{base}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                        {"adjusted": "true", "sort": "asc", "limit": 50000})
    days = [datetime.fromtimestamp(r["t"] / 1000, UTC).strftime("%Y-%m-%d") for r in rows]
    return {"day": np.array(days), "c": np.array([float(r["c"]) for r in rows]), "o": np.array([float(r["o"]) for r in rows])}


def pull_market(market: str, pt: ds.Throttle, t1: datetime) -> dict:
    mid = market.split(":")[1]
    g = ds.get_json(f"{ds.GAMMA}/markets/{mid}", throttle=pt)
    tokens = g.get("clobTokenIds")
    tokens = json.loads(tokens) if isinstance(tokens, str) else (tokens or [])
    start = max(ds._iso(g.get("startDate") or g.get("createdAt")),
                datetime.fromisoformat(cfg.WINDOW_START).replace(tzinfo=UTC) - timedelta(days=4))
    h = ds.pm_history({"token": tokens[0]}, start.replace(second=0, microsecond=0), t1, pt)
    np.savez_compressed(CACHE / f"pm_{mid}.npz", **h)
    return {"market": market, "question": g.get("question"), "start": start.isoformat(), "end": g.get("endDate"),
            "closed": bool(g.get("closed")), "points": int(len(h["t"])), "volume": float(g.get("volumeNum") or 0)}


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    t1 = datetime.now(UTC).replace(second=0, microsecond=0)
    links = proposer_links()
    markets = sorted({l["market"] for l in links})
    tickers = sorted({l["ticker"] for l in links} | {"SPY"})
    t0 = time.time()
    pt = ds.Throttle(5.0)
    metas, failures = [], []

    def job(mk):
        try:
            return pull_market(mk, pt, t1)
        except Exception as e:
            failures.append({"market": mk, "error": repr(e)[:200]})
            return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        metas = [m for m in ex.map(job, markets) if m]
    print(f"{time.time() - t0:5.0f}s odds: {len(metas)} markets, {len(failures)} failures", flush=True)

    s, base = _massive_session()
    eq = {}
    for tk in tickers:
        try:
            b, d = equity_bars(s, base, tk), daily_bars(s, base, tk)
            np.savez_compressed(CACHE / f"eq_{tk}.npz", **b)
            np.savez_compressed(CACHE / f"day_{tk}.npz", **d)
            eq[tk] = {"bars": int(len(b["t"])), "days": int(len(d["day"]))}
        except Exception as e:
            failures.append({"ticker": tk, "error": repr(e)[:200].replace(s.headers["Authorization"], "<key>")})
            eq[tk] = {"bars": 0, "days": 0}
    print(f"{time.time() - t0:5.0f}s equities: {sum(1 for v in eq.values() if v['bars'])} of {len(tickers)} tickers", flush=True)
    (CACHE / "pull_meta.json").write_text(json.dumps({"t1": t1.isoformat(), "markets": metas, "equities": eq, "failures": failures,
                                                      "seconds": round(time.time() - t0, 1)}, indent=1))
    print(f"done: {len(failures)} failures, {time.time() - t0:.0f}s", flush=True)
    for f in failures[:10]:
        print("  failure:", f, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
