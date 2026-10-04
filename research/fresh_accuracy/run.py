"""Single run of the fresh-market accuracy study (METHOD.md). Sequential requests only.

    cd research && SHARED_MASSIVE_CACHE=<dir> .venv/bin/python -m fresh_accuracy.run          # primary
    cd research && SHARED_MASSIVE_CACHE=<dir> .venv/bin/python -m fresh_accuracy.run --h3     # gated H3
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import fresh_accuracy  # noqa: F401
from arbscan import datasrc as ds
from polybridge_research.calendar import TradingCalendar
from polybridge_research.massive import MassiveClient, load_api_key

from fresh_accuracy import report
from fresh_accuracy import rows as rw
from fresh_accuracy import stats as st
from fresh_accuracy.config import CACHE_DIR, MASSIVE_CACHE, PARAMS, REPO_DIR, RESEARCH_DIR, RESULTS_DIR
from fresh_accuracy.freeze import _jl, keyset_events, load_frozen

UTC = timezone.utc


def log(msg: str) -> None:
    print(f"{datetime.now(rw.ET):%H:%M:%S} {msg}", flush=True)


def outcome_map(events: list[dict]) -> dict[str, int | None]:
    out = {}
    for ev in events:
        for m in ev.get("markets") or []:
            pr = [str(x) for x in _jl(m.get("outcomePrices"))]
            out[str(m.get("id"))] = 1 if pr[:2] == ["1", "0"] else 0 if pr[:2] == ["0", "1"] else None
    return out


class Runner:
    def __init__(self, out: Path = RESULTS_DIR):
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = ds.Http(CACHE_DIR / "http")
        key = load_api_key(search_from=RESEARCH_DIR, interactive=False)
        self.massive = MassiveClient(key, cache_dir=MASSIVE_CACHE, session=ds.CountingSession())
        self.opts = ds.OptionSource(self.massive, datetime.now(rw.ET).date())
        self.cal = TradingCalendar()
        self.scope: Counter = Counter()
        self.t0 = time.time()

    def prev_session(self, d: date) -> date:
        return self.cal.before(pd.Timestamp(d)).date()

    def history(self, token: str, a: int, b: int):
        return ds.clob_history(self.http, token, a, b, 1)

    def market_rows(self, markets: list[dict], tag: str) -> list[dict]:
        out = []
        for i, m in enumerate(markets):
            rows, drop = rw.pm_market_rows(m, history_fn=self.history, chain_fn=self.opts.contracts,
                                           quote_fn=self.opts.quote, prev_session_fn=self.prev_session)
            self.scope.update(drop)
            out.extend(rows)
            if (i + 1) % 250 == 0:
                log(f"{tag} {i + 1}/{len(markets)} markets, rows {len(out)}, scored {sum(map(rw.is_scored, out))}, "
                    f"http {dict(self.http.session.counts)}, massive {dict(self.massive.session.counts)}")
        return out

    def counts(self) -> dict:
        return dict(http=dict(self.http.session.counts), massive=dict(self.massive.session.counts),
                    http_failures=len(self.http.failures), massive_failures=len(self.opts.failures),
                    failures_sample=(self.http.failures + self.opts.failures)[:30])


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "?"


def slice_check(r: Runner, frozen: list[dict], p=PARAMS) -> dict:
    pick = random.Random(p.seed).sample(frozen, min(p.slice_n, len(frozen)))
    rows = r.market_rows(pick, "slice")
    status = Counter(x["status"] for x in rows)
    valid = sum(map(rw.is_scored, rows))
    res = dict(markets=len(pick), rows=len(rows), valid=valid, valid_rate=valid / len(rows) if rows else 0.0,
               status=dict(status), threshold=p.slice_min_valid, requests=r.counts(),
               pm_hist_points_median=float(np.median([x.get("hist_points", 0) for x in rows])) if rows else 0.0)
    res["pass"] = res["valid_rate"] >= p.slice_min_valid
    return res


def score_frame(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["d_B"] = st.brier_diff(d.pm_mid, d.p_mid, d.outcome)
    d["d_L"] = st.log_diff(d.pm_mid, d.p_mid, d.outcome)
    d["brier_pm"] = (d.pm_mid - d.outcome) ** 2
    d["brier_opt"] = (d.p_mid.clip(0, 1) - d.outcome) ** 2
    d["ls_pm"] = st.log_score(d.pm_mid, d.outcome)
    d["ls_opt"] = st.log_score(d.p_mid.clip(0, 1), d.outcome)
    return d


def block(d: pd.DataFrame, cluster: str = "res_date") -> dict:
    if len(d) == 0:
        return {"n": 0, "clusters": 0}
    b = st.cluster_boot({"d_B": d.d_B.values, "d_L": d.d_L.values}, d[cluster].values)
    b.update(brier_pm=float(d.brier_pm.mean()), brier_opt=float(d.brier_opt.mean()), ls_pm=float(d.ls_pm.mean()),
             ls_opt=float(d.ls_opt.mean()))
    return b


def trade_flags(r: Runner, sc: pd.DataFrame, frozen: dict[str, dict], p=PARAMS) -> pd.Series:
    from arbscan import verify as vf
    cache: dict[str, list] = {}
    flags = []
    for i, (mid, snap) in enumerate(zip(sc.market_id, sc.snap_utc)):
        cid = frozen[mid]["cid"]
        if cid not in cache:
            cache[cid] = [float(t["timestamp"]) for t in vf.fetch_trades(r.http, cid) if t.get("timestamp") is not None]
            if len(cache) % 500 == 0:
                log(f"trades {len(cache)} markets")
        s = datetime.fromisoformat(snap).timestamp()
        flags.append(any(abs(t - s) <= p.trade_window for t in cache[cid]))
    return pd.Series(flags, index=sc.index)


def primary(args) -> int:
    out = RESULTS_DIR
    done = out / ".done"
    if done.exists():
        print(f"{done} exists: the study has already been run once. Refusing a second run.", file=sys.stderr)
        return 2
    frozen = load_frozen()
    r = Runner(out)
    t_start = datetime.now(UTC)
    log(f"frozen markets {len(frozen)}; massive cache {MASSIVE_CACHE}")
    sl = slice_check(r, frozen)
    (out / "slice_check.json").write_text(json.dumps(sl, indent=1))
    log(f"slice valid rate {sl['valid_rate']:.3f} ({sl['valid']}/{sl['rows']}) status {sl['status']}")
    if not sl["pass"]:
        done.write_text("stopped at slice check\n")
        report.write_stopped(out, "SLICE-STOP", sl, git_head(), t_start)
        return 0
    if args.slice_only:
        return 0
    rows = r.market_rows(frozen, "full")
    df = pd.DataFrame(rows)
    scored_mask = df.apply(rw.is_scored, axis=1) if len(df) else pd.Series(dtype=bool)
    n_rows, n_dates = int(scored_mask.sum()), int(df.loc[scored_mask, "res_date"].nunique()) if len(df) else 0
    gate = dict(scored_rows=n_rows, dates=n_dates, status=df.status.value_counts().to_dict() if len(df) else {},
                dropped_snapshots=dict(r.scope), requests=r.counts(), seconds=time.time() - r.t0)
    (out / "gate.json").write_text(json.dumps(gate, indent=1, default=str))
    log(f"coverage gate: rows {n_rows}, dates {n_dates}")
    if n_rows < PARAMS.min_rows or n_dates < PARAMS.min_dates:
        df.to_csv(out / "rows.csv", index=False)
        done.write_text("INSUFFICIENT at coverage gate\n")
        report.write_stopped(out, "INSUFFICIENT", gate, git_head(), t_start)
        return 0
    sc = df[scored_mask].copy()
    fz = {m["id"]: m for m in frozen}
    sc["trade_print"] = trade_flags(r, sc, fz)
    log("trade prints done; joining outcomes")
    om = outcome_map(keyset_events(r.http))
    sc["outcome"] = sc.market_id.map(om)
    n_no = int(sc.outcome.isna().sum())
    sc = sc[sc.outcome.isin([0, 1])].copy()
    sc["outcome"] = sc.outcome.astype(int)
    sc = score_frame(sc)
    res = analyse(sc)
    res.update(no_outcome_rows=n_no, gate=gate, slice=sl, commit=git_head(), started_utc=t_start.isoformat(),
               finished_utc=datetime.now(UTC).isoformat(), seconds=time.time() - r.t0, requests=r.counts())
    df = df.merge(sc[["market_id", "snapshot", "outcome", "d_B", "d_L", "trade_print"]], on=["market_id", "snapshot"], how="left")
    df.to_csv(out / "rows.csv", index=False)
    (out / "stats.json").write_text(json.dumps(res, indent=1, default=str))
    report.chart(sc, out / "accuracy_chart.png")
    report.write_summary(out, res)
    report.write_run_log(out, res, "primary")
    done.write_text(f"primary run finished {res['finished_utc']} verdict {res['verdict']}\n")
    log(f"VERDICT {res['verdict']}")
    return 0


def analyse(sc: pd.DataFrame, p=PARAMS) -> dict:
    main = block(sc)
    n_dates = int(sc.res_date.nunique())
    v = st.verdict(len(sc), n_dates, main["d_B"], main["d_L"])
    v_cw = st.verdict(len(sc), n_dates, main["d_B"], main["d_L"], mean_key="cw_mean", ci_key="cw_ci95")
    sec = {"event_cluster": block(sc, "event")}
    for col in ("snapshot", "kind"):
        for k, g in sc.groupby(col):
            sec[f"{col}={k}"] = block(g)
    sec["trade_print"] = block(sc[sc.trade_print.astype(bool)])
    sec["no_trade_print"] = block(sc[~sc.trade_print.astype(bool)])
    enc = st.logit_cluster(np.column_stack([st.logit(sc.p_mid), st.logit(sc.pm_mid)]), sc.outcome.values, sc.res_date.values)
    fl = st.ols_cluster(sc.p_mid - 0.5, sc.pm_mid - sc.p_mid, sc.res_date.values)
    costs = dict(opt_half_band_mean=float(sc.opt_half_band.mean()), opt_half_band_median=float(sc.opt_half_band.median()),
                 opt_comm_per_dollar_mean=float(sc.opt_comm_per_dollar.mean()),
                 opt_comm_per_dollar_median=float(sc.opt_comm_per_dollar.median()))
    return dict(verdict=v, verdict_equal_weight=v_cw, n_rows=int(len(sc)), n_dates=n_dates, n_markets=int(sc.market_id.nunique()),
                n_events=int(sc.event.nunique()), tickers=sc.ticker.value_counts().to_dict(), primary=main, secondary=sec,
                encompassing_logit=dict(names=["const", "logit_p_opt", "logit_p_pm"], **enc),
                favourite_longshot=dict(names=["const", "p_opt_minus_half"], **fl), costs=costs,
                coarse_share=float(sc.coarse.astype(bool).mean()), mean_abs_gap=float((sc.pm_mid - sc.p_mid).abs().mean()))


def h3(args, p=PARAMS) -> int:
    out = RESULTS_DIR
    done = out / ".done_h3"
    if done.exists():
        print(f"{done} exists: H3 already run. Refusing.", file=sys.stderr)
        return 2
    sj = out / "stats.json"
    prim = json.loads(sj.read_text()) if sj.exists() else {}
    deadline = datetime.fromisoformat(p.h3_deadline_et).replace(tzinfo=rw.ET)
    fin = datetime.fromisoformat(prim["finished_utc"]) if prim.get("finished_utc") else None
    why = None
    if prim.get("verdict") != "PASS":
        why = f"primary verdict is {prim.get('verdict')}, not PASS (fixed sequence)"
    elif fin is None or fin > deadline:
        why = "primary results were not written before 01:30 ET"
    if why:
        prim["h3"] = {"run": False, "reason": why}
        sj.write_text(json.dumps(prim, indent=1, default=str))
        report.write_summary(out, prim)
        log(f"H3 not run: {why}")
        return 0
    r = Runner(out)
    t_start = datetime.now(UTC)
    days = [d.date() for d in r.cal.sessions if date.fromisoformat(p.kalshi_start) <= d.date() <= date.fromisoformat(p.kalshi_end)]
    rows = []
    for i, d in enumerate(days):
        for series, und in p.kalshi_series:
            et_ = rw.kalshi_event_ticker(series, d)
            ms, src = rw.kalshi_event_markets(r.http, et_)
            r.scope[f"events_{src}_{'found' if ms else 'empty'}"] += 1
            for m in rw.kalshi_select(ms):
                rows.append(rw.kalshi_rows(m, series, und, src, candles_fn=lambda *a: rw.kalshi_candles(r.http, *a),
                                           chain_fn=r.opts.contracts, quote_fn=r.opts.quote))
        if (i + 1) % 20 == 0:
            log(f"h3 {i + 1}/{len(days)} days, rows {len(rows)}, scored {sum(map(rw.is_scored, rows))}")
    df = pd.DataFrame(rows)
    sc = df[df.apply(rw.is_scored, axis=1)].copy()
    sc = sc[sc.outcome.isin([0, 1])].copy()
    sc["outcome"] = sc.outcome.astype(int)
    sc = score_frame(sc)
    b = block(sc) if len(sc) else {"n": 0, "clusters": 0}
    v = st.h3_verdict(b["d_B"]) if len(sc) else "INCONCLUSIVE"
    h = dict(run=True, verdict=v, n_rows=int(len(sc)), n_dates=int(sc.res_date.nunique()) if len(sc) else 0, result=b,
             by_series={k: block(g) for k, g in sc.groupby("series")} if len(sc) else {},
             status=df.status.value_counts().to_dict() if len(df) else {}, scope=dict(r.scope),
             costs=dict(k_half_spread_mean=float(sc.k_half_spread.mean()) if len(sc) else None,
                        k_fee_mean=float(sc.k_fee.mean()) if len(sc) else None,
                        opt_half_band_mean=float(sc.opt_half_band.mean()) if len(sc) else None),
             started_utc=t_start.isoformat(), finished_utc=datetime.now(UTC).isoformat(), requests=r.counts(), commit=git_head())
    df.to_csv(out / "kalshi_rows.csv", index=False)
    prim["h3"] = h
    sj.write_text(json.dumps(prim, indent=1, default=str))
    report.write_summary(out, prim)
    report.write_run_log(out, prim, "h3")
    done.write_text(f"h3 finished {h['finished_utc']} verdict {v}\n")
    log(f"H3 VERDICT {v}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h3", action="store_true")
    ap.add_argument("--slice-only", action="store_true")
    a = ap.parse_args(argv)
    return h3(a) if a.h3 else primary(a)


if __name__ == "__main__":
    sys.exit(main())
