from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import httpx

CLOB = "https://clob.polymarket.com/prices-history"
ATTEMPTS = ({"interval": "1w", "fidelity": 1}, {"interval": "1m", "fidelity": 60})


def parse_history(payload: dict) -> list[dict]:
    rows: dict[int, float] = {}
    for h in payload.get("history") or []:
        try:
            t, p = int(h["t"]), float(h["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(p) and 0.0 <= p <= 1.0:
            rows[t] = p
    return [{"ts_ns": t * 1_000_000_000, "p": rows[t]} for t in sorted(rows)]


def fetch(token_id: str, http: httpx.Client) -> list[dict]:
    for params in ATTEMPTS:
        r = http.get(CLOB, params={"market": token_id, **params}, timeout=15)
        if r.status_code == 200:
            rows = parse_history(r.json())
            if rows:
                return rows
    raise SystemExit("no history returned")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    with httpx.Client() as http:
        rows = fetch(a.token_id, http)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    import json
    a.out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    ps = [r["p"] for r in rows]
    print(f"{len(rows)} points, p {min(ps)}..{max(ps)} -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
