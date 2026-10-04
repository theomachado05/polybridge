from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fresh_accuracy  # noqa: F401,E402
from arbscan import datasrc as ds  # noqa: E402
from polybridge_research.massive import MassiveClient, load_api_key  # noqa: E402

from fresh_accuracy import rows as rw  # noqa: E402
from fresh_accuracy import stats as st  # noqa: E402
from fresh_accuracy.config import MASSIVE_CACHE, PARAMS, RESEARCH_DIR, RESULTS_DIR  # noqa: E402

OUT = RESEARCH_DIR / "results" / "fresh_accuracy_synced"
UTC = timezone.utc
_local = threading.local()
KEY = None
SOURCES: list = []


def opts() -> ds.OptionSource:
    if not hasattr(_local, "o"):
        s = ds.CountingSession()
        _local.o = ds.OptionSource(MassiveClient(KEY, cache_dir=MASSIVE_CACHE, session=s), datetime.now(rw.ET).date())
        SOURCES.append((s, _local.o))
    return _local.o


def one(r: dict, at_snapshot: bool) -> dict:
    o = opts()
    snap = datetime.fromisoformat(r["snap_utc"])
    t = snap if at_snapshot else snap - timedelta(seconds=float(r["pm_age_s"]))
    chain = o.contracts(r["ticker"], r["res_date"]) or {}
    base = dict(market_id=r["market_id"], snapshot=r["snapshot"], t_opt_utc=t.isoformat())
    if not chain:
        return {**base, "s_status": "no_clean_expiry"}
    k1, k2 = float(r["k1"]), float(r["k2"])
    chain = {k: v for k, v in chain.items() if k <= k1 + 1e-6 or k >= k2 - 1e-6}
    x = rw.option_row(mid=r["pm_mid"], age=0.0, strike=float(r["strike"]), chain=chain,
                      get_quote=lambda tk: o.quote(tk, t), snap=t, res_date=date.fromisoformat(r["res_date"]))
    out = {**base, "s_status": x["status"]}
    if x["status"] == "scored":
        out.update(s_p_mid=x["p_mid"], s_k1=x["k1"], s_k2=x["k2"], s_stepped=x["stepped"], s_width=x["width"],
                   s_opt_quote_age_s=x["opt_quote_age_s"])
    return out


def compute(sc: pd.DataFrame, at_snapshot: bool, workers: int) -> pd.DataFrame:
    recs = sc.to_dict("records")
    res, t0 = [], time.time()
    with ThreadPoolExecutor(workers) as ex:
        for i, x in enumerate(ex.map(lambda r: one(r, at_snapshot), recs)):
            res.append(x)
            if (i + 1) % 500 == 0:
                print(f"{i + 1}/{len(recs)} {time.time() - t0:.0f}s", flush=True)
    return pd.DataFrame(res)


def series(d: pd.DataFrame) -> dict:
    y, pm = d.outcome.values, d.pm_mid.values
    snap, syn = np.clip(d.p_mid.values, 0, 1), np.clip(d.s_p_mid.values, 0, 1)
    return {"dB_pm_minus_sync": st.brier_diff(pm, syn, y), "dB_snap_minus_sync": st.brier_diff(snap, syn, y),
            "dB_pm_minus_snap": st.brier_diff(pm, snap, y), "dL_pm_minus_sync": st.log_diff(pm, syn, y),
            "dL_snap_minus_sync": st.log_diff(snap, syn, y), "dL_pm_minus_snap": st.log_diff(pm, snap, y)}


def block(d: pd.DataFrame) -> dict:
    y = d.outcome.values
    b = st.cluster_boot(series(d), d.res_date.values)
    for name, p in (("pm", d.pm_mid.values), ("opt_snap", d.p_mid.values), ("opt_sync", d.s_p_mid.values)):
        p = np.clip(p, 0, 1)
        b[f"brier_{name}"] = float(((p - y) ** 2).mean())
        b[f"ls_{name}"] = float(st.log_score(p, y).mean())
    b["dates"] = int(d.res_date.nunique())
    return b


def fmt(x: dict) -> str:
    return f"{x['mean']:+.5f} [{x['ci95'][0]:+.5f}, {x['ci95'][1]:+.5f}]"


def summary_md(s: dict) -> str:
    L = ["# Fresh-market accuracy, options repriced at the Polymarket timestamp (exploratory)", "",
         "Alignment sensitivity check chosen after the original test was seen (see `research/fresh_accuracy_synced/METHOD.md`, "
         "Amendment 1). It measures how the comparison changes when the option and Polymarket timestamps match. It does not "
         "identify trader bias or true quote-update delays, and it does not change the pre-registered verdict.", "",
         "Each option leg is the last NBBO at or before the Polymarket history timestamp. The original strikes k1, k2 are held "
         f"fixed; {s['rows_needing_step']} valid rows needed a step outward (steps: {s['step_counts']}). "
         "All comparisons use the same surviving rows.", "",
         f"Scored rows in the primary study: {s['input_rows']}. Synced option probability valid on {s['valid_rows']}; "
         f"dropped {s['input_rows'] - s['valid_rows']} ({', '.join(f'{k} {v}' for k, v in s['drop_reasons'].items()) or 'none'}).", "",
         "Differences are row-weighted means over resolution-date clusters, 95% bootstrap intervals (10,000 draws, seed 20261004). "
         "Positive means the second forecast was more accurate.", ""]
    for key, title in (("all", "All valid rows"), ("pm_age_le_30", "Rows with pm_age_s <= 30")):
        b = s[key]
        L += [f"## {title} (n = {b['n']}, dates = {b['dates']})", "",
              "| | PM | options at snapshot | options at PM timestamp |", "|---|---|---|---|",
              f"| mean Brier | {b['brier_pm']:.5f} | {b['brier_opt_snap']:.5f} | {b['brier_opt_sync']:.5f} |",
              f"| mean log score | {b['ls_pm']:.5f} | {b['ls_opt_snap']:.5f} | {b['ls_opt_sync']:.5f} |", "",
              "| difference | Brier | log score |", "|---|---|---|",
              f"| PM minus synced options | {fmt(b['dB_pm_minus_sync'])} | {fmt(b['dL_pm_minus_sync'])} |",
              f"| snapshot options minus synced options | {fmt(b['dB_snap_minus_sync'])} | {fmt(b['dL_snap_minus_sync'])} |",
              f"| PM minus snapshot options (same rows) | {fmt(b['dB_pm_minus_snap'])} | {fmt(b['dL_pm_minus_snap'])} |", ""]
    return "\n".join(L)


def requests_made() -> dict:
    c = Counter()
    for s, _ in SOURCES:
        c.update(s.counts)
    return dict(massive_requests=dict(c), massive_failures=sum(len(o.failures) for _, o in SOURCES),
                failures_sample=[f for _, o in SOURCES for f in o.failures][:20])


def main(argv=None) -> int:
    global KEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args(argv)
    KEY = load_api_key(search_from=RESEARCH_DIR, interactive=False)
    df = pd.read_csv(RESULTS_DIR / "rows.csv", low_memory=False, dtype={"market_id": str})
    sc = df[df.status == "scored"].copy()
    t_start = datetime.now(UTC)
    print(f"start {t_start.isoformat()} rows {len(sc)} check={a.check}", flush=True)
    r = compute(sc, a.check, a.workers)
    m = sc.merge(r, on=["market_id", "snapshot"], how="left", validate="1:1")
    if a.check:
        ok = m.s_status.eq("scored") & np.isclose(m.s_p_mid, m.p_mid, rtol=0, atol=1e-12)
        print(f"check: reproduced {int(ok.sum())}/{len(m)}; status {m.s_status.value_counts().to_dict()}; "
              f"max abs diff {float((m.s_p_mid - m.p_mid).abs().max())}; {requests_made()}")
        return 0 if ok.all() else 1
    OUT.mkdir(parents=True, exist_ok=True)
    keep = ["market_id", "ticker", "kind", "res_date", "event", "snapshot", "snap_utc", "strike", "pm_mid", "pm_age_s",
            "k1", "k2", "stepped", "p_mid", "outcome", "t_opt_utc", "s_status", "s_p_mid", "s_k1", "s_k2", "s_stepped",
            "s_width", "s_opt_quote_age_s"]
    m[keep].to_csv(OUT / "rows.csv", index=False)
    v = m[m.s_status == "scored"].copy()
    v["outcome"] = v.outcome.astype(int)
    s = dict(exploratory=True, input_rows=int(len(m)), valid_rows=int(len(v)),
             drop_reasons=m.loc[m.s_status != "scored", "s_status"].value_counts().to_dict(),
             same_strikes_as_snapshot=int(((v.s_k1 == v.k1) & (v.s_k2 == v.k2)).sum()),
             rows_needing_step=int((v.s_stepped > 0).sum()), step_counts=v.s_stepped.value_counts().sort_index().to_dict(),
             pm_age_le_30_input=int((m.pm_age_s <= 30).sum()),
             all=block(v), pm_age_le_30=block(v[v.pm_age_s <= 30]),
             started_utc=t_start.isoformat(), finished_utc=datetime.now(UTC).isoformat(), workers=a.workers, **requests_made())
    (OUT / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    (OUT / "SUMMARY.md").write_text(summary_md(s) + "\n")
    print(summary_md(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
