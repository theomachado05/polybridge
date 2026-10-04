from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s6_monday_fade.run import closure_metrics, verify, write_csv
from s7_weekend_straddle.run import boot_diff, boot_mean
from s9_weekend_price_markets.run import _ts, calendar, trade

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s15_weekend_scare"
CACHE = HERE / ".cache"
UTC = timezone.utc


def universe() -> dict:
    return json.loads((HERE / "universe.json").read_text())


def half_spread(asset_class: str, kind: str) -> float:
    return cfg.HALF_SPREAD_WEEKLY if kind == "weekly" else cfg.HALF_SPREAD[asset_class]


def group(w: float) -> str:
    if w >= cfg.RISE:
        return "riser"
    if w <= -cfg.RISE:
        return "faller"
    return "quiet" if abs(w) < cfg.QUIET else "between"


def select(df: pd.DataFrame, v: cfg.Variant) -> pd.DataFrame:
    ok = (df.w >= v.threshold) & df.p_entry.between(*cfg.ENTRY_BAND) & df.p_exit.notna()
    if v.classes:
        ok &= df.asset_class.isin(v.classes)
    return df[ok].sort_values(["weekend", "w", "market"], ascending=[True, False, True]).groupby("weekend", sort=True).head(cfg.MAX_POSITIONS)


def _cached(mid: str) -> bool:
    try:
        np.load(CACHE / f"pm_{mid}.npz")["t"]
        return True
    except Exception:  # noqa: BLE001  (missing, or cut short by an interrupted pull)
        return False


def pull(workers: int = 6, rps: float = 5.0, resume: bool = False) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cal, pt, t0 = calendar(), ds.Throttle(rps), time.time()
    lo = np.array([w["start"] - 3600 for w in cal])
    hi = np.array([w["exit"] + 1800 for w in cal])
    first, fails = datetime.fromtimestamp(lo.min(), UTC), []

    def job(m):
        try:
            a = max(datetime.fromtimestamp(_ts(m["start"]), UTC), first).replace(second=0, microsecond=0)
            b = min(datetime.fromtimestamp(_ts(m["end"]), UTC) + timedelta(days=1), datetime.now(UTC))
            h = ds.pm_history({"token": m["token"]}, a, b, pt) if b > a else {"t": np.array([], dtype=np.int64), "p": np.array([], dtype=np.float32)}
            j = np.searchsorted(lo, h["t"], side="right") - 1
            keep = (j >= 0) & (h["t"] <= hi[np.maximum(j, 0)])
            np.savez_compressed(CACHE / f"pm_{m['id']}.npz", t=h["t"][keep], p=h["p"][keep], served=len(h["t"]))
            return int(keep.sum())
        except Exception as e:  # noqa: BLE001
            fails.append({"market": m["id"], "error": repr(e)[:200]})
            return 0

    every = universe()["markets"]
    ms = [m for m in every if not (resume and _cached(m["id"]))]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, ms))
    kept = [int(len(np.load(CACHE / f"pm_{m['id']}.npz")["t"])) if _cached(m["id"]) else -1 for m in every]
    (CACHE / "pull_meta.json").write_text(json.dumps({"t1": datetime.now(UTC).isoformat(), "markets": len(every), "pulled_this_pass": len(ms),
                                                      "on_disk": sum(1 for k in kept if k >= 0), "with_data": sum(1 for k in kept if k > 0),
                                                      "points_kept": int(sum(k for k in kept if k > 0)), "failures": fails,
                                                      "seconds": round(time.time() - t0, 1)}, indent=1))
    print(f"{time.time() - t0:.0f}s: pulled {len(ms)} this pass; {sum(1 for k in kept if k >= 0)} of {len(every)} markets on disk, "
          f"{sum(1 for k in kept if k > 0)} with weekend prices, {len(fails)} failures")


def build() -> tuple[pd.DataFrame, dict]:
    cal = calendar()
    starts, entries, exits = (np.array([w[k] for w in cal]) for k in ("start", "entry", "exit"))
    keys = np.array([w["key"] for w in cal])
    frames = []
    for m in universe()["markets"]:
        f = CACHE / f"pm_{m['id']}.npz"
        if not f.exists():
            continue
        pm = np.load(f)
        t, p = pm["t"], pm["p"].astype(float)
        if len(t) == 0:
            continue
        p_f, p_s, p_m = (asof(np.asarray(at, dtype=np.int64), t, p, cfg.PM_MAX_AGE_S) for at in (starts, entries, exits))
        closed, outcome = _ts(m.get("closed_time")), m.get("outcome")
        settled = np.isnan(p_m) & (closed is not None and outcome is not None) & (np.full(len(exits), closed if closed is not None else np.inf) <= exits)
        p_m = np.where(settled, outcome if outcome is not None else np.nan, p_m)
        live = np.isfinite(p_f) & (p_f >= cfg.LIVE_BAND[0]) & (p_f <= cfg.LIVE_BAND[1]) & np.isfinite(p_s)
        if not live.any():
            continue
        frames.append(pd.DataFrame({
            "weekend": keys[live], "market": m["id"], "event": m["event"], "asset_class": m["asset_class"], "kind": m["kind"], "sign": m["sign"],
            "question": m["question"], "volume": m["volume"], "fee_rate": m["fee_rate"], "fee_exponent": m["fee_exponent"],
            "p_start": p_f[live], "p_entry": p_s[live], "p_exit": p_m[live], "settled": settled[live], "entry_epoch": entries[live],
            "w": 100.0 * (p_s - p_f)[live], "y": 100.0 * (p_m - p_s)[live]}))
    df = pd.concat(frames, ignore_index=True)
    df["group"] = [group(w) for w in df.w]
    live_weekends = sorted(df.weekend.unique())
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(live_weekends)))
    oos_from = live_weekends[len(live_weekends) - n_oos]
    df["segment"] = np.where(df.weekend >= oos_from, "OOS", "IS")
    meta = {"weekends_live": len(live_weekends), "first_weekend": live_weekends[0], "last_weekend": live_weekends[-1], "oos_from": oos_from,
            "oos_weekends": n_oos, "markets_in_universe": len(universe()["markets"]), "markets_live": int(df.market.nunique()),
            "market_weekends": int(len(df)), "live_weekend_keys": live_weekends}
    return df, meta


def tests(df: pd.DataFrame) -> list[dict]:
    d = df[df.y.notna()]
    scopes = [("all fresh markets", d)] + [(f"class: {c}", d[d.asset_class == c]) for c, _ in cfg.ASSET_CLASSES] \
        + [(f"tag: {k}", d[d.kind == k]) for k in ("other event", "weekly", "leftover of an S9 event")] \
        + [("not in an S9 event (other and weekly)", d[d.kind != "leftover of an S9 event"]),
           ("oil \"hit high\" markets", d[(d.asset_class == "crude") & (d.sign == 1)])]
    rows = []
    for thr in cfg.TEST_THRESHOLDS:
        for name, s in scopes:
            quiet = {k: list(v) for k, v in s[s.w.abs() < cfg.QUIET].groupby("weekend").y}
            q = boot_mean(quiet)
            for side, sel in (("risers", s[s.w >= thr]), ("fallers", s[s.w <= -thr])):
                by = {k: list(v) for k, v in sel.groupby("weekend").y}
                m, dff = boot_mean(by), boot_diff(by, quiet)
                rows.append({"threshold": thr, "scope": name, "side": side, "n": len(sel), "weekends": len(by), "markets": int(sel.market.nunique()),
                             "mean_weekend_move": float(sel.w.mean()) if len(sel) else float("nan"), "mean_y": m[0], "ci_lo": m[1], "ci_hi": m[2],
                             "quiet_n": int(sum(len(v) for v in quiet.values())), "quiet_mean_y": q[0], "diff_vs_quiet": dff[0],
                             "diff_ci_lo": dff[1], "diff_ci_hi": dff[2]})
    return rows


def load_prints(need: dict[str, list[float]], cond: dict[str, str]) -> dict[str, dict]:
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


def main() -> int:
    if "--pull" in sys.argv:
        pull(1, 2.0, True) if "--gentle" in sys.argv else pull()
        return 0
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    df, meta = build()
    weekends_live = meta.pop("live_weekend_keys")
    tt = tests(df)

    trades = []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            for r in select(df, v).itertuples():
                h = half_spread(r.asset_class, r.kind)
                side, entry, pnl = trade("fade", r.w, r.p_entry, r.p_exit, bool(r.settled), h, r.fee_rate, r.fee_exponent, c)
                gross = -(r.p_exit - r.p_entry)
                trades.append({"variant": v.id, "cost_mult": c, "segment": r.segment, "weekend": r.weekend, "asset_class": r.asset_class,
                               "kind": r.kind, "market": r.market, "question": r.question, "weekend_move_pp": r.w, "side": side,
                               "p_start": r.p_start, "p_entry": r.p_entry, "entry": entry, "p_out": r.p_exit, "settled": bool(r.settled),
                               "gross_points": 100.0 * gross, "cost_points": 100.0 * (gross - pnl), "net_points": 100.0 * pnl,
                               "pnl": cfg.CONTRACTS * pnl, "capital": cfg.CONTRACTS * (1.0 - entry), "entry_epoch": float(r.entry_epoch)})
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
                gv = boot_mean({k: [t["gross_points"] for t in ts if t["verified"]] for k, ts in by.items()})
                rows.append({"segment": seg, "variant": v.id, "threshold": v.threshold, "classes": "all" if not v.classes else " ".join(v.classes),
                             "cost_mult": c, "weekends": len(wl), "weekends_traded": len(by), "trades": len(st), "markets": len({t["market"] for t in st}),
                             "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0], "gross_ci_lo": g[1], "gross_ci_hi": g[2],
                             "mean_cost_points": float(np.mean([t["cost_points"] for t in st])) if st else float("nan"),
                             "cost_bp_of_capital": float(np.mean([t["cost_points"] / 100.0 * cfg.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                             "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"), "pnl": float(pc.sum()),
                             "settled_trades": sum(t["settled"] for t in st), "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)),
                             **m, "checkable_trades": sum(t["checkable"] for t in st), "verified_trades": len(ver),
                             "verified_share": len(ver) / len(st) if st else float("nan"), "mean_net_points_verified": bv[0],
                             "ci_lo_verified": bv[1], "ci_hi_verified": bv[2], "mean_gross_points_verified": gv[0],
                             "gross_ci_lo_verified": gv[1], "gross_ci_hi_verified": gv[2], "pnl_verified": float(sum(t["pnl_verified"] for t in st))})
                if seg == "ALL":
                    gp = np.array([sum(t["gross_points"] for t in by.get(k, [])) for k in wl])
                    eq += [{"variant": v.id, "cost_mult": c, "weekend": k, "pnl": float(a), "gross": float(g_)} for k, a, g_ in zip(wl, np.cumsum(pc), np.cumsum(gp))]
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
        **meta, "pull_t1": pull_meta["t1"], "pull_failures": len(pull_meta["failures"]), "groups": {k: int(n) for k, n in df.group.value_counts().items()},
        "by_class": {k: int(n) for k, n in df.asset_class.value_counts().items()}, "by_kind": {k: int(n) for k, n in df.kind.value_counts().items()},
        "exit_missing": int(df.y.isna().sum()), "markets_checked_for_prints": len(prints), "run_seconds": round(time.time() - t_run, 1)}, indent=1))
    print(json.dumps(meta), dict(df.group.value_counts()))
    for r in tt:
        print(f"{r['threshold']:4.0f}+ | {r['scope'][:38]:38} | {r['side']:7} | n {r['n']:4d} wk {r['weekends']:3d} | y {r['mean_y']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] "
              f"| quiet {r['quiet_mean_y']:5.2f} (n {r['quiet_n']}) | diff {r['diff_vs_quiet']:6.2f} [{r['diff_ci_lo']:6.2f},{r['diff_ci_hi']:6.2f}]")
    print("seg var cost trades wk   net_pts [ci]             gross  cost   hit  sharpe  check  ver  gross_ver")
    for x in rows:
        print(f"{x['segment']:3} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['weekends_traded']:3d} {x['mean_net_points']:7.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] {x['mean_gross_points']:6.2f} {x['mean_cost_points']:5.2f} {x['hit_rate']:5.2f} "
              f"{x['sharpe']:6.2f} {x['checkable_trades']:5d} {x['verified_trades']:4d} {x['mean_gross_points_verified']:7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
