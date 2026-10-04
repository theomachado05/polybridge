"""S10 Part 5 recorder (METHOD.md amendment 5): the live order book of the current 15-minute Bitcoin Up/Down market
and Coinbase's live BTC-USD price, about once a second, until a stop time. Read-only; one Polymarket request a second.

Run from `research/`:  python -m s10_weekend_lag.live --until "2026-10-04 06:00"
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime

import requests

from s1_twin_spread import data as ds

from . import config as cfg
from .btc_pull import ET
from .run import CACHE

LIVE = CACHE / "live"


def token_for(start: int, sess: requests.Session) -> dict | None:
    r = sess.get(f"{ds.GAMMA}/events", params={"slug": cfg.BTC_SLUG.format(start=start)}, timeout=10)
    if not r.ok or not r.json():
        return None
    m = r.json()[0]["markets"][0]
    outs, toks = json.loads(m["outcomes"]), json.loads(m["clobTokenIds"])
    fs = m.get("feeSchedule") or {}
    return {"start": start, "id": m["id"], "condition": m["conditionId"], "token_up": toks[outs.index("Up")],
            "fee_rate": float(fs.get("rate", 0.0)) if m.get("feesEnabled") else 0.0}


def main() -> int:
    until = datetime.strptime(sys.argv[sys.argv.index("--until") + 1], "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp()
    LIVE.mkdir(parents=True, exist_ok=True)
    pm, cb = requests.Session(), requests.Session()
    markets: dict[int, dict] = {}
    candles_at = 0.0
    out = open(LIVE / f"rec_{datetime.now(ET).strftime('%Y%m%d_%H%M')}.jsonl", "a")
    while time.time() < until:
        t0 = time.time()
        start = int(t0) - int(t0) % cfg.BTC_WINDOW_S
        rec: dict = {"ts": t0, "start": start}
        try:
            for s in (start, start + cfg.BTC_WINDOW_S):            # the current window and the next one
                if s not in markets:
                    markets[s] = token_for(s, pm)
                    if markets[s]:
                        out.write(json.dumps({"type": "market", **markets[s]}) + "\n")
            tk = cb.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", timeout=5).json()
            rec.update({"cb_price": float(tk["price"]), "cb_bid": float(tk["bid"]), "cb_ask": float(tk["ask"]), "cb_time": tk.get("time"),
                        "cb_rtt": time.time() - t0})
            m = markets.get(start)
            if m:
                t1 = time.time()
                b = pm.post(f"{ds.CLOB}/books", json=[{"token_id": m["token_up"]}], timeout=5).json()[0]
                bids = sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])), reverse=True)[:5]
                asks = sorted((float(x["price"]), float(x["size"])) for x in b.get("asks", []))[:5]
                rec.update({"market": m["id"], "bids": bids, "asks": asks, "pm_ts": b.get("timestamp"), "pm_rtt": time.time() - t1})
            if t0 - candles_at > 60:
                c = cb.get("https://api.exchange.coinbase.com/products/BTC-USD/candles", params={"granularity": 60}, timeout=10).json()
                rec["candles"] = [[int(x[0]), float(x[3]), float(x[4])] for x in c[:70]]
                candles_at = t0
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        out.write(json.dumps(rec) + "\n")
        out.flush()
        time.sleep(max(0.0, 1.0 - (time.time() - t0)))
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
