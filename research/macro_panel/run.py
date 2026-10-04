from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from .analysis import analyse
from .closures import Closure, calendar_close, market_closures, panel_row, pm_covered, window_closures
from .config import (CACHE_DIR, CLASSES, DONE_PATH, MARKETS_PATH, PARAMS, PRIMARY, REPLICATION_ROWS, REPO_ENV_DIR,
                     RESEARCH_DIR, RESULTS_DIR)
from .data import CountingSession, fetch_equity_range, fetch_market_pm

METHOD_COMMIT = "bb3ca5f"


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RESEARCH_DIR, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def load_candidates(path=MARKETS_PATH) -> list[dict]:
    return json.loads(path.read_text())["candidates"]


def trim(points: list[tuple[int, float]], c: Closure) -> list[tuple[int, float]]:
    a = int(calendar_close(c).timestamp())
    o = int(c.nominal_open.timestamp())
    return [(t, p) for t, p in points if a - 3600 <= t <= a + 60 or o - 1860 <= t <= o]


def select_markets(cands: list[dict], pm_session, all_closures=None, fetch_pm=fetch_market_pm,
                   progress=True) -> tuple[list[dict], pd.DataFrame]:
    all_closures = all_closures if all_closures is not None else window_closures()
    taken = {c: 0 for c in CLASSES}
    selected, cov = [], []
    for m in sorted(cands, key=lambda d: d["rank"]):
        if len(selected) >= PARAMS.max_markets or all(v >= PARAMS.max_per_class for v in taken.values()):
            break
        if taken.get(m["cls"], PARAMS.max_per_class) >= PARAMS.max_per_class:
            continue
        cl = market_closures(m["start"], m["end"], all_closures)
        raw = fetch_pm(m["token_id"], cl, session=pm_session) if cl else {}
        pts = {k: (v if isinstance(v, Exception) else trim(v or [], next(c for c in cl if c.key == k))) for k, v in raw.items()}
        ok = sum(1 for c in cl if not isinstance(pts.get(c.key), Exception) and pm_covered(pts.get(c.key) or [], c))
        failed = sum(isinstance(pts.get(c.key), Exception) for c in cl)
        passed = ok >= PARAMS.min_pm_closures
        cov.append({"rank": m["rank"], "market": m["market_slug"], "cls": m["cls"], "closures": len(cl),
                    "pm_both_ends": ok, "fetch_failed": failed, "qualifies": passed})
        if progress:
            print(f"  rank {m['rank']:>3} {m['cls']:<12} {m['market_slug'][:58]:<58} closures {len(cl):>3}, quoted {ok:>3} "
                  f"-> {'SELECTED' if passed else 'skip'}", flush=True)
        if passed:
            taken[m["cls"]] += 1
            selected.append({"market": m, "closures": cl, "points": pts})
    return selected, pd.DataFrame(cov, columns=["rank", "market", "cls", "closures", "pm_both_ends", "fetch_failed", "qualifies"])


def collect_rows(selected: list[dict], bars: pd.DataFrame | None) -> pd.DataFrame:
    rows = []
    for s in selected:
        m = s["market"]
        for c in s["closures"]:
            pts = s["points"].get(c.key)
            if isinstance(pts, Exception):
                rows.append({"market": m["market_slug"], "rank": m["rank"], "sign": m["sign"], "cls": m["cls"],
                             "closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind,
                             "reason": f"fetch failed: {type(pts).__name__}: {str(pts)[:120]}"})
            else:
                rows.append(panel_row(c, m, pts or [], bars))
    df = pd.DataFrame(rows)
    for col in ("x_pp", "dpm_pp", "pm_close", "pm_open", "gap_spy_bp"):
        if col not in df:
            df[col] = float("nan")
    df["fresh_date"] = df.get("fresh_date", pd.Series(False, index=df.index)).fillna(False)
    return df


def equity_range(selected: list[dict]) -> tuple[str, str]:
    first = min(c.close_day for s in selected for c in s["closures"]).strftime("%Y-%m-%d")
    last = max(c.open_day for s in selected for c in s["closures"]).strftime("%Y-%m-%d")
    return first, last


def load_geo(path=REPLICATION_ROWS) -> pd.DataFrame:
    g = pd.read_csv(path)
    return g[g["cls"] == "geopolitics"].reset_index(drop=True)


def write_run_log(entry: str, results_dir=None) -> None:
    out = results_dir or RESULTS_DIR
    path = out / "RUN_LOG.md"
    out.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Macro-panel run log\n\nOne entry per invocation of `python -m macro_panel.run`: code commit, "
                        "stage reached, wall time, network requests (cache hits not counted), exit status.\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)


def main(argv: list[str] | None = None, load_key=None, fetch_pm=fetch_market_pm, fetch_bars=None,
         markets_path=MARKETS_PATH, results_dir=None, done_path=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-csv", action="store_true", help="re-analyse results.csv (report regeneration only)")
    args = ap.parse_args(argv)
    out = results_dir or RESULTS_DIR
    done = done_path or (out / ".done" if results_dir else DONE_PATH)
    t0, started = time.time(), datetime.now(timezone.utc)
    commit = _git("rev-parse", "--short", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--", "macro_panel"))
    pm_session, massive_session = CountingSession(), CountingSession()
    exit_code, note, stage = 0, "", "start"
    if done.exists() and not args.reuse_csv:
        print(f"{done} exists: the single pre-registered run has already happened; use --reuse-csv to re-render", file=sys.stderr)
        return 3
    try:
        from .report import write_all

        out.mkdir(parents=True, exist_ok=True)
        if args.reuse_csv:
            stage = "re-analysis"
            rows = pd.read_csv(out / "results.csv")
            rows["reason"] = rows["reason"].fillna("")
            cov = pd.read_csv(out / "coverage.csv")
        else:
            if not markets_path.exists():
                from .select import freeze

                stage = "selection"
                df = freeze(markets_path)
                note = f"froze {len(df)} eligible markets to {markets_path.name}; commit it, then run again"
                print(note)
                return exit_code
            stage = "pm coverage"
            cands = load_candidates(markets_path)
            print(f"{len(cands)} frozen candidates; PM coverage walk (PM data only)", flush=True)
            selected, cov = select_markets(cands, pm_session, fetch_pm=fetch_pm)
            cov.to_csv(out / "coverage.csv", index=False)
            n_closures = sum(len(s["closures"]) for s in selected)
            n_cov = int(cov.loc[cov["qualifies"], "pm_both_ends"].sum()) if len(cov) else 0
            print(f"{len(selected)} markets selected; {n_closures} market x closure rows, {n_cov} quoted at both ends", flush=True)
            stage = "equity"
            if load_key is None:
                from polybridge_research.massive import MissingApiKey, load_api_key

                def load_key():
                    try:
                        return load_api_key(search_from=REPO_ENV_DIR, interactive=False)
                    except MissingApiKey:
                        return None
            key = load_key()
            if not key:
                note = (f"ready, needs MASSIVE_API_KEY: {len(selected)} markets, {n_cov} PM-quoted rows; stopped before "
                        f"any equity request")
                print(note, file=sys.stderr)
                exit_code = 2
                return exit_code
            if fetch_bars is None:
                from polybridge_research.massive import MassiveClient

                client = MassiveClient(key, cache_dir=CACHE_DIR / "massive", session=massive_session)

                def fetch_bars(first, last):
                    return fetch_equity_range(client, PRIMARY, first, last)
            first, last = equity_range(selected)
            print(f"equity bars {PRIMARY} {first}..{last}", flush=True)
            bars = fetch_bars(first, last)
            rows = collect_rows(selected, bars)
            rows.to_csv(out / "results.csv", index=False)
            done.write_text(f"{started.isoformat()} commit {commit}\n")
        stage = "analysis"
        res = analyse(rows, load_geo())
        write_all(rows, res, cov, out_dir=out)
        p = res["primary"]
        note = (f"{res['n_markets_usable']} markets, {res['n_rows_usable']} of {res['n_rows_total']} rows usable "
                f"({res['n_dates_usable']} dates); b = {p['b']:+.2f} bp/pp [{p['ci'][0]:+.2f}, {p['ci'][1]:+.2f}], "
                f"clustered t = {p['cluster_t']:+.2f}, date-perm p = {p['p_perm']:.4f}; verdict: {res['verdict']}")
        c = res["contrast"]
        if c and "ci" in c:
            note += f"; macro - geo d = {c['d']:+.2f} [{c['ci'][0]:+.2f}, {c['ci'][1]:+.2f}] ({c['label']})"
        print(note)
    except Exception:  # noqa: BLE001
        exit_code = 1
        note = f"crashed at {stage}: " + traceback.format_exc().splitlines()[-1]
        traceback.print_exc()
    finally:
        if stage != "start":
            reqs = (f"Polymarket CLOB {pm_session.counts.get('clob.polymarket.com', 0)}, "
                    f"Massive {sum(massive_session.counts.values())} (cached responses are not counted)")
            write_run_log(
                f"## {started:%Y-%m-%d %H:%M:%S}Z\n"
                f"- code commit: `{commit}`{' + uncommitted changes in macro_panel/' if dirty else ''}"
                f" (METHOD.md pre-registered at `{METHOD_COMMIT}`)\n"
                f"- stage reached: {stage}\n- wall time: {time.time() - t0:.0f} s\n- network requests: {reqs}\n"
                f"- result: {note}\n- exit: {exit_code}\n", out)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
