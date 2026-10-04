from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import datetime
from itertools import combinations

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s5_big_moves.run import CACHE as S5_CACHE
from s6_monday_fade.run import closure_metrics, write_csv
from s8_open_referee.run import links as event_links
from s9_weekend_price_markets import run as s9

from . import config as cfg
from .run import CACHE, RESULTS, S9_CACHE, boot_mean, load_prints, trade, verify

ET = s9.ET
STOCK_RE = re.compile(r"\((META|TSLA|NVDA|GOOGL|AMZN|MSFT|AAPL|NFLX|PLTR)\)")


def activity(t: np.ndarray, p: np.ndarray, grid: np.ndarray, window: float) -> np.ndarray:
    ct = t[1:][np.abs(np.diff(p)) > 1e-9]
    return (np.searchsorted(ct, grid, side="right") - np.searchsorted(ct, grid - window, side="right")).astype(float)


def on_grid(s: dict, grid: np.ndarray, first: int = 3) -> dict:
    P = 100.0 * asof(grid.astype(np.int64), s["t"], s["p"], cfg.PM_MAX_AGE_S)
    return {"id": s["id"], "P": P, "A": activity(s["t"], s["p"], grid, cfg.ACTIVITY_WINDOW_S),
            "stale": activity(s["t"], s["p"], grid, cfg.STALE_WINDOW_S) == 0, "J": jumps_vec(P, first)}


class Acc:

    def __init__(self, n_clusters: int):
        self.n, self.s = n_clusters, {}

    def add(self, key, x: np.ndarray, y: np.ndarray, c: np.ndarray) -> None:
        ok = np.isfinite(x) & np.isfinite(y)
        if not ok.any():
            return
        x, y, c = x[ok], y[ok], c[ok]
        sxy, sxx, n = self.s.setdefault(key, (np.zeros(self.n), np.zeros(self.n), np.zeros(self.n)))
        sxy += np.bincount(c, x * y, self.n)
        sxx += np.bincount(c, x * x, self.n)
        n += np.bincount(c, None, self.n)

    def slope(self, key) -> dict:
        if key not in self.s:
            return {"slope": float("nan"), "se": float("nan"), "t": float("nan"), "n": 0, "clusters": 0}
        sxy, sxx, n = self.s[key]
        b = sxy.sum() / sxx.sum() if sxx.sum() > 0 else float("nan")
        se = math.sqrt(float(np.sum((sxy - b * sxx) ** 2))) / sxx.sum() if sxx.sum() > 0 else float("nan")
        return {"slope": float(b), "se": se, "t": float(b / se) if se > 0 else float("nan"), "n": int(n.sum()), "clusters": int((n > 0).sum())}

    def diff(self, k1, k2) -> tuple[float, float, float]:
        if k1 not in self.s or k2 not in self.s:
            return (float("nan"),) * 3
        a, b = self.s[k1], self.s[k2]
        keep = np.where((a[2] > 0) | (b[2] > 0))[0]
        rng = np.random.default_rng(cfg.BOOT_SEED)
        pick = keep[rng.integers(0, len(keep), size=(cfg.N_BOOT_MECH, len(keep)))]
        d = a[0][pick].sum(1) / a[1][pick].sum(1) - b[0][pick].sum(1) / b[1][pick].sum(1)
        lo, hi = np.percentile(d, [2.5, 97.5])
        return float(a[0].sum() / a[1].sum() - b[0].sum() / b[1].sum()), float(lo), float(hi)


def pair_bins(acc: Acc, kind: str, group: str, a: dict, b: dict, sign: float, cl: np.ndarray, first: int = 1) -> None:
    Pa, Pb = a["P"], b["P"]
    n = len(Pa)
    lo, hi = 100 * cfg.PAIR_BAND[0], 100 * cfg.PAIR_BAND[1]
    i = np.arange(max(first, 1), n)
    ref_ok = (Pa[i - 1] >= lo) & (Pa[i - 1] <= hi) & (Pb[i - 1] >= lo) & (Pb[i - 1] <= hi)
    i = i[ref_ok & np.isfinite(Pa[i]) & np.isfinite(Pb[i])]
    if not len(i):
        return
    da, db = Pa[i] - Pa[i - 1], sign * (Pb[i] - Pb[i - 1])
    a_act = a["A"][i] > b["A"][i]
    b_act = b["A"][i] > a["A"][i]
    sel = a_act | b_act
    x_act = np.where(a_act, da, db)
    x_thin = np.where(a_act, db, da)
    thin_stale = np.where(a_act, b["stale"][i], a["stale"][i])
    c = cl[i]
    for g in (group, "all"):
        acc.add((kind, g, "same bin", 5, "all"), x_act[sel], x_thin[sel], c[sel])
        for st, m in (("stale", sel & thin_stale), ("active", sel & ~thin_stale)):
            acc.add((kind, g, "same bin", 5, st), x_act[m], x_thin[m], c[m])
        for h in cfg.MECH_HORIZONS_S:
            k = h // cfg.BIN_S
            j = i + k
            okj = j < n
            fa = np.full(len(i), np.nan)
            fb = np.full(len(i), np.nan)
            fa[okj] = Pa[j[okj]] - Pa[i[okj]]
            fb[okj] = sign * (Pb[j[okj]] - Pb[i[okj]])
            y_thin, y_act = np.where(a_act, fb, fa), np.where(a_act, fa, fb)
            acc.add((kind, g, "active->thin", h // 60, "all"), x_act[sel], y_thin[sel], c[sel])
            acc.add((kind, g, "thin->active", h // 60, "all"), x_thin[sel], y_act[sel], c[sel])
            for st, m in (("stale", sel & thin_stale), ("active", sel & ~thin_stale)):
                acc.add((kind, g, "active->thin", h // 60, st), x_act[m], y_thin[m], c[m])


def jumps_vec(P: np.ndarray, first: int) -> dict[int, float]:
    lo, hi = 100 * cfg.JUMP_REF_BAND[0], 100 * cfg.JUMP_REF_BAND[1]
    best = np.zeros(len(P))
    for win, thr in cfg.JUMP_RULES:
        k = win // cfg.BIN_S
        if len(P) <= k:
            continue
        a, b = P[:-k], P[k:]
        with np.errstate(invalid="ignore"):
            d = np.where(np.isfinite(a) & np.isfinite(b) & (a >= lo) & (a <= hi), b - a, 0.0)
            d = np.where(np.abs(d) >= thr, d, 0.0)
        full = np.zeros(len(P))
        full[k:] = d
        best = np.where(np.abs(full) > np.abs(best), full, best)
    best[:first] = 0.0
    idx = np.nonzero(best)[0]
    return {int(i): float(best[i]) for i in idx}


def pickoffs(kind: str, a: dict, b: dict, sign: float, grid: np.ndarray, cl_keys: np.ndarray) -> list[dict]:
    out, last = [], -1e18
    cands = []
    lo, hi = 100 * cfg.PAIR_BAND[0], 100 * cfg.PAIR_BAND[1]
    for J, O in ((a, b), (b, a)):
        for i, j in J["J"].items():
            if J["A"][i] > O["A"][i] and O["stale"][i] and np.isfinite(O["P"][i]) and lo <= O["P"][i] <= hi:
                cands.append((i, j * sign, O))
    for i, d, other in sorted(cands, key=lambda x: (x[0], -abs(x[1]))):
        t = float(grid[i])
        if t - last < cfg.REFRACTORY_S:
            continue
        last = t
        out.append({"kind": kind, "t": t, "cluster": str(cl_keys[i]), "stale_market": other["id"], "dir": float(np.sign(d)), "jump": abs(d)})
    return out


def settle_trades(sigs: list[dict], series: dict[str, dict], cap_key: str) -> tuple[list[dict], int]:
    seen, by_cl, rows, dropped = set(), {}, [], 0
    for s in sorted(sigs, key=lambda x: (x["t"], x["stale_market"])):
        key = (s["stale_market"], s["t"])
        if key in seen:
            continue
        seen.add(key)
        if by_cl.get(s[cap_key], 0) >= cfg.PICKOFF_MAX_PER_DATE:
            continue
        m = series[s["stale_market"]]
        t_in, t_out = s["t"] + cfg.ENTRY_DELAY_S, s["t"] + cfg.ENTRY_DELAY_S + cfg.PICKOFF_EXIT_S
        p_in, p_out = (float(x) for x in asof(np.array([t_in, t_out], dtype=np.int64), m["t"], m["p"], cfg.PM_MAX_AGE_S))
        if not (np.isfinite(p_in) and cfg.ENTRY_BAND[0] <= p_in <= cfg.ENTRY_BAND[1]):
            continue
        if not np.isfinite(p_out):
            dropped += 1
            continue
        by_cl[s[cap_key]] = by_cl.get(s[cap_key], 0) + 1
        buy = s["dir"] > 0
        for c in cfg.COST_MULTIPLIERS:
            entry, gross, pnl = trade(buy, p_in, p_out, False, m["half"], m["fee_rate"], m["fee_exponent"], c)
            rows.append({**s, "cost_mult": c, "market_kind": m["mkind"], "question": m["question"], "side": "buy YES" if buy else "sell YES",
                         "p_entry": p_in, "entry": entry, "p_exit": p_out, "gross_points": 100 * gross, "cost_points": 100 * (gross - pnl),
                         "net_points": 100 * pnl, "pnl": cfg.CONTRACTS * pnl, "capital": cfg.CONTRACTS * (entry if buy else 1 - entry),
                         "condition": m.get("condition")})
    return rows, dropped


def load_questions() -> tuple[dict[str, dict], dict[str, dict[str, int]]]:
    dirs: dict[str, dict[str, int]] = {}
    src: dict[str, str] = {}
    qtext: dict[str, str] = {}
    for l in event_links():
        dirs.setdefault(l["market"], {}).setdefault(l["ticker"], 0)
        dirs[l["market"]][l["ticker"]] += l["direction"]
        src.setdefault(l["market"], l["source"])
        qtext[l["market"]] = l["question"]
    series = {}
    for mid in dirs:
        f = (S5_CACHE if src[mid] == "S5" else d4.CACHE) / f"pm_{mid.split(':')[1]}.npz"
        if not f.exists():
            continue
        pm = np.load(f)
        if len(pm["t"]) > 1:
            series[mid] = {"id": mid, "question": qtext[mid], "t": pm["t"], "p": pm["p"].astype(float), "half": cfg.EVENT_HALF_SPREAD,
                           "fee_rate": cfg.EVENT_FEE_RATE, "fee_exponent": 1.0, "mkind": "event question"}
    dirs = {m: {t: int(np.sign(v)) for t, v in d.items() if v != 0} for m, d in dirs.items() if m in series}
    return series, dirs


def ticker_group(t: str) -> str:
    if cfg.TICKER_CLASS.get(t) == "crude":
        return "oil"
    if t in ("SHY", "IEF", "TLT"):
        return "rates"
    return "other"


def type_b_pairs(dirs: dict[str, dict[str, int]]) -> list[tuple[str, str, float, str]]:
    by_t: dict[str, list[str]] = {}
    for m, d in dirs.items():
        for t in d:
            by_t.setdefault(t, []).append(m)
    signs: dict[tuple[str, str], set] = {}
    group: dict[tuple[str, str], str] = {}
    for t, ms in by_t.items():
        for a, b in combinations(sorted(ms), 2):
            signs.setdefault((a, b), set()).add(dirs[a][t] * dirs[b][t])
            group.setdefault((a, b), ticker_group(t))
    return [(a, b, float(next(iter(s))), group[(a, b)]) for (a, b), s in sorted(signs.items()) if len(s) == 1]


def price_series() -> dict[str, dict]:
    out = {}
    for m in s9.universe()["markets"]:
        if m["sign"] == 0 or m["asset_class"] not in ("crude", "gold", "stock"):
            continue
        f = S9_CACHE / f"pm_{m['id']}.npz"
        if not f.exists():
            continue
        pm = np.load(f)
        if len(pm["t"]) < 2:
            continue
        cls = m["asset_class"] if m["asset_class"] != "stock" else "stock:" + (STOCK_RE.search(m["question"]) or STOCK_RE.search(m["event_title"])).group(1)
        out[m["id"]] = {"id": m["id"], "question": m["question"], "cls": cls, "sign": float(m["sign"]), "t": pm["t"], "p": pm["p"].astype(float),
                        "half": {"crude": 0.005, "gold": 0.0125}.get(m["asset_class"], 0.025), "fee_rate": m["fee_rate"],
                        "fee_exponent": m["fee_exponent"], "condition": m["condition"], "mkind": "price market"}
    return out


def condition_ids(ids: list[str]) -> dict[str, str]:
    f = CACHE / "conditions.json"
    known = json.loads(f.read_text()) if f.exists() else {}
    pt = ds.Throttle(cfg.PRINT_RATE)
    for mid in ids:
        if mid in known:
            continue
        try:
            d = ds.get_json(f"{ds.GAMMA}/markets/{mid.split(':')[1]}", throttle=pt, allow=(404,))
            known[mid] = d.get("conditionId") if isinstance(d, dict) else None
        except Exception:  # noqa: BLE001
            known[mid] = None
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(known))
    return known


def ny_date(t: np.ndarray) -> np.ndarray:
    return np.array([datetime.fromtimestamp(float(x), ET).strftime("%Y-%m-%d") for x in t])


def book(tr: list[dict], cap_key: str, per_year: float, all_keys: list[str], oos_from: str, label: str) -> list[dict]:
    rows = []
    for c in cfg.COST_MULTIPLIERS:
        vt = [t for t in tr if t["cost_mult"] == c]
        cap = pd.Series([t["capital"] for t in vt], index=[t[cap_key] for t in vt]).groupby(level=0).sum() if vt else pd.Series(dtype=float)
        K = float(cap.max()) if len(cap) else 0.0
        for seg, keys in (("IS", [k for k in all_keys if k < oos_from]), ("OOS", [k for k in all_keys if k >= oos_from]), ("ALL", all_keys)):
            ks = set(keys)
            st = [t for t in vt if t[cap_key] in ks]
            by: dict[str, list[dict]] = {}
            for t in st:
                by.setdefault(t[cap_key], []).append(t)
            pc = np.array([sum(t["pnl"] for t in by.get(k, [])) for k in keys])
            m = closure_metrics(pc, keys, K, sum(t["capital"] for t in st), per_year) if len(keys) > 1 else {}
            b = boot_mean({k: [t["net_points"] for t in v] for k, v in by.items()})
            g = boot_mean({k: [t["gross_points"] for t in v] for k, v in by.items()})
            bv = boot_mean({k: [t["net_points"] for t in v if t["verified"]] for k, v in by.items()})
            chk = [t for t in st if t["checkable"]]
            rows.append({"book": label, "segment": seg, "cost_mult": c, "clusters": len(keys), "clusters_traded": len(by), "trades": len(st),
                         "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0], "gross_ci_lo": g[1], "gross_ci_hi": g[2],
                         "mean_cost_points": float(np.mean([t["cost_points"] for t in st])) if st else float("nan"),
                         "cost_bp_of_capital": float(np.mean([t["cost_points"] / 100 * cfg.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                         "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"), "pnl": float(pc.sum()), "capital_base": K, **m,
                         "checkable_trades": len(chk), "verified_trades": sum(t["verified"] for t in st),
                         "verified_share_of_checkable": sum(t["verified"] for t in chk) / len(chk) if chk else float("nan"),
                         "mean_net_points_verified": bv[0], "ci_lo_verified": bv[1], "ci_hi_verified": bv[2]})
    return rows


def main() -> int:
    t_run = time.time()
    qs, dirs = load_questions()
    pairs_b = type_b_pairs(dirs)
    t0 = min(int(s["t"][0]) for s in qs.values()) // cfg.BIN_S * cfg.BIN_S
    t1 = max(int(s["t"][-1]) for s in qs.values())
    grid = np.arange(t0, t1 + 1, cfg.BIN_S)
    dates = pd.to_datetime(grid, unit="s", utc=True).tz_convert("America/New_York").strftime("%Y-%m-%d").to_numpy()
    date_keys, cl = np.unique(dates, return_inverse=True)
    G = {m: on_grid(s, grid) for m, s in qs.items()}
    acc_b = Acc(len(date_keys))
    sig_b = []
    for a, b, sign, group in pairs_b:
        pair_bins(acc_b, "B", group, G[a], G[b], sign, cl)
        sig_b += pickoffs("B", G[a], G[b], sign, grid, dates)
    ps = price_series()
    cal = s9.calendar()
    acc_a = Acc(len(cal))
    sig_a = []
    pairs_a = [(q, pm, d * ps[pm]["sign"], cfg.TICKER_CLASS[t]) for q, dd in dirs.items() for t, d in dd.items() if t in cfg.TICKER_CLASS
               for pm in ps if ps[pm]["cls"] == cfg.TICKER_CLASS[t]]
    sa: dict[tuple, set] = {}
    for q, pm, sg, c in pairs_a:
        sa.setdefault((q, pm, c), set()).add(sg)
    pairs_a = [(q, pm, next(iter(v)), c) for (q, pm, c), v in sorted(sa.items()) if len(v) == 1]
    for wi, w in enumerate(cal):
        wg = np.arange(w["start"], w["entry"] + 1, cfg.BIN_S)
        cl_w = np.full(len(wg), wi)
        keys_w = np.full(len(wg), w["key"])
        GQ, GP = {}, {}
        for q, pm, sign, c in pairs_a:
            if q not in GQ:
                GQ[q] = on_grid(qs[q], wg, cfg.LOOKBACK_S // cfg.BIN_S)
            if pm not in GP:
                GP[pm] = on_grid(ps[pm], wg, cfg.LOOKBACK_S // cfg.BIN_S)
            if not (np.isfinite(GQ[q]["P"]).any() and np.isfinite(GP[pm]["P"]).any()):
                continue
            pair_bins(acc_a, "A", c.split(":")[0], GQ[q], GP[pm], sign, cl_w, first=cfg.LOOKBACK_S // cfg.BIN_S)
            sig_a += pickoffs("A", GQ[q], GP[pm], sign, wg, keys_w)

    rows = []
    for kind, acc in (("B", acc_b), ("A", acc_a)):
        for key in sorted(acc.s, key=str):
            rows.append({"pairs": kind, "group": key[1], "direction": key[2], "horizon_min": key[3], "follower": key[4], **acc.slope(key)})
    tests = []
    for kind, acc, groups in (("B", acc_b, ("all", "oil", "rates", "other")), ("A", acc_a, ("all", "crude", "gold", "stock"))):
        for g in groups:
            for h in (5, 15, 30):
                d = acc.diff((kind, g, "active->thin", h, "all"), (kind, g, "thin->active", h, "all"))
                tests.append({"test": "M1 active->thin minus thin->active", "pairs": kind, "group": g, "horizon_min": h, "diff": d[0], "ci_lo": d[1], "ci_hi": d[2]})
                d = acc.diff((kind, g, "active->thin", h, "stale"), (kind, g, "active->thin", h, "active"))
                tests.append({"test": "M2 stale follower minus active follower", "pairs": kind, "group": g, "horizon_min": h, "diff": d[0], "ci_lo": d[1], "ci_hi": d[2]})
            d = acc.diff((kind, g, "same bin", 5, "stale"), (kind, g, "same bin", 5, "active"))
            tests.append({"test": "M2 same-bin: stale follower minus active follower", "pairs": kind, "group": g, "horizon_min": 0, "diff": d[0], "ci_lo": d[1], "ci_hi": d[2]})

    series = {**qs, **ps}
    tr_b, drop_b = settle_trades([{**s, "date": s["cluster"]} for s in sig_b], series, "date")
    tr_a, drop_a = settle_trades([{**s, "weekend": s["cluster"]} for s in sig_a], series, "weekend")
    prints: dict[str, dict] = {}
    if "--no-prints" not in sys.argv:
        conds = condition_ids(sorted({t["stale_market"] for t in tr_b + tr_a if t["market_kind"] == "event question"}))
        for t in tr_b + tr_a:
            if t["market_kind"] == "event question":
                t["condition"] = conds.get(t["stale_market"])
        need: dict[str, tuple[str, list[float]]] = {}
        for t in tr_b + tr_a:
            if t["condition"]:
                need.setdefault(str(t["stale_market"]).replace(":", "_"), (t["condition"], []))[1].append(t["t"])
        prints = load_prints(need)
    for t in tr_b + tr_a:
        rec = prints.get(str(t["stale_market"]).replace(":", "_"))
        t["checkable"] = bool(rec is not None and rec.get("reach_oldest") is not None and rec["reach_oldest"] <= t["t"])
        n, size = verify(rec["prints"], t["side"] == "buy YES", t["entry"], t["t"]) if rec and rec["prints"] else (0, 0.0)
        t["verify_n"], t["verify_size"], t["verified"] = n, size, n > 0
        t.pop("condition", None)
    metrics = []
    for tr, key, per_year, label in ((tr_b, "date", 365.0, "B: question pairs, all hours"), (tr_a, "weekend", 52.0, "A: question-price market pairs, weekends")):
        if not tr:
            continue
        keys = sorted({t[key] for t in tr})
        oos_from = keys[len(keys) - int(math.ceil(cfg.OOS_FRACTION * len(keys)))]
        for t in tr:
            t["segment"] = "OOS" if t[key] >= oos_from else "IS"
        if key == "date":
            span = pd.date_range(keys[0], keys[-1]).strftime("%Y-%m-%d").tolist()
        else:
            span = sorted({w["key"] for w in cal if keys[0] <= w["key"] <= keys[-1]})
        metrics += book(tr, key, per_year, span, oos_from, label)

    R = RESULTS / "mechanism"
    R.mkdir(parents=True, exist_ok=True)
    write_csv(R / "slopes.csv", rows)
    write_csv(R / "tests.csv", tests)
    write_csv(R / "trades.csv", tr_b + tr_a)
    write_csv(R / "metrics.csv", metrics)
    meta = {"questions": len(qs), "type_b_pairs": len(pairs_b), "type_a_pairs": len(pairs_a), "dates": len(date_keys),
            "first_date": str(date_keys[0]), "last_date": str(date_keys[-1]), "price_markets": len(ps),
            "pickoff_signals_b": len(sig_b), "pickoff_signals_a": len(sig_a), "trades_b": len(tr_b) // 2, "trades_a": len(tr_a) // 2,
            "dropped_b": drop_b, "dropped_a": drop_a, "markets_checked_for_prints": len(prints),
            "print_errors": sum(1 for r in prints.values() if "error" in r), "run_seconds": round(time.time() - t_run, 1)}
    (R / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in rows:
        if r["group"] in ("all",) or r["direction"] != "same bin":
            print(f"{r['pairs']} {r['group']:6} {r['direction']:13} {r['horizon_min']:3d} {r['follower']:6} n {r['n']:8d} cl {r['clusters']:4d} slope {r['slope']:7.3f} t {r['t']:6.2f}")
    for r in tests:
        print(f"{r['test'][:45]:45} {r['pairs']} {r['group']:6} {r['horizon_min']:3d} diff {r['diff']:7.3f} [{r['ci_lo']:7.3f},{r['ci_hi']:7.3f}]")
    for x in metrics:
        print(f"{x['book'][:2]} {x['segment']:3} {x['cost_mult']:.0f}x trades {x['trades']:5d} cl {x['clusters_traded']:4d} net {x['mean_net_points']:6.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] gross {x['mean_gross_points']:6.2f} cost {x['mean_cost_points']:5.2f} chk {x['checkable_trades']} "
              f"ver {x['verified_trades']} ver_net {x['mean_net_points_verified']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
