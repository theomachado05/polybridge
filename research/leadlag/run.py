from __future__ import annotations

import argparse
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from .charts import plot_event
from .config import CACHE_DIR, PARAMS, REPO_ENV_DIR, RESEARCH_DIR, RESULTS_DIR, SENSITIVITY_K
from .data import CountingSession, fetch_equity_minutes, fetch_pm_history
from .events import Event, load_events
from .pipeline import EventResult, analyse_event
from .report import pooled_tests, write_csvs, write_summary


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RESEARCH_DIR, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def fetch_event(ev: Event, client, session, pm_session) -> tuple[list, dict[str, pd.DataFrame]]:
    fetch_start = ev.start - pd.Timedelta(minutes=PARAMS.warmup_min)
    pts = fetch_pm_history(ev.token_id, fetch_start, ev.end, CACHE_DIR / "pm", session=pm_session)
    bars = {t: fetch_equity_minutes(client, t, fetch_start, ev.end) for t in ev.instruments}
    return pts, bars


def write_run_log(entry: str) -> None:
    path = RESULTS_DIR / "RUN_LOG.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Lead-lag run log\n\nOne entry per run of `python -m leadlag.run`: code commit, wall time, network requests, exit status.\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated event ids")
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args(argv)

    t0, started = time.time(), datetime.now(timezone.utc)
    commit, dirty = _git("rev-parse", "--short", "HEAD"), bool(_git("status", "--porcelain", "--", "leadlag"))
    pm_session, massive_session = CountingSession(), CountingSession()
    exit_code, note, n_use, n_drop = 0, "", 0, 0
    try:
        from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key
        try:
            key = load_api_key(search_from=REPO_ENV_DIR, interactive=False)
        except MissingApiKey as exc:
            note = f"MASSIVE_API_KEY missing: {exc}"
            print(note, file=sys.stderr)
            exit_code = 2
            return exit_code
        client = MassiveClient(key, cache_dir=CACHE_DIR / "massive", session=massive_session)
        events = load_events()
        if args.only:
            wanted = set(args.only.split(","))
            events = [e for e in events if e.id in wanted]
        results: list[EventResult] = []
        fetch_failed: list[tuple[Event, str]] = []
        for ev in events:
            try:
                pts, bars = fetch_event(ev, client, massive_session, pm_session)
                res = analyse_event(ev, pts, bars)
            except Exception as exc:  # noqa: BLE001
                fetch_failed.append((ev, f"fetch failed: {type(exc).__name__}: {str(exc)[:160]}"))
                print(f"[{ev.id}] FETCH FAILED {exc}", file=sys.stderr)
                continue
            results.append(res)
            tag = "ok " if res.usable else "DROP"
            prim = res.primary
            print(f"[{ev.id}] {tag} pm_pts={res.pm_points} pm_chg={res.pm_changes} "
                  f"lead={None if prim is None else prim.lead} {'; '.join(res.drop_reasons)}")
        usable = [r for r in results if r.usable]
        n_use, n_drop = len(usable), len(events) - len(usable)
        tests = pooled_tests(usable)
        write_csvs(results, fetch_failed, tests)
        if not args.no_charts:
            for r in usable:
                prim = r.primary
                plot_event(r.event, prim.frame, prim.ticker, r.pm_move, prim.eq_move, prim.lead, prim.lead_cls, prim.xc,
                           RESULTS_DIR / "charts" / f"{r.event.id}.png")
        write_summary(results, fetch_failed, tests)
        note = f"{n_use} usable, {n_drop} dropped of {len(events)}"
    except Exception:  # noqa: BLE001
        exit_code = 1
        note = "crashed: " + traceback.format_exc().splitlines()[-1]
        traceback.print_exc()
    finally:
        dur = time.time() - t0
        reqs = (f"Polymarket CLOB {pm_session.counts.get('clob.polymarket.com', 0)}, "
                f"Massive {sum(massive_session.counts.values())} (cached responses are not counted)")
        write_run_log(
            f"## {started:%Y-%m-%d %H:%M:%S}Z\n"
            f"- code commit: `{commit}`{' + uncommitted changes in leadlag/' if dirty else ''}\n"
            f"- wall time: {dur:.0f} s\n"
            f"- network requests: {reqs}\n"
            f"- result: {note}\n"
            f"- exit: {exit_code}\n"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
