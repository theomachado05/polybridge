"""Single run of the chronological holdout (METHOD.md). Reuses fresh_accuracy rows, scoring and bootstrap unchanged.

    cd research && SHARED_MASSIVE_CACHE=<dir> FRESH_ACC_CACHE=<dir> .venv/bin/python -m fresh_accuracy_latest.run
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import fresh_accuracy  # noqa: F401
from fresh_accuracy import rows as rw
from fresh_accuracy.freeze import load_frozen
from fresh_accuracy.run import block, git_head, outcome_map, score_frame

from fresh_accuracy_latest.freeze import FROZEN_IDS, FROZEN_SHA, HOLDOUT

OUT = Path(__file__).resolve().parent.parent / "results" / "fresh_accuracy_latest"
MIN_ROWS = 100
UTC = timezone.utc


def verdict(n: int, b: dict) -> str:
    if n < MIN_ROWS:
        return "INSUFFICIENT"
    if b["mean"] <= 0:
        return "FAIL"
    return "PASS" if b["ci95"][0] > 0 else "DIRECTION-CONSISTENT"


def analyse(sc: pd.DataFrame) -> dict:
    t = block(sc, "ticker")
    res = dict(n_rows=int(len(sc)), n_markets=int(sc.market_id.nunique()), n_tickers=int(sc.ticker.nunique()),
               n_dates=int(sc.res_date.nunique()), ticker_cluster=t, event_cluster=block(sc, "event"),
               pm_age_mean_s=float(sc.pm_age_s.mean()),
               opt_age_mean_s=float(sc.opt_quote_age_s.mean()) if "opt_quote_age_s" in sc else None)
    if res["n_dates"] > 1:
        res["date_cluster"] = block(sc, "res_date")
    s30 = sc[sc.pm_age_s <= 30]
    res["pm_age_le_30s"] = block(s30, "ticker") if len(s30) else {"n": 0}
    res["verdict"] = verdict(len(sc), t["d_B"])
    return res


def summary_md(res: dict) -> str:
    L = [f"# Chronological holdout: {res['verdict']}", ""]
    if res["n_rows"] == 0:
        L += [res["note"], ""]
    else:
        t = res["ticker_cluster"]
        L += [f"Rows {res['n_rows']}, markets {res['n_markets']}, tickers {res['n_tickers']}, dates {res['n_dates']}.",
              f"Brier PM {t['brier_pm']:.4f}, options {t['brier_opt']:.4f}; difference {t['d_B']['mean']:+.4f} "
              f"ticker 95% [{t['d_B']['ci95'][0]:+.4f}, {t['d_B']['ci95'][1]:+.4f}], event 95% "
              f"[{res['event_cluster']['d_B']['ci95'][0]:+.4f}, {res['event_cluster']['d_B']['ci95'][1]:+.4f}].",
              f"Log-score difference {t['d_L']['mean']:+.4f} ticker 95% [{t['d_L']['ci95'][0]:+.4f}, {t['d_L']['ci95'][1]:+.4f}].",
              f"Mean PM age {res['pm_age_mean_s']:.0f} s, option-leg age {res['opt_age_mean_s']}.", ""]
    L += [f"Method: `research/fresh_accuracy_latest/METHOD.md` (commit {res['method_commit']}). Run commit {res['commit']}."]
    return "\n".join(L) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    done = OUT / ".done"
    if done.exists():
        print(f"{done} exists: refusing a second run.", file=sys.stderr)
        return 2
    t0 = datetime.now(UTC)
    frozen = load_frozen(FROZEN_IDS, FROZEN_SHA)
    method_commit = git_head()
    first_fetch = None
    if not frozen:
        sc = pd.DataFrame()
        df = pd.DataFrame(columns=["market_id", "snapshot", "status"])
        res = dict(verdict="INSUFFICIENT", n_rows=0, n_markets=0, n_tickers=0, n_dates=0,
                   note="The frozen holdout list is empty: no NYSE session closed between the arb-scan commit "
                        "(2026-10-03 05:14:24 EDT) and the run, and every market resolving 2026-10-02 is in arb_gaps.csv. "
                        "No price, quote or outcome was fetched.")
    else:
        from fresh_accuracy.freeze import keyset_events
        from fresh_accuracy.run import Runner
        r = Runner(OUT)
        first_fetch = datetime.now(UTC).isoformat()
        df = pd.DataFrame(r.market_rows(frozen, "holdout"))
        sc = df[df.apply(rw.is_scored, axis=1)].copy() if len(df) else pd.DataFrame()
        if len(sc):
            sc["outcome"] = sc.market_id.map(outcome_map(keyset_events(r.http, HOLDOUT)))
            sc = sc[sc.outcome.isin([0, 1])].copy()
            sc["outcome"] = sc.outcome.astype(int)
        if len(sc):
            sc = score_frame(sc)
            res = analyse(sc)
            df = df.merge(sc[["market_id", "snapshot", "outcome", "d_B", "d_L"]], on=["market_id", "snapshot"], how="left")
        else:
            res = dict(verdict="INSUFFICIENT", n_rows=0, n_markets=0, n_tickers=0, n_dates=0, note="No scored rows.")
        res["status"] = df.status.value_counts().to_dict() if len(df) else {}
        res["requests"] = r.counts()
    res.update(frozen_markets=len(frozen), method_commit=method_commit, commit=git_head(), started_utc=t0.isoformat(),
               first_fetch_utc=first_fetch, finished_utc=datetime.now(UTC).isoformat())
    df.to_csv(OUT / "rows.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "SUMMARY.md").write_text(summary_md(res))
    (OUT / "RUN_LOG.md").write_text(
        "# Run log: chronological holdout\n\n"
        f"- Command: `cd research && .venv/bin/python -m fresh_accuracy_latest.run`\n"
        f"- METHOD commit at run time: {method_commit}\n- Started (UTC): {res['started_utc']}\n"
        f"- First price fetch (UTC): {first_fetch or 'none (empty frozen list)'}\n- Finished (UTC): {res['finished_utc']}\n"
        f"- Frozen markets: {len(frozen)}; scored rows with outcomes: {res['n_rows']}\n- Verdict: {res['verdict']}\n")
    done.write_text(f"run finished {res['finished_utc']} verdict {res['verdict']}\n")
    print(json.dumps({k: res[k] for k in ("verdict", "n_rows", "frozen_markets", "method_commit")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
