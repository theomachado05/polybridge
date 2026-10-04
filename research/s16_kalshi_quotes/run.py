"""S16: the give-back at Kalshi's real bid and ask, and the same nights on Polymarket (METHOD.md). Cached data only.

Run from `research/`:  python -m s16_kalshi_quotes.run
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof, kalshi_fee
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s6_monday_fade.run import closure_metrics, write_csv
from s7_weekend_straddle.run import boot_mean

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
S1_CACHE = RESEARCH / "s1_twin_spread" / ".cache"
RESULTS = RESEARCH / "results" / "s16_kalshi_quotes"
CLIP = (0.01, 0.99)


def standing_quote(grid: np.ndarray, t: np.ndarray, bid: np.ndarray, ask: np.ndarray, max_age: float) -> tuple[np.ndarray, np.ndarray]:
    """The quote in force at each instant: the last candle at or before it, if it is at most max_age old and
    two-sided (bid above 0, ask below 1, ask above bid). A later one-sided candle cancels an earlier two-sided one."""
    b, a = np.full(len(grid), np.nan), np.full(len(grid), np.nan)
    if len(t) == 0:
        return b, a
    idx = np.searchsorted(t, grid, side="right") - 1
    ok = idx >= 0
    j = idx[ok]
    bj, aj = bid[j].astype(float), ask[j].astype(float)
    good = (grid[ok] - t[j] <= max_age) & np.isfinite(bj) & np.isfinite(aj) & (bj > 0) & (aj < 1) & (aj > bj)
    bj[~good], aj[~good] = np.nan, np.nan
    b[ok], a[ok] = bj, aj
    return b, a


def fade_at_quotes(x: float, bid_in: float, ask_in: float, bid_out: float, ask_out: float, mult: float, c: float) -> dict:
    """Sell a rise at the bid and buy it back at the ask (or the mirror), 100 contracts, Kalshi's taker fee on each fill.
    At c = 2 each fill is a further half-spread worse and the fee is doubled. Per contract, in price units."""
    half_in, half_out = (ask_in - bid_in) / 2.0, (ask_out - bid_out) / 2.0
    sell = x > 0
    entry = bid_in - (c - 1.0) * half_in if sell else ask_in + (c - 1.0) * half_in
    out = ask_out + (c - 1.0) * half_out if sell else bid_out - (c - 1.0) * half_out
    entry, out = min(max(entry, CLIP[0]), CLIP[1]), min(max(out, CLIP[0]), CLIP[1])
    fees = c * float(kalshi_fee(entry, cfg.CONTRACTS, mult) + kalshi_fee(out, cfg.CONTRACTS, mult))
    mid_in, mid_out = (bid_in + ask_in) / 2.0, (bid_out + ask_out) / 2.0
    gross_mid = (mid_in - mid_out) if sell else (mid_out - mid_in)
    at_quotes = (entry - out) if sell else (out - entry)
    return {"side": "sell YES" if sell else "buy YES", "entry": entry, "exit": out, "gross_mid": gross_mid, "spread_cost": gross_mid - at_quotes,
            "fee_cost": fees, "net": at_quotes - fees, "capital": cfg.CONTRACTS * ((1.0 - entry) if sell else entry)}


def build() -> tuple[pd.DataFrame, dict]:
    sess = en.sessions_from(np.load(S5_CACHE / "eq_SPY.npz")["t"])
    days, op, cl = np.array(sess.day), sess.open.to_numpy().astype(np.int64), sess.close.to_numpy().astype(np.int64)
    prev = np.concatenate([[0], cl[:-1]]).astype(np.int64)
    pairs = json.loads((S1_CACHE / "pull_meta.json").read_text())["pairs"]
    frames = []
    for m in pairs:
        fk, fp = S1_CACHE / f"k_{m['ticker']}.npz", S1_CACHE / f"p_{m['pm_id']}.npz"
        if not fk.exists():
            continue
        k = np.load(fk)
        pm = np.load(fp) if fp.exists() else None
        for age, tag in ((cfg.QUOTE_AGE_PRIMARY_S, "6h"), (cfg.QUOTE_AGE_STRICT_S, "15m")):
            q = {name: standing_quote(at, k["t"], k["bid"], k["ask"], age)
                 for name, at in (("prev", prev), ("sig", op - cfg.SIGNAL_LEAD_S), ("in", op + cfg.ENTRY_AFTER_OPEN_S), ("out", cl))}
            mid = {n: (b + a) / 2.0 for n, (b, a) in q.items()}
            x = 100.0 * (mid["sig"] - mid["prev"])
            if pm is not None and len(pm["t"]):
                p_in = asof(op + cfg.ENTRY_AFTER_OPEN_S, pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
                p_out = asof(cl, pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
                p_prev = asof(prev, pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
                p_sig = asof(op - cfg.SIGNAL_LEAD_S, pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
            else:
                p_in = p_out = p_prev = p_sig = np.full(len(days), np.nan)
            ok = np.isfinite(x) & np.isfinite(mid["in"])
            frames.append(pd.DataFrame({
                "day": days[ok], "quote_age": tag, "ticker": m["ticker"], "question": m["question"], "fee_multiplier": float(m["kalshi_fee_multiplier"]),
                "x": x[ok], "bid_in": q["in"][0][ok], "ask_in": q["in"][1][ok], "mid_in": mid["in"][ok], "bid_out": q["out"][0][ok],
                "ask_out": q["out"][1][ok], "mid_out": mid["out"][ok], "y_kalshi": (np.sign(x) * 100.0 * (mid["out"] - mid["in"]))[ok],
                "x_polymarket": (100.0 * (p_sig - p_prev))[ok], "y_polymarket": (np.sign(x) * 100.0 * (p_out - p_in))[ok]}))
    df = pd.concat(frames, ignore_index=True)
    live_days = sorted(df[df.quote_age == "6h"].day.unique())
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(live_days)))
    oos_from = live_days[len(live_days) - n_oos]
    df["segment"] = np.where(df.day >= oos_from, "OOS", "IS")
    meta = {"markets": len(pairs), "markets_with_sessions": int(df.ticker.nunique()), "sessions_live": len(live_days), "first_session": live_days[0],
            "last_session": live_days[-1], "oos_from": oos_from, "oos_sessions": n_oos, "market_sessions_6h": int((df.quote_age == "6h").sum()),
            "market_sessions_15m": int((df.quote_age == "15m").sum()), "live_days": live_days}
    return df, meta


def tests(df: pd.DataFrame) -> list[dict]:
    rows = []
    for tag in ("6h", "15m"):
        d = df[(df.quote_age == tag) & df.mid_in.between(*cfg.ENTRY_BAND)]
        for thr in cfg.TEST_THRESHOLDS:
            s = d[d.x.abs() >= thr]
            k = s[s.y_kalshi.notna()]
            m = boot_mean({g: list(v) for g, v in k.groupby("day").y_kalshi})
            rows.append({"test": "K1 give-back on Kalshi's quoted mid", "quote_age": tag, "threshold": thr, "n": len(k), "dates": int(k.day.nunique()),
                         "markets": int(k.ticker.nunique()), "mean": m[0], "ci_lo": m[1], "ci_hi": m[2],
                         "no_exit_quote": int(s.y_kalshi.isna().sum()), "mean_abs_move": float(k.x.abs().mean()) if len(k) else float("nan")})
            both = s[s.y_kalshi.notna() & s.y_polymarket.notna()]
            for name, col in (("K2 the same nights, Polymarket's history price", "y_polymarket"), ("K2 the same nights, Kalshi's quoted mid", "y_kalshi")):
                m = boot_mean({g: list(v) for g, v in both.groupby("day")[col]})
                rows.append({"test": name, "quote_age": tag, "threshold": thr, "n": len(both), "dates": int(both.day.nunique()),
                             "markets": int(both.ticker.nunique()), "mean": m[0], "ci_lo": m[1], "ci_hi": m[2]})
            diff = both.assign(d=both.y_polymarket - both.y_kalshi)
            m = boot_mean({g: list(v) for g, v in diff.groupby("day").d})
            rows.append({"test": "K2 Polymarket minus Kalshi, paired", "quote_age": tag, "threshold": thr, "n": len(both), "dates": int(both.day.nunique()),
                         "markets": int(both.ticker.nunique()), "mean": m[0], "ci_lo": m[1], "ci_hi": m[2]})
    return rows


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    df, meta = build()
    live_days = meta.pop("live_days")
    tt = tests(df)
    trades, dropped = [], {}
    for v in cfg.VARIANTS:
        tag = "6h" if v.quote_age_s == cfg.QUOTE_AGE_PRIMARY_S else "15m"
        s = df[(df.quote_age == tag) & (df.x.abs() >= v.threshold) & df.mid_in.between(*cfg.ENTRY_BAND)]
        dropped[v.id] = int(s.mid_out.isna().sum())
        for c in cfg.COST_MULTIPLIERS:
            for r in s[s.mid_out.notna()].itertuples():
                f = fade_at_quotes(r.x, r.bid_in, r.ask_in, r.bid_out, r.ask_out, r.fee_multiplier, c)
                trades.append({"variant": v.id, "cost_mult": c, "segment": r.segment, "day": r.day, "ticker": r.ticker, "question": r.question,
                               "overnight_move_pp": r.x, "side": f["side"], "bid_in": r.bid_in, "ask_in": r.ask_in, "bid_out": r.bid_out,
                               "ask_out": r.ask_out, "entry": f["entry"], "exit": f["exit"], "gross_points": 100.0 * f["gross_mid"],
                               "spread_cost_points": 100.0 * f["spread_cost"], "fee_cost_points": 100.0 * f["fee_cost"],
                               "net_points": 100.0 * f["net"], "pnl": cfg.CONTRACTS * f["net"], "capital": f["capital"]})
    oos_from = meta["oos_from"]
    segments = (("IS", [d for d in live_days if d < oos_from]), ("OOS", [d for d in live_days if d >= oos_from]), ("ALL", live_days))
    rows, eq = [], []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            vt = [t for t in trades if t["variant"] == v.id and t["cost_mult"] == c]
            cap = pd.Series([t["capital"] for t in vt], index=[t["day"] for t in vt]).groupby(level=0).sum() if vt else pd.Series(dtype=float)
            K = float(cap.max()) if len(cap) else 0.0
            for seg, dl in segments:
                ds_ = set(dl)
                st = [t for t in vt if t["day"] in ds_]
                by: dict[str, list[dict]] = {}
                for t in st:
                    by.setdefault(t["day"], []).append(t)
                pc = np.array([sum(t["pnl"] for t in by.get(d, [])) for d in dl])
                m = closure_metrics(pc, dl, K, sum(t["capital"] for t in st), cfg.DAYS_PER_YEAR)
                b = boot_mean({d: [t["net_points"] for t in ts] for d, ts in by.items()})
                g = boot_mean({d: [t["gross_points"] for t in ts] for d, ts in by.items()})

                def avg(key):
                    return float(np.mean([t[key] for t in st])) if st else float("nan")

                rows.append({"segment": seg, "variant": v.id, "threshold": v.threshold, "quote_age_s": v.quote_age_s, "cost_mult": c, "sessions": len(dl),
                             "dates_traded": len(by), "trades": len(st), "markets": len({t["ticker"] for t in st}), "mean_net_points": b[0],
                             "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0], "gross_ci_lo": g[1], "gross_ci_hi": g[2],
                             "mean_spread_cost_points": avg("spread_cost_points"), "mean_fee_cost_points": avg("fee_cost_points"),
                             "cost_bp_of_capital": float(np.mean([(t["spread_cost_points"] + t["fee_cost_points"]) / 100.0 * cfg.CONTRACTS / t["capital"] * 1e4
                                                                  for t in st])) if st else float("nan"),
                             "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"), "pnl": float(pc.sum()),
                             "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)), **m})
                if seg == "ALL":
                    gp = np.array([sum(t["gross_points"] for t in by.get(d, [])) for d in dl])
                    eq += [{"variant": v.id, "cost_mult": c, "day": d, "pnl": float(a), "gross": float(g_)} for d, a, g_ in zip(dl, np.cumsum(pc), np.cumsum(gp))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in rows:
        peers = [x["daily_sharpe"] for x in rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["sessions"], len(cfg.VARIANTS), float(np.var(peers)), row["skew"],
                                                      row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")
    big = df[(df.x.abs() >= min(cfg.TEST_THRESHOLDS)) & df.mid_in.between(*cfg.ENTRY_BAND)]
    write_csv(RESULTS / "sessions.csv", big.to_dict("records"))
    write_csv(RESULTS / "tests.csv", tt)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    write_csv(RESULTS / "equity.csv", eq)
    d6 = df[(df.quote_age == "6h") & df.mid_in.between(*cfg.ENTRY_BAND)]
    sp = (d6.ask_in - d6.bid_in).dropna()
    (RESULTS / "run_meta.json").write_text(json.dumps({
        **meta, "dropped_no_exit_quote": dropped, "spread_at_entry_points": {"median": float(100 * sp.median()), "p25": float(100 * sp.quantile(.25)),
                                                                              "p75": float(100 * sp.quantile(.75)), "n": int(len(sp))},
        "fee_multipliers": sorted({float(x) for x in df.fee_multiplier.unique()}), "run_seconds": round(time.time() - t_run, 1)}, indent=1))
    print(json.dumps(meta), "| dropped for want of an exit quote:", dropped)
    for r in tt:
        print(f"{r['quote_age']:3} | {r['threshold']:4.0f}+ | {r['test'][:46]:46} | n {r['n']:4d} dates {r['dates']:3d} mkts {r['markets']:2d} | "
              f"{r['mean']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}]")
    print("seg var cost trades dates  net_pts [ci]             gross spread   fee   hit  sharpe  maxDD")
    for x in rows:
        print(f"{x['segment']:3} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['dates_traded']:5d} {x['mean_net_points']:7.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] {x['mean_gross_points']:6.2f} {x['mean_spread_cost_points']:6.2f} {x['mean_fee_cost_points']:5.2f} "
              f"{x['hit_rate']:5.2f} {x['sharpe']:6.2f} {x['max_drawdown']:6.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
