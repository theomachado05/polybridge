from __future__ import annotations

import gzip
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from s1_twin_spread import data as ds

from . import config as cfg
from . import engine as en

HERE = Path(__file__).resolve().parent
OUT = HERE / ".cache" / "live"
ET = ZoneInfo("America/New_York")
DEPTH = 10


def fetch_books(tokens: list[str], pt: ds.Throttle) -> dict[str, dict]:
    out: dict[str, dict] = {}
    s = requests.Session()
    for i in range(0, len(tokens), cfg.BOOKS_PER_CALL):
        chunk = tokens[i:i + cfg.BOOKS_PER_CALL]
        for attempt in range(4):
            pt.wait()
            try:
                r = s.post(f"{ds.CLOB}/books", json=[{"token_id": t} for t in chunk], timeout=30)
                if r.status_code == 200:
                    for b in r.json():
                        out[b.get("asset_id")] = b
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
    return out


def levels(book: dict | None, side: str) -> list[tuple[float, float]]:
    if not book:
        return []
    lv = [(float(x["price"]), float(x["size"])) for x in book.get(side) or []]
    lv.sort(key=lambda x: -x[0] if side == "bids" else x[0])
    return lv[:DEPTH]


def check(bundle: dict, meta: dict, books: dict) -> list[dict]:
    fees = {i: (meta[i]["fee_rate"], meta[i]["fee_exponent"]) for i in bundle["legs"]}
    tok = {i: meta[i]["token"] for i in bundle["legs"]}
    out = []
    if bundle["kind"] == "negrisk":
        bk = [books.get(tok[i]) for i in bundle["legs"]]
        for side, s in (("buy_yes", "asks"), ("buy_no", "bids")):
            r = en.basket_arb([levels(b, s) for b in bk], [fees[i] for i in bundle["legs"]], side)
            tops = [levels(b, s)[:1] for b in bk]
            r.update(kind="negrisk", event=bundle["event"], legs=bundle["legs"], side=side, augmented=bundle.get("negRiskAugmented"),
                     n=len(bundle["legs"]), missing=sum(1 for x in tops if not x),
                     sum_top=sum(x[0][0] for x in tops if x) if all(tops) else None)
            out.append(r)
        return out
    for a, b in bundle["pairs"]:
        ba, ab = levels(books.get(tok[a]), "bids"), levels(books.get(tok[b]), "asks")
        r = en.pair_arb(ba, ab, fees[a], fees[b])
        r.update(kind=bundle["kind"], event=bundle["event"], rich=a, cheap=b, bid_rich=ba[0][0] if ba else None,
                 ask_cheap=ab[0][0] if ab else None, bid_rich_size=ba[0][1] if ba else None, ask_cheap_size=ab[0][1] if ab else None)
        out.append(r)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lb = json.loads((HERE / "live_bundles.json").read_text())
    bundles, meta = lb["bundles"], lb["markets"]
    tokens = sorted({meta[i]["token"] for b in bundles for i in b["legs"]})
    until = datetime.strptime(cfg.LIVE_UNTIL_ET, "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp()
    pt = ds.Throttle(1.0)
    n = 0
    print(f"{len(bundles)} bundles, {len(tokens)} tokens; until {cfg.LIVE_UNTIL_ET} New York", flush=True)
    while time.time() < until:
        t0 = time.time()
        books = fetch_books(tokens, pt)
        snap = {"t": t0, "books": {k: {"b": levels(v, "bids"), "a": levels(v, "asks")} for k, v in books.items()}}
        with gzip.open(OUT / "books.jsonl.gz", "at") as fh:
            fh.write(json.dumps(snap) + "\n")
        arbs = 0
        with open(OUT / "checks.jsonl", "a") as fh:
            for b in bundles:
                for r in check(b, meta, books):
                    r["t"] = t0
                    arbs += r["size"] > 0
                    fh.write(json.dumps(r) + "\n")
        n += 1
        print(f"{datetime.now(ET):%H:%M:%S} snapshot {n}: {len(books)}/{len(tokens)} books, {arbs} checks with money locked in", flush=True)
        time.sleep(max(5.0, cfg.LIVE_INTERVAL_S - (time.time() - t0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
