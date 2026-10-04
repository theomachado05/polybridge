"""Frozen holdout frame (METHOD.md section 1). Listing metadata only, never a price or outcome field.

    cd research && FRESH_ACC_CACHE=<dir> .venv/bin/python -m fresh_accuracy_latest.freeze
"""
from __future__ import annotations

import csv
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

import fresh_accuracy  # noqa: F401
from arbscan import datasrc as ds

from fresh_accuracy.config import ARB_GAPS, CACHE_DIR, PARAMS
from fresh_accuracy.freeze import _iso, frame, keyset_events, r3_exclusions, write_frozen

PKG = Path(__file__).resolve().parent
FROZEN_IDS = PKG / "frozen_ids.csv"
FROZEN_SHA = PKG / "frozen_ids.sha256"
SCAN_COMMIT = datetime.fromisoformat("2026-10-03T05:14:24-04:00")
CUTOFF = datetime.fromisoformat("2026-10-04T23:59:59-04:00")
HOLDOUT = dataclasses.replace(PARAMS, end_min="2026-10-02", end_max="2026-10-04")


def scan_ids(path: Path = ARB_GAPS) -> set[str]:
    with open(path, newline="") as f:
        return {str(r["market_id"]) for r in csv.DictReader(f)}


def main() -> int:
    http = ds.Http(CACHE_DIR / "http")
    events = keyset_events(http, HOLDOUT)
    ex_ids, ex_dates = r3_exclusions()
    rows, counts = frame(events, ex_ids, ex_dates, HOLDOUT)
    seen = scan_ids()
    counts["dropped_in_arb_scan"] = sum(r["id"] in seen for r in rows)
    counts["dropped_end_not_after_scan_commit"] = sum(r["id"] not in seen and _iso(r["end"]) <= SCAN_COMMIT for r in rows)
    keep = [r for r in rows if r["id"] not in seen and SCAN_COMMIT < _iso(r["end"]) <= CUTOFF]
    h = write_frozen(keep, FROZEN_IDS, FROZEN_SHA)
    counts.update(events_listed=len(events), holdout_markets=len(keep),
                  holdout_dates=sorted({r["res_date"] for r in keep}), holdout_tickers=sorted({r["ticker"] for r in keep}))
    (PKG / "frozen_counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    print(json.dumps(counts, sort_keys=True), h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
