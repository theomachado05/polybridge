"""Forward test orchestrator (METHOD.md section 8). Per reopening: frozen universe -> prints and same-instant option
probability -> frozen trade list -> outcomes once resolved. Then cumulative stats. `.done` refuses further runs.

    cd research && .venv/bin/python -m forward_monday.run
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import forward_monday  # noqa: F401
from arbscan import datasrc as ds
from pm_taker import core as P
from pm_taker.run import fetch_trades
from polybridge_research.calendar import TradingCalendar

from . import config as C
from . import core
from .core import ET

UTC = timezone.utc
UNI_COLS = ["id", "cond", "tok", "tk", "k", "kind", "reopening", "res_date", "w0", "w1", "exp_close", "fees_listing",
            "listed", "empty_window", "n_strikes"]
EVAL_COLS = ["market_id", "tk", "k", "res_date", "ts", "side", "px", "size", "tx", "status", "p_mid", "p_lo", "p_hi",
             "k1", "k2", "stepped"]
TRADE_COLS = ["reopening", "market_id", "tk", "k", "res_date", "tau", "ts", "side", "px", "size", "tx", "p_mid", "p_lo",
              "p_hi", "k1", "k2"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sessions() -> set[date]:
    return {d.date() for d in TradingCalendar("2026-01-01", "2026-12-31").sessions}


def listing(http: ds.Http, d0: date, d1: date, closed_states=("false", "true")) -> list[dict]:
    """Gamma equity events resolving in [d0, d1]; metadata only (core.strip_meta), never cached to disk."""
    out: dict[str, dict] = {}
    for closed in closed_states:
        offset = 0
        while True:
            rows = http.get_json(f"{C.GAMMA}/events", {"tag_id": C.GAMMA_TAG, "closed": closed, "limit": 100, "offset": offset,
                                                        "end_date_min": f"{d0}T00:00:00Z", "end_date_max": f"{d1 + timedelta(days=1)}T12:00:00Z",
                                                        "order": "endDate", "ascending": "true"}, cache=False)
            if not rows:
                break
            for e in rows:
                for m in e.get("markets") or []:
                    out[str(m.get("id"))] = core.strip_meta(m, e.get("title") or "")
            if len(rows) < 100:
                break
            offset += 100
    return list(out.values())


def universe(meta: list[dict], d: date, sess: set[date], opts, scope: Counter) -> list[dict]:
    rows = []
    for m in meta:
        r, why = core.select(m, d, sess)
        if r is None:
            scope[f"drop_{why}"] += 1
            continue
        chain = opts.contracts(r["tk"], r["res_date"])
        if not chain:
            scope["drop_no_clean_expiry"] += 1
            continue
        r["n_strikes"] = len(chain)
        rows.append(r)
    rows.sort(key=lambda r: (r["res_date"], r["tk"], r["k"], r["id"]))
    return rows


def write_csv(path: Path, cols: list[str], rows: list[dict]):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class Log:
    def __init__(self, path: Path):
        self.path = path
        if not path.exists():
            path.write_text("# Forward reopening taker run log\n\n")

    def __call__(self, msg: str):
        line = f"- {datetime.now(ET):%Y-%m-%d %H:%M:%S} ET: {msg}"
        print(line, flush=True)
        with self.path.open("a") as f:
            f.write(line + "\n")


class Run:
    def __init__(self, out: Path, cache: Path, now: datetime):
        from polybridge_research.massive import MassiveClient, load_api_key
        self.out, self.now = out, now
        self.http = ds.Http(cache / "http")
        self.massive = MassiveClient(load_api_key(search_from=C.RESEARCH_DIR, interactive=False), cache_dir=cache / "massive",
                                     session=ds.CountingSession())
        self.opts = ds.OptionSource(self.massive, now.astimezone(ET).date())
        self.sess = sessions()
        self.log = Log(out / "RUN_LOG.md")

    def freeze(self, d: date):
        scope: Counter = Counter()
        meta = listing(self.http, d, core.week_end(d, self.sess))
        rows = universe(meta, d, self.sess, self.opts, scope)
        up = self.out / f"universe_{d}.csv"
        write_csv(up, UNI_COLS, rows)
        self.log(f"{d}: universe frozen, {len(rows)} markets, sha256 {sha256(up)}; drops {dict(scope)}")
        evals, trades = [], []
        for r in rows:
            if r["empty_window"]:
                scope["empty_window"] += 1
                continue
            raw, capped = fetch_trades(self.http, r["cond"], r["w0"], r["w1"])
            scope["offset_cap"] += int(capped)
            kept = P.thin(raw, r["w0"], r["w1"])
            scope["prints_kept"] += len(kept)
            chain = self.opts.contracts(r["tk"], r["res_date"])

            def spread_at(t, r=r, chain=chain):
                return P.option_spread(chain, float(r["k"]), lambda tkr, s: self.opts.quote(tkr, datetime.fromtimestamp(s, UTC)),
                                       t, r["exp_close"])

            ev, tr = core.evaluate(kept, spread_at)
            base = {"market_id": r["id"], "tk": r["tk"], "k": r["k"], "res_date": r["res_date"]}
            for e in ev:
                scope[f"eval_{e['status']}"] += 1
                evals.append({**base, **e})
            for tau, e in tr.items():
                trades.append({**e, **base, "reopening": d.isoformat(), "tau": tau})
        ep, tp = self.out / f"prints_evaluated_{d}.csv", self.out / f"trades_frozen_{d}.csv"
        write_csv(ep, EVAL_COLS, evals)
        write_csv(tp, TRADE_COLS, sorted(trades, key=lambda t: (t["tau"], t["res_date"], t["tk"], float(t["k"]), t["market_id"])))
        self.log(f"{d}: trade list FROZEN before any outcome fetch, trades_frozen sha256 {sha256(tp)}, "
                 f"{sum(t['tau'] == C.TAU for t in trades)} primary trades; prints_evaluated sha256 {sha256(ep)}; scope {dict(scope)}")
        (self.out / f".frozen_{d}").write_text(self.now.isoformat())

    def settle(self, d: date) -> bool:
        tr = pd.read_csv(self.out / f"trades_frozen_{d}.csv", dtype={"market_id": str})
        rows, pending = [], 0
        for mid in sorted(set(tr["market_id"])):
            m = self.http.get_json(f"{C.GAMMA}/markets/{mid}", cache=False) or {}
            en, rate, ex = P.fee_params(m)
            y = P.outcome_from_gamma(m)
            sub = tr[tr["market_id"] == mid]
            late = self.now.astimezone(ET).date() > date.fromisoformat(sub["res_date"].iloc[0]) + timedelta(days=C.UNRESOLVED_DROP_DAYS)
            if y is None and not late:
                pending += 1
            for _, t in sub.iterrows():
                rows.append({**t.to_dict(), "y": y, "fee_enabled": en, "fee_rate": rate, "fee_exp": ex})
        if pending:
            self.log(f"{d}: {pending} traded markets not yet resolved; outcomes pending, rerun later")
            return False
        sc = pd.DataFrame(rows, columns=TRADE_COLS + ["y", "fee_enabled", "fee_rate", "fee_exp"])
        sc.to_csv(self.out / f"trades_scored_{d}.csv", index=False)
        self.log(f"{d}: outcomes joined, {len(sc)} trade rows, {int(sc['y'].isna().sum())} unresolved after "
                 f"{C.UNRESOLVED_DROP_DAYS} days (dropped)")
        (self.out / f".done_{d}").write_text(self.now.isoformat())
        return True


def score(sc: pd.DataFrame, window_over: bool) -> dict:
    sc = sc[sc["y"].notna()].copy()
    sc["y"] = sc["y"].astype(int)

    def add(df, tick):
        return df.assign(net=[core.net(r.side, float(r.px), int(r.y), tick, bool(r.fee_enabled), float(r.fee_rate), float(r.fee_exp))
                              for r in df.itertuples()])

    prim = add(sc[sc["tau"].round(4) == round(C.TAU, 4)], C.TICK)
    p = core.summarize(prim["net"], prim["reopening"])
    p["reopenings"] = p.pop("clusters")
    p["verdict"] = core.verdict(p["n"], p["reopenings"], p["ci_lo"], p["ci_hi"], window_over)
    sec = {f"tick_{t:.2f}": core.summarize(add(prim, t)["net"], prim["reopening"]) for t in C.TICK_SECONDARY}
    for tau in C.TAUS:
        if tau != C.TAU:
            x = add(sc[sc["tau"].round(4) == round(tau, 4)], C.TICK)
            sec[f"tau_{tau:.2f}"] = core.summarize(x["net"], x["reopening"])
    sec["ticker_day_cluster"] = core.summarize(prim["net"], prim["tk"] + "|" + prim["reopening"])
    sec["splits"] = {c: {str(k): core.summarize(v["net"], v["reopening"]) for k, v in prim.groupby(c)}
                     for c in ("reopening", "side", "fee_enabled")}
    entry = (prim["px"].where(prim["side"] == "BUY", 1 - prim["px"]) + C.TICK) if len(prim) else pd.Series(dtype=float)
    half = C.CAPACITY_SHARE * prim["size"].astype(float)
    sec["capacity"] = {"shares": float(half.sum()), "dollars_deployed": float((half * entry).sum()),
                       "dollars_pnl": float((half * prim["net"]).sum()) if len(prim) else 0.0}
    return {"verdict": p["verdict"], "primary": p, "secondary": sec}, prim


def summary_md(s: dict, done: list[str], pending: list[str], commit: str) -> str:
    p = s["primary"]
    f = lambda x: "n/a" if x is None else f"{100 * x:+.2f}"
    lines = [f"# Forward reopening taker: {p['verdict']}", "",
             f"Verdict: **{p['verdict']}**. Primary rule (tau 0.05 from 09:45 ET, entry = taker print + 1c, Polymarket fee, hold to "
             f"settlement): mean net P&L {f(p['mean'])} pt per $1 [{f(p['ci_lo'])}, {f(p['ci_hi'])}], 95% reopening-cluster bootstrap "
             f"(10,000 draws), {p['n']} trades over {p['reopenings']} reopenings. Pass rule: lower bound > 0 with >= 30 trades over "
             f">= 4 reopenings; below that the status is RUNNING (window open) or INSUFFICIENT (window over).", "",
             f"Closed reopenings: {', '.join(done) or 'none'}. Pending: {', '.join(pending) or 'none'}.", "",
             "| variant | n | clusters | mean, pt | 95% CI |", "|---|---|---|---|---|"]
    for k, x in s["secondary"].items():
        if isinstance(x, dict) and "n" in x:
            lines.append(f"| {k} | {x['n']} | {x['clusters']} | {f(x['mean'])} | [{f(x['ci_lo'])}, {f(x['ci_hi'])}] |")
    cap = s["secondary"]["capacity"]
    lines += ["", f"Capacity (half of each qualifying print): {cap['shares']:.0f} shares, ${cap['dollars_deployed']:,.0f} deployed, "
              f"${cap['dollars_pnl']:,.0f} net P&L.", "", f"Commit {commit}. Method: `research/forward_monday/METHOD.md`."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.RESULTS_DIR))
    ap.add_argument("--cache", default=str(C.CACHE_DIR))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / ".done").exists():
        raise SystemExit("forward_monday is closed (.done exists); further runs are refused (METHOD.md section 8)")
    now = datetime.now(UTC)
    sess = sessions()
    reo = core.reopenings(sess)
    started = [d for d in reo if now >= P.et(d, (16, 0))]
    if not started:
        raise SystemExit(f"no reopening has finished trading yet (first is {reo[0]} 16:00 ET); nothing fetched")
    run = Run(out, Path(a.cache), now)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=C.RESEARCH_DIR).stdout.strip()
    run.log(f"invocation start, commit {commit}, reopenings started {[str(d) for d in started]}")
    t0 = time.time()
    for d in started:
        if (out / f".done_{d}").exists():
            continue
        if not (out / f".frozen_{d}").exists():
            run.freeze(d)
        run.settle(d)
    done = [str(d) for d in reo if (out / f".done_{d}").exists()]
    pending = [str(d) for d in reo if str(d) not in done]
    files = sorted(out.glob("trades_scored_*.csv"))
    sc = pd.concat([pd.read_csv(p, dtype={"market_id": str, "reopening": str}) for p in files]) if files else \
        pd.DataFrame(columns=TRADE_COLS + ["y", "fee_enabled", "fee_rate", "fee_exp"])
    window_over = not pending
    stats, prim = score(sc, window_over)
    stats.update(closed=done, pending=pending, commit=commit, massive_requests=sum(run.massive.session.counts.values()),
                 http_requests=dict(run.http.session.counts))
    prim.to_csv(out / "trades.csv", index=False)
    (out / "stats.json").write_text(json.dumps(stats, indent=1, default=str))
    (out / "SUMMARY.md").write_text(summary_md(stats, done, pending, commit))
    run.log(f"cumulative: {stats['verdict']}, n {stats['primary']['n']}, reopenings {stats['primary']['reopenings']}, "
            f"elapsed {time.time() - t0:.0f}s")
    if window_over:
        (out / ".done").write_text(now.isoformat())
        run.log("all reopenings closed; .done written")


if __name__ == "__main__":
    main()
