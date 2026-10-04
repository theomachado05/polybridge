from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s6_monday_fade.run import closure_metrics, write_csv
from s7_weekend_straddle.run import boot_mean
from s9_weekend_price_markets import config as c9
from s9_weekend_price_markets.run import _ts, calendar
from s15_weekend_scare import config as c15

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s18_price_market_calibration"
SOURCES = (("S9", RESEARCH / "s9_weekend_price_markets"), ("S15", RESEARCH / "s15_weekend_scare"))


def half_spread(universe: str, asset_class: str, kind: str) -> float:
    if universe == "S15":
        return c15.HALF_SPREAD_WEEKLY if kind == "weekly" else c15.HALF_SPREAD[asset_class]
    return c9.HALF_SPREAD[asset_class]


def first_entry(starts: np.ndarray, t: np.ndarray, p: np.ndarray) -> tuple[float, float] | None:
    px = asof(starts.astype(np.int64), t, p, cfg.PM_MAX_AGE_S)
    ok = np.flatnonzero(np.isfinite(px))
    return (float(starts[ok[0]]), float(px[ok[0]])) if len(ok) else None


def hold_to_result(side: str, p: float, outcome: float, h: float, rate: float, exponent: float, c: float) -> tuple[float, float, float]:
    lo, hi = cfg.PRICE_CLIP
    entry = min(max(p - c * h if side == "sell YES" else p + c * h, lo), hi)
    fee = c * rate * (entry * (1.0 - entry)) ** exponent
    if side == "sell YES":
        return entry, entry - fee - outcome, 1.0 - entry
    return entry, outcome - entry - fee, entry


def bucket(p: float) -> str:
    for lo, hi in cfg.BUCKETS:
        if lo <= p < hi or (hi == cfg.BUCKETS[-1][1] and p == hi):
            return f"{100 * lo:.0f} to {100 * hi:.0f}%"
    return "outside"


def select(df: pd.DataFrame, v: cfg.Variant) -> pd.DataFrame:
    ok = (df.p >= v.lo) & (df.p <= v.hi)
    if v.universe:
        ok &= df.universe == v.universe
    if v.classes:
        ok &= df.asset_class.isin(v.classes)
    return df[ok]


def max_locked(trades: list[dict]) -> float:
    ev = sorted([(t["entry_epoch"], t["capital"]) for t in trades] + [(t["result_epoch"], -t["capital"]) for t in trades], key=lambda e: (e[0], e[1]))
    cur = best = 0.0
    for _, c in ev:
        cur += c
        best = max(best, cur)
    return best


def build() -> pd.DataFrame:
    starts = np.array([w["start"] for w in calendar()])
    rows = []
    for universe, root in SOURCES:
        for m in json.loads((root / "universe.json").read_text())["markets"]:
            f = root / ".cache" / f"pm_{m['id']}.npz"
            if m.get("outcome") is None or not f.exists():
                continue
            z = np.load(f)
            e = first_entry(starts, z["t"], z["p"].astype(float)) if len(z["t"]) else None
            closed = _ts(m.get("closed_time"))
            if e is None or closed is None or closed <= e[0] or not (cfg.PRICE_RANGE[0] <= e[1] <= cfg.PRICE_RANGE[1]):
                continue
            kind = m.get("kind", "S9 event")
            rows.append({"universe": universe, "market": m["id"], "event": m["event"], "asset_class": m["asset_class"], "kind": kind,
                         "sign": m["sign"], "question": m["question"], "fee_rate": m["fee_rate"], "fee_exponent": m["fee_exponent"],
                         "half_spread": half_spread(universe, m["asset_class"], kind), "entry_epoch": e[0], "p": e[1], "outcome": float(m["outcome"]),
                         "result_epoch": closed, "days_to_result": (closed - e[0]) / 86400.0, "bucket": bucket(e[1])})
    df = pd.DataFrame(rows)
    first = df.groupby("event").entry_epoch.min().sort_values()
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(first)))
    oos_events = set(first.index[len(first) - n_oos:])
    df["segment"] = np.where(df.event.isin(oos_events), "OOS", "IS")
    return df


def calibration(df: pd.DataFrame) -> list[dict]:
    scopes = [("all markets", df), ("\"hit high\" markets", df[df.sign == 1]), ("\"hit low\" markets", df[df.sign == -1]),
              ("S9's markets", df[df.universe == "S9"]), ("S15's markets", df[df.universe == "S15"])] \
        + [(f"class: {c}", df[df.asset_class == c]) for c in sorted(df.asset_class.unique())]
    ranges = [(f"{100 * lo:.0f} to {100 * hi:.0f}%", lo, hi) for lo, hi in cfg.BUCKETS] \
        + [("C1: 2 to 25%", *cfg.C1_RANGE), ("C2: 75 to 98%", *cfg.C2_RANGE), ("every price", *cfg.PRICE_RANGE)]
    rows = []
    for name, d in scopes:
        for label, lo, hi in ranges:
            s = d[(d.p >= lo) & (d.p <= hi)] if label[0] in "Ce" else d[d.bucket == label]
            b = boot_mean({k: list(100.0 * (v.outcome - v.p)) for k, v in s.groupby("event")})
            rows.append({"scope": name, "price_range": label, "markets": len(s), "events": int(s.event.nunique()),
                         "mean_price": float(100 * s.p.mean()) if len(s) else float("nan"),
                         "share_yes": float(100 * s.outcome.mean()) if len(s) else float("nan"), "diff_points": b[0], "ci_lo": b[1], "ci_hi": b[2]})
    return rows


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    df = build()
    cal = calibration(df)
    trades = []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            for r in select(df, v).itertuples():
                entry, pnl, cap = hold_to_result(v.side, r.p, r.outcome, r.half_spread, r.fee_rate, r.fee_exponent, c)
                gross = (r.p - r.outcome) if v.side == "sell YES" else (r.outcome - r.p)
                trades.append({"variant": v.id, "cost_mult": c, "segment": r.segment, "universe": r.universe, "event": r.event, "market": r.market,
                               "question": r.question, "asset_class": r.asset_class, "sign": r.sign, "side": v.side, "p": r.p, "entry": entry,
                               "outcome": r.outcome, "gross_points": 100.0 * gross, "cost_points": 100.0 * (gross - pnl), "net_points": 100.0 * pnl,
                               "pnl": cfg.CONTRACTS * pnl, "capital": cfg.CONTRACTS * cap, "return_on_capital": pnl / cap,
                               "entry_epoch": r.entry_epoch, "result_epoch": r.result_epoch, "days_to_result": r.days_to_result,
                               "result_month": datetime.fromtimestamp(r.result_epoch, timezone.utc).strftime("%Y-%m")})
    months = sorted({t["result_month"] for t in trades})
    rows, eq = [], []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            vt = [t for t in trades if t["variant"] == v.id and t["cost_mult"] == c]
            K = max_locked(vt)
            for seg in ("IS", "OOS", "ALL"):
                st = [t for t in vt if seg == "ALL" or t["segment"] == seg]
                by_ev: dict[str, list[dict]] = {}
                for t in st:
                    by_ev.setdefault(t["event"], []).append(t)
                ml = [mo for mo in months if not st or min(t["result_month"] for t in st) <= mo <= max(t["result_month"] for t in st)]
                pc = np.array([sum(t["pnl"] for t in st if t["result_month"] == mo) for mo in ml])
                m = closure_metrics(pc, ml, K, sum(t["capital"] for t in st), cfg.MONTHS_PER_YEAR)
                b = boot_mean({e: [t["net_points"] for t in ts] for e, ts in by_ev.items()})
                g = boot_mean({e: [t["gross_points"] for t in ts] for e, ts in by_ev.items()})
                ev_pnl = sorted(sum(t["pnl"] for t in ts) for ts in by_ev.values())

                def avg(key):
                    return float(np.mean([t[key] for t in st])) if st else float("nan")

                rows.append({"segment": seg, "variant": v.id, "side": v.side, "price_lo": v.lo, "price_hi": v.hi, "universe": v.universe or "all",
                             "classes": "all" if not v.classes else " ".join(v.classes), "cost_mult": c, "trades": len(st), "events": len(by_ev),
                             "months": len(ml), "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0],
                             "gross_ci_lo": g[1], "gross_ci_hi": g[2], "mean_cost_points": avg("cost_points"),
                             "cost_bp_of_capital": float(np.mean([t["cost_points"] / 100.0 * cfg.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                             "mean_entry_price": avg("p"), "share_yes": avg("outcome"), "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"),
                             "mean_return_on_capital": avg("return_on_capital"), "mean_days_to_result": avg("days_to_result"), "pnl": float(pc.sum()),
                             "worst_event_pnl": ev_pnl[0] if ev_pnl else float("nan"), "best_event_pnl": ev_pnl[-1] if ev_pnl else float("nan"),
                             "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)), **m})
                if seg == "ALL":
                    gp = np.array([sum(t["gross_points"] for t in st if t["result_month"] == mo) for mo in ml])
                    eq += [{"variant": v.id, "cost_mult": c, "month": mo, "pnl": float(a), "gross": float(g_)} for mo, a, g_ in zip(ml, np.cumsum(pc), np.cumsum(gp))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in rows:
        peers = [x["daily_sharpe"] for x in rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["months"], len(cfg.VARIANTS), float(np.var(peers)), row["skew"],
                                                      row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")
    write_csv(RESULTS / "entries.csv", df.to_dict("records"))
    write_csv(RESULTS / "calibration.csv", cal)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    write_csv(RESULTS / "equity.csv", eq)
    first = df.groupby("event").entry_epoch.min()
    meta = {"markets_with_an_entry": int(len(df)), "events": int(df.event.nunique()), "by_universe": {k: int(n) for k, n in df.universe.value_counts().items()},
            "by_class": {k: int(n) for k, n in df.asset_class.value_counts().items()}, "share_yes": float(df.outcome.mean()), "mean_price": float(df.p.mean()),
            "oos_events": int(df[df.segment == "OOS"].event.nunique()),
            "oos_from": datetime.fromtimestamp(float(first[df[df.segment == "OOS"].event.unique()].min()), timezone.utc).strftime("%Y-%m-%d"),
            "first_entry": datetime.fromtimestamp(float(df.entry_epoch.min()), timezone.utc).strftime("%Y-%m-%d"),
            "last_entry": datetime.fromtimestamp(float(df.entry_epoch.max()), timezone.utc).strftime("%Y-%m-%d"),
            "median_days_to_result": float(df.days_to_result.median()), "run_seconds": round(time.time() - t_run, 1)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in cal:
        if r["scope"] in ("all markets", "\"hit high\" markets", "\"hit low\" markets", "S9's markets", "S15's markets") or r["price_range"].startswith("C"):
            print(f"{r['scope'][:20]:20} | {r['price_range']:14} | mkts {r['markets']:4d} ev {r['events']:3d} | price {r['mean_price']:5.1f} yes {r['share_yes']:5.1f} | "
                  f"diff {r['diff_points']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}]")
    print("seg var cost trades ev   net_pts [ci]             gross  cost  yes%  hit  ret/cap  sharpe  maxDD")
    for x in rows:
        print(f"{x['segment']:3} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['events']:3d} {x['mean_net_points']:7.2f} [{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] "
              f"{x['mean_gross_points']:6.2f} {x['mean_cost_points']:5.2f} {100 * x['share_yes']:5.1f} {x['hit_rate']:5.2f} {100 * x['mean_return_on_capital']:6.1f}% "
              f"{x['sharpe']:6.2f} {x['max_drawdown']:6.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
