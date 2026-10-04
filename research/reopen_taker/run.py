"""Study A orchestrator: R3 events -> gamma metadata -> taker prints -> frozen trades -> P&L with R3 outcomes. Runs once.

    cd research && .venv/bin/python -m reopen_taker.run
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import datetime

import pandas as pd

import reopen_taker  # noqa: F401
from arbscan import datasrc as ds
from pm_taker import core as pc
from pm_taker.run import fetch_trades

from . import config as C
from . import core
from .core import ET

GAMMA = "https://gamma-api.polymarket.com"
TRADE_COLS = ["market_id", "closure", "open_day", "kind", "tk", "k", "tau", "ts", "side", "px", "size", "tx", "p_mid",
              "fee_enabled", "fee_rate", "fee_exp"]


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    out = C.RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    if (out / ".done").exists():
        raise SystemExit("reopen_taker already ran (.done exists)")
    logp = out / "RUN_LOG.md"
    if not logp.exists():
        logp.write_text("# Study A run log\n\n")

    def log(msg):
        line = f"- {datetime.now(ET):%Y-%m-%d %H:%M:%S} ET: {msg}"
        print(line, flush=True)
        with logp.open("a") as f:
            f.write(line + "\n")

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=C.RESEARCH_DIR).stdout.strip()
    t0 = time.time()
    log(f"start, commit {commit}; events.csv sha256 {sha(C.EVENTS_CSV)}")
    ev = pd.read_csv(C.EVENTS_CSV, dtype={"market_id": str})
    ev = ev[ev["status"] == C.EVENT_STATUS].reset_index(drop=True)
    http = ds.Http(C.CACHE_DIR / "http")
    sc: Counter = Counter(events=len(ev), closures=ev["closure"].nunique())
    trades = []
    for i, r in ev.iterrows():
        if not core.usable(float(r["oo_mid"]), float(r["oo_lo"]), float(r["oo_hi"])):
            sc["drop_option_unusable"] += 1
            continue
        m = http.get_json(f"{GAMMA}/markets/{r['market_id']}") or {}
        cond = m.get("conditionId")
        if not cond:
            sc["drop_no_condition_id"] += 1
            continue
        en, rate, ex = pc.fee_params(m)
        w0, w1 = core.window(r["open_day"])
        raw, capped = fetch_trades(http, cond, w0, w1)
        sc["markets_evaluated"] += 1
        sc["markets_offset_cap"] += int(capped)
        sc["prints_raw"] += len(raw)
        kept = pc.thin(raw, w0, w1)
        sc["prints_kept"] += len(kept)
        for tau, p in core.first_trades(kept, float(r["oo_mid"])).items():
            trades.append({"market_id": r["market_id"], "closure": r["closure"], "open_day": r["open_day"], "kind": r["kind"],
                           "tk": r["underlying"], "k": r["strike"], "tau": tau, "ts": p["ts"], "side": p["side"], "px": p["px"],
                           "size": p["size"], "tx": p["tx"], "p_mid": float(r["oo_mid"]), "fee_enabled": en, "fee_rate": rate,
                           "fee_exp": ex})
        if i % 100 == 0:
            log(f"{i}/{len(ev)} events; trades(tau 0.05) {sum(t['tau'] == C.TAU for t in trades)}; elapsed {time.time() - t0:.0f}s")
    fz = out / "trades_frozen.csv"
    with fz.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_COLS)
        w.writeheader()
        w.writerows(sorted(trades, key=lambda t: (t["tau"], t["open_day"], t["market_id"])))
    log(f"trade list FROZEN before outcomes were joined: trades_frozen.csv sha256 {sha(fz)}; scope {dict(sc)}; "
        f"http requests {dict(http.session.counts)}; failures {len(http.failures)}")

    td = pd.read_csv(fz, dtype={"market_id": str})
    y = ev.drop_duplicates("market_id").set_index("market_id")["outcome"]
    td["y"] = td["market_id"].map(y)
    sc["drop_no_outcome"] = int(td["y"].isna().sum())
    td = td.dropna(subset=["y"]).copy()
    td["y"] = td["y"].astype(int)
    for tick in (C.TICK, *C.TICK_SECONDARY):
        td[f"pnl_t{int(round(tick * 100))}"] = [core.net(a.side, a.px, a.y, tick, bool(a.fee_enabled), a.fee_rate, a.fee_exp)
                                                for a in td.itertuples()]
    td.to_csv(out / "trades.csv", index=False)

    pr = td[td["tau"] == C.TAU]
    prim = core.summarize(pr["pnl_t1"], pr["closure"])
    v = core.verdict(prim["n"], prim["clusters"], prim["lo"], prim["hi"])
    sec = {"tick_0.02_tau_0.05": core.summarize(pr["pnl_t2"], pr["closure"])}
    for tau in C.TAUS_SECONDARY:
        s = td[td["tau"] == tau]
        sec[f"tau_{tau}"] = core.summarize(s["pnl_t1"], s["closure"])
    for side in ("BUY", "SELL"):
        s = pr[pr["side"] == side]
        sec[f"side_{side}"] = core.summarize(s["pnl_t1"], s["closure"])
    for kind in sorted(pr["kind"].unique()):
        s = pr[pr["kind"] == kind]
        sec[f"kind_{kind}"] = core.summarize(s["pnl_t1"], s["closure"])
    entry = pr["px"].where(pr["side"] == "BUY", 1 - pr["px"]) + C.TICK
    cap = {"print_notional_usd": float((pr["size"] * entry).sum()),
           "profit_at_half_print_size_usd": float((C.CAPACITY_SHARE * pr["size"] * pr["pnl_t1"]).sum()),
           "median_print_size_shares": float(pr["size"].median()) if len(pr) else float("nan")}
    stats = {"verdict": v, "primary": prim, "secondary": sec, "capacity": cap, "scope": dict(sc), "commit": commit,
             "fee_enabled_share": float(pr["fee_enabled"].mean()) if len(pr) else float("nan")}
    (out / "stats.json").write_text(json.dumps(stats, indent=1, default=str))

    def f(s):
        return f"{100 * s['mean']:+.2f} pt [{100 * s['lo']:+.2f}, {100 * s['hi']:+.2f}], n = {s['n']} trades, {s['clusters']} closures"
    lines = [f"# Study A: options-anchored taker on reopening days: {v}", "",
             f"Verdict: **{v}**. Primary (tau 0.05, one tick, net of fee): mean net P&L per $1 contract {f(prim)} "
             f"(closure-cluster bootstrap 95% CI).", "",
             "These closures and their PM and option prices were already seen in R3 and the overshoot study; this is a "
             "pre-registered re-analysis at printed trade prices, not a confirmation (METHOD.md section 0).", "",
             "## Secondary (labelled secondary, never change the verdict)", ""]
    lines += [f"- {k}: {f(s)}" if s["n"] else f"- {k}: no trades" for k, s in sec.items()]
    lines += ["", "## Capacity", "",
              f"- Sum of print notional at entry: ${cap['print_notional_usd']:,.0f}; profit at half the print size: "
              f"${cap['profit_at_half_print_size_usd']:,.0f}; median print size {cap['median_print_size_shares']:.0f} shares.", "",
              "## Scope", "", "```", json.dumps(dict(sc), indent=1), "```", "",
              "Caveats: seen closures; copy-the-taker; the 09:45 option probability is stale for later prints; "
              "trades within a closure share the market move; monthly markets tie up capital for weeks."]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    log(f"done: verdict {v}; primary {json.dumps(prim)}; elapsed {time.time() - t0:.0f}s")
    (out / ".done").write_text(datetime.now(ET).isoformat())


if __name__ == "__main__":
    main()
