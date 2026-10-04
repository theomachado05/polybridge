"""S10 Part 3: 15-minute Bitcoin Up/Down markets against a fair value from spot (METHOD.md amendment 2).

Run from `research/` after `python -m s10_weekend_lag.btc_pull`:
    python -m s10_weekend_lag.btc               # tests, every variant, the print check
    python -m s10_weekend_lag.btc --no-prints
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import engine as en
from s6_monday_fade.run import write_csv

from . import config as cfg
from .btc_pull import BTC, ET
from .mechanism import book
from .run import RESULTS, trade

R = RESULTS / "btc"


def phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def fair_value(m: int, s0: float, closes: np.ndarray, sigma: float) -> float:
    """P(final 15-minute average >= s0) at minute m, given the m completed closes and per-minute log volatility sigma."""
    n = 15 - m
    a, s = float(np.mean(closes[:m])), float(closes[m - 1])
    num = m * a + n * s - 15.0 * s0
    if n == 0:
        return 1.0 if num >= 0 else 0.0
    den = n * s * sigma * math.sqrt(n / 3.0)
    if den <= 0:
        return float("nan")
    return phi(num / den)


def verify(prints: list[dict], buy_up: bool, entry_up: float, t_signal: float) -> tuple[int, float]:
    """Section 6's rule in Up-token terms over [t, t + BTC_PRINT_WINDOW_S]: buying Up needs a taker who bought Up at or
    below our price; selling Up (buying Down) needs a taker who sold Up at or above it. Down prints are converted."""
    n, size = 0, 0.0
    for t in prints:
        ts = t.get("timestamp")
        if ts is None or not (t_signal <= float(ts) <= t_signal + cfg.BTC_PRINT_WINDOW_S):
            continue
        px, sd, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
        if out == "up":
            upx, usd = px, sd
        elif out == "down":
            upx, usd = 1.0 - px, ("BUY" if sd == "SELL" else "SELL")
        else:
            continue
        if (buy_up and usd == "BUY" and upx <= entry_up + 1e-9) or (not buy_up and usd == "SELL" and upx >= entry_up - 1e-9):
            n, size = n + 1, size + float(t.get("size", 0))
    return n, size


# ---------------------------------------------------------------- build the market-minutes

def build() -> tuple[pd.DataFrame, list[dict], dict]:
    cat = json.loads((BTC / "catalogue.json").read_text())
    sp = np.load(BTC / "spot.npz")
    st, so, sc = sp["t"], sp["o"].astype(float), sp["c"].astype(float)
    pos = {int(t): i for i, t in enumerate(st)}
    pm: dict[str, list] = {}
    for f in sorted(BTC.glob("pm_*.json")):
        pm.update(json.loads(f.read_text()))
    rows, n_missing = [], {"no_result": 0, "no_pm": 0, "spot_gap": 0}
    for mk in cat:
        if mk["result_up"] is None:
            n_missing["no_result"] += 1
            continue
        h = pm.get(mk["id"])
        if not isinstance(h, list) or not h[0]:
            n_missing["no_pm"] += 1
            continue
        pt, pp = np.array(h[0], dtype=np.int64), np.array(h[1], dtype=float)
        s = mk["start"]
        idx = [pos.get(s + 60 * k) for k in range(15)]
        back = [pos.get(s - 60 * k) for k in range(1, cfg.BTC_VOL_LOOKBACK_MIN + 1)]
        if idx[0] is None:
            n_missing["spot_gap"] += 1
            continue
        s0 = so[idx[0]]
        day = datetime.fromtimestamp(s, ET).strftime("%Y-%m-%d")
        closes_all = np.array([sc[i] if i is not None else np.nan for i in idx])
        a15 = float(np.nanmean(closes_all))
        for m in range(1, 16):
            t = s + 60 * m
            closes = closes_all[:m]
            if not np.all(np.isfinite(closes)):
                continue
            # volatility from the 60 one-minute returns ending at t (closes of the candles before and inside the window)
            seq = [sc[i] for i in reversed(back) if i is not None] + list(closes)
            lr = np.diff(np.log(np.array(seq[-(cfg.BTC_VOL_LOOKBACK_MIN + 1):])))
            sigma = float(np.std(lr, ddof=1)) if len(lr) >= 30 else float("nan")
            fair = fair_value(m, s0, closes, sigma) if np.isfinite(sigma) else float("nan")
            p_t, p_in = asof(np.array([t, t + 60], dtype=np.int64), pt, pp, cfg.BTC_PM_MAX_AGE_S)
            rows.append({"market": mk["id"], "date": day, "start": s, "minute": m, "t": t, "fair": fair, "pm": p_t, "pm_entry": p_in,
                         "result": mk["result_up"], "sigma": sigma, "model_sign_15": float(a15 >= s0), "fee_rate": mk["fee_rate"],
                         "fee_exponent": mk["fee_exponent"], "volume": mk["volume"]})
    df = pd.DataFrame(rows)
    return df, cat, {"markets_in_catalogue": len(cat), "windows": None, **n_missing}


# ---------------------------------------------------------------- tests before costs

def tests(df: pd.DataFrame) -> list[dict]:
    out = []
    d = df[(df.minute <= 13) & df.fair.notna() & df.pm.notna()]
    for m, g in d.groupby("minute"):
        out.append({"test": "T1 Brier", "minute": int(m), "n": len(g), "brier_fair": float(np.mean((g.fair - g.result) ** 2)),
                    "brier_pm": float(np.mean((g.pm - g.result) ** 2)), "mean_abs_gap_points": float(100 * np.mean(np.abs(g.fair - g.pm)))})
    for name, g in (("all minutes 1-13", d), ("minutes 1-5", d[d.minute <= 5]), ("minutes 6-9", d[(d.minute >= 6) & (d.minute <= 9)]),
                    ("minutes 10-13", d[d.minute >= 10])):
        r = en.clustered_slope((g.fair - g.pm).to_numpy(), (g.result - g.pm).to_numpy(), g.date.to_numpy())
        out.append({"test": "T2 slope of (result - Polymarket) on (fair - Polymarket)", "minute": name, **r})
    m15 = df[(df.minute == 15)].drop_duplicates("market")
    out.append({"test": "model check: sign of the Coinbase 15-minute average against the start matches the result", "minute": 15,
                "n": len(m15), "match_rate": float(np.mean(m15.model_sign_15 == m15.result)) if len(m15) else float("nan")})
    return out


# ---------------------------------------------------------------- trades

def make_trades(df: pd.DataFrame) -> list[dict]:
    out = []
    d = df[(df.minute <= 13) & df.fair.notna() & df.pm.notna() & df.pm_entry.notna()].sort_values(["market", "minute"])
    for v in cfg.BTC_VARIANTS:
        g = d[(d.minute >= v.min_minute) & ((d.fair - d.pm).abs() * 100 >= v.theta)]
        first = g.groupby("market", sort=False).head(1)
        for r in first.itertuples():
            buy_up = r.fair > r.pm
            for c in cfg.COST_MULTIPLIERS:
                entry, gross, pnl = trade(buy_up, r.pm_entry, r.result, True, cfg.BTC_HALF_SPREAD, r.fee_rate, r.fee_exponent, c)
                out.append({"variant": v.id, "cost_mult": c, "market": r.market, "date": r.date, "t": float(r.t), "minute": int(r.minute),
                            "fair": r.fair, "pm_signal": r.pm, "gap_points": 100 * (r.fair - r.pm), "side": "buy Up" if buy_up else "buy Down",
                            "p_entry": r.pm_entry, "entry": entry, "result": r.result, "gross_points": 100 * gross,
                            "cost_points": 100 * (gross - pnl), "net_points": 100 * pnl, "pnl": cfg.CONTRACTS * pnl,
                            "capital": cfg.CONTRACTS * (entry if buy_up else 1.0 - entry)})
    return out


def load_prints(cat: list[dict], need: dict[str, list[float]]) -> dict[str, dict]:
    cond = {m["id"]: m["condition"] for m in cat}
    pt, out = ds.Throttle(cfg.BTC_RATE), {}
    PR = BTC / "prints"
    PR.mkdir(parents=True, exist_ok=True)
    for mid, at in sorted(need.items()):
        f = PR / f"{mid}.json"
        if f.exists():
            out[mid] = json.loads(f.read_text())
            continue
        rec = {"reach_oldest": None, "served": 0, "prints": []}
        try:
            raw = ds.pm_trades(cond[mid], min(at) - 60, pt, max_pages=cfg.PRINT_PAGES)
            ts, ats = np.array([float(t.get("timestamp", 0)) for t in raw]), np.array(sorted(at))
            keep = [t for t, s in zip(raw, ts) if np.any((s >= ats - 60) & (s <= ats + cfg.BTC_PRINT_WINDOW_S + 60))]
            rec = {"reach_oldest": float(ts.min()) if len(ts) else None, "served": len(raw),
                   "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]}
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        out[mid] = rec
    return out


def main() -> int:
    t_run = time.time()
    R.mkdir(parents=True, exist_ok=True)
    df, cat, meta = build()
    tt = tests(df)
    trades = make_trades(df)
    prints: dict[str, dict] = {}
    if "--no-prints" not in sys.argv:
        need: dict[str, list[float]] = {}
        for t in trades:
            need.setdefault(t["market"], []).append(t["t"])
        prints = load_prints(cat, need)
    for t in trades:
        rec = prints.get(t["market"])
        t["checkable"] = bool(rec is not None and rec.get("reach_oldest") is not None and rec["reach_oldest"] <= t["t"])
        buy_up = t["side"] == "buy Up"
        n, size = verify(rec["prints"], buy_up, t["entry"] if buy_up else t["entry"], t["t"]) if rec and rec["prints"] else (0, 0.0)
        t["verify_n"], t["verify_size"], t["verified"] = n, size, n > 0
    dates = sorted(df.date.unique())
    oos_from = dates[len(dates) - int(math.ceil(cfg.OOS_FRACTION * len(dates)))]
    for t in trades:
        t["segment"] = "OOS" if t["date"] >= oos_from else "IS"
    metrics = []
    for v in cfg.BTC_VARIANTS:
        rows = book([t for t in trades if t["variant"] == v.id], "date", 365.0, dates, oos_from, v.id)
        for r in rows:
            r["variant"] = v.id
        metrics += rows
    sys.path.insert(0, str(RESULTS.parent.parent))
    from polybridge_research.stats import deflated_sharpe
    for row in metrics:
        ds_ = row.get("daily_sharpe", float("nan"))
        peers = [x["daily_sharpe"] for x in metrics if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x.get("daily_sharpe") == x.get("daily_sharpe")]
        row["deflated_sharpe_prob"] = deflated_sharpe(ds_, row["clusters"], len(cfg.BTC_VARIANTS), float(np.var(peers)), row["skew"], row["kurtosis"]) \
            if ds_ == ds_ and len(peers) > 1 else float("nan")
    write_csv(R / "tests.csv", tt)
    write_csv(R / "trades.csv", trades)
    write_csv(R / "metrics.csv", metrics)
    df[df.minute <= 13].to_csv(R / "minutes.csv.gz", index=False, compression="gzip")
    meta.update({"windows": len(cat), "markets_used": int(df.market.nunique()), "dates": len(dates), "first_date": dates[0], "last_date": dates[-1],
                 "oos_from": oos_from, "markets_checked_for_prints": len(prints), "print_errors": sum(1 for r in prints.values() if "error" in r),
                 "fee_rates_seen": sorted({m["fee_rate"] for m in cat}), "run_seconds": round(time.time() - t_run, 1)})
    (R / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in tt:
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    for x in metrics:
        print(f"{x['variant']} {x['segment']:3} {x['cost_mult']:.0f}x trades {x['trades']:5d} days {x['clusters_traded']:3d} net {x['mean_net_points']:6.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] gross {x['mean_gross_points']:6.2f} cost {x['mean_cost_points']:5.2f} hit {x['hit_rate']:.2f} "
              f"sharpe {x.get('sharpe', float('nan')):6.2f} chk {x['checkable_trades']} ver {x['verified_trades']} ver_net {x['mean_net_points_verified']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
