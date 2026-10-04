from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from polybridge_research.calendar import TradingCalendar

from .analysis import analyse
from .closures import market_closures, pm_covered, replication_row
from .config import CACHE_DIR, MARKETS_PATH, PARAMS, PRIMARY, REPO_ENV_DIR, RESEARCH_DIR, RESULTS_DIR, SECONDARY
from .data import CountingSession, fetch_equity_range, fetch_market_pm


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RESEARCH_DIR, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def load_candidates(path=MARKETS_PATH) -> list[dict]:
    return json.loads(path.read_text())["candidates"]


def select_markets(cands: list[dict], pm_session, cal=None, n: int | None = None, fetch_pm=fetch_market_pm,
                   progress=True) -> tuple[list[dict], pd.DataFrame]:
    cal = cal or TradingCalendar()
    n = n or PARAMS.n_markets
    selected, cov = [], []
    for m in sorted(cands, key=lambda d: d["rank"]):
        if len(selected) >= n:
            break
        cl = market_closures(m["start"], m["end"], cal)
        pts = fetch_pm(m["token_id"], cl, session=pm_session)
        ok = [c for c in cl if not isinstance(pts.get(c.key), Exception) and pm_covered(pts.get(c.key) or [], c)]
        failed = sum(isinstance(pts.get(c.key), Exception) for c in cl)
        passed = len(ok) >= PARAMS.min_pm_closures
        cov.append({"rank": m["rank"], "market": m["market_slug"], "closures": len(cl), "pm_both_ends": len(ok),
                    "fetch_failed": failed, "qualifies": passed})
        if progress:
            print(f"  rank {m['rank']:>2} {m['market_slug'][:60]:<60} closures {len(cl):>3}, quoted {len(ok):>3} "
                  f"-> {'SELECTED' if passed else 'skip'}", flush=True)
        if passed:
            selected.append({"market": m, "closures": cl, "points": pts})
    return selected, pd.DataFrame(cov)


def collect_rows(selected: list[dict], bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for s in selected:
        m = s["market"]
        for c in s["closures"]:
            pts = s["points"].get(c.key)
            if isinstance(pts, Exception):
                row = {"market": m["market_slug"], "rank": m["rank"], "sign": m["sign"], "closure": c.key,
                       "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind,
                       "reason": f"fetch failed: {type(pts).__name__}: {str(pts)[:120]}"}
            else:
                row = replication_row(c, m, pts or [], bars, PRIMARY)
            rows.append(row)
    df = pd.DataFrame(rows)
    for col in ("x_pp", "dpm_pp", "pm_close", "pm_open", *[f"gap_{t.lower()}_bp" for t in bars]):
        if col not in df:
            df[col] = float("nan")
    return df


def equity_range(selected: list[dict]) -> tuple[str, str]:
    first = min(c.close_day for s in selected for c in s["closures"]).strftime("%Y-%m-%d")
    last = max(c.open_day for s in selected for c in s["closures"]).strftime("%Y-%m-%d")
    return first, last


def write_run_log(entry: str) -> None:
    path = RESULTS_DIR / "RUN_LOG.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Overnight-gap replication run log\n\nOne entry per run of `python -m leadlag_replication.run`: code "
                        "commit, wall time, network requests (cache hits not counted; the cache is gitignored), exit status.\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-csv", action="store_true", help="skip fetching; re-analyse results.csv (report regeneration only)")
    args = ap.parse_args(argv)
    t0, started = time.time(), datetime.now(timezone.utc)
    commit = _git("rev-parse", "--short", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--", "leadlag_replication"))
    pm_session, massive_session = CountingSession(), CountingSession()
    exit_code, note = 0, ""
    try:
        from polybridge_research.massive import MassiveClient, MissingApiKey, load_api_key

        from .report import write_all

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        if args.reuse_csv:
            rows = pd.read_csv(RESULTS_DIR / "results.csv")
            rows["reason"] = rows["reason"].fillna("")
            cov = pd.read_csv(RESULTS_DIR / "coverage.csv")
        else:
            try:
                key = load_api_key(search_from=REPO_ENV_DIR, interactive=False)
            except MissingApiKey as exc:
                note = f"MASSIVE_API_KEY missing: {exc}"
                print(note, file=sys.stderr)
                exit_code = 2
                return exit_code
            cands = load_candidates()
            print(f"{len(cands)} frozen candidates; selecting {PARAMS.n_markets} by PM coverage (PM data only)", flush=True)
            selected, cov = select_markets(cands, pm_session)
            cov.to_csv(RESULTS_DIR / "coverage.csv", index=False)
            if len(selected) < PARAMS.n_markets:
                print(f"only {len(selected)} markets qualified", file=sys.stderr)
            client = MassiveClient(key, cache_dir=CACHE_DIR / "massive", session=massive_session)
            first, last = equity_range(selected)
            print(f"equity bars {PRIMARY},{','.join(SECONDARY)} {first}..{last}", flush=True)
            bars = {t: fetch_equity_range(client, t, first, last) for t in (PRIMARY, *SECONDARY)}
            rows = collect_rows(selected, bars)
            rows.to_csv(RESULTS_DIR / "results.csv", index=False)
        res = analyse(rows)
        write_all(rows, res, cov)
        s1, s2 = res["s1"], res["s2"]
        note = (f"{res['n_markets']} markets, {res['n_rows_usable']} of {res['n_rows_total']} rows usable "
                f"({res['n_dates_usable']} dates); b = {s1['b']:+.2f} bp/pp, HC3 t = {s1['t']:+.2f}, date-perm p = "
                f"{s1['p_perm']:.4f}; sign {s2['k']}/{s2['n']} p = {s2['p']:.3f}; verdict: {res['verdict']}")
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
            f"- code commit: `{commit}`{' + uncommitted changes in leadlag_replication/' if dirty else ''}"
            f" (METHOD.md pre-registered at `7a780b5`)\n"
            f"- mode: {'re-analysis of saved CSV' if args.reuse_csv else 'fetch + analysis'}\n"
            f"- wall time: {dur:.0f} s\n"
            f"- network requests: {reqs}\n"
            f"- result: {note}\n"
            f"- exit: {exit_code}\n"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
