"""Run the closed-market study:  cd research && uv run --env-file ../.env python -m leadlag_closed.run

Writes closures_all.csv, events.csv, tests.json, SUMMARY.md, charts and appends to RUN_LOG.md under
research/results/leadlag_closed/. A missing Massive key logs a message and exits 2 (never prompts, never prints it).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from polybridge_research.calendar import TradingCalendar

from .analysis import analyse
from .closures import Closure, build_closures, closure_for_news, closure_row, load_events
from .config import CACHE_DIR, PANELS, PRIMARY, REPO_ENV_DIR, RESEARCH_DIR, RESULTS_DIR, SECONDARY
from .data import CountingSession, fetch_closure_pm, fetch_equity_range


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RESEARCH_DIR, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def plan_closures(markets: dict, events: list[dict], cal: TradingCalendar | None = None) -> list[dict]:
    """Every closure to analyse: placebo panels plus event closures. Each plan item carries market, sign, news flag, event."""
    cal = cal or TradingCalendar()
    items: dict[str, dict] = {}
    all_closures: list[Closure] = []
    for pname, spec in PANELS.items():
        cl = build_closures(spec["start"], spec["end"], cal)
        all_closures += cl
        for c in cl:
            items[c.key] = {"closure": c, "market": pname, "sign": spec["sign"], "news": False, "event": ""}
    pool = build_closures("2024-03-01", "2025-12-31", cal)
    for e in events:
        c = closure_for_news(e["news_et"], pool)
        if c is None:
            raise ValueError(f"{e['id']}: news time {e['news_et']} is not inside a closure")
        m = markets[e["market"]]
        items[c.key] = {"closure": c, "market": e["market"], "sign": int(m["sign"]), "news": True, "event": e["id"],
                        "name": e["name"], "family": e["family"], "news_et": e["news_et"], "precision": e.get("precision", "")}
    return sorted(items.values(), key=lambda d: d["closure"].key)


def collect_rows(plan: list[dict], markets: dict, client, pm_session, progress=True) -> pd.DataFrame:
    first = min(p["closure"].close_day for p in plan).strftime("%Y-%m-%d")
    last = max(p["closure"].open_day for p in plan).strftime("%Y-%m-%d")
    bars = fetch_equity_range(client, PRIMARY, first, last)
    bars2 = fetch_equity_range(client, SECONDARY, first, last)
    rows = []
    for i, p in enumerate(plan):
        c = p["closure"]
        try:
            pts = fetch_closure_pm(markets[p["market"]]["token_id"], c, pm_session)
            row = closure_row(c, bars, bars2, pts, p["sign"], p["market"])
        except Exception as exc:  # noqa: BLE001
            row = {"closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind, "market": p["market"],
                   "sign": p["sign"], "reason": f"fetch failed: {type(exc).__name__}: {str(exc)[:120]}"}
            print(f"[{c.key}] FETCH FAILED {exc}", file=sys.stderr)
        row.update(news=p["news"], event=p["event"], name=p.get("name", ""), family=p.get("family", ""),
                   news_et=p.get("news_et", ""), precision=p.get("precision", ""))
        rows.append(row)
        if progress and (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(plan)} closures", flush=True)
    df = pd.DataFrame(rows)
    for col in ("dpm_o_pp", "gap_bp", "ret30_bp", "resid_bp", "dpm_early_o_pp", "gap_qqq_bp", "pm_close", "pm_open", "dpm_pp"):
        if col not in df:
            df[col] = float("nan")
    return df


def write_run_log(entry: str) -> None:
    path = RESULTS_DIR / "RUN_LOG.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Closed-market lead-lag run log\n\nOne entry per run of `python -m leadlag_closed.run`: code commit, wall time, "
                        "network requests, exit status. Cached responses are not counted (the cache is gitignored, so a fresh clone repeats the cold run).\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--reuse-csv", action="store_true", help="skip fetching; re-analyse results/leadlag_closed/closures_all.csv")
    args = ap.parse_args(argv)

    t0, started = time.time(), datetime.now(timezone.utc)
    commit, dirty = _git("rev-parse", "--short", "HEAD"), bool(_git("status", "--porcelain", "--", "leadlag_closed"))
    pm_session, massive_session = CountingSession(), CountingSession()
    exit_code, note = 0, ""
    try:
        from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key
        from .report import write_all

        markets, events = load_events()
        if args.reuse_csv:
            rows = pd.read_csv(RESULTS_DIR / "closures_all.csv")
            rows["news"] = rows["news"].astype(bool)
            for col in ("name", "family", "news_et", "precision", "event", "reason"):
                rows[col] = rows[col].fillna("")
        else:
            try:
                key = load_api_key(search_from=REPO_ENV_DIR, interactive=False)
            except MissingApiKey as exc:
                note = f"MASSIVE_API_KEY missing: {exc}"
                print(note, file=sys.stderr)
                exit_code = 2
                return exit_code
            client = MassiveClient(key, cache_dir=CACHE_DIR / "massive", session=massive_session)
            plan = plan_closures(markets, events)
            print(f"{len(plan)} closures ({sum(p['news'] for p in plan)} news events)", flush=True)
            rows = collect_rows(plan, markets, client, pm_session)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            rows.to_csv(RESULTS_DIR / "closures_all.csv", index=False)
        res = analyse(rows)
        write_all(rows, res, markets, charts=not args.no_charts)
        note = (f"{res['n_events_usable']} of {res['n_events_total']} events usable, "
                f"{res['n_placebo_usable']} of {res['n_placebo_total']} placebo closures usable; verdict: {res['verdict']}")
        print(note)
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
            f"- code commit: `{commit}`{' + uncommitted changes in leadlag_closed/' if dirty else ''}\n"
            f"- mode: {'re-analysis of saved CSV' if args.reuse_csv else 'fetch + analysis'}\n"
            f"- wall time: {dur:.0f} s\n"
            f"- network requests: {reqs}\n"
            f"- result: {note}\n"
            f"- exit: {exit_code}\n"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
