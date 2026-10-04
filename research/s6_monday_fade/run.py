"""S6: on Monday at 09:45, trade Polymarket toward the options' probability and hold to resolution (METHOD.md).

Run from `research/`:
    python -m s6_monday_fade.run            # calibrate the half-spread, run every variant, check entries against prints
    python -m s6_monday_fade.run --no-prints
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
EVENTS = RESEARCH / "results" / "open_options" / "events.csv"
RAW = RESEARCH / "forward" / "raw" / "thresholds"
RESULTS = RESEARCH / "results" / "s6_monday_fade"
CACHE = HERE / ".cache"
ET = ZoneInfo("America/New_York")


def fee(x: float, c: float = 1.0) -> float:
    return c * cfg.FEE_RATE * x * (1.0 - x) if 0.0 < x < 1.0 else 0.0


def decide(p: float, lo: float, hi: float, h: float, c: float, theta: float) -> tuple[str, float, float] | None:
    """(side, entry price in YES terms, edge against the options' band) or None. Selling YES is buying NO."""
    b = min(max(p - c * h, cfg.PRICE_CLIP[0]), cfg.PRICE_CLIP[1])
    a = min(max(p + c * h, cfg.PRICE_CLIP[0]), cfg.PRICE_CLIP[1])
    sell, buy = b - fee(b, c) - hi, lo - a - fee(a, c)
    if sell >= theta and sell >= buy:
        return "sell YES", b, sell
    if buy >= theta:
        return "buy YES", a, buy
    return None


def pnl_resolution(side: str, entry: float, outcome: float, c: float) -> float:
    """Per contract, held to the result."""
    return (entry - fee(entry, c) - outcome) if side == "sell YES" else (outcome - entry - fee(entry, c))


def pnl_end_of_day(side: str, entry: float, pm_eod: float, h: float, c: float) -> float:
    """Per contract, closed at the end of the reopening day across another half-spread and fee."""
    if side == "sell YES":
        out = min(pm_eod + c * h, cfg.PRICE_CLIP[1])
        return entry - fee(entry, c) - out - fee(out, c)
    out = max(pm_eod - c * h, cfg.PRICE_CLIP[0])
    return out - fee(out, c) - entry - fee(entry, c)


def capital(side: str, entry: float) -> float:
    return cfg.CONTRACTS * (entry if side == "buy YES" else 1.0 - entry)


def calibrate() -> dict:
    """Half-spread and size at the touch of this weekend's recorded Polymarket threshold books (METHOD.md section 2)."""
    s, e = cfg.CALIBRATION_START.timestamp(), cfg.CALIBRATION_END.timestamp()
    lo, hi = cfg.CALIBRATION_MID_RANGE
    half: dict[str, list[float]] = {}
    touch: dict[str, list[float]] = {}
    for f in sorted(RAW.glob("*.jsonl.gz")):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("v") != "pm" or "err" in r or not (s <= r["t"] < e) or not r["b"] or not r["a"]:
                        continue
                    bid, ask = r["b"][0][0], r["a"][0][0]
                    mid = (bid + ask) / 2
                    if lo <= mid <= hi:
                        half.setdefault(r["id"], []).append((ask - bid) / 2)
                        touch.setdefault(r["id"], []).append(min(r["b"][0][1] * bid, r["a"][0][1] * (1 - bid)))
        except (EOFError, OSError):
            continue
    per = [float(np.median(v)) for v in half.values()]
    return {"markets": len(per), "h": float(np.median(per)), "h_p25": float(np.percentile(per, 25)), "h_p75": float(np.percentile(per, 75)),
            "touch_dollars_median": float(np.median([np.median(v) for v in touch.values()])),
            "slice": [cfg.CALIBRATION_START.isoformat(), cfg.CALIBRATION_END.isoformat()]}


def entry_epoch(open_day: str) -> float:
    return pd.Timestamp(f"{open_day} {cfg.ENTRY_TIME_ET}", tz=ET).timestamp()


def verify(prints: list[dict], side: str, entry: float, at: float) -> tuple[int, float]:
    """Prints within the window at a price at least as good as assumed (YES terms). A YES sale needs a taker who sold
    YES at or above our price; a YES purchase needs a taker who bought YES at or below it."""
    n, size = 0, 0.0
    for t in prints:
        ts = t.get("timestamp")
        if ts is None or abs(float(ts) - at) > cfg.PRINT_WINDOW_S:
            continue
        px, sd, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
        if out == "yes":
            ypx, ysd = px, sd
        elif out == "no":
            ypx, ysd = 1.0 - px, ("BUY" if sd == "SELL" else "SELL")
        else:
            continue
        if (side == "sell YES" and ysd == "SELL" and ypx >= entry - 1e-9) or (side == "buy YES" and ysd == "BUY" and ypx <= entry + 1e-9):
            n, size = n + 1, size + float(t.get("size", 0))
    return n, size


def boot(by: dict[str, list[float]]) -> tuple[float, float, float]:
    keys = sorted(k for k, v in by.items() if v)
    allv = [x for k in keys for x in by[k]]
    if not allv:
        return (float("nan"),) * 3
    if len(keys) < 5:
        return (float(np.mean(allv)), float("nan"), float("nan"))
    rng = np.random.default_rng(cfg.BOOT_SEED)
    sums, cnts = np.array([sum(by[k]) for k in keys]), np.array([len(by[k]) for k in keys])
    pick = rng.integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(np.mean(allv)), float(lo), float(hi)


def closure_metrics(pnl: np.ndarray, closures: list[str], K: float, deployed: float, per_year: float) -> dict:
    if K <= 0:
        return {"sharpe": float("nan"), "daily_sharpe": float("nan"), "max_drawdown": float("nan"), "total_return": float("nan"),
                "worst_month": float("nan"), "turnover_ann": float("nan"), "skew": 0.0, "kurtosis": 3.0}
    r = pnl / K
    sd = float(np.std(r, ddof=1)) if len(r) > 2 else 0.0
    e = np.concatenate([[0.0], np.cumsum(r)])
    months: dict[str, float] = {}
    for x, d in zip(r, closures):
        months[d[:7]] = months.get(d[:7], 0.0) + float(x)
    s = pd.Series(r)
    return {"sharpe": float(np.mean(r) / sd * math.sqrt(per_year)) if sd > 0 else float("nan"), "daily_sharpe": float(np.mean(r) / sd) if sd > 0 else float("nan"),
            "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)), "total_return": float(e[-1]),
            "worst_month": min(months.values()) if months else float("nan"), "turnover_ann": deployed / K / max(len(r) / per_year, 1e-9),
            "skew": float(s.skew()) if sd > 0 and len(r) > 2 else 0.0, "kurtosis": float(s.kurt() + 3) if sd > 0 and len(r) > 3 else 3.0}


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


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    cal = calibrate()
    h = cal["h"]
    ev = pd.read_csv(EVENTS)
    valid = ev[ev.status.isin(["event", "f3_move_below_3pt"]) & ev.pm_0945.notna() & ev.oo_lo.notna() & ev.oo_hi.notna() & ev.outcome.notna()].copy()
    all_closures = sorted(ev.open_day.dropna().unique())
    span_years = max((pd.Timestamp(all_closures[-1]) - pd.Timestamp(all_closures[0])).days / 365.0, 1e-9)
    per_year = len(all_closures) / span_years
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(all_closures)))
    oos = set(all_closures[-n_oos:])
    trades = []
    for v in cfg.VARIANTS:
        rows = valid if v.rows == "all valid" else valid[valid.status == "event"]
        if v.exit == "end of day":
            rows = rows[rows.pm_eod.notna()]
        for c in cfg.COST_MULTIPLIERS:
            for r in rows.itertuples():
                d = decide(float(r.pm_0945), float(r.oo_lo), float(r.oo_hi), h, c, v.theta)
                if d is None:
                    continue
                side, entry, edge = d
                p = pnl_resolution(side, entry, float(r.outcome), c) if v.exit == "resolution" else pnl_end_of_day(side, entry, float(r.pm_eod), h, c)
                trades.append({"variant": v.id, "cost_mult": c, "segment": "OOS" if r.open_day in oos else "IS", "closure": r.open_day,
                               "closure_kind": r.closure_kind, "market_id": int(r.market_id), "question": r.question, "underlying": r.underlying,
                               "kind": r.kind, "res_date": r.res_date, "side": side, "pm_0945": float(r.pm_0945), "opt_lo": float(r.oo_lo),
                               "opt_hi": float(r.oo_hi), "entry": entry, "edge_vs_options": edge, "outcome": float(r.outcome),
                               "pnl": cfg.CONTRACTS * p, "pnl_per_contract": p, "capital": capital(side, entry),
                               "cost_per_contract": c * h + fee(entry, c), "pm_closure_move": float(r.d_pm) if r.d_pm == r.d_pm else float("nan"),
                               "prints_in_closure": bool(r.prints_in_closure)})

    # ---- trade-print check for the primary's entries (both cost levels)
    prints: dict[int, list[dict]] = {}
    if "--no-prints" not in sys.argv:
        pt = ds.Throttle(4.0)
        need = sorted({t["market_id"] for t in trades if t["variant"] == cfg.PRIMARY})
        for i, mid in enumerate(need):
            f = CACHE / f"prints_{mid}.json"
            if f.exists():
                prints[mid] = json.loads(f.read_text())
                continue
            try:
                g = ds.get_json(f"{ds.GAMMA}/markets/{mid}", throttle=pt)
                prints[mid] = ds.pm_trades(g["conditionId"], 0, pt, max_pages=1)
            except Exception:
                prints[mid] = []
            f.write_text(json.dumps(prints[mid]))
    for t in trades:
        ps = prints.get(t["market_id"])
        n, size = verify(ps, t["side"], t["entry"], entry_epoch(t["closure"])) if ps else (0, 0.0)
        t["verify_n"], t["verify_size"], t["verified"] = n, size, n > 0
        t["pnl_verified"] = t["pnl"] * min(size, cfg.CONTRACTS) / cfg.CONTRACTS if n else 0.0

    rows_out, eq = [], []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            vt = [t for t in trades if t["variant"] == v.id and t["cost_mult"] == c]
            by_closure_cap = pd.Series([t["capital"] for t in vt], index=[t["closure"] for t in vt]).groupby(level=0).sum() if vt else pd.Series(dtype=float)
            K = float(by_closure_cap.max()) if len(by_closure_cap) else 0.0
            for seg, cl in (("IS", [d for d in all_closures if d not in oos]), ("OOS", [d for d in all_closures if d in oos]), ("ALL", all_closures)):
                st = [t for t in vt if t["closure"] in set(cl)]
                pc = np.array([sum(t["pnl"] for t in st if t["closure"] == d) for d in cl])
                m = closure_metrics(pc, cl, K, sum(t["capital"] for t in st), per_year)
                b = boot({d: [t["pnl"] for t in st if t["closure"] == d] for d in cl})
                ver = [t for t in st if t["verified"]]
                bv = boot({d: [t["pnl_verified"] for t in ver if t["closure"] == d] for d in cl})
                rows_out.append({"segment": seg, "variant": v.id, "theta": v.theta, "rows": v.rows, "exit": v.exit, "cost_mult": c,
                                 "closures": len(cl), "closures_traded": len({t["closure"] for t in st}), "trades": len(st),
                                 "markets": len({t["market_id"] for t in st}), "underlyings": len({t["underlying"] for t in st}),
                                 "sell_yes_share": float(np.mean([t["side"] == "sell YES" for t in st])) if st else float("nan"),
                                 "pnl": float(pc.sum()), "mean_pnl_per_trade": b[0], "ci_lo": b[1], "ci_hi": b[2],
                                 "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"),
                                 "mean_edge_vs_options": float(np.mean([t["edge_vs_options"] for t in st])) if st else float("nan"),
                                 "cost_bp_of_capital": float(np.mean([t["cost_per_contract"] * cfg.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                                 "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)), **m,
                                 "verified_trades": len(ver), "verified_share": len(ver) / len(st) if st else float("nan"),
                                 "pnl_verified": float(sum(t["pnl_verified"] for t in st)), "mean_pnl_per_verified_trade": bv[0],
                                 "ci_lo_verified": bv[1], "ci_hi_verified": bv[2],
                                 "verified_contracts": float(sum(min(t["verify_size"], cfg.CONTRACTS) for t in ver))})
                if seg == "ALL":
                    eq += [{"variant": v.id, "cost_mult": c, "closure": d, "pnl": float(x), "pnl_verified": float(y)}
                           for d, x, y in zip(cl, np.cumsum(pc), np.cumsum([sum(t["pnl_verified"] for t in st if t["closure"] == d) for d in cl]))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in rows_out:
        peers = [x["daily_sharpe"] for x in rows_out if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["closures"], len(cfg.VARIANTS), float(np.var(peers)), row["skew"],
                                                      row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows_out)
    write_csv(RESULTS / "equity.csv", eq)
    (RESULTS / "run_meta.json").write_text(json.dumps({
        "half_spread": cal, "events_rows": int(len(ev)), "valid_rows": int(len(valid)), "event_rows": int((valid.status == "event").sum()),
        "closures": len(all_closures), "closures_per_year": per_year, "first_closure": all_closures[0], "last_closure": all_closures[-1],
        "oos_from": sorted(oos)[0], "oos_closures": n_oos, "markets_checked_for_prints": len(prints),
        "run_seconds": round(time.time() - t_run, 1)}, indent=1))
    print("half-spread:", json.dumps(cal))
    print(f"valid rows {len(valid)}, events {(valid.status == 'event').sum()}, closures {len(all_closures)} ({per_year:.0f} a year), OOS from {sorted(oos)[0]}")
    print("seg var cost trades closures     pnl  per_trade [ci]              hit  sharpe  maxDD  verified ver_pnl ver_per_trade [ci]")
    for x in rows_out:
        print(f"{x['segment']:3} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['closures_traded']:5d} {x['pnl']:9.0f} {x['mean_pnl_per_trade']:7.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] {x['hit_rate']:5.2f} {x['sharpe']:6.2f} {x['max_drawdown']:6.3f} {x['verified_trades']:5d} "
              f"{x['pnl_verified']:8.0f} {x['mean_pnl_per_verified_trade']:7.2f} [{x['ci_lo_verified']:6.2f},{x['ci_hi_verified']:6.2f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
