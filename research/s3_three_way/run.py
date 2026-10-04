from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import kalshi_fee, pm_fee

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ARB = RESEARCH / "results" / "arb" / "arb_gaps.csv"
RESULTS = RESEARCH / "results" / "s3_three_way"
CACHE = HERE / ".cache"
PM_FEE_RATE, PM_FEE_EXP = 0.04, 1.0
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, cfg.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_ticker(date: str) -> str:
    y, m, d = date.split("-")
    return f"{cfg.KALSHI_SERIES}-{y[2:]}{MONTHS[int(m) - 1]}{d}H1600"


def cached(name: str, fn):
    f = CACHE / name
    if f.exists():
        return json.loads(f.read_text())
    out = fn()
    f.write_text(json.dumps(out))
    return out


def closes(client, ticker: str, start: str, end: str) -> dict[str, float]:
    rows = client.get_all(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}", {"adjusted": "false", "sort": "asc", "limit": 50000})
    return {datetime.fromtimestamp(r["t"] / 1000, cfg.UTC).strftime("%Y-%m-%d"): float(r["c"]) for r in rows}


def ratio_for(date: str, spx: dict, spy: dict) -> tuple[str, float] | None:
    prior = sorted(d for d in spx if d < date and d in spy)
    return (prior[-1], spx[prior[-1]] / spy[prior[-1]]) if prior else None


def kalshi_event(date: str, kt) -> list[dict]:
    ev = event_ticker(date)
    return cached(f"markets_{ev}.json", lambda: ds.get_json(f"{ds.KALSHI}/markets", {"event_ticker": ev, "limit": 1000},
                                                            throttle=kt).get("markets", []))


def kalshi_settlement(markets: list[dict]) -> float | None:
    vals = {m.get("expiration_value") for m in markets if m.get("expiration_value")}
    try:
        return float(vals.pop()) if len(vals) == 1 else None
    except ValueError:
        return None


def map_strike(k_spy: float, ratio: float, listed: list[float]) -> tuple[float, float] | None:
    if not listed:
        return None
    target = ratio * k_spy
    best = min(listed, key=lambda s: abs(s - target))
    return (best, best - target) if abs(best - target) <= cfg.STRIKE_TOLERANCE else None


def kalshi_quote(candles: list[dict], snap: float) -> dict | None:
    best = None
    for c in candles:
        t = c.get("end_period_ts")
        if t is None or t > snap:
            continue
        if best is None or t > best["end_period_ts"]:
            best = c
    if best is None or snap - best["end_period_ts"] > cfg.KALSHI_MAX_AGE_S:
        return None
    try:
        bid, ask = float(best["yes_bid"]["close_dollars"]), float(best["yes_ask"]["close_dollars"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (bid > 0 and ask < 1 and ask >= bid):
        return None
    return {"kb": bid, "ka": ask, "k_age_s": snap - best["end_period_ts"]}


def widen(bid: float, ask: float, c: float) -> tuple[float, float]:
    mid, h = (bid + ask) / 2, (ask - bid) / 2
    return max(mid - c * h, 0.001), min(mid + c * h, 0.999)


def evaluate(s: dict, v: cfg.Variant, c: float, r: float, k_mult: float, qty: float = cfg.CLIP_HISTORY) -> dict | None:
    pb, pa = widen(s["pb"], s["pa"], c)
    kb, ka = widen(s["kb"], s["ka"], c)
    lo, hi = s["lo"], s["hi"]
    pm_state = "rich" if pb > hi else "cheap" if pa < lo else "agrees"
    k_state = "rich" if kb > hi else "cheap" if ka < lo else "agrees"
    outlier = None
    if (pm_state != "agrees") != (k_state != "agrees"):
        outlier = ("pm", pm_state) if pm_state != "agrees" else ("kalshi", k_state)
    carry = c * r * s["tau_years"]

    def fk(p):
        return c * float(kalshi_fee(p, qty, k_mult))

    def fp(p):
        return c * float(pm_fee(p, PM_FEE_RATE, PM_FEE_EXP))

    base = {"pm_state": pm_state, "k_state": k_state, "outlier": outlier[0] if outlier else "", "outlier_side": outlier[1] if outlier else ""}
    if v.trade == "lock":
        cost = {"A": pa + fp(pa) + (1 - kb) + fk(1 - kb), "B": ka + fk(ka) + (1 - pb) + fp(1 - pb)}
        edge = {d: 1 - cost[d] * (1 + carry) for d in "AB"}
        if v.outlier_filter:
            if outlier is None:
                return None
            d = "B" if outlier in (("pm", "rich"), ("kalshi", "cheap")) else "A"
        else:
            d = max("AB", key=lambda x: edge[x])
        if edge[d] < v.theta:
            return None
        y_pm, y_k = s["y_pm"], s["y_k"]
        payoff = (y_pm + (1 - y_k)) if d == "A" else (y_k + (1 - y_pm))
        fees = (fp(pa) + fk(1 - kb)) if d == "A" else (fk(ka) + fp(1 - pb))
        return {**base, "dir": d, "edge": edge[d], "cost": cost[d], "fees": fees, "payoff": payoff,
                "pnl": qty * (payoff - cost[d] * (1 + carry)), "pm_px": pa if d == "A" else pb, "split": y_pm != y_k}
    if outlier is None:
        return None
    venue, side = outlier
    bid, ask, fee, y = (pb, pa, fp, s["y_pm"]) if venue == "pm" else (kb, ka, fk, s["y_k"])
    if side == "cheap":
        cost, edge, payoff, d = ask + fee(ask), lo - ask - fee(ask), y, f"buy {venue} YES"
    else:
        cost, edge, payoff, d = (1 - bid) + fee(1 - bid), bid - hi - fee(1 - bid), 1 - y, f"buy {venue} NO"
    if edge < v.theta:
        return None
    return {**base, "dir": d, "edge": edge, "cost": cost, "fees": fee(ask) if side == "cheap" else fee(1 - bid), "payoff": payoff,
            "pnl": qty * (payoff - cost * (1 + carry)), "pm_px": (pa if side == "cheap" else pb) if venue == "pm" else float("nan"),
            "split": False}


def verify(prints: list[dict], t: dict, snap: float) -> tuple[int, float]:
    if t["pm_px"] != t["pm_px"]:
        return 0, 0.0
    buy_yes = t["dir"] in ("A", "buy pm YES")
    n, size = 0, 0.0
    for p in prints:
        ts = p.get("timestamp")
        if ts is None or abs(float(ts) - snap) > cfg.PRINT_WINDOW_S:
            continue
        px, side, out = float(p["price"]), str(p.get("side", "")).upper(), str(p.get("outcome", "")).lower()
        if out == "yes":
            ypx, yside = px, side
        elif out == "no":
            ypx, yside = 1 - px, ("BUY" if side == "SELL" else "SELL")
        else:
            continue
        if (buy_yes and yside == "BUY" and ypx <= t["pm_px"] + 1e-9) or (not buy_yes and yside == "SELL" and ypx >= t["pm_px"] - 1e-9):
            n, size = n + 1, size + float(p.get("size", 0))
    return n, size


def day_metrics(pnl_by_day: np.ndarray, capital: float, traded: float) -> dict:
    if capital <= 0:
        return {"sharpe": float("nan"), "max_drawdown": float("nan"), "total_return": float("nan"), "turnover_ann": float("nan")}
    r = pnl_by_day / capital
    sd = float(np.std(r, ddof=1)) if len(r) > 2 else 0.0
    e = np.concatenate([[0.0], np.cumsum(r)])
    return {"sharpe": float(np.mean(r) / sd * math.sqrt(cfg.DAYS_PER_YEAR)) if sd > 0 else float("nan"),
            "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)), "total_return": float(e[-1]),
            "turnover_ann": traded / capital / max(len(r) / cfg.DAYS_PER_YEAR, 1e-9)}


def date_bootstrap(by_date: dict[str, list[float]]) -> tuple[float, float, float]:
    keys = sorted(k for k, v in by_date.items() if v)
    allv = [x for k in keys for x in by_date[k]]
    if not allv:
        return (float("nan"),) * 3
    if len(keys) < 3:
        return (float(np.mean(allv)), float("nan"), float("nan"))
    rng = np.random.default_rng(cfg.BOOT_SEED)
    sums, cnts = np.array([sum(by_date[k]) for k in keys]), np.array([len(by_date[k]) for k in keys])
    pick = rng.integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(np.mean(allv)), float(lo), float(hi)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.massive import MassiveClient, load_api_key

    RESULTS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    arb = pd.read_csv(ARB, low_memory=False)
    pm = arb[(arb.venue == "polymarket") & (arb.underlying == cfg.PM_UNDERLYING) & (arb.live == False)  # noqa: E712
             & (arb.status == "scored") & (arb.clean == True) & (arb.snapshot == cfg.SNAPSHOT)].copy()  # noqa: E712
    dates = sorted(pm.res_date.unique())
    log.append(f"Polymarket SPY rows at {cfg.SNAPSHOT}: {len(pm)} on {len(dates)} dates ({dates[0]} to {dates[-1]})")

    client = MassiveClient(load_api_key(search_from=RESEARCH), cache_dir=RESEARCH / ".massive_cache")
    spy = closes(client, "SPY", "2026-08-03", dates[-1])
    divs = client.get_all("/v3/reference/dividends", {"ticker": "SPY", "ex_dividend_date.gte": "2026-08-01", "ex_dividend_date.lte": dates[-1]})
    ex_dates = sorted({d["ex_dividend_date"] for d in divs})
    log.append(f"SPY ex-dividend dates in range: {ex_dates}")

    kt, pt = ds.Throttle(3.0), ds.Throttle(3.0)
    sessions = sorted(spy)
    spx = {}
    for d in sorted({max(x for x in sessions if x < date) for date in dates if any(x < date for x in sessions)}):
        v = kalshi_settlement(kalshi_event(d, kt))
        if v is not None:
            spx[d] = v
    log.append(f"S&P 500 closes from Kalshi settlement values: {len(spx)} sessions")
    series = cached("series.json", lambda: ds.get_json(f"{ds.KALSHI}/series/{cfg.KALSHI_SERIES}", throttle=kt)["series"])
    k_mult = float(series.get("fee_multiplier") or 1.0)
    log.append(f"Kalshi {cfg.KALSHI_SERIES}: fee_type {series.get('fee_type')}, fee_multiplier {k_mult}")

    sets, drops = [], {"ex_dividend": 0, "no_ratio": 0, "no_kalshi_event": 0, "no_strike_in_tolerance": 0, "no_kalshi_quote": 0,
                       "kalshi_unsettled": 0}
    for date in dates:
        rows = pm[pm.res_date == date]
        if date in ex_dates:
            drops["ex_dividend"] += len(rows)
            continue
        rt = ratio_for(date, spx, spy)
        if rt is None:
            drops["no_ratio"] += len(rows)
            continue
        mk = kalshi_event(date, kt)
        above = {round(float(m["floor_strike"]) + 0.0001, 2): m for m in mk
                 if m.get("strike_type") in ("greater", "greater_or_equal") and m.get("floor_strike") is not None}
        if not above:
            drops["no_kalshi_event"] += len(rows)
            continue
        for _, row in rows.iterrows():
            mp = map_strike(float(row.strike), rt[1], sorted(above))
            if mp is None:
                drops["no_strike_in_tolerance"] += 1
                continue
            m = above[mp[0]]
            if m.get("result") not in ("yes", "no"):
                drops["kalshi_unsettled"] += 1
                continue
            snap = float(row.snap_epoch)
            cd = cached(f"candles_{m['ticker']}.json", lambda: ds.get_json(
                f"{ds.KALSHI}/series/{cfg.KALSHI_SERIES}/markets/{m['ticker']}/candlesticks",
                {"start_ts": int(snap - cfg.KALSHI_MAX_AGE_S), "end_ts": int(snap), "period_interval": 1}, throttle=kt,
                allow=(400, 404)).get("candlesticks", []))
            q = kalshi_quote(cd, snap)
            if q is None:
                drops["no_kalshi_quote"] += 1
                continue
            sets.append({"date": date, "snap_utc": iso(snap), "snap": snap, "pm_id": str(row.market_id), "pm_strike": float(row.strike),
                         "kalshi_ticker": m["ticker"], "kalshi_strike": mp[0], "strike_gap_pts": mp[1], "ratio": rt[1], "ratio_date": rt[0],
                         "pm_mid": float(row.pm_mid), "pb": float(row.pm_bid), "pa": float(row.pm_ask), **q,
                         "lo": float(row.p_lo), "hi": float(row.p_hi), "y_pm": float(row.outcome), "y_k": 1.0 if m["result"] == "yes" else 0.0,
                         "tau_years": max(float(pd.Timestamp(m["close_time"]).timestamp()) - snap, 0.0) / (365 * 86400)})
    log.append(f"matched sets: {len(sets)} on {len({s['date'] for s in sets})} dates; dropped {drops}")
    used_dates = sorted({s["date"] for s in sets})
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(used_dates))) if used_dates else 0
    oos_dates = set(used_dates[-n_oos:]) if n_oos else set()
    for s in sets:
        s["segment"] = "OOS" if s["date"] in oos_dates else "IS"
        s["k_mid"] = (s["kb"] + s["ka"]) / 2
        s["opt_mid"] = (s["lo"] + s["hi"]) / 2
        s["split_resolution"] = s["y_pm"] != s["y_k"]

    trades = []
    for s in sets:
        for v in cfg.VARIANTS:
            for c in cfg.COST_MULTIPLIERS:
                t = evaluate(s, v, c, a.rate, k_mult)
                if t:
                    trades.append({"variant": v.id, "cost_mult": c, **{k: s[k] for k in ("segment", "date", "snap_utc", "snap", "pm_id", "pm_strike",
                                   "kalshi_ticker", "kalshi_strike", "pm_mid", "pb", "pa", "kb", "ka", "lo", "hi", "y_pm", "y_k")}, **t,
                                   "qty": cfg.CLIP_HISTORY, "capital": cfg.CLIP_HISTORY * t["cost"]})
    prints: dict[str, list[dict]] = {}
    for pid in sorted({t["pm_id"] for t in trades}):
        try:
            g = cached(f"gamma_{pid}.json", lambda: ds.get_json(f"{ds.GAMMA}/markets/{pid}", throttle=pt))
            prints[pid] = cached(f"prints_{pid}.json", lambda: ds.pm_trades(g["conditionId"], 0, pt))
        except Exception as e:
            prints[pid] = []
            log.append(f"prints failed for {pid}: {e!r}")
    for t in trades:
        n, size = verify(prints.get(t["pm_id"], []), t, t["snap"])
        if t["pm_px"] != t["pm_px"]:
            n, size = 1, float(cfg.CLIP_HISTORY)
        t["verify_n"], t["verify_size"], t["verified"] = n, size, n > 0
        t["verified_qty"] = min(size, t["qty"]) if n else 0.0
        t["pnl_verified"] = t["pnl"] * t["verified_qty"] / t["qty"]

    rows = []
    seg_dates = {"IS": [d for d in used_dates if d not in oos_dates], "OOS": sorted(oos_dates), "ALL": used_dates}
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            vt = [t for t in trades if t["variant"] == v.id and t["cost_mult"] == c]
            per_day = pd.Series([t["date"] for t in vt]).value_counts() if vt else pd.Series(dtype=int)
            capital = float(per_day.max()) * cfg.CLIP_HISTORY if len(per_day) else 0.0
            for seg, dl in seg_dates.items():
                tt = [t for t in vt if t["date"] in set(dl)]
                ver = [t for t in tt if t["verified"]]
                by_day = np.array([sum(t["pnl"] for t in tt if t["date"] == d) for d in dl]) if dl else np.array([])
                m = day_metrics(by_day, capital, sum(t["capital"] for t in tt))
                b = date_bootstrap({d: [t["pnl"] for t in tt if t["date"] == d] for d in dl})
                bv = date_bootstrap({d: [t["pnl_verified"] for t in ver if t["date"] == d] for d in dl})
                rows.append({"segment": seg, "variant": v.id, "trade": v.trade, "theta": v.theta, "outlier_filter": v.outlier_filter,
                             "cost_mult": c, "dates": len(dl), "sets": sum(1 for s in sets if s["date"] in set(dl)),
                             "entries": len(tt), "entry_dates": len({t["date"] for t in tt}), "pnl": float(sum(t["pnl"] for t in tt)),
                             "mean_pnl_per_trade": b[0], "ci_lo": b[1], "ci_hi": b[2], "wins": sum(1 for t in tt if t["pnl"] > 0),
                             "split_resolutions": sum(1 for t in tt if t.get("split")), "capital_base": capital, **m,
                             "mean_edge_bp": float(np.mean([t["edge"] / t["cost"] * 1e4 for t in tt])) if tt else float("nan"),
                             "fees_bp": float(np.mean([t["fees"] / t["cost"] * 1e4 for t in tt])) if tt else float("nan"),
                             "verified_entries": len(ver), "verified_dates": len({t["date"] for t in ver}),
                             "pnl_verified": float(sum(t["pnl_verified"] for t in tt)),
                             "mean_pnl_per_verified_trade": bv[0], "ci_lo_verified": bv[1], "ci_hi_verified": bv[2]})

    def write_csv(name, recs):
        keys = []
        for rec in recs:
            for k in rec:
                if k not in keys:
                    keys.append(k)
        with open(RESULTS / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(recs)

    write_csv("sets.csv", sets)
    write_csv("trades.csv", trades)
    write_csv("metrics_history.csv", rows)
    (RESULTS / "run_meta.json").write_text(json.dumps({
        "rate": a.rate, "dates": used_dates, "oos_dates": sorted(oos_dates), "ex_dividend_dates": ex_dates, "drops": drops,
        "kalshi_fee_type": series.get("fee_type"), "kalshi_fee_multiplier": k_mult, "sets": len(sets), "log": log,
        "run_utc": iso(time.time())}, indent=1))
    sd = pd.DataFrame(sets)
    if len(sd):
        print(f"sets {len(sd)} on {sd.date.nunique()} dates; mean |PM mid - Kalshi mid| {100 * (sd.pm_mid - sd.k_mid).abs().mean():.1f} pts; "
              f"mean |Kalshi mid - options mid| {100 * (sd.k_mid - sd.opt_mid).abs().mean():.1f}; mean |PM mid - options mid| "
              f"{100 * (sd.pm_mid - sd.opt_mid).abs().mean():.1f}; split resolutions {int(sd.split_resolution.sum())}")
    print("seg  var cost entries dates     pnl  wins splits verified ver_pnl sharpe")
    for x in rows:
        print(f"{x['segment']:4} {x['variant']} {x['cost_mult']:.0f}x {x['entries']:7d} {x['entry_dates']:5d} {x['pnl']:8.2f} {x['wins']:4d} "
              f"{x['split_resolutions']:5d} {x['verified_entries']:6d} {x['pnl_verified']:8.2f} {x['sharpe']:6.2f}")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
