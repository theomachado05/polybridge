"""S7: Friday at-the-money straddles on linked tickers when the prediction market shows a live event, sold Monday at
09:45; against the same trade on ordinary weekends (METHOD.md).

Run from `research/`:  python -m s7_weekend_straddle.run
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s4_linked_assets import engine as en
from s5_big_moves import run as r5

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s7_weekend_straddle"
ET = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 3)


def put_ticker(call: str) -> str:
    """The put with the same expiry and strike (OCC symbol: ...YYMMDD C 00038000)."""
    assert call[-9] == "C", call
    return call[:-9] + "P" + call[-8:]


def activity(x_abs: np.ndarray, friday: int) -> float:
    """Mean absolute overnight odds move over the five sessions ending on the Friday; NaN with under three nights."""
    w = x_abs[max(0, friday - cfg.ACTIVITY_NIGHTS + 1): friday + 1]
    ok = np.isfinite(w)
    return float(np.mean(w[ok])) if ok.sum() >= cfg.ACTIVITY_MIN_NIGHTS else float("nan")


def flagged(links_state: list[tuple[float, float]], v: cfg.Variant) -> bool:
    """links_state: (odds at Friday's close, activity) of each linked question of the ticker."""
    return any(a == a and p == p and a >= v.activity and v.lo <= p <= v.hi for p, a in links_state)


def match_controls(flag_idx: list[int], pool: list[int]) -> dict[int, int]:
    """Each flagged weekend gets the nearest earlier unflagged weekend not yet used (the nearest later one if none)."""
    used: set[int] = set()
    out: dict[int, int] = {}
    for w in sorted(flag_idx):
        earlier = [p for p in pool if p < w and p not in used]
        later = [p for p in pool if p > w and p not in used]
        pick = max(earlier) if earlier else (min(later) if later else None)
        if pick is not None:
            used.add(pick)
            out[w] = pick
    return out


def straddle(q: dict, c: float) -> dict | None:
    """P&L of one straddle from its four quotes (bid, ask) at cost multiplier c. Prices are per share."""
    def widen(b, a):
        m, h = (a + b) / 2, (a - b) / 2
        return max(m - c * h, 0.0), m + c * h

    (cb1, ca1), (pb1, pa1) = widen(*q["call_fri"]), widen(*q["put_fri"])
    (cb2, ca2), (pb2, pa2) = widen(*q["call_mon"]), widen(*q["put_mon"])
    cost = (ca1 + pa1) * 100 + 2 * c * cfg.COMMISSION
    proceeds = (cb2 + pb2) * 100 - 2 * c * cfg.COMMISSION
    mid1 = (sum(q["call_fri"]) + sum(q["put_fri"])) / 2 * 100
    mid2 = (sum(q["call_mon"]) + sum(q["put_mon"])) / 2 * 100
    if cost <= 0 or mid1 <= 0:
        return None
    return {"cost": cost, "proceeds": proceeds, "pnl": proceeds - cost, "ret": (proceeds - cost) / cost, "mid_ret": (mid2 - mid1) / mid1,
            "premium_mid": mid1, "cost_share_of_premium": (cost - mid1 + mid2 - proceeds) / mid1}


def boot_mean(by: dict[str, list[float]]) -> tuple[float, float, float]:
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


def boot_diff(a: dict[str, list[float]], b: dict[str, list[float]]) -> tuple[float, float, float]:
    """Mean of group a minus mean of group b, resampling weekends (each weekend carries its own trades of both groups)."""
    keys = sorted(set(k for k, v in a.items() if v) | set(k for k, v in b.items() if v))
    fa, fb = [x for k in keys for x in a.get(k, [])], [x for k in keys for x in b.get(k, [])]
    if not fa or not fb or len(keys) < 5:
        return (float(np.mean(fa) - np.mean(fb)) if fa and fb else float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(cfg.BOOT_SEED)
    sa, na = np.array([sum(a.get(k, [])) for k in keys]), np.array([len(a.get(k, [])) for k in keys])
    sb, nb = np.array([sum(b.get(k, [])) for k in keys]), np.array([len(b.get(k, [])) for k in keys])
    pick = rng.integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = sa[pick].sum(axis=1) / na[pick].sum(axis=1) - sb[pick].sum(axis=1) / nb[pick].sum(axis=1)
    d = d[np.isfinite(d)]
    lo, hi = np.percentile(d, [2.5, 97.5])
    return float(np.mean(fa) - np.mean(fb)), float(lo), float(hi)


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
    sys.path.insert(0, str(RESEARCH))
    sys.path.insert(0, str(RESEARCH / "arb"))
    from arbscan.datasrc import OptionSource
    from polybridge_research.massive import MassiveClient, load_api_key

    RESULTS.mkdir(parents=True, exist_ok=True)
    C = r5.CACHE
    links, _ = r5.merge_links()
    spy = dict(np.load(C / "eq_SPY.npz"))
    sess = en.sessions_from(spy["t"])
    days = list(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    weekends = [int(i) for i in np.flatnonzero(np.concatenate([[False], (op[1:] - cl[:-1]) > 40 * 3600]))]
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(weekends)))
    oos = set(weekends[-n_oos:])

    # ---- the flag: per ticker and weekend, the state of each linked question at Friday's close
    state: dict[str, dict[int, list[tuple[float, float]]]] = {}
    for l in links:
        pm = np.load(C / f"pm_{l['market'].split(':')[1]}.npz")
        if len(pm["t"]) == 0:
            continue
        p_close = asof(cl.astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
        p_sig = asof((op - 60).astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
        x_abs = np.abs(100.0 * (p_sig - np.concatenate([[np.nan], p_close[:-1]])))
        for w in weekends:
            state.setdefault(l["ticker"], {}).setdefault(w, []).append((float(p_close[w - 1]), activity(x_abs, w - 1)))
    variants = {v.id: v for v in cfg.VARIANTS}
    plan = []          # (ticker, weekend index, group, flags by variant, flagged weekend it controls for)
    for tk, by_w in state.items():
        flags = {w: {vid: flagged(st, v) for vid, v in variants.items()} for w, st in by_w.items()}
        loose = [w for w in weekends if flags.get(w, {}).get(cfg.LOOSEST)]
        pool = [w for w in weekends if w in flags and not flags[w][cfg.LOOSEST]]
        ctrl = match_controls(loose, pool)
        for w in loose:
            plan.append((tk, w, "flagged", flags[w], None))
            if w in ctrl:
                plan.append((tk, ctrl[w], "control", flags[w], w))

    # ---- quotes
    client = MassiveClient(load_api_key(search_from=RESEARCH), cache_dir=RESEARCH / ".massive_cache")
    src = OptionSource(client, TODAY)
    px = {}
    for tk in state:
        f = C / f"eq_{tk}.npz"
        px[tk] = en.session_prices(dict(np.load(f)), sess) if f.exists() else None
    strike_col = int((pd.Timestamp(f"2026-01-05 {cfg.STRIKE_ET}") - pd.Timestamp("2026-01-05 09:30")).total_seconds() // 1800)

    def job(item):
        tk, w, group, fl, controls = item
        fri, mon = days[w - 1], days[w]
        base = {"ticker": tk, "friday": fri, "monday": mon, "group": group, "controls_for": days[controls - 1] if controls else "",
                "segment": "OOS" if (controls or w) in oos else "IS", **{f"flag_{k}": bool(v) for k, v in fl.items()}}
        p = px.get(tk)
        if p is None or not np.isfinite(p["px"][w - 1, strike_col]):
            return {**base, "status": "no underlying price"}
        spot = float(p["px"][w - 1, strike_col])
        ne = src.nearest_expiry(tk, date.fromisoformat(fri) + timedelta(days=cfg.EXPIRY_MIN_DAYS), max_days=cfg.EXPIRY_SEARCH_DAYS)
        if ne is None:
            return {**base, "status": "no listed expiry"}
        expiry, calls = ne
        strike = min(calls, key=lambda k: abs(k - spot))
        call, put = calls[strike], put_ticker(calls[strike])
        t_fri = pd.Timestamp(f"{fri} {cfg.ENTRY_ET}", tz=ET).to_pydatetime()
        t_mon = pd.Timestamp(f"{mon} {cfg.EXIT_ET}", tz=ET).to_pydatetime()
        floor = pd.Timestamp(f"{mon} 09:30", tz=ET).timestamp()
        q = {}
        for name, tkr, at, age in (("call_fri", call, t_fri, cfg.FRIDAY_QUOTE_MAX_AGE_S), ("put_fri", put, t_fri, cfg.FRIDAY_QUOTE_MAX_AGE_S),
                                   ("call_mon", call, t_mon, cfg.MONDAY_QUOTE_MAX_AGE_S), ("put_mon", put, t_mon, cfg.MONDAY_QUOTE_MAX_AGE_S)):
            x = src.quote(tkr, at)
            if x is None or not x.valid(at.timestamp(), age) or (name.endswith("mon") and not (x.ts >= floor)):
                return {**base, "status": f"no valid quote: {name}", "expiry": expiry, "strike": strike, "spot_1530": spot}
            q[name] = (x.bid, x.ask)
            if name == "call_fri":
                base["ask_size_call_fri"] = x.ask_size
        out = {**base, "status": "ok", "expiry": expiry, "strike": strike, "spot_1530": spot, "call": call, "put": put,
               "underlying_move_bp": 1e4 * (p["px"][w, 0] / p["close"][w - 1] - 1), **{f"{k}_{s}": v[i] for k, v in q.items() for i, s in enumerate(("bid", "ask"))}}
        for c in cfg.COST_MULTIPLIERS:
            s = straddle(q, c)
            if s is None:
                return {**base, "status": "bad quotes"}
            out.update({f"{k}_{c:.0f}x": v for k, v in s.items()})
        return out

    with ThreadPoolExecutor(max_workers=4) as ex:
        trades = list(ex.map(job, plan))
    ok = [t for t in trades if t["status"] == "ok"]

    # ---- metrics
    all_w = [days[w - 1] for w in weekends]
    per_year = len(all_w) / max((pd.Timestamp(all_w[-1]) - pd.Timestamp(all_w[0])).days / 365.0, 1e-9)
    rows = []
    for vid in variants:
        fl = [t for t in ok if t["group"] == "flagged" and t[f"flag_{vid}"]]
        keys = {(t["ticker"], t["friday"]) for t in fl}
        ct = [t for t in ok if t["group"] == "control" and (t["ticker"], t["controls_for"]) in keys]
        for c in cfg.COST_MULTIPLIERS:
            r = f"ret_{c:.0f}x"
            for seg in ("IS", "OOS", "ALL"):
                f_, c_ = [t for t in fl if seg == "ALL" or t["segment"] == seg], [t for t in ct if seg == "ALL" or t["segment"] == seg]
                bf = boot_mean({d: [t[r] for t in f_ if t["friday"] == d] for d in all_w})
                bc = boot_mean({d: [t[r] for t in c_ if t["friday"] == d] for d in all_w})
                # the control of a flagged weekend is carried by that flagged weekend in the difference
                bd = boot_diff({d: [t[r] for t in f_ if t["friday"] == d] for d in all_w},
                               {d: [t[r] for t in c_ if t["controls_for"] == d] for d in all_w})
                seg_w = [d for d, w in zip(all_w, weekends) if seg == "ALL" or (w in oos) == (seg == "OOS")]
                wr = np.array([np.mean([t[r] for t in f_ if t["friday"] == d]) if any(t["friday"] == d for t in f_) else 0.0 for d in seg_w])
                sd = float(np.std(wr, ddof=1)) if len(wr) > 2 else 0.0
                e = np.concatenate([[0.0], np.cumsum(wr)])
                months: dict[str, float] = {}
                for x, d in zip(wr, seg_w):
                    months[d[:7]] = months.get(d[:7], 0.0) + float(x)
                rows.append({"variant": vid, "cost_mult": c, "segment": seg, "flagged_trades": len(f_), "flagged_weekends": len({t["friday"] for t in f_}),
                             "tickers": len({t["ticker"] for t in f_}), "mean_ret_flagged": bf[0], "ci_lo": bf[1], "ci_hi": bf[2],
                             "hit_rate_flagged": float(np.mean([t[r] > 0 for t in f_])) if f_ else float("nan"),
                             "mean_mid_ret_flagged": float(np.mean([t["mid_ret_1x"] for t in f_])) if f_ else float("nan"),
                             "abs_move_bp_flagged": float(np.mean([abs(t["underlying_move_bp"]) for t in f_])) if f_ else float("nan"),
                             "control_trades": len(c_), "mean_ret_control": bc[0], "control_ci_lo": bc[1], "control_ci_hi": bc[2],
                             "mean_mid_ret_control": float(np.mean([t["mid_ret_1x"] for t in c_])) if c_ else float("nan"),
                             "abs_move_bp_control": float(np.mean([abs(t["underlying_move_bp"]) for t in c_])) if c_ else float("nan"),
                             "diff_flagged_minus_control": bd[0], "diff_ci_lo": bd[1], "diff_ci_hi": bd[2],
                             "pnl_per_straddle": float(np.mean([t[f"pnl_{c:.0f}x"] for t in f_])) if f_ else float("nan"),
                             "cost_share_of_premium": float(np.mean([t[f"cost_share_of_premium_{c:.0f}x"] for t in f_])) if f_ else float("nan"),
                             "sharpe": float(np.mean(wr) / sd * math.sqrt(per_year)) if sd > 0 else float("nan"),
                             "weekend_sharpe": float(np.mean(wr) / sd) if sd > 0 else float("nan"),
                             "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)), "total_return": float(e[-1]),
                             "worst_month": min(months.values()) if months else float("nan"), "weekends": len(seg_w)})
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    st = pd.Series([t["status"] for t in trades]).value_counts().to_dict()
    (RESULTS / "run_meta.json").write_text(json.dumps({
        "weekends": len(weekends), "first_friday": all_w[0], "last_friday": all_w[-1], "oos_from": days[sorted(oos)[0] - 1], "oos_weekends": n_oos,
        "weekends_per_year": per_year, "planned_trades": len(plan), "status": st, "option_request_failures": len(src.failures),
        "run_seconds": round(time.time() - t_run, 1)}, indent=1))
    print("planned", len(plan), "status", st, "failures", len(src.failures), f"{time.time() - t_run:.0f}s")
    print("var cost seg  flagged weekends  ret_flagged [ci]               mid_flag  |move| flag  control ret_control  mid_ctrl |move| ctrl   diff [ci]            sharpe")
    for x in rows:
        print(f"{x['variant']} {x['cost_mult']:.0f}x {x['segment']:3} {x['flagged_trades']:7d} {x['flagged_weekends']:8d} {100 * x['mean_ret_flagged']:8.1f}% "
              f"[{100 * x['ci_lo']:6.1f},{100 * x['ci_hi']:6.1f}] {100 * x['mean_mid_ret_flagged']:8.1f}% {x['abs_move_bp_flagged']:8.0f} {x['control_trades']:8d} "
              f"{100 * x['mean_ret_control']:9.1f}% {100 * x['mean_mid_ret_control']:8.1f}% {x['abs_move_bp_control']:8.0f} {100 * x['diff_flagged_minus_control']:7.1f}% "
              f"[{100 * x['diff_ci_lo']:6.1f},{100 * x['diff_ci_hi']:6.1f}] {x['sharpe']:6.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
