"""S9: Polymarket's price markets over the weekend, while the asset is shut (METHOD.md).

Run from `research/`:
    python -m s9_weekend_price_markets.run --pull     # the markets' prices around every weekend (not committed)
    python -m s9_weekend_price_markets.run            # the tests, every variant, the print check on the primary's entries
    python -m s9_weekend_price_markets.run --no-prints
"""
from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s6_monday_fade.run import closure_metrics, verify, write_csv
from s7_weekend_straddle.run import boot_mean
from s8_open_referee.run import links as event_links

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s9_weekend_price_markets"
CACHE = HERE / ".cache"
ET, UTC = ZoneInfo("America/New_York"), timezone.utc


# ---------------------------------------------------------------- the weekend clock

def _at(day: date, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def weekends(days: list[str], opens: np.ndarray) -> list[dict]:
    """Stock-market closures that contain a Saturday and a Sunday. `key` is the session that follows."""
    out = []
    for i in range(1, len(days)):
        a, b = date.fromisoformat(days[i - 1]), date.fromisoformat(days[i])
        sun = a + timedelta(days=(6 - a.weekday()) % 7 or 7)
        if sun < b:
            out.append({"key": days[i], "last_session": days[i - 1], "start": _at(a, cfg.START_ET), "entry": _at(sun, cfg.ENTRY_SUNDAY_ET),
                        "early": _at(sun, cfg.EARLY_EXIT_SUNDAY_ET), "exit": float(opens[i]) + cfg.EXIT_AFTER_OPEN_S})
    return out


def calendar() -> list[dict]:
    sess = en.sessions_from(np.load(S5_CACHE / "eq_SPY.npz")["t"])
    return weekends(list(sess.day), sess.open.to_numpy())


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    if "T" not in s:
        s = s.replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    return datetime.fromisoformat(s).timestamp()


# ---------------------------------------------------------------- fills

def fee(p: float, rate: float, exponent: float, c: float) -> float:
    return c * rate * (p * (1.0 - p)) ** exponent if 0.0 < p < 1.0 else 0.0


def trade(direction: str, w: float, p_in: float, p_out: float, settled: bool, h: float, rate: float, exponent: float, c: float) -> tuple[str, float, float]:
    """(side, entry in YES terms, net P&L per contract). A fade sells a rise and buys a fall; a follow is the mirror.
    A settled exit is the market's result: no spread, no fee."""
    lo, hi = cfg.PRICE_CLIP
    sell = (w > 0) == (direction == "fade")
    entry = min(max(p_in - c * h if sell else p_in + c * h, lo), hi)
    if settled:
        out, out_fee = p_out, 0.0
    else:
        out = min(max(p_out + c * h if sell else p_out - c * h, lo), hi)
        out_fee = fee(out, rate, exponent, c)
    pnl = (entry - out) if sell else (out - entry)
    return ("sell YES" if sell else "buy YES"), entry, pnl - fee(entry, rate, exponent, c) - out_fee


def select(df: pd.DataFrame, v: cfg.Variant) -> pd.DataFrame:
    """The market-weekends a variant trades: threshold, entry band, asset classes, an exit price, the cap."""
    px, st = ("p_exit", "settled") if v.exit == "monday" else ("p_early", "settled_early")
    ok = (df.w.abs() >= v.threshold) & df.p_entry.between(*cfg.ENTRY_BAND) & df[px].notna()
    if v.classes:
        ok &= df.asset_class.isin(v.classes)
    s = df[ok].assign(_aw=lambda d: d.w.abs()).sort_values(["weekend", "_aw", "market"], ascending=[True, False, True])
    return s.groupby("weekend", sort=True).head(cfg.MAX_POSITIONS).drop(columns="_aw").assign(p_out=lambda d: d[px], out_settled=lambda d: d[st])


# ---------------------------------------------------------------- data

def universe() -> dict:
    return json.loads((HERE / "universe.json").read_text())


def pull() -> None:
    """One-minute prices of every market, kept only inside the weekend windows (an hour before the start to half an
    hour after the exit)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cal, pt, t0 = calendar(), ds.Throttle(5.0), time.time()
    lo = np.array([w["start"] - 3600 for w in cal])
    hi = np.array([w["exit"] + 1800 for w in cal])
    first, fails = datetime.fromtimestamp(lo.min(), UTC), []

    def job(m):
        try:
            a = max(datetime.fromtimestamp(_ts(m["start"]), UTC), first).replace(second=0, microsecond=0)
            b = min(datetime.fromtimestamp(_ts(m["end"]), UTC) + timedelta(days=1), datetime.now(UTC))
            if b <= a:
                h = {"t": np.array([], dtype=np.int64), "p": np.array([], dtype=np.float32)}
            else:
                h = ds.pm_history({"token": m["token"]}, a, b, pt)
            j = np.searchsorted(lo, h["t"], side="right") - 1
            keep = (j >= 0) & (h["t"] <= hi[np.maximum(j, 0)])
            np.savez_compressed(CACHE / f"pm_{m['id']}.npz", t=h["t"][keep], p=h["p"][keep], served=len(h["t"]))
            return int(keep.sum())
        except Exception as e:  # noqa: BLE001
            fails.append({"market": m["id"], "error": repr(e)[:200]})
            return 0

    ms = universe()["markets"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        pts = list(ex.map(job, ms))
    (CACHE / "pull_meta.json").write_text(json.dumps({"t1": datetime.now(UTC).isoformat(), "markets": len(ms), "with_data": sum(1 for p in pts if p),
                                                      "points_kept": int(sum(pts)), "failures": fails, "seconds": round(time.time() - t0, 1)}, indent=1))
    print(f"{time.time() - t0:.0f}s: {len(ms)} markets, {sum(1 for p in pts if p)} with weekend prices, {sum(pts):,} points kept, {len(fails)} failures")
    for f in fails[:8]:
        print("  failure:", f)


def build() -> tuple[pd.DataFrame, dict]:
    cal = calendar()
    starts, entries, earlies, exits = (np.array([w[k] for w in cal]) for k in ("start", "entry", "early", "exit"))
    keys = np.array([w["key"] for w in cal])
    frames, missing = [], 0
    for m in universe()["markets"]:
        f = CACHE / f"pm_{m['id']}.npz"
        if not f.exists():
            missing += 1
            continue
        pm = np.load(f)
        t, p = pm["t"], pm["p"].astype(float)
        if len(t) == 0:
            continue

        def get(at):
            return asof(np.asarray(at, dtype=np.int64), t, p, cfg.PM_MAX_AGE_S)

        p_f, p_s, p_e, p_m = get(starts), get(entries), get(earlies), get(exits)
        closed, outcome = _ts(m.get("closed_time")), m.get("outcome")
        resolved = closed is not None and outcome is not None

        def settle(px, at):
            s = np.isnan(px) & resolved & (np.full(len(at), closed if resolved else np.inf) <= at)
            return np.where(s, outcome if resolved else np.nan, px), s

        p_m, s_m = settle(p_m, exits)
        p_e, s_e = settle(p_e, earlies)
        live = np.isfinite(p_f) & (p_f >= cfg.LIVE_BAND[0]) & (p_f <= cfg.LIVE_BAND[1]) & np.isfinite(p_s)
        if not live.any():
            continue
        frames.append(pd.DataFrame({
            "weekend": keys[live], "market": m["id"], "event": m["event"], "asset_class": m["asset_class"], "label": m["label"],
            "question": m["question"], "sign": m["sign"], "fee_rate": m["fee_rate"], "fee_exponent": m["fee_exponent"],
            "p_start": p_f[live], "p_entry": p_s[live], "p_early": p_e[live], "p_exit": p_m[live], "settled": s_m[live],
            "settled_early": s_e[live], "entry_epoch": entries[live], "w": 100.0 * (p_s - p_f)[live], "y": 100.0 * (p_m - p_s)[live],
            "y_early": 100.0 * (p_e - p_s)[live]}))
    df = pd.concat(frames, ignore_index=True)
    live_weekends = sorted(df.weekend.unique())
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(live_weekends)))
    oos_from = live_weekends[len(live_weekends) - n_oos]
    df["segment"] = np.where(df.weekend >= oos_from, "OOS", "IS")

    # the weekend move in the odds of oil-linked event questions (T2)
    by_q: dict[str, dict] = {}
    for l in event_links():
        if l["ticker"] in cfg.OIL_TICKERS:
            q = by_q.setdefault(l["market"], {"source": l["source"], "d": 0})
            q["d"] += l["direction"]
    xs = []
    for mid, q in sorted(by_q.items()):
        f = (S5_CACHE if q["source"] == "S5" else d4.CACHE) / f"pm_{mid.split(':')[1]}.npz"
        if q["d"] == 0 or not f.exists():
            continue
        pm = np.load(f)
        if len(pm["t"]) == 0:
            continue
        q_f = asof(starts.astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
        q_s = asof(entries.astype(np.int64), pm["t"], pm["p"].astype(float), cfg.PM_MAX_AGE_S)
        ok = np.isfinite(q_f) & np.isfinite(q_s) & (q_f >= cfg.LIVE_BAND[0]) & (q_f <= cfg.LIVE_BAND[1])
        xs.append(np.where(ok, np.sign(q["d"]) * 100.0 * (q_s - q_f), np.nan))
    x = pd.DataFrame({"weekend": keys, "x": np.nanmean(np.vstack(xs), axis=0) if xs else np.nan,
                      "x_questions": np.isfinite(np.vstack(xs)).sum(axis=0) if xs else 0})
    df = df.merge(x, on="weekend", how="left")
    meta = {"weekends_in_calendar": len(cal), "weekends_live": len(live_weekends), "first_weekend": live_weekends[0], "last_weekend": live_weekends[-1],
            "oos_from": oos_from, "oos_weekends": n_oos, "markets_in_universe": len(universe()["markets"]), "markets_without_file": missing,
            "markets_live": int(df.market.nunique()), "market_weekends": int(len(df)), "oil_event_questions": len(xs),
            "weekends_with_oil_odds": int(np.isfinite(x.x).sum()), "live_weekend_keys": live_weekends}
    return df, meta


# ---------------------------------------------------------------- tests before costs

def tests(df: pd.DataFrame) -> list[dict]:
    rows = []
    groups = [("all", df)] + [(c, df[df.asset_class == c]) for c, _ in cfg.ASSET_CLASSES]
    for thr in cfg.TEST_THRESHOLDS:
        for name, g in groups:
            for col, window in (("y", "to the next session 09:40"), ("y_early", "to Sunday 19:00")):
                s = g[(g.w.abs() >= thr) & g[col].notna()]
                m = boot_mean({k: list(np.sign(v.w) * v[col]) for k, v in s.groupby("weekend")})
                rows.append({"test": "T1 give-back", "threshold": thr, "markets": name, "window": window, "n": len(s),
                             "weekends": int(s.weekend.nunique()), "mean": m[0], "ci_lo": m[1], "ci_hi": m[2],
                             "mean_abs_weekend_move": float(s.w.abs().mean()) if len(s) else float("nan"),
                             "settled": int(s["settled" if col == "y" else "settled_early"].sum())})
    c = df[(df.asset_class == "crude") & (df.sign != 0) & df.x.notna()]
    for col, name in (("w", "weekend move of the oil price markets on the weekend move of oil-linked event odds"),
                      ("y", "reopen move (to the next session 09:40) on the weekend move of oil-linked event odds"),
                      ("y_early", "reopen move (to Sunday 19:00) on the weekend move of oil-linked event odds")):
        s = c[c[col].notna()]
        rows.append({"test": "T2 link", "markets": "crude, signed", "window": name, "weekends": int(s.weekend.nunique()),
                     **en.clustered_slope(s.x.to_numpy(), (s.sign * s[col]).to_numpy(), s.weekend.to_numpy())})
    for name, g in (("all", df), ("crude", df[df.asset_class == "crude"])):
        for thr in (0.0, 5.0):
            s = g[(g.w.abs() >= thr) & g.y.notna()]
            rows.append({"test": "T3 slope of the reopen move on the weekend move", "threshold": thr, "markets": name,
                         "window": "to the next session 09:40", "weekends": int(s.weekend.nunique()),
                         **en.clustered_slope(s.w.to_numpy(), s.y.to_numpy(), s.weekend.to_numpy())})
    return rows


# ---------------------------------------------------------------- prints

def load_prints(need: dict[str, list[float]], cond: dict[str, str]) -> dict[str, dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    pt, out = ds.Throttle(4.0), {}
    for mid, at in sorted(need.items()):
        f = CACHE / f"prints_{mid}.json"
        if f.exists():
            out[mid] = json.loads(f.read_text())
            continue
        rec = {"reach_oldest": None, "served": 0, "prints": []}
        try:
            raw = ds.pm_trades(cond[mid], min(at) - cfg.PRINT_WINDOW_S, pt, max_pages=cfg.PRINT_PAGES)
            ts, ats = np.array([float(t.get("timestamp", 0)) for t in raw]), np.array(sorted(at))
            keep = [t for t, s in zip(raw, ts) if np.min(np.abs(ats - s)) <= cfg.PRINT_WINDOW_S]
            rec = {"reach_oldest": float(ts.min()) if len(ts) else None, "served": len(raw),
                   "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]}
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        out[mid] = rec
    return out


# ---------------------------------------------------------------- run

def main() -> int:
    if "--pull" in sys.argv:
        pull()
        return 0
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    df, meta = build()
    weekends_live = meta.pop("live_weekend_keys")
    tt = tests(df)

    trades = []
    for v in cfg.VARIANTS:
        sel = select(df, v)
        for c in cfg.COST_MULTIPLIERS:
            for r in sel.itertuples():
                h = cfg.HALF_SPREAD[r.asset_class]
                side, entry, pnl = trade(v.direction, r.w, r.p_entry, r.p_out, bool(r.out_settled), h, r.fee_rate, r.fee_exponent, c)
                gross = (-1.0 if v.direction == "fade" else 1.0) * np.sign(r.w) * (r.p_out - r.p_entry)
                trades.append({"variant": v.id, "cost_mult": c, "segment": r.segment, "weekend": r.weekend, "asset_class": r.asset_class,
                               "market": r.market, "question": r.question, "weekend_move_pp": r.w, "side": side, "p_start": r.p_start,
                               "p_entry": r.p_entry, "entry": entry, "p_out": r.p_out, "settled": bool(r.out_settled),
                               "gross_points": 100.0 * gross, "cost_points": 100.0 * (gross - pnl), "net_points": 100.0 * pnl,
                               "pnl": cfg.CONTRACTS * pnl, "capital": cfg.CONTRACTS * (entry if side == "buy YES" else 1.0 - entry),
                               "entry_epoch": float(r.entry_epoch)})

    prints: dict[str, dict] = {}
    if "--no-prints" not in sys.argv:
        need: dict[str, list[float]] = {}
        for t in trades:
            if t["variant"] == cfg.PRIMARY:
                need.setdefault(t["market"], []).append(t["entry_epoch"])
        prints = load_prints(need, {m["id"]: m["condition"] for m in universe()["markets"]})
    for t in trades:
        rec = prints.get(t["market"])
        reach = rec is not None and rec.get("reach_oldest") is not None and rec["reach_oldest"] <= t["entry_epoch"] - cfg.PRINT_WINDOW_S
        n, size = verify(rec["prints"], t["side"], t["entry"], t["entry_epoch"]) if rec and rec["prints"] else (0, 0.0)
        t["checkable"], t["verify_n"], t["verify_size"], t["verified"] = bool(reach), n, size, n > 0
        t["pnl_verified"] = t["pnl"] * min(size, cfg.CONTRACTS) / cfg.CONTRACTS if n else 0.0

    oos_from = meta["oos_from"]
    segments = (("IS", [k for k in weekends_live if k < oos_from]), ("OOS", [k for k in weekends_live if k >= oos_from]), ("ALL", weekends_live))
    rows, eq = [], []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            vt = [t for t in trades if t["variant"] == v.id and t["cost_mult"] == c]
            cap = pd.Series([t["capital"] for t in vt], index=[t["weekend"] for t in vt]).groupby(level=0).sum() if vt else pd.Series(dtype=float)
            K = float(cap.max()) if len(cap) else 0.0
            for seg, wl in segments:
                ws = set(wl)
                st = [t for t in vt if t["weekend"] in ws]
                by: dict[str, list[dict]] = {}
                for t in st:
                    by.setdefault(t["weekend"], []).append(t)
                pc = np.array([sum(t["pnl"] for t in by.get(k, [])) for k in wl])
                m = closure_metrics(pc, wl, K, sum(t["capital"] for t in st), cfg.WEEKENDS_PER_YEAR)
                b = boot_mean({k: [t["net_points"] for t in ts] for k, ts in by.items()})
                g = boot_mean({k: [t["gross_points"] for t in ts] for k, ts in by.items()})
                ver = [t for t in st if t["verified"]]
                bv = boot_mean({k: [t["net_points"] for t in ts if t["verified"]] for k, ts in by.items()})
                best = max((sum(t["pnl"] for t in ts) for ts in by.values()), default=float("nan"))
                rows.append({"segment": seg, "variant": v.id, "threshold": v.threshold, "direction": v.direction, "exit": v.exit,
                             "classes": "all" if not v.classes else " ".join(v.classes), "cost_mult": c, "weekends": len(wl),
                             "weekends_traded": len(by), "trades": len(st), "markets": len({t["market"] for t in st}),
                             "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0], "gross_ci_lo": g[1],
                             "gross_ci_hi": g[2], "mean_cost_points": float(np.mean([t["cost_points"] for t in st])) if st else float("nan"),
                             "cost_bp_of_capital": float(np.mean([t["cost_points"] / 100.0 * cfg.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                             "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"), "pnl": float(pc.sum()),
                             "best_weekend_pnl": best, "settled_trades": sum(t["settled"] for t in st),
                             "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)), **m,
                             "checkable_trades": sum(t["checkable"] for t in st), "verified_trades": len(ver),
                             "verified_share": len(ver) / len(st) if st else float("nan"),
                             "mean_net_points_verified": bv[0], "ci_lo_verified": bv[1], "ci_hi_verified": bv[2],
                             "pnl_verified": float(sum(t["pnl_verified"] for t in st))})
                if seg == "ALL":
                    pv = np.array([sum(t["pnl_verified"] for t in by.get(k, [])) for k in wl])
                    gp = np.array([sum(t["gross_points"] for t in by.get(k, [])) for k in wl])
                    eq += [{"variant": v.id, "cost_mult": c, "weekend": k, "pnl": float(a), "pnl_verified": float(b_), "gross": float(g_)}
                           for k, a, b_, g_ in zip(wl, np.cumsum(pc), np.cumsum(pv), np.cumsum(gp))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in rows:
        peers = [x["daily_sharpe"] for x in rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["weekends"], len(cfg.VARIANTS), float(np.var(peers)), row["skew"],
                                                      row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")

    write_csv(RESULTS / "weekends.csv", df.to_dict("records"))
    write_csv(RESULTS / "tests.csv", tt)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    write_csv(RESULTS / "equity.csv", eq)
    pull_meta = json.loads((CACHE / "pull_meta.json").read_text())
    (RESULTS / "run_meta.json").write_text(json.dumps({
        **meta, "pull_t1": pull_meta["t1"], "pull_failures": len(pull_meta["failures"]),
        "market_weekends_by_class": {k: int(n) for k, n in df.asset_class.value_counts().items()},
        "moves_5pt": int((df.w.abs() >= 5).sum()), "moves_10pt": int((df.w.abs() >= 10).sum()),
        "exit_dropped_no_price_not_closed": int((df.w.abs() >= 5).sum() - ((df.w.abs() >= 5) & df.y.notna()).sum()),
        "markets_checked_for_prints": len(prints), "half_spread": cfg.HALF_SPREAD, "run_seconds": round(time.time() - t_run, 1)}, indent=1))

    print(json.dumps(meta), "| 5+ moves", int((df.w.abs() >= 5).sum()), "| 10+", int((df.w.abs() >= 10).sum()))
    for r in tt:
        if "slope" in r:
            print(f"{r['test'][:12]:12} | {r['markets'][:13]:13} | {str(r.get('threshold', '')):4} | {r['window'][:62]:62} | n {r['n']:5d} wk {r['weekends']:3d} "
                  f"slope {r['slope']:7.3f} t {r['t']:6.2f}")
        else:
            print(f"{r['test'][:12]:12} | {r['markets'][:13]:13} | {r['threshold']:4.0f} | {r['window'][:62]:62} | n {r['n']:5d} wk {r['weekends']:3d} "
                  f"mean {r['mean']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] settled {r['settled']}")
    print("seg var cost trades wk   net_pts [ci]             gross  cost   hit  sharpe  maxDD  settled check  ver")
    for x in rows:
        print(f"{x['segment']:3} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['weekends_traded']:3d} {x['mean_net_points']:7.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] {x['mean_gross_points']:6.2f} {x['mean_cost_points']:5.2f} {x['hit_rate']:5.2f} "
              f"{x['sharpe']:6.2f} {x['max_drawdown']:6.3f} {x['settled_trades']:5d} {x['checkable_trades']:5d} {x['verified_trades']:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
