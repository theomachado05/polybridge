"""Run the T4 overshoot study once (METHOD.md). No network: reads R3's committed events.csv only.

    cd research && .venv/bin/python -m overshoot.run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import analysis, report
from .config import DONE, EVENTS_CSV, PARAMS, REPO_DIR, RESULTS_DIR


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def run(events: Path = EVENTS_CSV, out: Path = RESULTS_DIR, params=PARAMS) -> dict:
    done = out / DONE.name
    if done.exists():
        raise SystemExit(f"{done} exists: this study has been run once already (METHOD.md). Refusing to run again.")
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    e = analysis.load(events)
    st = analysis.analyse(e, params)
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    commit = git("rev-parse", "--short", "HEAD")
    dirty = git("status", "--porcelain", "--", "research/overshoot")
    added = git("log", "--format=%h", "--diff-filter=A", "--", "research/overshoot/METHOD.md")
    meta = dict(run_utc=run_utc, code_commit=commit + (" + uncommitted changes in overshoot/" if dirty else ""),
                method_commit=(added.splitlines() or ["unknown"])[-1],
                events_sha256=hashlib.sha256(Path(events).read_bytes()).hexdigest(), network_requests=0,
                draws=params.draws, seed=params.seed)
    done.write_text(f"T4 overshoot study computed {run_utc}; input sha256 {meta['events_sha256']}\n")
    (out / "stats.json").write_text(json.dumps(dict(meta=meta, **st), indent=1, default=float))
    if st["decomposition"].get("n", 0):
        report.chart(st["decomposition"], out / "decomposition.png")
    (out / "SUMMARY.md").write_text(report.summary(st, meta))
    meta["wall_s"] = round(time.time() - t0, 1)
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1))
    a = st["decomposition"]
    po = st["open_pair"]
    res = (f"decomposition n={a.get('n', 0)} ({a.get('clusters', 0)} closures), verdict {st['verdict_a']['label']}; "
           f"forecast open pair n={po.get('n', 0)}, verdict {st['verdict_open']}; close pair verdict {st['verdict_close']}")
    log = out / "RUN_LOG.md"
    head = "" if log.exists() else ("# T4 overshoot run log\n\nOne entry per run of `python -m overshoot.run`: code commit, "
                                    "wall time, network requests, input hash, result.\n")
    with log.open("a") as f:
        f.write(head + f"\n## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}\n- code commit: `{meta['code_commit']}`\n"
                f"- mode: re-analysis of R3's committed events.csv (no fetch)\n- input sha256: `{meta['events_sha256']}`\n"
                f"- wall time: {meta['wall_s']} s\n- network requests: 0\n- result: {res}\n- exit: 0\n")
    return st


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    st = run()
    print(json.dumps(dict(verdict_a=st["verdict_a"], verdict_open=st["verdict_open"], verdict_close=st["verdict_close"]), indent=1))


if __name__ == "__main__":
    main()
