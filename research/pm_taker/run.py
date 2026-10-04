from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import pm_taker  # noqa: F401
from arbscan import datasrc as ds
from polybridge_research.calendar import TradingCalendar
from polybridge_research.massive import MassiveClient, load_api_key

from . import config as C
from . import core
from .core import ET

UTC = timezone.utc
DATA_API = "https://data-api.polymarket.com/trades"
EVAL_COLS = ["market_id", "tk", "k", "res_date", "ts", "side", "px", "size", "tx", "status", "p_mid", "p_lo", "p_hi",
             "k1", "k2", "stepped"]
TRADE_COLS = ["market_id", "tk", "k", "res_date", "tau", "ts", "side", "px", "size", "tx", "p_mid", "p_lo", "p_hi", "k1", "k2"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_trades(http: ds.Http, cond: str, w0: int, w1: int) -> tuple[list[dict], bool]:
    out: list[dict] = []
    offset = 0
    while offset <= C.TRADES_MAX_OFFSET - C.TRADES_PAGE:
        d = http.get_json(DATA_API, {"market": cond, "start": w0, "end": w1, "limit": C.TRADES_PAGE, "offset": offset},
                          allow_status=(400, 404))
        if not isinstance(d, list) or not d:
            return out, False
        out.extend(d)
        if len(d) < C.TRADES_PAGE:
            return out, False
        offset += C.TRADES_PAGE
    return out, True


class Log:
    def __init__(self, path: Path):
        self.path = path

    def __call__(self, msg: str):
        line = f"- {datetime.now(ET):%Y-%m-%d %H:%M:%S} ET: {msg}"
        print(line, flush=True)
        with self.path.open("a") as f:
            f.write(line + "\n")


class Study:
    def __init__(self, out: Path, cache: Path):
        self.out = out
        self.http = ds.Http(cache / "http")
        key = load_api_key(search_from=C.RESEARCH_DIR, interactive=False)
        self.massive = MassiveClient(key, cache_dir=cache / "massive", session=ds.CountingSession())
        self.cal = TradingCalendar("2025-06-01", "2026-12-31")
        self.sessions = {d.date() for d in self.cal.sessions}
        self.scope: Counter = Counter()
        self.log = Log(out / "RUN_LOG.md")
        self.t0 = time.time()

    def requests(self) -> dict:
        c = dict(self.http.session.counts)
        c["massive"] = sum(self.massive.session.counts.values())
        return c

    def universe(self) -> list[dict]:
        listing = json.loads(C.LISTING_PATH.read_text())
        h = sha256(C.LISTING_PATH)
        if h != C.LISTING_SHA256:
            raise SystemExit(f"listing hash mismatch {h}")
        rows, opts = [], ds.OptionSource(self.massive, date(2026, 10, 3))
        for m in listing:
            r, why = core.frame_row(m, lambda d: d in self.sessions)
            if r is None:
                self.scope[f"drop_{why}"] += 1
                continue
            chain = opts.contracts(r["tk"], r["res_date"])
            if not chain:
                self.scope["drop_no_clean_expiry"] += 1
                continue
            r["expiry"] = r["res_date"]
            r["n_strikes"] = len(chain)
            rows.append(r)
        rows.sort(key=lambda r: (r["res_date"], r["tk"], r["k"], r["id"]))
        self.scope["universe_markets"] = len(rows)
        self.scope["universe_days"] = len({r["res_date"] for r in rows})
        self.scope["universe_ticker_days"] = len({(r["res_date"], r["tk"]) for r in rows})
        self.scope["universe_empty_window"] = sum(r["empty_window"] for r in rows)
        path = self.out / "universe.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        self.log(f"universe frozen: {len(rows)} markets, {self.scope['universe_days']} days, "
                 f"{self.scope['universe_ticker_days']} ticker-days; universe.csv sha256 {sha256(path)}; "
                 f"listing sha256 {h}; drops {dict((k, v) for k, v in self.scope.items() if k.startswith('drop_'))}")
        return rows

    def process(self, rows: list[dict], ew: csv.DictWriter, trades: list[dict], deadline: datetime | None) -> bool:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            groups[(r["res_date"], r["tk"])].append(r)
        for (d, tk), ms in sorted(groups.items()):
            opts = ds.OptionSource(self.massive, date(2026, 10, 3))
            chain = opts.contracts(tk, d)
            for r in ms:
                if deadline is not None and datetime.now(ET) > deadline:
                    return False
                self.scope["markets_processed"] += 1
                if r["empty_window"]:
                    self.scope["markets_empty_window"] += 1
                    continue
                raw, capped = fetch_trades(self.http, r["cond"], r["w0"], r["w1"])
                self.scope["prints_raw"] += len(raw)
                self.scope["markets_offset_cap"] += int(capped)
                kept = core.thin(raw, r["w0"], r["w1"])
                self.scope["prints_kept"] += len(kept)
                self.scope["markets_with_prints"] += int(bool(kept))

                def spread_at(t, r=r):
                    return core.option_spread(chain, float(r["k"]), lambda tkr, s: opts.quote(tkr, datetime.fromtimestamp(s, UTC)), t, r["exp_close"])

                evals, tr = core.evaluate_market(kept, spread_at)
                base = {"market_id": r["id"], "tk": tk, "k": r["k"], "res_date": d}
                for e in evals:
                    self.scope[f"eval_{e['status']}"] += 1
                    ew.writerow({**base, **{c: e.get(c) for c in EVAL_COLS if c in e}})
                for tau, e in tr.items():
                    trades.append({**base, "tau": tau, **{c: e.get(c) for c in TRADE_COLS if c in e and c not in base}})
            self.log(f"{d} {tk}: {len(ms)} markets; trades so far {sum(1 for t in trades if t['tau'] == C.TAU)}; "
                     f"requests {self.requests()}; elapsed {time.time() - self.t0:.0f}s")
        return True


def write_insufficient(out: Path, reason: str, detail: dict, log: Log):
    (out / "stats.json").write_text(json.dumps({"verdict": "INSUFFICIENT", "reason": reason, **detail}, indent=1, default=str))
    (out / "SUMMARY.md").write_text(
        f"# P2 options-anchored Polymarket taker: INSUFFICIENT\n\nVerdict: **INSUFFICIENT** (no claim either way). "
        f"Reason: {reason}. Outcomes were never fetched.\n\n```\n{json.dumps(detail, indent=1, default=str)}\n```\n")
    log(f"INSUFFICIENT: {reason}")
    (out / ".done").write_text(datetime.now(ET).isoformat())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(C.RESULTS_DIR))
    ap.add_argument("--cache", default=str(C.CACHE_DIR))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / ".done").exists():
        raise SystemExit("pm_taker already ran (.done exists); a second run is refused (METHOD.md section 10)")
    st = Study(out, Path(a.cache))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=C.RESEARCH_DIR).stdout.strip()
    if not (out / "RUN_LOG.md").exists():
        (out / "RUN_LOG.md").write_text("# P2 run log\n\n")
    st.log(f"invocation start, commit {commit}, cache {a.cache}")
    rows = st.universe()
    deadline = datetime.fromisoformat(C.FREEZE_DEADLINE_ET).replace(tzinfo=ET)
    kill_rows = [r for r in rows if r["res_date"] <= C.KILL_MAX]
    rest = [r for r in rows if r["res_date"] > C.KILL_MAX]
    trades: list[dict] = []
    ef = (out / "prints_evaluated.csv").open("w", newline="")
    ew = csv.DictWriter(ef, fieldnames=EVAL_COLS)
    ew.writeheader()
    ok = st.process(kill_rows, ew, trades, deadline)
    ef.flush()
    k_tr = [t for t in trades if t["tau"] == C.TAU]
    n_eval = sum(v for k, v in st.scope.items() if k.startswith("eval_"))
    kp = core.kill_projection(len(k_tr), len({t["res_date"] for t in k_tr}), len(kill_rows), len(rows),
                              len({r["res_date"] for r in kill_rows}), len({r["res_date"] for r in rows}),
                              n_eval, st.scope["eval_no_spread"])
    kp.update(kill_trades=len(k_tr), kill_markets=len(kill_rows), kill_evaluated=n_eval,
              kill_no_spread=st.scope["eval_no_spread"], kill_unusable=st.scope["eval_unusable"])
    st.log(f"kill test: {json.dumps(kp, default=str)}")
    (out / "kill_test.json").write_text(json.dumps(kp, indent=1, default=str))
    if not ok:
        ef.close()
        return write_insufficient(out, "time stop before the trade list was frozen", {"scope": dict(st.scope)}, st.log)
    if kp["stop"]:
        ef.close()
        return write_insufficient(out, "day-one kill test: " + ", ".join(kp["reasons"]), {"kill": kp, "scope": dict(st.scope)}, st.log)
    ok = st.process(rest, ew, trades, deadline)
    ef.close()
    if not ok:
        return write_insufficient(out, "time stop before the trade list was frozen", {"scope": dict(st.scope)}, st.log)
    fz = out / "trades_frozen.csv"
    with fz.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_COLS)
        w.writeheader()
        w.writerows(sorted(trades, key=lambda t: (t["tau"], t["res_date"], t["tk"], float(t["k"]), t["market_id"])))
    st.log(f"trade list FROZEN before any outcome fetch: trades_frozen.csv sha256 {sha256(fz)}; "
           f"{sum(1 for t in trades if t['tau'] == C.TAU)} primary trades; prints_evaluated.csv sha256 "
           f"{sha256(out / 'prints_evaluated.csv')}; scope {dict(st.scope)}; requests {st.requests()}")
    from . import report
    report.finish(st, out, rows, commit)


if __name__ == "__main__":
    main()
