"""Run study T2 (METHOD.md section 4). Each arm runs once; a .done marker refuses a second run.

    cd research && .venv/bin/python -m pm_vs_premarket.run

Arm K needs no key and no network. Arm M needs MASSIVE_API_KEY (environment, or research/.env only); without it the
runner exits 2 before any Massive request.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from leadlag_closed.closures import Closure

from . import report
from .config import (ARM_K_DIR, OUTCOME, OUTCOME_2, PARAMS, PRIMARY_CSV, PRIMARY_EVENTS, RESEARCH_DIR,
                     RESULTS_DIR, SECONDARY_CSV, SECONDARY_MARKETS, FUTURES_ROOTS)
from .data import (CountingSession, arm_k_rows, closure_measures, fetch_equity_range, fetch_futures_bars,
                   front_contract, probe_futures)
from .stats import benchmark_test, describe, verdict


def git_commit() -> str:
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RESEARCH_DIR, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "pm_vs_premarket"], cwd=RESEARCH_DIR,
                               capture_output=True, text=True).stdout.strip()
        return (c or "unknown") + (" + uncommitted changes in pm_vs_premarket/" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def load_key(env_file: Path) -> str:
    key = (os.environ.get("MASSIVE_API_KEY") or "").strip()
    if key:
        return key
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith("MASSIVE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _month(dates) -> np.ndarray:
    return np.asarray([str(d)[:7] for d in dates])


def run_test(df: pd.DataFrame, g: str, b: str, x: str) -> dict:
    return benchmark_test(df[g], df[b], df[x], df["closure"], _month(df["closure"]),
                          PARAMS.n_perm, PARAMS.n_boot, PARAMS.seed)


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


def arm_k(out_dir: Path, primary_csv: Path, commit: str) -> str:
    rows = arm_k_rows(pd.read_csv(primary_csv))
    res = {"k_0800": run_test(rows, "g", "b_0800", "x_0800"), "s3_0800": run_test(rows, "g", "b_0800", "x_full"),
           "by_market": {m: run_test(rows[rows["market"] == m], "g", "b_0800", "x_0800") for m in sorted(rows["market"].unique())},
           "describe": describe(rows["g"], rows["b_0800"], rows["x_0800"]), "n_rows": len(rows)}
    res["n_dropped"] = len(rows) - res["k_0800"]["n"]
    res["k_0800_verdict"] = verdict(res["k_0800"], PARAMS.t_crit, PARAMS.alpha)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out_dir / "rows.csv", index=False)
    (out_dir / "tests.json").write_text(json.dumps(_clean(res), indent=2))
    (out_dir / "SUMMARY.md").write_text(report.arm_k_summary(res, commit))
    (out_dir / ".done").write_text(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {commit}\n")
    k = res["k_0800"]
    return (f"arm K: c = {k.get('c', float('nan')):+.2f} bp/pp, t {k.get('c_t', float('nan')):+.2f}, "
            f"p {k.get('p_perm', float('nan')):.3f}, n {k['n']}; {res['k_0800_verdict']}")


def _closure(r) -> Closure:
    return Closure(pd.Timestamp(r["closure"]), pd.Timestamp(r["open_day"]), str(r["kind"]))


def _bench_for(c: Closure, client, benchmark: str, spelling, root: str, cache: dict):
    if benchmark == "SPY":
        return None
    tk = front_contract(root, c.open_day, spelling)
    a = c.nominal_close - pd.Timedelta(minutes=30)
    b = c.nominal_open + pd.Timedelta(minutes=5)
    key = (tk, c.key)
    if key not in cache:
        cache[key] = fetch_futures_bars(client, tk, a, b)
    return cache.pop(key)


def collect(panel: pd.DataFrame, tokens: dict, client, pm_session, benchmark: str, spelling, bars: dict,
            fetch_pm) -> pd.DataFrame:
    rows = []
    for _, r in panel.iterrows():
        c = _closure(r)
        try:
            pts = fetch_pm(tokens[r["market"]], c)
            spy_b = _bench_for(c, client, benchmark, spelling, FUTURES_ROOTS[OUTCOME], {})
            row = closure_measures(c, bars[OUTCOME], pts, int(r["sign"]), spy_b)
            qqq_b = _bench_for(c, client, benchmark, spelling, FUTURES_ROOTS[OUTCOME_2], {})
            q = closure_measures(c, bars[OUTCOME_2], pts, int(r["sign"]), qqq_b)
            row.update({"g_qqq": q["g"], "b_qqq_0925": q["b_0925"]})
            row["fetch_error"] = ""
        except Exception as exc:  # noqa: BLE001
            row = {"closure": c.key, "open_day": c.open_day.strftime("%Y-%m-%d"), "kind": c.kind,
                   "fetch_error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        row.update({"market": r["market"], "sign": int(r["sign"]), "g_committed": r.get("g_committed", np.nan),
                    "pm_close_committed": r.get("pm_close", np.nan)})
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in ("g", "b_0925", "b_0800", "x_0925", "x_0800", "x_full", "g_qqq", "b_qqq_0925", "pm_close"):
        if col not in df:
            df[col] = np.nan
    return df


def load_panels(primary_csv: Path, events: Path, secondary_csv: Path, markets: Path):
    a = pd.read_csv(primary_csv)
    a = a[(~a["news"].astype(bool)) & (a["reason"].isna() | (a["reason"].astype(str) == ""))]
    meta = yaml.safe_load(events.read_text())["markets"]
    tok_a = {k: str(v["token_id"]) for k, v in meta.items()}
    pa = pd.DataFrame({"closure": a["closure"].astype(str), "open_day": a["open_day"].astype(str), "kind": a["kind"],
                       "market": a["market"], "sign": a["sign"].astype(int), "g_committed": a["gap_bp"].astype(float),
                       "pm_close": a["pm_close"].astype(float)})
    pb, tok_b = None, {}
    if secondary_csv.exists():
        b = pd.read_csv(secondary_csv)
        b = b[b["reason"].isna() | (b["reason"].astype(str) == "")]
        cands = {c["market_slug"]: c for c in json.loads(markets.read_text())["candidates"]}
        tok_b = {m: str(cands[m]["token_id"]) for m in b["market"].unique()}
        pb = pd.DataFrame({"closure": b["closure"].astype(str), "open_day": b["open_day"].astype(str), "kind": b["kind"],
                           "market": b["market"], "sign": b["sign"].astype(int), "g_committed": b["gap_spy_bp"].astype(float),
                           "pm_close": b["pm_close"].astype(float)})
    return pa, tok_a, pb, tok_b


def consistency(df: pd.DataFrame) -> str:
    parts = []
    for name, a, b in (("SPY gap (bp)", "g", "g_committed"), ("PM at close (pp)", "pm_close", "pm_close_committed")):
        m = np.isfinite(df[a].astype(float)) & np.isfinite(df[b].astype(float))
        diff = float(np.max(np.abs(df.loc[m, a].astype(float) - df.loc[m, b].astype(float)))) if m.any() else float("nan")
        parts.append(f"{name}: {int(m.sum())} rows with both, max abs difference {diff:.4g}")
    return "; ".join(parts) + "."


def arm_m(out_dir: Path, client, pm_session, commit: str, paths: dict, pm_fetch=None) -> str:
    from leadlag_closed.data import fetch_closure_pm
    from leadlag_replication.data import fetch_market_pm

    probe = probe_futures(client)
    benchmark, spelling = probe["benchmark"], probe["spelling"]
    print(f"benchmark: {benchmark} ({'; '.join(probe['log'])})", flush=True)
    pa, tok_a, pb, tok_b = load_panels(paths["primary_csv"], paths["events"], paths["secondary_csv"], paths["markets"])
    allp = pd.concat([pa, pb]) if pb is not None else pa
    first = min(allp["closure"])
    last = max(allp["open_day"])
    bars = {t: fetch_equity_range(client, t, first, last) for t in (OUTCOME, OUTCOME_2)}
    pm_cache = out_dir / ".massive_cache" / "pm"

    def pm_a(token, c):
        return fetch_closure_pm(token, c, pm_session, cache_dir=pm_cache)

    def pm_b(token, c):
        got = fetch_market_pm(token, [c], session=pm_session, cache_dir=pm_cache, workers=1)[c.key]
        if isinstance(got, Exception):
            raise got
        return got

    ra = collect(pa, tok_a, client, pm_session, benchmark, spelling, bars, pm_fetch or pm_a)
    rb = collect(pb, tok_b, client, pm_session, benchmark, spelling, bars, pm_fetch or pm_b) if pb is not None else None
    tests = {"primary_0925": run_test(ra, "g", "b_0925", "x_0925"), "s1_0800": run_test(ra, "g", "b_0800", "x_0800"),
             "s3_0925": run_test(ra, "g", "b_0925", "x_full"), "s3_0800": run_test(ra, "g", "b_0800", "x_full"),
             "s5_qqq_0925": run_test(ra, "g_qqq", "b_qqq_0925", "x_0925")}
    for m in sorted(ra["market"].unique()):
        tests[f"s4_{m}_0925"] = run_test(ra[ra["market"] == m], "g", "b_0925", "x_0925")
    if rb is not None:
        tests["s2_0925"] = run_test(rb, "g", "b_0925", "x_0925")
        tests["s2_0800"] = run_test(rb, "g", "b_0800", "x_0800")
    table = [("Primary: x to 09:25, bench 09:25", "primary_0925"), ("S1: x to 08:00, bench 08:00", "s1_0800"),
             ("S2: replication panel, 09:25", "s2_0925"), ("S2: replication panel, 08:00", "s2_0800"),
             ("S3: x full closure, bench 09:25", "s3_0925"), ("S3: x full closure, bench 08:00", "s3_0800")]
    table += [(f"S4: {k[3:-5]}, 09:25", k) for k in tests if k.startswith("s4_")]
    table.append(("S5: QQQ outcome and benchmark, 09:25", "s5_qqq_0925"))
    res = {"benchmark": benchmark, "probe_log": probe["log"], "tests": tests, "table": table,
           "primary_0925": tests["primary_0925"],
           "verdict": verdict(tests["primary_0925"], PARAMS.t_crit, PARAMS.alpha),
           "describe_primary": describe(ra["g"], ra["b_0925"], ra["x_0925"]),
           "consistency": consistency(ra) + (" Replication panel: " + consistency(rb) if rb is not None else "")}
    out_dir.mkdir(parents=True, exist_ok=True)
    ra.to_csv(out_dir / "rows_primary.csv", index=False)
    if rb is not None:
        rb.to_csv(out_dir / "rows_secondary.csv", index=False)
    (out_dir / "tests.json").write_text(json.dumps(_clean({k: v for k, v in res.items() if k != "table"}), indent=2))
    (out_dir / "SUMMARY.md").write_text(report.arm_m_summary(res, commit))
    (out_dir / ".done").write_text(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {commit}\n")
    p = tests["primary_0925"]
    return (f"arm M ({benchmark}): c = {p.get('c', float('nan')):+.2f} bp/pp, t {p.get('c_t', float('nan')):+.2f}, "
            f"p {p.get('p_perm', float('nan')):.3f}, n {p['n']}; {res['verdict']}")


def write_run_log(out_dir: Path, entry: str) -> None:
    path = out_dir / "RUN_LOG.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# T2 run log\n\nOne entry per invocation of `python -m pm_vs_premarket.run`: code commit, arms run, "
                        "wall time, network requests (cached responses not counted), exit status.\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)


def main(argv: list[str] | None = None, client=None, pm_fetch=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(RESULTS_DIR))
    ap.add_argument("--primary-csv", default=str(PRIMARY_CSV))
    ap.add_argument("--events", default=str(PRIMARY_EVENTS))
    ap.add_argument("--secondary-csv", default=str(SECONDARY_CSV))
    ap.add_argument("--markets", default=str(SECONDARY_MARKETS))
    ap.add_argument("--env-file", default=str(RESEARCH_DIR / ".env"))
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    k_dir = out_dir / ARM_K_DIR.name
    t0, started = time.time(), datetime.now(timezone.utc)
    commit = git_commit()
    pm_session, massive_session = CountingSession(), CountingSession()
    notes, exit_code = [], 0
    try:
        if (k_dir / ".done").exists():
            notes.append("arm K already run (.done present), skipped")
        else:
            notes.append(arm_k(k_dir, Path(args.primary_csv), commit))
        if (out_dir / ".done").exists():
            notes.append("arm M already run (.done present), skipped")
        else:
            if client is None:
                key = load_key(Path(args.env_file))
                if not key:
                    notes.append("arm M not run: MASSIVE_API_KEY missing (ready, needs MASSIVE_API_KEY)")
                    exit_code = 2
                else:
                    from polybridge_research.massive import MassiveClient
                    client = MassiveClient(key, cache_dir=out_dir / ".massive_cache" / "massive", session=massive_session)
            if client is not None:
                paths = {"primary_csv": Path(args.primary_csv), "events": Path(args.events),
                         "secondary_csv": Path(args.secondary_csv), "markets": Path(args.markets)}
                notes.append(arm_m(out_dir, client, pm_session, commit, paths, pm_fetch))
        for n in notes:
            print(n, flush=True)
    except Exception:  # noqa: BLE001
        exit_code = 1
        notes.append("crashed: " + traceback.format_exc().splitlines()[-1])
        traceback.print_exc()
    finally:
        reqs = (f"Polymarket CLOB {pm_session.counts.get('clob.polymarket.com', 0)}, "
                f"Massive {sum(massive_session.counts.values())}")
        write_run_log(out_dir, f"## {started:%Y-%m-%d %H:%M:%S}Z\n- code commit: `{commit}`\n- wall time: {time.time() - t0:.0f} s\n"
                               f"- network requests: {reqs}\n" + "".join(f"- {n}\n" for n in notes) + f"- exit: {exit_code}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
