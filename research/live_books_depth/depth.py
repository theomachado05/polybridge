import glob, gzip, json, statistics as st, sys
from pathlib import Path

raw = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "polybridge-live/research/results/live_books/raw")
books = {}
for f in sorted(glob.glob(f"{raw}/*.gz")):
    try:
        with gzip.open(f, "rt") as h:
            for line in h:
                if '"book"' not in line:
                    continue
                try:
                    m = json.loads(line)["m"]
                except Exception:
                    continue
                for e in (m if isinstance(m, list) else [m]):
                    if isinstance(e, dict) and e.get("event_type") == "book":
                        books[e["asset_id"]] = e
    except EOFError:
        pass
dep, spr = [], []
for e in books.values():
    bids = [(float(x["price"]), float(x["size"])) for x in e.get("bids", [])]
    asks = [(float(x["price"]), float(x["size"])) for x in e.get("asks", [])]
    if not bids or not asks:
        continue
    bb, ba = max(p for p, _ in bids), min(p for p, _ in asks)
    if not 0.03 <= bb <= 0.97:
        continue
    dep.append(sum(s for p, s in bids if p >= bb - 0.02) + sum(s for p, s in asks if p <= ba + 0.02))
    spr.append(ba - bb)
dep.sort()
out = {"tokens_recorded": len(books), "usable_books": len(dep), "median_depth_within_2c": st.median(dep),
       "p25_depth": dep[len(dep) // 4], "p75_depth": dep[3 * len(dep) // 4], "median_spread": round(st.median(spr), 4),
       "note": "Saturday 3-4 Oct 2026 night snapshot, both sides of the book, contracts"}
Path(__file__).resolve().parent.parent.joinpath("results/live_books_depth/depth.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
