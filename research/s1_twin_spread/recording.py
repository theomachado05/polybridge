"""Reads the forward recording of the twin pairs (research/forward/raw/twins) and calibrates the modelled
Polymarket half-spread from its calibration slice (METHOD.md section 2)."""
from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import CALIBRATION_END, CALIBRATION_MIN_TWO_SIDED, CALIBRATION_START, HALF_SPREAD_FLOOR

RAW = Path(__file__).resolve().parents[1] / "forward" / "raw" / "twins"


def load_rows(start: datetime, end: datetime, folder: Path = RAW) -> list[dict]:
    """Book rows with start <= t < end. Error rows are skipped; a truncated last line of a live file is ignored."""
    s, e = start.timestamp(), end.timestamp()
    rows: list[dict] = []
    for f in sorted(folder.glob("*.jsonl.gz")):
        hour = datetime.strptime(f.name[:11], "%Y%m%dT%H").replace(tzinfo=start.tzinfo)
        if hour.timestamp() + 3600 <= s or hour.timestamp() >= e:
            continue
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if "err" not in r and s <= r["t"] < e:
                        rows.append(r)
        except (EOFError, OSError):
            continue
    return rows


def calibrate_half_spreads(rows: list[dict] | None = None) -> dict[str, dict]:
    """Per Polymarket token: median half-spread of its two-sided books in the calibration slice, floored. `usable`
    is False when the book was one-sided or empty in more than half of the snapshots."""
    if rows is None:
        rows = load_rows(CALIBRATION_START, CALIBRATION_END)
    by: dict[str, list[float | None]] = {}
    for r in rows:
        if r["v"] != "pm":
            continue
        two = bool(r["b"]) and bool(r["a"])
        by.setdefault(r["id"], []).append((r["a"][0][0] - r["b"][0][0]) / 2.0 if two else None)
    out = {}
    for tok, xs in by.items():
        good = [x for x in xs if x is not None]
        share = len(good) / len(xs)
        med = float(np.median(good)) if good else float("nan")
        out[tok] = {"snapshots": len(xs), "two_sided_share": share, "median_half_spread": med,
                    "h": max(med, HALF_SPREAD_FLOOR) if good else float("nan"),
                    "usable": share > CALIBRATION_MIN_TWO_SIDED}
    return out
