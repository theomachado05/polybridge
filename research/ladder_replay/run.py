"""Ladder replay runner (METHOD steps 1 to 3). Run from `research/`:  python -m ladder_replay.run [s11|fresh|all]"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config as cfg
from . import replay as rp

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "results" / "ladder_replay"


def pairs_of(bundles: list[dict], kinds=("date", "strike")) -> list[dict]:
    out = []
    for b in bundles:
        if b["kind"] not in kinds:
            continue
        for rich, cheap in b["pairs"]:
            out.append({"pid": f"{rich}>{cheap}", "kind": b["kind"], "bundle": b, "rich": rich, "cheap": cheap,
                        "event": b.get("event_title") or b["event"]})
    return out


def classify(pairs: list[dict], g: dict, name: str) -> list[dict]:
    rows = []
    for p in pairs:
        ok, why = rp.nested(p["kind"], p["bundle"], p["rich"], p["cheap"], g)
        p["nested"], p["why"] = ok, why
        rows.append({"universe": name, "pair": p["pid"], "kind": p["kind"], "event": p["event"], "nested": ok, "reason": why,
                     "q_rich": (g.get(p["rich"]) or {}).get("question"), "q_cheap": (g.get(p["cheap"]) or {}).get("question")})
    return rows


def replay(pairs: list[dict], g: dict, name: str) -> tuple[list[dict], dict]:
    t_lo = datetime.fromisoformat(cfg.WINDOW_START).replace(tzinfo=rp.NY).timestamp()
    t_hi = datetime.fromisoformat(cfg.WINDOW_END).replace(tzinfo=rp.NY).timestamp()
    allc, per_pair_cands, cover = [], {}, []
    for p in pairs:
        ga, gb = g[p["rich"]], g[p["cheap"]]
        pa, pb = rp.prints(ga), rp.prints(gb)
        if pa is None or pb is None:
            continue
        for m, z in ((ga, pa), (gb, pb)):
            cover.append({"universe": name, "market": m["id"], "prints": int(len(z["t"])), "oldest": int(z["t"][0]) if len(z["t"]) else None,
                          "start": rp.ts_of(m.get("startDate")), "truncated": bool(z["truncated"]), "requests": int(z["requests"])})
        hi = min([t_hi] + [x for x in (rp.ts_of(ga.get("closedTime")) if ga.get("closed") else None,
                                        rp.ts_of(gb.get("closedTime")) if gb.get("closed") else None) if x])
        c = rp.candidates(pa, pb, ga, gb, t_lo, hi)
        per_pair_cands[p["pid"]] = c
        allc += [(p["pid"], x) for x in c]
        del pa, pb
    trades = rp.walk(allc)
    byid = {p["pid"]: p for p in pairs}
    rows = []
    for tr in trades:
        p = byid[tr["pair"]]
        r = rp.settle(tr, g[p["rich"]], g[p["cheap"]])
        r.update(universe=name, kind=p["kind"], event=p["event"], rich=p["rich"], cheap=p["cheap"])
        rows.append(r)
    return rows, {"cands": per_pair_cands, "cover": cover}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main(which: str = "all") -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s11 = json.loads((HERE.parent / "s11_bundles" / "bundles.json").read_text())
    fresh = json.loads((HERE / "fresh_universe.json").read_text())
    unis = {"s11": pairs_of(s11["bundles"]), "fresh": pairs_of(fresh["bundles"], ("date",))}
    if which != "all":
        unis = {which: unis[which]}
    ids = sorted({x for ps in unis.values() for p in ps for x in (p["rich"], p["cheap"])})
    t0 = time.time()
    g = rp.gamma_markets(ids)
    print(f"gamma: {len(g)} of {len(ids)} markets, {time.time() - t0:.0f}s", flush=True)
    settle_rows, summary = [], {}
    for name, ps in unis.items():
        settle_rows += classify(ps, g, name)
        nest = [p for p in ps if p["nested"]]
        print(f"{name}: {len(ps)} pairs, nested {len(nest)}", flush=True)
        legs = sorted({x for p in nest for x in (p["rich"], p["cheap"])})
        t0 = time.time()
        rp.prefetch([g[i] for i in legs])
        print(f"{name}: prints for {len(legs)} markets, {time.time() - t0:.0f}s", flush=True)
        rows, aux = replay(nest, g, name)
        write_csv(OUT / f"trades_{name}.csv", rows)
        write_csv(OUT / f"coverage_{name}.csv", aux["cover"])
        m = {"all": rp.metrics(rows), "date": rp.metrics([r for r in rows if r["kind"] == "date"]),
             "strike": rp.metrics([r for r in rows if r["kind"] == "strike"]),
             "s11_IS": rp.metrics([r for r in rows if r["date"] < cfg.S11_OOS_START]),
             "s11_OOS": rp.metrics([r for r in rows if r["date"] >= cfg.S11_OOS_START])}
        summary[name] = {"pairs": len(ps), "nested": len(nest), "reasons": {}, "metrics": m}
        for p in ps:
            summary[name]["reasons"][p["why"]] = summary[name]["reasons"].get(p["why"], 0) + 1
        if name == "s11":
            summary[name]["survival"] = survival(aux["cands"], {p["pid"]: p for p in ps})
        if name == "fresh":
            a = m["all"]
            n, d = a.get("trades", 0), a.get("dates", 0)
            summary[name]["verdict"] = ("INSUFFICIENT" if n < cfg.PASS_MIN_TRADES or d < cfg.PASS_MIN_DATES
                                        else "PASS" if a["ci_lo"] > 0 else "NULL")
        print(name, json.dumps(summary[name], default=str)[:3000], flush=True)
    write_csv(OUT / "settlement_check.csv", settle_rows)
    random.seed(cfg.MANUAL_SAMPLE_SEED)
    sample = random.sample(settle_rows, min(cfg.MANUAL_SAMPLE_N, len(settle_rows)))
    write_csv(OUT / "manual_sample.csv", sample)
    (OUT / f"summary_{which}.json").write_text(json.dumps(summary, indent=1, default=str))
    return 0


def survival(cands: dict, pairs: dict) -> dict:
    rows = [x for x in csv.DictReader((HERE.parent / "results" / "s11_bundles" / "trades.csv").open())
            if x["study"] == "violation" and x["prints"] == "verified" and x["cost_mult"] == "1.0" and x["kind"] != "negrisk"]
    out = {"s11_verified_monotone": len(rows), "pair_not_nested": 0, "no_prints": 0, "survive": 0, "fail": 0, "detail": []}
    for x in rows:
        pid, t = f"{x['rich']}>{x['cheap']}", float(x["t_entry"])
        p = pairs.get(pid)
        if p is None or not p["nested"]:
            out["pair_not_nested"] += 1
            out["detail"].append([pid, x["date"], "not nested" if p else "pair not found"])
            continue
        if pid not in cands:
            out["no_prints"] += 1
            out["detail"].append([pid, x["date"], "no prints"])
            continue
        ok = any(abs(c[0] - t) <= 600 for c in cands[pid])
        out["survive" if ok else "fail"] += 1
        out["detail"].append([pid, x["date"], "survives" if ok else "fails"])
    return out


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:] or ["all"])))
