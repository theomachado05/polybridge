"""S17 (folder s16_overnight_options): the three trades, the speed curve, spreads and the case files, from the cache
(METHOD.md sections 5 to 9). No network: a quote that was not pulled is "not pulled", never a modelled price.

Run from `research/`:  python -m s16_overnight_options.run
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

from . import config as cfg
from . import engine as eg
from .plan import CACHE, RESEARCH, build_plan
from .pull import NOT_PULLED, Src, observe

RESULTS = RESEARCH / "results" / "s16_overnight_options"
COSTS = (("mid", None), ("1x", 1.0), ("2x", 2.0))
VAR_SAMPLES = {"V0": ("main",), "V1": ("main",), "V2": ("main",), "V3": ("main", "v3extra"), "V4": ("main",)}
MORNING_KEYS = [eg.KEYS[k] for k in cfg.MORNING]
LABEL = {v: k for k, v in eg.KEYS.items()}


def write_csv(path: Path, recs: list[dict]) -> None:
    keys: list[str] = []
    for rec in recs:
        for k in rec:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(recs)


def legs_of(hyp: str, direction: int) -> list[str]:
    return ["call" if direction > 0 else "put"] if hyp == "H-dir" else ["call", "put"]


def make_trades(recs: list[dict], variant: cfg.Variant, samples: tuple[str, ...], hyps=cfg.HYPOTHESES) -> list[dict]:
    """Every trade of a variant: one row per observation (event or control) and hypothesis."""
    ek, xk = eg.KEYS[variant.entry], eg.KEYS[variant.exit]
    out = []
    for r in recs:
        if r["status"] != "ok" or r["sample"] not in samples or (variant.weekends_only and not r["weekend"]):
            continue
        entry, exit_ = eg.legs_at(r, ek), eg.legs_at(r, xk)
        for hyp in hyps:
            if hyp == "H-dir" and r["direction"] == 0:
                continue
            t = {name: eg.trade(hyp, r["direction"], entry, exit_, c) for name, c in COSTS}
            if t["mid"] is None or t["1x"] is None:
                continue
            legs = legs_of(hyp, r["direction"])
            sizes = [r.get(f"{l[0]}_{'asz' if hyp != 'H-rich' else 'bsz'}_{ek}") for l in legs]
            vols = [r.get(f"vol_{l}") for l in legs]
            out.append({
                "variant": variant.id, "hypothesis": hyp, "sample": r["sample"], "kind": r["kind"], "segment": r["segment"], "ticker": r["ticker"],
                "day": r["day"], "event_day": r["event_day"], "weekend": r["weekend"], "x": r["x"], "direction": r["direction"],
                "market": r["market"], "question": r["question"], "legs": "+".join(legs), "expiry": r["expiry"], "strike": r["strike"],
                "dte": r["dte"], "spot_open": r["spot_open"], "entry": variant.entry, "exit": variant.exit,
                "entry_bid": sum(entry[l][0] for l in legs), "entry_ask": sum(entry[l][1] for l in legs),
                "exit_bid": sum(exit_[l][0] for l in legs), "exit_ask": sum(exit_[l][1] for l in legs),
                "entry_spread_share": eg.rel_spread(entry, legs), "exit_spread_share": eg.rel_spread(exit_, legs),
                "ret_mid": t["mid"]["ret"], "ret_1x": t["1x"]["ret"], "ret_2x": t["2x"]["ret"] if t["2x"] else float("nan"),
                "pnl_mid": t["mid"]["pnl"], "pnl_1x": t["1x"]["pnl"], "pnl_2x": t["2x"]["pnl"] if t["2x"] else float("nan"),
                "premium_1x": t["1x"]["premium"], "cost_dollars_1x": t["mid"]["pnl"] - t["1x"]["pnl"],
                "cost_bp_of_underlying_1x": 1e4 * (t["mid"]["pnl"] - t["1x"]["pnl"]) / (100 * r["spot_open"]),
                "size_at_entry_contracts": min(sizes) if all(s is not None for s in sizes) else float("nan"),
                "day_volume_contracts": min(vols) if all(v is not None for v in vols) else float("nan"),
                "underlying_move_bp": 1e4 * (r.get(f"u_{xk}", float("nan")) / r.get(f"u_{ek}", float("nan")) - 1) if r.get(f"u_{ek}") else float("nan"),
            })
    return out


def by_date(tr: list[dict], col: str, key: str = "event_day") -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for t in tr:
        if t[col] == t[col]:
            out.setdefault(t[key], []).append(t[col])
    return out


def pair_diffs(ev: list[dict], ct: list[dict], col: str) -> dict[str, list[float]]:
    """Event minus its matched control, keyed by the event's date; only pairs where both traded."""
    c = {(t["sample"], t["ticker"], t["event_day"]): t[col] for t in ct}
    out: dict[str, list[float]] = {}
    for t in ev:
        k = (t["sample"], t["ticker"], t["event_day"])
        if k in c and t[col] == t[col] and c[k] == c[k]:
            out.setdefault(t["event_day"], []).append(t[col] - c[k])
    return out


def stat_row(ev: list[dict], ct: list[dict], col: str, days: list[str] | None = None) -> dict:
    be, bc, bd = by_date(ev, col), by_date(ct, col), pair_diffs(ev, ct, col)
    m, c, d = eg.boot_mean(be), eg.boot_mean(bc), eg.boot_mean(bd)
    vals = [t[col] for t in ev if t[col] == t[col]]
    row = {"trades": len(vals), "dates": len(be), "tickers": len({t["ticker"] for t in ev}), "mean": m[0], "ci_lo": m[1], "ci_hi": m[2],
           "median": float(np.median(vals)) if vals else float("nan"), "hit_rate": float(np.mean([v > 0 for v in vals])) if vals else float("nan"),
           "control_trades": int(sum(len(v) for v in bc.values())), "control_mean": c[0], "control_ci_lo": c[1], "control_ci_hi": c[2],
           "pairs": int(sum(len(v) for v in bd.values())), "pair_dates": len(bd), "diff_mean": d[0], "diff_ci_lo": d[1], "diff_ci_hi": d[2]}
    if days is not None:
        dr = np.array([float(np.mean(be[x])) if x in be else 0.0 for x in days])
        row.update(eg.book(dr, days))
    return row


def segments(days: list[str]) -> list[tuple[str, list[str]]]:
    return [("IS", [d for d in days if d < cfg.OOS_FROM]), ("OOS", [d for d in days if d >= cfg.OOS_FROM]), ("ALL", days)]


def metrics(trades: list[dict], days: list[str], label: dict) -> list[dict]:
    rows = []
    for hyp in cfg.HYPOTHESES:
        th = [t for t in trades if t["hypothesis"] == hyp]
        if not th:
            continue
        for seg, dl in segments(days):
            ds_ = set(dl)
            ev = [t for t in th if t["kind"] == "event" and t["event_day"] in ds_]
            ct = [t for t in th if t["kind"] == "control" and t["event_day"] in ds_]
            for name, _ in COSTS:
                rows.append({**label, "hypothesis": hyp, "segment": seg, "costs": name, **stat_row(ev, ct, f"ret_{name}", dl),
                             "mean_entry_spread_share": float(np.mean([t["entry_spread_share"] for t in ev])) if ev else float("nan"),
                             "mean_cost_bp_of_underlying_1x": float(np.mean([t["cost_bp_of_underlying_1x"] for t in ev])) if ev else float("nan")})
    return rows


def mid_ret(r: dict, k1: str, k2: str, legs: list[str]) -> float:
    a, b = eg.legs_at(r, k1), eg.legs_at(r, k2)
    if any(a[l] is None or b[l] is None for l in legs):
        return float("nan")
    m1, m2 = sum(sum(a[l]) / 2 for l in legs), sum(sum(b[l]) / 2 for l in legs)
    return (m2 - m1) / m1 if m1 > 0 else float("nan")


def speed_curve(recs: list[dict], sample: str, days: list[str]) -> list[dict]:
    """Mean mid-to-mid return to 15:55 from each morning instant: straddle and directional option; event, control, pairs."""
    rows = []
    ok = [r for r in recs if r["status"] == "ok" and r["sample"] == sample]
    for seg, dl in segments(days):
        ds_ = set(dl)
        for inst, legs_fn in (("straddle", lambda r: ["call", "put"]), ("directional", lambda r: legs_of("H-dir", r["direction"]))):
            spans = [(k, "close") for k in MORNING_KEYS] + [("prev", "0931"), ("prev", "0935")]
            for k1, k2 in spans:
                tr = []
                for r in ok:
                    if r["event_day"] not in ds_ or (inst == "directional" and r["direction"] == 0):
                        continue
                    tr.append({"sample": sample, "ticker": r["ticker"], "event_day": r["event_day"], "kind": r["kind"],
                               "v": mid_ret(r, k1, k2, legs_fn(r))})
                ev, ct = [t for t in tr if t["kind"] == "event"], [t for t in tr if t["kind"] == "control"]
                s = stat_row(ev, ct, "v")
                rows.append({"sample": sample, "segment": seg, "instrument": inst, "from": LABEL[k1], "to": LABEL[k2],
                             **{k: s[k] for k in ("trades", "dates", "mean", "ci_lo", "ci_hi", "median", "control_trades", "control_mean",
                                                  "control_ci_lo", "control_ci_hi", "pairs", "pair_dates", "diff_mean", "diff_ci_lo", "diff_ci_hi")}})
    return rows


def spreads(recs: list[dict], sample: str) -> list[dict]:
    rows = []
    ok = [r for r in recs if r["status"] == "ok" and r["sample"] == sample]
    for key in MORNING_KEYS + ["close", "prev"]:
        for kind in ("event", "control"):
            for inst in ("straddle", "call", "put", "directional"):
                vals = []
                for r in ok:
                    if r["kind"] != kind or (inst == "directional" and r["direction"] == 0):
                        continue
                    legs = ["call", "put"] if inst == "straddle" else ([inst] if inst != "directional" else legs_of("H-dir", r["direction"]))
                    v = eg.rel_spread(eg.legs_at(r, key), legs)
                    if v == v:
                        vals.append(v)
                if vals:
                    rows.append({"sample": sample, "instant": LABEL[key], "kind": kind, "instrument": inst, "n": len(vals),
                                 "median_spread_share": float(np.median(vals)), "mean_spread_share": float(np.mean(vals)),
                                 "p25": float(np.percentile(vals, 25)), "p75": float(np.percentile(vals, 75))})
    return rows


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    plan, ctx, meta = build_plan()
    src = Src(offline=True)
    recs = []
    for it in plan:
        r = observe(src, it, ctx)
        if r["status"] == "ok":
            for leg, key in (("call", "call"), ("put", "put")):
                v = src.volume(r[key], r["day"])
                if v != NOT_PULLED and v is not None:
                    r[f"vol_{leg}"] = v["v"]
            if r.get("u_0935") == r.get("u_0935") and r.get("c_bid_0935") is not None:
                c_mid, p_mid = (r["c_bid_0935"] + r["c_ask_0935"]) / 2, (r["p_bid_0935"] + r["p_ask_0935"]) / 2
                r["parity_gap_share"] = ((c_mid - p_mid) - (r["u_0935"] - r["strike"])) / r["spot_open"]
            r["gap_bp"] = 1e4 * (r["spot_open"] / r["u_prev"] - 1) if r.get("u_prev") == r.get("u_prev") and r.get("u_prev") else float("nan")
        recs.append(r)
    days = ctx.days

    trades: list[dict] = []
    rows: list[dict] = []
    for v in cfg.VARIANTS:
        tv = make_trades(recs, v, VAR_SAMPLES[v.id])
        trades += tv
        rows += metrics(tv, days, {"scope": "main", "variant": v.id, "note": v.note})
    v0 = cfg.VARIANTS[0]
    # ---- case files (exploratory): the primary timing on each case sample
    case_trades = {"oil": [t for t in trades if t["variant"] == "V0" and t["ticker"] in cfg.OIL_TICKERS],
                   "brazil": make_trades(recs, v0, ("brazil",)), "fed": make_trades(recs, v0, ("fed",), hyps=("H-slow", "H-rich"))}
    for name, tv in case_trades.items():
        rows += metrics(tv, days, {"scope": f"case: {name}", "variant": "V0", "note": "exploratory"})
        if name != "oil":
            trades += [{**t, "variant": f"case-{name}"} for t in tv]
    for tk in cfg.FED_TICKERS:
        rows += metrics([t for t in case_trades["fed"] if t["ticker"] == tk], days, {"scope": f"case: fed, {tk}", "variant": "V0", "note": "exploratory"})

    sc = speed_curve(recs, "main", days) + speed_curve(recs, "brazil", days)
    oil = [r for r in recs if r["sample"] == "main" and r["ticker"] in cfg.OIL_TICKERS]
    sc += [{**r, "sample": "main, oil only"} for r in speed_curve(oil, "main", days)]
    sp = spreads(recs, "main") + spreads(recs, "brazil")

    # ---- verdicts on the primary
    verdicts = []
    for hyp in cfg.HYPOTHESES:
        def g(seg, costs, col="mean"):
            x = [r for r in rows if r["scope"] == "main" and r["variant"] == "V0" and r["hypothesis"] == hyp and r["segment"] == seg and r["costs"] == costs]
            return x[0][col] if x else float("nan")
        n = g("OOS", "1x", "trades")
        vd, lines = eg.verdict(int(n) if n == n else 0, g("OOS", "1x"), g("OOS", "1x", "ci_lo"), g("OOS", "2x"), g("IS", "1x"))
        for text, ok, evid in lines:
            verdicts.append({"hypothesis": hyp, "verdict": vd, "line": text, "met": ok, "evidence": evid})

    # ---- the 12 largest moves since 2026-07-01
    main_ev = [r for r in recs if r["sample"] == "main" and r["kind"] == "event" and r["day"] >= cfg.SINCE_DAY]
    top = sorted(main_ev, key=lambda r: (-abs(r["x"]), r["day"], r["ticker"]))[:cfg.TOP_N]
    top_rows = []
    for r in top:
        row = {"day": r["day"], "ticker": r["ticker"], "question": r["question"], "x": r["x"], "direction": r["direction"], "weekend": r["weekend"],
               "status": r["status"]}
        if r["status"] == "ok":
            d = legs_of("H-dir", r["direction"])
            e, x_ = eg.legs_at(r, "0935"), eg.legs_at(r, "close")
            net = eg.trade("H-dir", r["direction"], e, x_, 1.0)
            row.update({"expiry": r["expiry"], "strike": r["strike"], "gap_bp_signed": r["direction"] * r["gap_bp"],
                        "underlying_0935_to_close_bp_signed": r["direction"] * 1e4 * (r["u_close"] / r["u_0935"] - 1),
                        "straddle_prev_to_0931_mid": mid_ret(r, "prev", "0931", ["call", "put"]),
                        "directional_prev_to_0931_mid": mid_ret(r, "prev", "0931", d),
                        "straddle_spread_0931": eg.rel_spread(eg.legs_at(r, "0931"), ["call", "put"]),
                        "straddle_spread_0935": eg.rel_spread(e, ["call", "put"]),
                        "directional_0931_to_close_mid": mid_ret(r, "0931", "close", d),
                        "directional_0935_to_close_mid": mid_ret(r, "0935", "close", d),
                        "directional_0935_to_close_net": net["ret"] if net else float("nan"),
                        "straddle_0935_to_close_mid": mid_ret(r, "0935", "close", ["call", "put"])})
        top_rows.append(row)

    # ---- counts and checks
    def counts(sample):
        out = {}
        for kind in ("event", "control"):
            st: dict[str, int] = {}
            for r in recs:
                if r["sample"] == sample and r["kind"] == kind:
                    st[r["status"]] = st.get(r["status"], 0) + 1
            out[kind] = dict(sorted(st.items()))
        return out

    pg = np.array([abs(r["parity_gap_share"]) for r in recs if r.get("parity_gap_share") == r.get("parity_gap_share") and "parity_gap_share" in r])
    drops: dict[str, dict[str, int]] = {}
    for r in recs:
        if r["sample"] == "main" and r["kind"] == "event" and r["status"] != "ok":
            drops.setdefault(r["ticker"], {}).setdefault(r["status"], 0)
            drops[r["ticker"]][r["status"]] += 1
    state = json.loads((CACHE / "pull_state.json").read_text()) if (CACHE / "pull_state.json").exists() else []
    run_meta = {**meta, "oos_from": cfg.OOS_FROM, "status": {s: counts(s) for s in ("main", "brazil", "fed", "v3extra")},
                "main_event_drops_by_ticker": drops,
                "main_events_ok_by_segment": {seg: sum(1 for r in recs if r["sample"] == "main" and r["kind"] == "event" and r["status"] == "ok"
                                                       and r["segment"] == seg) for seg in ("IS", "OOS")},
                "partial_records": sum(1 for r in recs if r.get("partial")),
                "parity_gap_share_abs": {"n": int(len(pg)), "median": float(np.median(pg)) if len(pg) else None,
                                         "p99": float(np.percentile(pg, 99)) if len(pg) else None, "max": float(pg.max()) if len(pg) else None,
                                         "over_2pct": int((pg > 0.02).sum())},
                "cache_lines": len(src.cache), "pull_runs": state}

    # ---- the daily book of the three primary trades (events only): equity and drawdown
    eq = []
    for hyp in cfg.HYPOTHESES:
        ev = [t for t in trades if t["variant"] == "V0" and t["hypothesis"] == hyp and t["kind"] == "event"]
        for name, _ in COSTS:
            be = by_date(ev, f"ret_{name}")
            dr = np.array([float(np.mean(be[d])) if d in be else 0.0 for d in days])
            cum = np.cumsum(dr)
            dd = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:] - cum
            eq += [{"hypothesis": hyp, "costs": name, "day": d, "segment": "OOS" if d >= cfg.OOS_FROM else "IS", "trades": len(be.get(d, [])),
                    "day_return": float(a), "cumulative": float(b), "drawdown": float(c)} for d, a, b, c in zip(days, dr, cum, dd)]
    write_csv(RESULTS / "equity.csv", eq)

    obs = [{k: v for k, v in r.items()} for r in recs]
    write_csv(RESULTS / "observations.csv", obs)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    write_csv(RESULTS / "speed_curve.csv", sc)
    write_csv(RESULTS / "spreads.csv", sp)
    write_csv(RESULTS / "verdicts.csv", verdicts)
    write_csv(RESULTS / "top_moves.csv", top_rows)
    (RESULTS / "run_meta.json").write_text(json.dumps(run_meta, indent=1, default=str))

    print(json.dumps(run_meta["status"], indent=0))
    print("hyp   var seg costs  n  dates   mean  [ci]              ctrl_n ctrl_mean  pairs diff [ci]            sharpe")
    for x in rows:
        if x["scope"] == "main":
            print(f"{x['hypothesis']:6} {x['variant']} {x['segment']:3} {x['costs']:3} {x['trades']:4d} {x['dates']:4d} {100 * x['mean']:7.1f}% "
                  f"[{100 * x['ci_lo']:6.1f},{100 * x['ci_hi']:6.1f}] {x['control_trades']:5d} {100 * x['control_mean']:7.1f}% {x['pairs']:5d} "
                  f"{100 * x['diff_mean']:6.1f}% [{100 * x['diff_ci_lo']:6.1f},{100 * x['diff_ci_hi']:6.1f}] {x['sharpe']:6.2f}")
    for v in verdicts:
        print(v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
