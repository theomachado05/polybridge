from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import requests

from s1_twin_spread import data as ds

from . import config as cfg
from .run import CACHE

ET = __import__("zoneinfo").ZoneInfo("America/New_York")
BTC = CACHE / "btc"


def window_starts() -> list[int]:
    a = int(datetime.strptime(cfg.BTC_FIRST_ET, "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp())
    b = int(datetime.strptime(cfg.BTC_LAST_ET, "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp())
    return list(range(a, b, cfg.BTC_WINDOW_S))


def parse_market(e: dict) -> dict | None:
    if not e.get("markets"):
        return None
    m = e["markets"][0]
    outs, toks = json.loads(m["outcomes"]), json.loads(m["clobTokenIds"])
    prices = json.loads(m.get("outcomePrices") or "[]")
    up = outs.index("Up")
    res = None
    if m.get("closed") and prices and prices[up] in ("1", "0"):
        res = float(prices[up])
    fs = m.get("feeSchedule") or {}
    return {"slug": e["slug"], "start": int(e["slug"].rsplit("-", 1)[1]), "id": m["id"], "condition": m["conditionId"],
            "token_up": toks[up], "result_up": res, "fee_rate": float(fs.get("rate", 0.0)) if m.get("feesEnabled") else 0.0,
            "fee_exponent": float(fs.get("exponent", 1.0)), "volume": float(m.get("volume") or 0.0), "closed_time": m.get("closedTime")}


def catalogue(pt: ds.Throttle) -> list[dict]:
    f = BTC / "catalogue.json"
    if f.exists():
        return json.loads(f.read_text())
    starts, out = window_starts(), []
    for i in range(0, len(starts), cfg.BTC_GAMMA_BATCH):
        chunk = [cfg.BTC_SLUG.format(start=s) for s in starts[i:i + cfg.BTC_GAMMA_BATCH]]
        d = ds.get_json(f"{ds.GAMMA}/events", [("slug", s) for s in chunk], throttle=pt)
        for e in d if isinstance(d, list) else []:
            m = parse_market(e)
            if m:
                out.append(m)
    out.sort(key=lambda m: m["start"])
    f.write_text(json.dumps(out))
    return out


def histories(cat: list[dict], pt: ds.Throttle) -> None:
    by_day: dict[str, list[dict]] = {}
    for m in cat:
        by_day.setdefault(datetime.fromtimestamp(m["start"], ET).strftime("%Y-%m-%d"), []).append(m)

    def one(m):
        a = datetime.fromtimestamp(m["start"] - 60, timezone.utc)
        b = datetime.fromtimestamp(m["start"] + cfg.BTC_WINDOW_S + 60, timezone.utc)
        try:
            h = ds.pm_history({"token": m["token_up"]}, a, b, pt)
            return m["id"], [h["t"].tolist(), [round(float(x), 4) for x in h["p"]]]
        except Exception as e:  # noqa: BLE001
            return m["id"], {"error": str(e)[:200]}

    for day, ms in sorted(by_day.items()):
        f = BTC / f"pm_{day}.json"
        if f.exists():
            continue
        with ThreadPoolExecutor(max_workers=4) as ex:
            res = dict(ex.map(one, ms))
        f.write_text(json.dumps(res))
        print(day, len(ms), "markets", sum(1 for v in res.values() if isinstance(v, list) and v[0]), "with prices", flush=True)


def spot() -> None:
    f = BTC / "spot.npz"
    if f.exists():
        return
    starts = window_starts()
    a, b = starts[0] - 3 * 3600, starts[-1] + cfg.BTC_WINDOW_S + 3600
    rows: dict[int, tuple] = {}
    s = a
    while s < b:
        e = min(s + 300 * 60, b)
        for k in range(6):
            r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles", timeout=30,
                             params={"granularity": 60, "start": datetime.fromtimestamp(s, timezone.utc).isoformat(),
                                     "end": datetime.fromtimestamp(e - 60, timezone.utc).isoformat()})
            if r.ok:
                break
            time.sleep(2 + 2 * k)
        r.raise_for_status()
        for t, lo, hi, o, c, v in r.json():
            rows[int(t)] = (o, c, v)
        s = e
        time.sleep(0.34)
    t = np.array(sorted(rows), dtype=np.int64)
    np.savez_compressed(f, t=t, o=np.array([rows[x][0] for x in t]), c=np.array([rows[x][1] for x in t]), v=np.array([rows[x][2] for x in t]))
    print("spot minutes", len(t), flush=True)


def main() -> int:
    BTC.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    pt = ds.Throttle(cfg.BTC_RATE)
    spot()
    cat = catalogue(pt)
    print("catalogue", len(cat), "markets of", len(window_starts()), "windows", f"{time.time() - t0:.0f}s", flush=True)
    histories(cat, pt)
    (BTC / "pull_meta.json").write_text(json.dumps({"t1": datetime.now(timezone.utc).isoformat(), "seconds": round(time.time() - t0, 1),
                                                    "markets": len(cat), "windows": len(window_starts())}))
    print(f"done {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
