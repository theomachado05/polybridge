"""Ladder forward check: ``research/ladder_replay/live.py`` (METHOD step 4) run once, its output redirected here.

live.py reads every open Polymarket date ladder's real books and prices each rung pair after both fees. Its rules are
frozen; this module only points its output directory at ``backend/data_forward/ladders/raw/<stamp>/`` (raw, gitignored)
and writes a small committed summary to ``backend/data_forward/ladders/snapshots/<stamp>.json``.
"""
from __future__ import annotations

import contextlib
import csv
import importlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import LADDER_FILES, data_dir, ensure_research_path, frozen_info, stamp


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _truthy(x: Any) -> bool:
    return str(x).strip().lower() in ("true", "1")


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def gap_stats(rows: list[dict]) -> dict | None:
    """Points each pair is from an arbitrage (positive = no violation), over the pairs that have both books. The range
    (min, 10th and 90th percentile, max) and the sample size travel with the median."""
    gaps = [-100 * e for r in rows if _truthy(r.get("has_books")) and (e := _f(r.get("edge_top"))) is not None]
    if not gaps:
        return None
    return {"n_pairs": len(gaps), "median": round(_quantile(gaps, 0.5), 2), "p10": round(_quantile(gaps, 0.1), 2),
            "p90": round(_quantile(gaps, 0.9), 2), "min": round(min(gaps), 2), "max": round(max(gaps), 2)}


def summarize(totals: dict, pairs: list[dict]) -> dict:
    """The committed summary of one live check: live.py's own totals plus the violations found after fees (each with
    its contracts and locked dollars) and the gap range. Per-pair rows stay in the raw CSV."""
    viol = []
    for r in pairs:
        c = _f(r.get("contracts"))
        if c and c > 0:
            viol.append({"event": r.get("event"), "rich": r.get("rich"), "cheap": r.get("cheap"), "nested": _truthy(r.get("nested")),
                         "nesting_reason": r.get("reason"), "edge_top_points": round(100 * (_f(r.get("edge_top")) or 0.0), 2),
                         "contracts": c, "locked_usd": _f(r.get("locked_usd"))})
    return {"snapshot_utc": totals.get("snapshot_utc"), "events_read": totals.get("events_read"),
            "date_ladders": totals.get("date_ladders"), "pairs": totals.get("pairs"),
            "pairs_with_books": totals.get("pairs_with_books"), "nested_pairs": totals.get("nested_pairs"),
            "violations_net_of_fees": totals.get("violations_net_of_fees"),
            "violations_nested": totals.get("violations_nested"), "locked_usd": totals.get("locked_usd"),
            "locked_usd_nested": totals.get("locked_usd_nested"), "median_gap_points_to_arb": totals.get("median_gap_points_to_arb"),
            "gap_points_to_arb": gap_stats(pairs), "violations": viol}


def run(now: datetime | None = None, base: Path | None = None, live: Any = None) -> dict:
    """Run the live check once. ``live`` is the ``ladder_replay.live`` module (tests pass a fake). Returns the summary
    record written to ``snapshots/<stamp>.json`` (``error`` set instead when the check failed)."""
    base = (base or data_dir()) / "ladders"
    now = now or datetime.now(timezone.utc)
    st = stamp(now)
    raw = base / "raw" / st
    raw.mkdir(parents=True, exist_ok=True)
    if live is None:
        ensure_research_path()
        live = importlib.import_module("ladder_replay.live")
    original, buf, error = live.OUT, io.StringIO(), None
    live.OUT = raw  # live.py writes live_pairs.csv / live_totals.json to OUT: point it here, not at research/results
    try:
        with contextlib.redirect_stdout(buf):
            live.main()
    except Exception as e:  # noqa: BLE001  a failed sweep is recorded, not hidden
        error = f"{type(e).__name__}: {e}"
    finally:
        live.OUT = original
    rec: dict[str, Any] = {"kind": "ladder_live_check", "run_utc": now.isoformat(), "stamp": st,
                           "raw_dir": str(raw.relative_to(base.parent)) if raw.is_relative_to(base.parent) else str(raw),
                           "frozen": frozen_info(LADDER_FILES)}
    totals_f, pairs_f = raw / "live_totals.json", raw / "live_pairs.csv"
    if error is None and totals_f.is_file() and pairs_f.is_file():
        with pairs_f.open(newline="") as fh:
            pairs = list(csv.DictReader(fh))
        rec.update(summarize(json.loads(totals_f.read_text()), pairs))
    else:
        rec["error"] = error or "live check wrote no totals"
    snaps = base / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / f"{st}.json").write_text(json.dumps(rec, indent=1))
    return rec
