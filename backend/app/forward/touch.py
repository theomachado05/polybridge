"""Touch-ticket forward test: the procedure of ``research/touch_fresh/FORWARD.md``, wired here without changing it.

``research/touch_fresh/forward.py`` is the frozen runner (stages snapshot, prints, evaluate). This module:

* ``list_state()``: lists the "will it hit" markets listed from 2026-10-05 (forward.open_markets, unchanged), parses
  each with the S21 parser, and records which of them can enter the book on their first weekend. Reads only.
  No order is placed and no option quote is fetched.
* ``run_stage(stage)``: calls the frozen runner's snapshot / prints / evaluate with its log directory redirected to
  ``backend/data_forward/touch/`` (the runner writes ``forward_log/`` and ``.cache_forward/`` next to itself by default).

Timing is the runner's: the snapshot is only taken on a market's first Friday at 15:55 New York; prints after Sunday 20:00.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .paths import TOUCH_FILES, data_dir, ensure_research_path, frozen_info, stamp

STAGES = ("snapshot", "prints", "evaluate")


def _modules() -> dict[str, Any]:
    ensure_research_path()
    return {"forward": importlib.import_module("touch_fresh.forward"),
            "fc": importlib.import_module("touch_fresh.forward_config"),
            "cfg": importlib.import_module("touch_fresh.config"),
            "universe": importlib.import_module("touch_fresh.universe"),
            "eg": importlib.import_module("s21_options_anchor.engine")}


def classify_market(m: dict, mods: dict[str, Any]) -> dict:
    """One listed market's state under FORWARD.md: parsed or why not, its first-weekend entry Friday, and whether its
    window ends after that Friday (the rule's condition). The Sunday $10,000 volume floor is not applied here."""
    eg, cfg, universe = mods["eg"], mods["cfg"], mods["universe"]
    rec = {k: m.get(k) for k in ("id", "event", "event_title", "asset_class", "question", "label", "start")}
    p, why = eg.parse_market(m)
    if p is None:
        return {**rec, "parsed": False, "reason": why, "eligible": False}
    es = date.fromisoformat(p["end_session"])
    while es.isoformat() in cfg.HOLIDAYS or es.weekday() >= 5:  # FORWARD.md amendment: step back over holidays
        es -= timedelta(days=1)
    day, at = universe.entry_instant(m["start"])
    ok = es > day
    return {**rec, "parsed": True, "ticker": p["ticker"], "level": p["level"], "direction": p["direction"],
            "window_end": p["window_end"], "end_session": es.isoformat(), "entry_day": day.isoformat(),
            "entry_epoch": at, "eligible": ok,
            "reason": "" if ok else "window ends on or before its first weekend's Friday"}


def list_state(now: datetime | None = None, base: Path | None = None, open_markets: Callable[[], list[dict]] | None = None,
               mods: dict[str, Any] | None = None) -> dict:
    """List the eligible markets and record the state. Returns the summary written to ``snapshots/<stamp>.json``."""
    base = (base or data_dir()) / "touch"
    now = now or datetime.now(timezone.utc)
    st = stamp(now)
    mods = mods or _modules()
    listed = (open_markets or mods["forward"].open_markets)()
    rows = [classify_market(m, mods) for m in listed]
    eligible = [r for r in rows if r["eligible"]]
    raw = base / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"state_{st}.json").write_text(json.dumps(rows, indent=1))
    fc = mods["fc"]
    by_day: dict[str, int] = {}
    for r in eligible:
        by_day[r["entry_day"]] = by_day.get(r["entry_day"], 0) + 1
    reasons: dict[str, int] = {}
    for r in rows:
        if not r["eligible"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    rec = {"kind": "touch_forward_state", "run_utc": now.isoformat(), "stamp": st,
           "first_listing_et": fc.FIRST_LISTING_ET, "frozen": frozen_info(TOUCH_FILES),
           "markets_listed": len(rows), "parsed": sum(r["parsed"] for r in rows), "eligible_first_weekend": len(eligible),
           "eligible_events": len({r["event"] for r in eligible}), "by_entry_day": by_day, "not_eligible_reasons": reasons,
           "eligible": [{k: r[k] for k in ("id", "event", "event_title", "question", "ticker", "level", "direction",
                                           "window_end", "end_session", "entry_day", "start")} for r in eligible],
           "pending": {"volume_floor_usd": fc.MIN_MARKET_VOLUME, "read_at": "Sunday 20:00 New York snapshot",
                       "verdict_needs": {"markets": fc.MIN_MARKETS, "events": fc.MIN_EVENTS, "by": fc.EVALUATE_BY}},
           "note": "state only: no order, no option quote; the anchor is taken by `snapshot` on the entry Friday at 15:55 New York"}
    snaps = base / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / f"{st}.json").write_text(json.dumps(rec, indent=1))
    return rec


def run_stage(stage: str, base: Path | None = None, mods: dict[str, Any] | None = None, now: datetime | None = None) -> dict:
    """Call one frozen stage with its log and cache redirected under ``data_forward/touch``. Returns what it printed and
    the log row counts; also written to ``snapshots/stage_<stage>_<stamp>.json``."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    base = (base or data_dir()) / "touch"
    base.mkdir(parents=True, exist_ok=True)
    mods = mods or _modules()
    fw = mods["forward"]
    old = (fw.HERE, fw.LOG)
    fw.HERE, fw.LOG = base, base / mods["fc"].LOG_DIR  # the runner builds its cache path from HERE and logs to LOG
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = getattr(fw, stage)()
    finally:
        fw.HERE, fw.LOG = old
    now = now or datetime.now(timezone.utc)
    rec = {"kind": "touch_forward_stage", "stage": stage, "run_utc": now.isoformat(), "return_code": rc, "output": buf.getvalue(),
           "log_rows": {s: len(_read(base / mods["fc"].LOG_DIR / f"{s}.jsonl")) for s in STAGES if s != "evaluate"},
           "frozen": frozen_info(TOUCH_FILES)}
    snaps = base / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / f"stage_{stage}_{stamp(now)}.json").write_text(json.dumps(rec, indent=1))
    return rec


def _read(f: Path) -> list[str]:
    return [x for x in f.read_text().splitlines() if x.strip()] if f.exists() else []
