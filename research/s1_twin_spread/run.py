from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config as cfg
from . import data as ds
from . import engine as en
from .recording import calibrate_half_spreads

RESULTS = Path(__file__).resolve().parents[1] / "results" / "s1_twin_spread"
MARKS = ("mid", "liq", "locked")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, cfg.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_pair(meta: dict, t1: int, h: float, k_max_age: float = cfg.MAX_QUOTE_AGE_S) -> tuple[en.Pair, dict]:
    k = np.load(ds.CACHE / f"k_{meta['ticker']}.npz")
    p = np.load(ds.CACHE / f"p_{meta['pm_id']}.npz")
    start = int(ds._iso(meta["hist_start"]).timestamp())
    deadline = ds._iso(meta["deadline"]).timestamp()
    P = en.build_pair(meta["ticker"], start, t1, k["t"], k["bid"], k["ask"], p["t"], p["p"], deadline, h,
                      meta["kalshi_fee_multiplier"], meta["pm_fee_rate"] if meta["pm_fees_enabled"] else 0.0,
                      meta["pm_fee_exponent"], k_max_age)
    return P, {"k_t": k["t"], "p_t": p["t"]}


def coverage(P: en.Pair) -> dict:
    both = ~np.isnan(P.kb) & ~np.isnan(P.pm)
    first = int(P.t[np.argmax(both)]) if both.any() else None
    return {"minutes": int(len(P.t)), "kalshi_share": float(np.mean(~np.isnan(P.kb))),
            "pm_share": float(np.mean(~np.isnan(P.pm))), "both_share": float(np.mean(both)), "first_both": first}


def seg_index(P: en.Pair, start: int, end: int) -> tuple[int, int]:
    return int(np.searchsorted(P.t, start, "left")), int(np.searchsorted(P.t, end, "left"))


def age_at(ts: np.ndarray, t: int) -> float:
    j = np.searchsorted(ts, t, "right") - 1
    return float(t - ts[j]) if j >= 0 else float("nan")


def verify_print(prints: list[dict], tr: en.Trade, window: float = cfg.PRINT_WINDOW_S) -> tuple[int, float]:
    n, size = 0, 0.0
    for t in prints:
        ts = t.get("timestamp")
        if ts is None or abs(float(ts) - tr.t_in) > window:
            continue
        px, side, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
        if out == "yes":
            ypx, yside = px, side
        elif out == "no":
            ypx, yside = 1.0 - px, ("BUY" if side == "SELL" else "SELL")
        else:
            continue
        if (tr.dir == "A" and yside == "BUY" and ypx <= tr.pm_px + 1e-9) or \
           (tr.dir == "B" and yside == "SELL" and ypx >= tr.pm_px - 1e-9):
            n, size = n + 1, size + float(t.get("size", 0))
    return n, size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, required=True, help="3-month Treasury yield as a fraction, e.g. 0.0417")
    ap.add_argument("--rate-date", default="")
    ap.add_argument("--skip-prints", action="store_true")
    a = ap.parse_args()
    r = a.rate
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    pull = json.loads((ds.CACHE / "pull_meta.json").read_text())
    t1 = int(ds._iso(pull["t1"]).timestamp())
    calib = calibrate_half_spreads()
    log: list[str] = []

    usable, pair_rows = [], []
    for meta in pull["pairs"]:
        c = calib.get(meta["token"])
        row = {"ticker": meta["ticker"], "question": meta["question"], "deadline": meta["deadline"],
               "hist_start": meta["hist_start"], "kalshi_candles": meta["kalshi_candles"], "pm_points": meta["pm_points"],
               "kalshi_fee_type": meta["kalshi_fee_type"], "kalshi_fee_multiplier": meta["kalshi_fee_multiplier"],
               "pm_fee_rate": meta["pm_fee_rate"] if meta["pm_fees_enabled"] else 0.0,
               "h": c["h"] if c else float("nan"), "calib_two_sided_share": c["two_sided_share"] if c else float("nan"),
               "calib_snapshots": c["snapshots"] if c else 0, "used": False, "reason": ""}
        if not c or not c["usable"]:
            row["reason"] = "Polymarket book one-sided or empty in more than half of the calibration snapshots"
        elif meta["kalshi_candles"] == 0 or meta["pm_points"] == 0:
            row["reason"] = "no history on one venue"
        else:
            P, _ = load_pair(meta, t1, c["h"])
            cov = coverage(P)
            row.update(cov)
            P6, _ = load_pair(meta, t1, c["h"], cfg.QUOTE_RULES[1][1])
            row["both_share_kalshi_carry_6h"] = coverage(P6)["both_share"]
            del P6
            if cov["first_both"] is None:
                row["reason"] = "the two venues never have a fresh quote in the same minute"
            else:
                row["used"] = True
                usable.append(meta)
        pair_rows.append(row)
    for f in pull.get("failures", []):
        pair_rows.append({"ticker": f["ticker"], "used": False, "reason": f"pull failed: {f['error']}"})
    t0 = min(x["first_both"] for x in pair_rows if x.get("used"))
    split = int((t0 + (1 - cfg.OOS_FRACTION) * (t1 - t0)) // 60 * 60)
    segs = {"IS": (t0, split), "OOS": (split, t1 + 60)}
    marks = {s: en.day_marks(a_, min(b_, t1)) for s, (a_, b_) in segs.items()}
    log.append(f"history window {iso(t0)} to {iso(t1)}; split {iso(split)}; {len(usable)} pairs used")

    runs = [(q, v, c, s) for q, _ in cfg.QUOTE_RULES for v in cfg.VARIANTS for c in cfg.COST_MULTIPLIERS for s in segs]
    equity = {(q, v.id, c, s, m): np.zeros(len(marks[s])) for q, v, c, s in runs for m in MARKS}
    trades: list[dict] = []
    pm_start = {m["ticker"]: ds._iso(m["pm_start"]).timestamp() for m in usable}
    signal_minutes: list[dict] = []
    raw_ts: dict[str, dict] = {}
    for meta, (q, k_age) in ((m_, q_) for m_ in usable for q_ in cfg.QUOTE_RULES):
        P, ts = load_pair(meta, t1, calib[meta["token"]]["h"], k_age)
        raw_ts[meta["ticker"]] = ts
        for c in cfg.COST_MULTIPLIERS:
            L = en.legs(P, c, r, cfg.CLIP_HISTORY)
            with np.errstate(invalid="ignore"):
                for s, (sa, sb) in segs.items():
                    i0, i1 = seg_index(P, sa, sb)
                    if i1 > i0:
                        both = int(np.sum(~np.isnan(L.edge["A"][i0:i1])))
                        signal_minutes.append({"quote_rule": q, "ticker": P.key, "segment": s, "cost_mult": c, "minutes_both_fresh": both,
                                               **{f"minutes_edge{d}_ge_{int(th * 100)}c": int(np.sum(L.edge[d][i0:i1] >= th))
                                                  for d in "AB" for th in (0.0, 0.01, 0.02, 0.03)},
                                               "median_gap_mid": float(np.nanmedian((P.pm - (P.kb + P.ka) / 2)[i0:i1])) if both else float("nan"),
                                               "mean_abs_gap_mid": float(np.nanmean(np.abs(P.pm - (P.kb + P.ka) / 2)[i0:i1])) if both else float("nan")})
            for v in cfg.VARIANTS:
                for s, (sa, sb) in segs.items():
                    i0, i1 = seg_index(P, sa, sb)
                    if i1 - i0 < 2:
                        continue
                    for tr in en.simulate(P, L, v.theta, v.exit_on, i0, i1, cfg.CLIP_HISTORY):
                        idx = np.clip((marks[s] - P.t[0]) // 60, 0, i1 - 1).astype(int)
                        path = {m: np.array([en.pnl_at(P, L, tr, int(i), c, r, m) for i in idx]) for m in MARKS}
                        for m in MARKS:
                            equity[(q, v.id, c, s, m)] += path[m]
                        d = asdict(tr)
                        d["_path"] = path["mid"]
                        d["pm_market_age_h"] = (tr.t_in - pm_start[P.key]) / 3600.0
                        d.update(quote_rule=q, variant=v.id, cost_mult=c, segment=s, entry_utc=iso(tr.t_in),
                                 exit_utc=iso(tr.t_out) if tr.t_out else "", capital=tr.qty * tr.cost_in,
                                 pnl_mid=path["mid"][-1], pnl_liq=path["liq"][-1], pnl_locked=path["locked"][-1],
                                 fees_bp=tr.fees_in / tr.cost_in * 1e4, spread_bp=tr.spread_in / tr.cost_in * 1e4,
                                 carry_bp=tr.carry_in / tr.cost_in * 1e4, edge_bp=tr.edge_in / tr.cost_in * 1e4,
                                 pm_hist_price=float(P.pm[tr.i_in]), kalshi_bid=float(P.kb[tr.i_in]),
                                 kalshi_ask=float(P.ka[tr.i_in]), tau_days=float(P.tau[tr.i_in] * 365),
                                 kalshi_quote_age_s=age_at(ts["k_t"], tr.t_in), pm_point_age_s=age_at(ts["p_t"], tr.t_in),
                                 traded=tr.qty * tr.cost_in + (tr.qty * tr.liq_out if tr.liq_out is not None else 0.0))
                        trades.append(d)
        del P, L

    metas = {m["ticker"]: m for m in usable}
    prints: dict[str, list[dict]] = {}
    if not a.skip_prints:
        pt = ds.Throttle(4.0)
        for tk in sorted({d["pair"] for d in trades}):
            oldest = min(d["t_in"] for d in trades if d["pair"] == tk) - cfg.PRINT_WINDOW_S
            try:
                prints[tk] = ds.pm_trades(metas[tk]["condition_id"], oldest, pt)
            except Exception as e:
                prints[tk] = []
                log.append(f"trade prints failed for {tk}: {e!r}")
            reach = min((float(x["timestamp"]) for x in prints[tk]), default=float("nan"))
            log.append(f"prints {tk}: {len(prints[tk])} trades, oldest {iso(reach) if reach == reach else 'none'}, needed back to {iso(oldest)}")
    for d in trades:
        ps = prints.get(d["pair"], [])
        reach = min((float(x["timestamp"]) for x in ps), default=float("inf"))
        tr = en.Trade(**{k: d[k] for k in en.Trade.__dataclass_fields__})
        n, size = verify_print(ps, tr) if ps else (0, 0.0)
        d["prints_reach_entry"] = bool(reach <= d["t_in"] - cfg.PRINT_WINDOW_S)
        d["verify_n"], d["verify_size"], d["verified"] = n, size, n > 0
        share = min(size, d["qty"]) / d["qty"] if n else 0.0
        d["verified_qty"] = share * d["qty"]
        d["pnl_mid_verified"] = d["pnl_mid"] * share
        d["pnl_locked_verified"] = d["pnl_locked"] * share
        d["edge_at_entry_verified"] = d["edge_in"] * d["verified_qty"]
        key = (d["quote_rule"], d["variant"], d["cost_mult"], d["segment"], "mid_verified")
        equity.setdefault(key, np.zeros(len(marks[d["segment"]])))
        equity[key] += d.pop("_path") * share

    rows = []
    for q, v, c, s in runs:
        tt = [d for d in trades if (d["quote_rule"], d["variant"], d["cost_mult"], d["segment"]) == (q, v.id, c, s)]
        m = en.metrics(equity[(q, v.id, c, s, "mid")], marks[s], cfg.CAPITAL_HISTORY, sum(d["traded"] for d in tt), segs[s][0])
        by_mid, by_locked = {}, {}
        for d in tt:
            by_mid.setdefault(d["pair"], []).append(d["pnl_mid"])
            by_locked.setdefault(d["pair"], []).append(d["pnl_locked"])
        bm = en.pair_bootstrap(by_mid, cfg.N_BOOT, cfg.BOOT_SEED)
        bl = en.pair_bootstrap(by_locked, cfg.N_BOOT, cfg.BOOT_SEED)
        ver = [d for d in tt if d["verified"]]
        mv = en.metrics(equity.get((q, v.id, c, s, "mid_verified"), np.zeros(len(marks[s]))), marks[s], cfg.CAPITAL_HISTORY,
                        sum(d["traded"] * d["verified_qty"] / d["qty"] for d in tt), segs[s][0])
        bv = en.pair_bootstrap({k: [d["pnl_mid_verified"] for d in ver if d["pair"] == k] for k in {d["pair"] for d in ver}},
                               cfg.N_BOOT, cfg.BOOT_SEED)
        rows.append({
            "quote_rule": q, "segment": s, "variant": v.id, "theta": v.theta, "exit_on": v.exit_on, "cost_mult": c,
            "start": iso(segs[s][0]), "end": iso(min(segs[s][1], t1)), "entries": len(tt),
            "pairs_traded": len({d["pair"] for d in tt}), "exits": sum(1 for d in tt if d["t_out"]),
            "open_at_end": sum(1 for d in tt if not d["t_out"]),
            "pnl_mid": float(equity[(q, v.id, c, s, "mid")][-1]), "pnl_liq": float(equity[(q, v.id, c, s, "liq")][-1]),
            "pnl_locked": float(equity[(q, v.id, c, s, "locked")][-1]),
            "mean_pnl_per_trade_mid": bm[0], "ci_lo_mid": bm[1], "ci_hi_mid": bm[2],
            "mean_pnl_per_trade_locked": bl[0], "ci_lo_locked": bl[1], "ci_hi_locked": bl[2],
            "sharpe_mid": m["sharpe"], "ann_return": m["ann_return"], "ann_vol": m["ann_vol"],
            "max_drawdown": m["max_drawdown"], "worst_month": m["worst_month"], "worst_month_label": m["worst_month_label"],
            "turnover_ann": m["turnover_ann"], "days": m["days"], "daily_sharpe": m["daily_sharpe"], "skew": m["skew"],
            "kurtosis": m["kurtosis"],
            "mean_edge_bp": float(np.mean([d["edge_bp"] for d in tt])) if tt else float("nan"),
            "fees_bp": float(np.mean([d["fees_bp"] for d in tt])) if tt else float("nan"),
            "spread_bp": float(np.mean([d["spread_bp"] for d in tt])) if tt else float("nan"),
            "carry_bp": float(np.mean([d["carry_bp"] for d in tt])) if tt else float("nan"),
            "capital_base": cfg.CAPITAL_HISTORY, "max_capital_locked": float(sum(d["capital"] for d in tt if not d["t_out"])),
            "verified_entries": len(ver), "verified_share": len(ver) / len(tt) if tt else float("nan"),
            "prints_reach_share": float(np.mean([d["prints_reach_entry"] for d in tt])) if tt else float("nan"),
            "pnl_mid_verified": float(sum(d["pnl_mid_verified"] for d in tt)),
            "pnl_locked_verified": float(sum(d["pnl_locked_verified"] for d in tt)),
            "edge_at_entry_verified": float(sum(d["edge_at_entry_verified"] for d in tt)),
            "verified_pairs": len({d["pair"] for d in ver}), "verified_contracts": float(sum(d["verified_qty"] for d in tt)),
            "sharpe_mid_verified": mv["sharpe"], "max_drawdown_verified": mv["max_drawdown"],
            "mean_pnl_per_verified_trade": bv[0], "ci_lo_verified": bv[1], "ci_hi_verified": bv[2],
            "entries_pm_market_under_48h": sum(1 for d in tt if d["pm_market_age_h"] < 48),
            "entries_pm_price_45_55": sum(1 for d in tt if 0.45 <= d["pm_hist_price"] <= 0.55),
            "median_abs_gap_at_entry": float(np.median([abs(d["pm_hist_price"] - (d["kalshi_bid"] + d["kalshi_ask"]) / 2) for d in tt])) if tt else float("nan"),
        })
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from polybridge_research.stats import deflated_sharpe
    for row in rows:
        peers = [x["daily_sharpe"] for x in rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"])
                 and x["daily_sharpe"] == x["daily_sharpe"]]
        if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1:
            row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["days"],
                                                          len(cfg.VARIANTS) * len(cfg.QUOTE_RULES),
                                                          float(np.var(peers)), row["skew"], row["kurtosis"])
        else:
            row["deflated_sharpe_prob"] = float("nan")

    def write_csv(name: str, recs: list[dict]) -> None:
        keys: list[str] = []
        for rec in recs:
            for k in rec:
                if k not in keys:
                    keys.append(k)
        with open(RESULTS / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(recs)

    for d in trades:
        d.pop("_path", None)
    write_csv("metrics_history.csv", rows)
    write_csv("trades.csv", sorted(trades, key=lambda d: (d["quote_rule"], d["variant"], d["cost_mult"], d["segment"], d["t_in"])))
    write_csv("pairs.csv", pair_rows)
    write_csv("signal_minutes.csv", signal_minutes)
    eq_rows = []
    for (q, vid, c, s, m), e in equity.items():
        for t, x in zip(marks[s], e):
            eq_rows.append({"quote_rule": q, "variant": vid, "cost_mult": c, "segment": s, "mark": m, "utc": iso(int(t)),
                            "t": int(t), "pnl": float(x)})
    write_csv("equity_history.csv", eq_rows)
    meta_out = {"t0": iso(t0), "split": iso(split), "t1": iso(t1), "rate": r, "rate_source": "Alpha Vantage TREASURY_YIELD, 3-month constant maturity (FRED DGS3MO)",
                "rate_date": a.rate_date, "pairs_in_universe": cfg.N_PAIRS, "pairs_used": len(usable),
                "capital_base": cfg.CAPITAL_HISTORY, "clip": cfg.CLIP_HISTORY, "pull_seconds": pull.get("seconds"),
                "pull_failures": pull.get("failures", []), "run_seconds": round(time.time() - t_run, 1),
                "calibration": {"start": cfg.CALIBRATION_START.isoformat(), "end": cfg.CALIBRATION_END.isoformat()},
                "log": log}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta_out, indent=1))

    print(f"window {iso(t0)} .. {iso(split)} .. {iso(t1)}; pairs used {len(usable)}/{cfg.N_PAIRS}; {time.time() - t_run:.0f}s")
    print("rule            seg  var cost entries pairs exits  pnl_mid  pnl_liq pnl_locked  sharpe   maxDD  verified  ver_pnl_mid ver_edge_entry ver_sharpe")
    for x in rows:
        print(f"{x['quote_rule']:15} {x['segment']:4} {x['variant']} {x['cost_mult']:.0f}x {x['entries']:7d} {x['pairs_traded']:5d} {x['exits']:5d} "
              f"{x['pnl_mid']:8.2f} {x['pnl_liq']:8.2f} {x['pnl_locked']:9.2f} {x['sharpe_mid']:7.2f} {x['max_drawdown']:7.4f} "
              f"{x['verified_entries']:4d}/{x['entries']:<4d} {x['pnl_mid_verified']:10.2f} {x['edge_at_entry_verified']:12.2f} {x['sharpe_mid_verified']:9.2f}")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
