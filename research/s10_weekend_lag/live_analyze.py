"""S10 Part 5 analysis (METHOD.md amendment 5): the live book of the 15-minute Bitcoin markets against Coinbase.

Run from `research/` after the recorder stops:  python -m s10_weekend_lag.live_analyze
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s4_linked_assets import engine as en
from s6_monday_fade.run import write_csv

from . import config as cfg
from .btc import phi
from .live import LIVE
from .run import RESULTS, boot_mean

R = RESULTS / "live"
THETA = 0.02
FILL_MAX_GAP_S = 3.0
MAX_WORSE = 0.01


def fee_pts(p: float, rate: float, c: float = 1.0) -> float:
    return c * rate * p * (1 - p)


def load() -> tuple[pd.DataFrame, dict[str, dict], list[tuple[float, list]]]:
    snaps, markets, candles = [], {}, []
    for f in sorted(LIVE.glob("rec_*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") == "market":
                markets[r["id"]] = r
                continue
            if "candles" in r:
                candles.append((r["ts"], r["candles"]))
            if "cb_price" in r:
                b, a = r.get("bids") or [], r.get("asks") or []
                snaps.append({"ts": r["ts"], "start": r["start"], "cb": r["cb_price"], "market": r.get("market"),
                              "bid": b[0][0] if b else np.nan, "bid_size": b[0][1] if b else np.nan,
                              "ask": a[0][0] if a else np.nan, "ask_size": a[0][1] if a else np.nan})
    return pd.DataFrame(snaps).sort_values("ts").reset_index(drop=True), markets, sorted(candles, key=lambda x: x[0])


def sigma_at(candles: list[tuple[float, list]], s: float) -> float:
    """Std of the last 60 one-minute log returns from the latest candle fetch before s."""
    prior = [c for t, c in candles if t <= s]
    if not prior:
        return float("nan")
    rows = sorted((x for x in prior[-1] if x[0] + 60 <= s), key=lambda x: x[0])[-61:]
    closes = np.array([x[2] for x in rows], dtype=float)
    return float(np.std(np.diff(np.log(closes)), ddof=1)) if len(closes) >= 31 else float("nan")


def add_fair(df: pd.DataFrame, candles) -> pd.DataFrame:
    ts, cb = df.ts.to_numpy(), df.cb.to_numpy()
    lo = np.searchsorted(ts, ts - 60.0, side="right")
    cs = np.concatenate([[0.0], np.cumsum(cb)])
    x = (cs[np.arange(len(ts)) + 1] - cs[lo]) / (np.arange(len(ts)) + 1 - lo)       # mean over (s - 60, s]
    df = df.assign(x=x)
    s0 = {}
    for st in df.start.unique():
        j = np.searchsorted(ts, st, side="right") - 1
        s0[st] = x[j] if j >= 0 and st - ts[j] <= 3 and ts[j] - ts[0] >= 60 else np.nan
    df["s0"] = df.start.map(s0)
    df["el"] = df.ts - df.start
    df["sigma"] = [sigma_at(candles, s) for s in df.ts]
    tau = cfg.BTC_WINDOW_S - df.el
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.log(df.x / df.s0) / (df.sigma * np.sqrt(tau / 60.0))
    df["fair"] = [phi(v) if np.isfinite(v) else np.nan for v in z]
    df["mid"] = (df.bid + df.ask) / 2
    return df


def trades(df: pd.DataFrame, markets: dict, results: dict, c: float = 1.0) -> list[dict]:
    out = []
    for (st, mk), g in df[df.market.notna()].groupby(["start", "market"]):
        g = g[(g.el >= 60) & (g.el <= 870) & g.fair.notna()].reset_index(drop=True)
        rate = markets.get(mk, {}).get("fee_rate", 0.07)
        res = results.get(mk)
        for k in range(len(g) - 1):
            r, n = g.loc[k], g.loc[k + 1]
            if n.ts - r.ts > FILL_MAX_GAP_S:
                continue
            side = None
            if np.isfinite(r.ask) and r.fair - r.ask >= THETA + fee_pts(r.ask, rate):
                side, quote, fill, size = "buy Up", r.ask, n.ask, n.ask_size
                ok = np.isfinite(fill) and fill <= quote + MAX_WORSE
            elif np.isfinite(r.bid) and r.bid - r.fair >= THETA + fee_pts(r.bid, rate):
                side, quote, fill, size = "sell Up", r.bid, n.bid, n.bid_size
                ok = np.isfinite(fill) and fill >= quote - MAX_WORSE
            if side is None or not ok:
                continue
            q = min(float(size), cfg.CONTRACTS)
            slip = (c - 1.0) * 0.01
            px = fill + slip if side == "buy Up" else fill - slip
            gross = (res - fill) if side == "buy Up" else (fill - res)
            net = ((res - px) if side == "buy Up" else (px - res)) - fee_pts(px, rate, c) if res is not None else np.nan
            out.append({"cost_mult": c, "start": int(st), "market": mk, "elapsed_s": float(r.el), "side": side, "fair": r.fair, "quote": quote,
                        "fill": fill, "size": q, "result": res, "gross_points": 100 * gross if res is not None else np.nan,
                        "net_points": 100 * net, "pnl": q * net if res is not None else np.nan})
            break
    return out


def lag_rows(df: pd.DataFrame) -> list[dict]:
    rows = []
    d = df[(df.el >= 60) & (df.el <= 870) & df.fair.notna() & df.mid.notna()].copy()
    d = d.set_index("ts")
    for st, g in d.groupby("start"):
        g = g[~g.index.duplicated()]
        sec = pd.DataFrame(index=np.arange(int(g.index.min()), int(g.index.max()) + 1))
        sec["fair"] = np.interp(sec.index, g.index, g.fair)
        sec["mid"] = np.interp(sec.index, g.index, g.mid)
        sec["df5"] = sec.fair.diff(5)
        for h in (0, 5, 15, 30, 60):
            y = (sec.mid.shift(-h) - sec.mid) if h else sec.mid.diff(5)
            rows.append(pd.DataFrame({"start": st, "h": h, "x": sec.df5.to_numpy(), "y": y.to_numpy()}))
    if not rows:
        return []
    a = pd.concat(rows)
    out = []
    for h, g in a.groupby("h"):
        r = en.clustered_slope(g.x.to_numpy(), g.y.to_numpy(), g.start.to_numpy())
        out.append({"measure": "same 5 seconds" if h == 0 else f"next {h} seconds", "h": int(h), **r})
    return out


def main() -> int:
    R.mkdir(parents=True, exist_ok=True)
    df, markets, candles = load()
    df = add_fair(df, candles)
    pt = ds.Throttle(1.0)
    results = {}
    for mk in sorted(df.market.dropna().unique()):
        d = ds.get_json(f"{ds.GAMMA}/markets/{mk}", throttle=pt, allow=(404,))
        if isinstance(d, dict):
            outs, prices = json.loads(d.get("outcomes") or "[]"), json.loads(d.get("outcomePrices") or "[]")
            if d.get("closed") and "Up" in outs and prices and prices[outs.index("Up")] in ("0", "1"):
                results[mk] = float(prices[outs.index("Up")])
    tr = trades(df, markets, results, 1.0) + trades(df, markets, results, 2.0)
    ll = lag_rows(df)
    summ = []
    for c in cfg.COST_MULTIPLIERS:
        t = [x for x in tr if x["cost_mult"] == c and x["result"] is not None]
        b = boot_mean({str(x["start"]): [x["net_points"]] for x in t})
        g = boot_mean({str(x["start"]): [x["gross_points"]] for x in t})
        summ.append({"cost_mult": c, "windows": int(df.start.nunique()), "windows_with_book": len({x for x in df.market.dropna()}),
                     "trades": len(t), "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0],
                     "hit_rate": float(np.mean([x["net_points"] > 0 for x in t])) if t else float("nan"),
                     "mean_size": float(np.mean([x["size"] for x in t])) if t else float("nan"), "pnl": float(np.nansum([x["pnl"] for x in t]))})
    write_csv(R / "trades.csv", tr)
    write_csv(R / "lag.csv", ll)
    write_csv(R / "metrics.csv", summ)
    meta = {"snapshots": len(df), "first": float(df.ts.min()), "last": float(df.ts.max()), "markets_resolved": len(results),
            "median_gap_s": float(np.median(np.diff(df.ts))), "spread_median_points": float(100 * np.nanmedian(df.ask - df.bid))}
    (R / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in ll:
        print(f"{r['measure']:16} slope {r['slope']:.3f} t {r['t']:.2f} n {r['n']} windows {r.get('clusters')}")
    for s in summ:
        print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
