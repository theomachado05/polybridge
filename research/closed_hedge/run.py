"""One run of the R1 closed-market hedge test (METHOD.md). `python -m closed_hedge.run`."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import analysis as A
from .books import fetch_live
from .config import ARB_META, PANEL_CSV, PARAMS, REPLICATION_CSV, REPO_DIR, RESULTS_DIR
from .report import write_chart, write_summary


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def replication_panel() -> tuple[pd.DataFrame | None, str]:
    """Section 7: only a git-committed results.csv is used."""
    rel = REPLICATION_CSV.relative_to(REPO_DIR).as_posix()
    if not _git("ls-files", rel):
        return None, "not available (results.csv not committed when this study ran)"
    rep = pd.read_csv(REPLICATION_CSV)
    x = "dpm_o_pp" if "dpm_o_pp" in rep else ("x" if "x" in rep else None)
    if x is None or "gap_bp" not in rep or "closure" not in rep:
        return None, f"committed but columns not recognised: {list(rep.columns)[:20]}"
    rep = rep.rename(columns={x: "dpm_o_pp"})
    if "reason" in rep:
        rep = rep[rep["reason"].isna() | (rep["reason"].astype(str).str.strip() == "")]
    if "open_day" not in rep:
        return None, "committed but no open_day column"
    mcol = "market" if "market" in rep else ("slug" if "slug" in rep else None)
    if mcol is None:
        return None, "committed but no market column"
    rep = rep.rename(columns={mcol: "market"})
    rep = rep[np.isfinite(rep["dpm_o_pp"]) & np.isfinite(rep["gap_bp"])]
    return rep[["market", "closure", "open_day", "dpm_o_pp", "gap_bp"]].copy(), "available"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    t0 = time.time()
    out = Path(RESULTS_DIR)
    out.mkdir(parents=True, exist_ok=True)
    offline = "--offline-books" in argv  # tests only: skip the network, use the fallback spread

    panel_all = pd.read_csv(PANEL_CSV)
    panel_all["news"] = panel_all["news"].astype(str).str.lower().eq("true")
    placebo = panel_all[~panel_all["news"]].copy()

    if offline:
        books = {"hs_pp": PARAMS.hs_fallback_pp, "n": 0, "fallback": True, "requests": {"gamma": 0, "clob": 0},
                 "fetched_utc": None, "n_markets": 0}
        raw = {"summary": books, "books": []}
    else:
        books, raw = fetch_live()
    (out / "books_live.json").write_text(json.dumps(raw, indent=1))
    hs = books["hs_pp"]

    res: dict = {"hs": books, "params": PARAMS.__dict__ | {"k_sens": list(PARAMS.k_sens)}}
    d = A.prepare(placebo)
    prim, st = A.evaluate(d, hs)
    res["primary"] = prim
    res["n_panel"] = int(len(d))
    res["n_eval"] = int((d["excluded"] == "").sum())
    res["rate_src"] = d["rate_src"].value_counts().to_dict()
    res["block"] = A.evaluate(d, hs, block=PARAMS.block_len)[0]["tests"]
    res["cost_sens"] = {
        f"hs={PARAMS.hs_tick_pp}pp": A.evaluate(d, PARAMS.hs_tick_pp)[0]["tests"]["A"],
        f"hs={PARAMS.hs_thin_pp}pp": A.evaluate(d, PARAMS.hs_thin_pp)[0]["tests"]["A"],
        f"pre-market equity {PARAMS.eq_cost_pre_bp}bp/side": A.evaluate(d, hs, eq_pre_side_bp=PARAMS.eq_cost_pre_bp)[0]["tests"]["B08"],
    }
    res["cost_sens_desc"] = {
        f"hs={PARAMS.hs_tick_pp}pp": A.evaluate(d, PARAMS.hs_tick_pp)[0]["describe"]["A"],
        f"hs={PARAMS.hs_thin_pp}pp": A.evaluate(d, PARAMS.hs_thin_pp)[0]["describe"]["A"],
    }
    res["k_sens"] = {str(k): {h: A.evaluate(d, hs, k_bp=k)[0]["tests"][h] for h in ("B", "B08")} for k in PARAMS.k_sens}
    res["per_market"] = A.per_market(d, hs)
    res["whole_path"] = A.whole_path(st)
    res["in_sample"] = A.in_sample_bound(d, hs)
    try:
        arb = json.loads(Path(ARB_META).read_text())
        res["arb_half_spread_pp"] = 100 * float(arb.get("half_spread", float("nan")))
    except Exception:
        res["arb_half_spread_pp"] = None

    d_all = A.prepare(panel_all)
    res["all397"] = A.evaluate(d_all, hs)[0]
    res["all397"]["n_eval"] = int((d_all["excluded"] == "").sum())

    rep, rep_status = replication_panel()
    res["replication_status"] = rep_status
    res["replication"] = A.replication(rep, hs) if rep is not None else None

    # per-closure CSV
    cols = ["closure", "open_day", "kind", "market", "sign", "pm_close", "pm_open", "dpm_o_pp", "dpm_early_o_pp", "gap_bp",
            "ret30_bp", "resid_bp", "rate", "rate_raw", "rate_src", "n_prior", "excluded"]
    csv = d[cols].join(st)
    csv.to_csv(out / "closures_hedged.csv", index=False)
    res["wall_s"] = round(time.time() - t0, 1)
    res["commit"] = _git("rev-parse", "--short", "HEAD")
    res["dirty"] = bool(_git("status", "--porcelain", "--", "research/closed_hedge"))
    (out / "results.json").write_text(json.dumps(res, indent=1, default=float))
    write_chart(res, d, out / "chart.png")
    write_summary(res, out / "SUMMARY.md")
    _log(out / "RUN_LOG.md", res, books, offline)
    print(f"A: {prim['tests']['A']['verdict']} (VR0 {prim['tests']['A']['VR0']:+.4f}); "
          f"B: {prim['tests']['B']['verdict']} (VR0 {prim['tests']['B']['VR0']:+.4f}); hs {hs:.3f} pp; n {res['n_eval']}")
    return 0


def _log(path: Path, res: dict, books: dict, offline: bool) -> None:
    head = ("# Closed-market hedge run log\n\nOne entry per run of `python -m closed_hedge.run`: code commit, wall time, "
            "network requests, exit status.\n")
    text = path.read_text() if path.exists() else head
    t = res["primary"]["tests"]
    entry = (f"\n## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}\n"
             f"- code commit: `{res['commit']}`{' + uncommitted changes in research/closed_hedge/' if res['dirty'] else ''}\n"
             f"- mode: {'offline (fallback spread, test)' if offline else 'live books + analysis of the saved closure panel'}\n"
             f"- wall time: {res['wall_s']} s\n"
             f"- network requests: gamma {books['requests']['gamma']}, CLOB /book {books['requests']['clob']}; Massive 0; "
             f"no 8-K or option data\n"
             f"- PM half-spread: {books['hs_pp']:.3f} pp from {books['n']} books{' (FALLBACK)' if books['fallback'] else ''}\n"
             f"- replication panel: {res['replication_status']}\n"
             f"- result: hedge A {t['A']['verdict']}, hedge B {t['B']['verdict']}, B 08:00 {t['B08']['verdict']}; "
             f"n = {res['n_eval']} of {res['n_panel']}\n- exit: 0\n")
    path.write_text(text + entry)


if __name__ == "__main__":
    raise SystemExit(main())
