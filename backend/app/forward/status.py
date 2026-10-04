"""GET /forward/status payload: the latest forward snapshots, labelled with the frozen rule files they ran under."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .paths import LADDER_FILES, REPO, TOUCH_FILES, data_dir, frozen_info

LABEL = "forward test, rules frozen"
# research/touch_fresh/FORWARD.md: markets listed at or after 2026-10-05 00:00 New York. Snapshots taken before that are
# checks of the plumbing, not forward-test observations, and are never counted as such.
FORWARD_START = "2026-10-05"
FORWARD_START_UTC = datetime(2026, 10, 5, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
PRE_START = "pre-start check (not part of the forward test)"
IN_TEST = "forward test"


def _taken_at(f: Path, snap: dict | None = None) -> datetime | None:
    """When a snapshot was taken: its <YYYYMMDDTHHMMSSZ> file stamp, else its run_utc."""
    stem = f.stem.rsplit("_", 1)[-1]
    try:
        return datetime.strptime(stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    raw = str((snap or {}).get("run_utc") or "")
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def phase(t: datetime | None) -> str:
    """The label of a snapshot taken at ``t``: in the forward test from FORWARD_START_UTC, a pre-start check before."""
    return IN_TEST if t is not None and t >= FORWARD_START_UTC else PRE_START


def _counts(d: Path, prefix: str = "") -> dict:
    files = _snapshots(d, prefix)
    pre = sum(phase(_taken_at(f)) == PRE_START for f in files)
    return {"snapshots_taken": len(files) - pre, "pre_start_checks": pre, "forward_starts": FORWARD_START,
            "pre_start_label": PRE_START}


def _snapshots(d: Path, prefix: str = "") -> list[Path]:
    return sorted(p for p in d.glob(f"{prefix}*.json") if p.is_file()) if d.is_dir() else []


def _latest(d: Path, prefix: str = "") -> tuple[dict | None, int]:
    """(latest readable snapshot with its ``phase`` label, number of files)."""
    files = _snapshots(d, prefix)
    for f in reversed(files):
        try:
            snap = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(snap, dict):
            snap["_phase"] = phase(_taken_at(f, snap))
        return snap, len(files)
    return None, len(files)


def _frozen_label(files: list[dict]) -> str:
    return "; ".join(f"{f['file']} @ {f['commit'] or 'uncommitted'}" for f in files)


def ladders(base: Path) -> dict:
    snap, _n = _latest(base / "ladders" / "snapshots")
    out: dict = {"label": f"{LABEL} ({_frozen_label(frozen_info(LADDER_FILES))})", "rule": "research/ladder_replay/METHOD.md step 4",
                 **_counts(base / "ladders" / "snapshots"), "latest": None}
    if snap is None:
        out["state"] = "no snapshot yet: run `make forward-ladders`"
        return out
    out["frozen_at_run"] = snap.get("frozen")
    if snap.get("error"):
        out["state"] = "last run failed"
        out["latest"] = {"run_utc": snap.get("run_utc"), "error": snap["error"], "phase": snap.get("_phase")}
        return out
    out["state"] = "ok"
    out["latest"] = {
        "run_utc": snap.get("run_utc"), "snapshot_utc": snap.get("snapshot_utc"), "phase": snap.get("_phase"),
        "events_read": snap.get("events_read"), "date_ladders": snap.get("date_ladders"),
        "pairs": snap.get("pairs"), "pairs_with_books": snap.get("pairs_with_books"), "nested_pairs": snap.get("nested_pairs"),
        # each count carries its denominator (the sample it is out of)
        "violations_net_of_fees": {"count": snap.get("violations_net_of_fees"), "of_pairs_with_books": snap.get("pairs_with_books"),
                                   "nested": snap.get("violations_nested"), "locked_usd": snap.get("locked_usd")},
        "gap_points_to_arb": snap.get("gap_points_to_arb"), "violations": snap.get("violations") or []}
    return out


def touch(base: Path) -> dict:
    snap, _n = _latest(base / "touch" / "snapshots", "20")  # state files are <stamp>.json; stage_*.json are separate
    stage, _ = _latest(base / "touch" / "snapshots", "stage_evaluate_")
    out: dict = {"label": f"{LABEL} ({_frozen_label(frozen_info(TOUCH_FILES))})", "rule": "research/touch_fresh/FORWARD.md",
                 "status": "open lead, unvalidated: proposals only, no trading from this test",
                 **_counts(base / "touch" / "snapshots", "20"), "latest": None,
                 "last_evaluate": stage and {"run_utc": stage.get("run_utc"), "output": stage.get("output"), "phase": stage.get("_phase")}}
    if snap is None:
        out["state"] = "no snapshot yet: run `make forward-touch`"
        return out
    out["frozen_at_run"] = snap.get("frozen")
    out["state"] = "ok"
    out["latest"] = {k: snap.get(k) for k in ("run_utc", "first_listing_et", "markets_listed", "parsed", "eligible_first_weekend",
                                              "eligible_events", "by_entry_day", "not_eligible_reasons", "eligible", "pending", "note")}
    out["latest"]["phase"] = snap.get("_phase")
    return out


def recorder() -> dict | None:
    """Read-only heartbeat of the live book recorder (research/forward). Another checkout may be the one running it:
    set POLYBRIDGE_RECORDER_DIR to that checkout's research/forward."""
    d = Path(os.environ.get("POLYBRIDGE_RECORDER_DIR", "").strip() or REPO / "research" / "forward")
    beats = {}
    for f in sorted(d.glob("heartbeat_*.json")) if d.is_dir() else []:
        try:
            hb = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        beats[f.stem.removeprefix("heartbeat_")] = {"age_s": round(time.time() - f.stat().st_mtime, 1), **{k: hb[k] for k in list(hb)[:8]}}
    return {"dir": str(d), "heartbeats": beats} if beats else None


def build(base: Path | None = None) -> dict:
    base = base or data_dir()
    return {"label": LABEL, "forward_starts": FORWARD_START, "pre_start_label": PRE_START,
            "ladders": ladders(base), "touch": touch(base), "recorder": recorder()}
