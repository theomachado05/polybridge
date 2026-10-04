"""S11 history: violations (part a) and propagation (part b) on one-minute mids, with half-spreads, fees and prints.

Run from `research/`:
    python -m s11_bundles.run              # everything, with the print check
    python -m s11_bundles.run --no-prints
"""
from __future__ import annotations

import gzip
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s6_monday_fade.run import verify as _verify

from . import config as cfg
from . import engine as en
from .pull import CACHE, S5, S9, ts

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "s11_bundles"
LIVE = CACHE / "live"
ET = ZoneInfo("America/New_York")
OOS = pd.Timestamp(cfg.OOS_START, tz=ET).timestamp()


# ---------------------------------------------------------------- costs

def calibrate() -> dict:
    """Half-spread by bundle kind from the first hour of this study's own live snapshots (METHOD.md section 2)."""
    lb = json.loads((HERE / "live_bundles.json").read_text())
    kind = {lb["markets"][i]["token"]: b["kind"] for b in lb["bundles"] for i in b["legs"]}
    per: dict[str, dict[str, list[float]]] = {}
    t0 = None
    with gzip.open(LIVE / "books.jsonl.gz", "rt") as fh:
        for line in fh:
            s = json.loads(line)
            t0 = t0 or s["t"]
            if s["t"] > t0 + 3600:
                break
            for tok, bk in s["books"].items():
                if bk["b"] and bk["a"]:
                    bid, ask = bk["b"][0][0], bk["a"][0][0]
                    if cfg.HALF_SPREAD_CALIBRATION_BAND[0] <= (bid + ask) / 2 <= cfg.HALF_SPREAD_CALIBRATION_BAND[1]:
                        per.setdefault(kind.get(tok, "?"), {}).setdefault(tok, []).append((ask - bid) / 2)
    out = {}
    for k, d in per.items():
        meds = [float(np.median(v)) for v in d.values()]
        out[k] = {"h": max(cfg.HALF_SPREAD_FLOOR, float(np.median(meds))), "markets": len(meds), "raw_median": float(np.median(meds)),
                  "p25": float(np.percentile(meds, 25)), "p75": float(np.percentile(meds, 75))}
    out["slice_start_utc"] = datetime.fromtimestamp(t0).astimezone(ET).isoformat() if t0 else None
    return out


# ---------------------------------------------------------------- data

_mem: dict[str, tuple[np.ndarray, np.ndarray] | None] = {}


def series(mid: str, src: str) -> tuple[np.ndarray, np.ndarray] | None:
    if mid in _mem:
        return _mem[mid]
    out = None
    for p in ((S9 / f"pm_{mid}.npz") if src == "s9" else None, S5 / f"pm_{mid}.npz", CACHE / f"pm_{mid}.npz"):
        if p is not None and p.exists():
            z = np.load(p)
            if len(z["t"]):
                out = (z["t"].astype(np.int64), z["p"].astype(float))
            break
    _mem[mid] = out
    return out


def grid_for(legs: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    a = max(int(x[0][0]) for x in legs)
    b = min(int(x[0][-1]) for x in legs)
    a -= a % 60
    return np.arange(a, b + 1, 60, dtype=np.int64) if b > a else np.array([], np.int64)


def is_weekend(t: float) -> bool:
    d = datetime.fromtimestamp(t, ET)
    wd, hr = d.weekday(), d.hour + d.minute / 60
    return (wd == 4 and hr >= 17) or wd == 5 or (wd == 6 and hr < 18)


def et_date(t: float) -> str:
    return datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- part (a): violations

def pair_episodes(b: dict, a_id: str, b_id: str, M: dict, out_of: dict, h: float) -> tuple[list[dict], dict]:
    sa, sb = series(a_id, b["source"]), series(b_id, b["source"])
    if sa is None or sb is None:
        return [], {}
    g = grid_for([sa, sb])
    if not len(g):
        return [], {}
    A, B = asof(g, *sa, max_age=cfg.PRICE_MAX_AGE_S), asof(g, *sb, max_age=cfg.PRICE_MAX_AGE_S)
    ok = ~np.isnan(A) & ~np.isnan(B)
    wk = np.array([is_weekend(x) for x in g[ok][::60]]) if ok.any() else np.array([], bool)   # hourly sample for exposure
    exposure = {"hours_weekend": float(wk.sum()), "hours_weekday": float((~wk).sum())}
    fa, fb = (M[a_id]["fee_rate"], M[a_id]["fee_exponent"]), (M[b_id]["fee_rate"], M[b_id]["fee_exponent"])
    recs = []
    for c in cfg.COST_MULTIPLIERS:
        e = en.pair_edge(A, B, h, fa, fb, c)
        flag = np.nan_to_num(e, nan=-1) > cfg.MIN_VIOLATION
        for i0, i1 in en.episodes(flag, g):
            gap_close = np.flatnonzero(ok[i0:] & (A[i0:] <= B[i0:]))
            j = i0 + int(gap_close[0]) if len(gap_close) else None
            lo, hi = cfg.PRICE_CLIP
            pa, pb = min(max(A[i0] - c * h, lo), hi), min(max(B[i0] + c * h, lo), hi)
            oa, ob = out_of.get(a_id), out_of.get(b_id)
            if oa is not None and ob is not None:
                settle, how = float(e[i0]) + ob - oa, "result"
            else:
                last = np.flatnonzero(ok)[-1]
                xa, xb = min(A[last] + c * h, hi), max(B[last] - c * h, lo)
                settle, how = float(e[i0]) + xb - float(en.fee(xb, *fb, c)) - xa - float(en.fee(xa, *fa, c)), "marked"
            if j is not None:
                xa, xb = min(A[j] + c * h, hi), max(B[j] - c * h, lo)
                pnl_close = float(e[i0]) + xb - float(en.fee(xb, *fb, c)) - xa - float(en.fee(xa, *fa, c))
            else:
                pnl_close = settle
            recs.append({"kind": b["kind"], "source": b["source"], "event": b["event"], "bundle": f"{b['event']}|{b.get('template', '')}|{b.get('orient', '')}",
                         "rich": a_id, "cheap": b_id, "rich_q": M[a_id]["question"], "cheap_q": M[b_id]["question"], "cost_mult": c,
                         "t_entry": int(g[i0]), "date": et_date(g[i0]), "weekend": is_weekend(g[i0]),
                         "segment": "OOS" if g[i0] >= OOS else "IS", "mid_rich": float(A[i0]), "mid_cheap": float(B[i0]),
                         "gap_points": float((A[i0] - B[i0]) * 100), "edge": float(e[i0]),
                         "minutes_beyond_cost": float((g[i1] - g[i0]) / 60 + 1),
                         "minutes_to_gap_close": float((g[j] - g[i0]) / 60) if j is not None else float("nan"),
                         "entry_rich": pa, "entry_cheap": pb, "capital": (1 - pa) + pb,
                         "pnl_close": pnl_close, "pnl_hold": settle, "settled_by": how,
                         "t_exit": int(g[j]) if j is not None else None,
                         "broken": bool(oa is not None and ob is not None and oa > ob)})
    return recs, exposure


def set_episodes(b: dict, M: dict, out_of: dict, h: float) -> tuple[list[dict], dict]:
    legs = b["legs"]
    ss = [series(i, b["source"]) for i in legs]
    # a member that resolved counts at its result after it closed; one with no prices at all and no result: untestable
    live = [s for s in ss if s is not None]
    if len(live) < 2:
        return [], {}
    g = grid_for(live)
    if not len(g):
        return [], {}
    mids = np.empty((len(legs), len(g)))
    for k, (i, s) in enumerate(zip(legs, ss)):
        x = asof(g, *s, max_age=cfg.PRICE_MAX_AGE_S) if s is not None else np.full(len(g), np.nan)
        o, ct = out_of.get(i), ts(M[i].get("closedTime"))
        if o is not None and ct is not None:
            x[g >= ct.timestamp()] = o
        mids[k] = x
    ok = ~np.isnan(mids).any(0)
    if not ok.any():
        return [], {"hours_weekend": 0.0, "hours_weekday": 0.0}
    wk = np.array([is_weekend(x) for x in g[ok][::60]])
    exposure = {"hours_weekend": float(wk.sum()), "hours_weekday": float((~wk).sum())}
    fees = [(M[i]["fee_rate"], M[i]["fee_exponent"]) for i in legs]
    outs = [out_of.get(i) for i in legs]
    total = mids.sum(0)
    recs = []
    n = len(legs)
    lo, hi = cfg.PRICE_CLIP
    for c in cfg.COST_MULTIPLIERS:
        ey, eno = en.basket_edge(np.where(np.isnan(mids), 0.5, mids), h, fees, c)
        for side, e in (("buy_yes", ey), ("buy_no", eno)):
            e = np.where(ok, e, np.nan)
            flag = np.nan_to_num(e, nan=-1) > cfg.MIN_VIOLATION
            for i0, i1 in en.episodes(flag, g):
                closed = ok[i0:] & ((total[i0:] >= 1) if side == "buy_yes" else (total[i0:] <= 1))
                cl = np.flatnonzero(closed)
                j = i0 + int(cl[0]) if len(cl) else None
                if all(o is not None for o in outs):
                    so = float(sum(outs))
                    settle, how = float(e[i0]) + ((so - 1) if side == "buy_yes" else (1 - so)), "result"
                else:
                    last = np.flatnonzero(ok)[-1]
                    jj = last
                    settle, how = None, "marked"
                if j is not None or settle is None:
                    jj = j if j is not None else jj
                    px = np.clip(mids[:, jj] - c * h, lo, hi) if side == "buy_yes" else np.clip(mids[:, jj] + c * h, lo, hi)
                    fx = sum(float(en.fee(p, *fees[k], c)) for k, p in enumerate(px))
                    unwind = (px.sum() - fx - 1.0) if side == "buy_yes" else (1.0 - px.sum() - fx)
                    pnl_x = float(e[i0]) + unwind
                    if settle is None:
                        settle = pnl_x
                    pnl_close = pnl_x if j is not None else settle
                else:
                    pnl_close = settle
                ent = np.clip(mids[:, i0] + (c * h if side == "buy_yes" else -c * h), lo, hi)
                recs.append({"kind": "negrisk", "source": b["source"], "event": b["event"], "bundle": b["event"], "side": side,
                             "members": n, "augmented": bool(b.get("negRiskAugmented")), "cost_mult": c, "t_entry": int(g[i0]),
                             "date": et_date(g[i0]), "weekend": is_weekend(g[i0]), "segment": "OOS" if g[i0] >= OOS else "IS",
                             "sum_mid": float(total[i0]), "gap_points": float((1 - total[i0]) * 100 if side == "buy_yes" else (total[i0] - 1) * 100),
                             "edge": float(e[i0]), "minutes_beyond_cost": float((g[i1] - g[i0]) / 60 + 1),
                             "minutes_to_gap_close": float((g[j] - g[i0]) / 60) if j is not None else float("nan"),
                             "capital": float(ent.sum()) if side == "buy_yes" else float(n - ent.sum()),
                             "pnl_close": pnl_close, "pnl_hold": settle, "settled_by": how, "t_exit": int(g[j]) if j is not None else None,
                             "broken": bool(all(o is not None for o in outs) and abs(sum(outs) - 1) > 1e-9),
                             "legs": legs, "entry_px": [float(x) for x in ent]})
    return recs, exposure


def cap(df: pd.DataFrame, size_col: str, hold_col: str | None = None, per_bundle: bool = True) -> pd.DataFrame:
    """At most MAX_NEW_TRADES_PER_DAY a day, largest first; one open trade per bundle (violations only: METHOD.md section 3)."""
    keep, open_until = [], {}
    for _, day in df.sort_values("t_entry").groupby("date", sort=True):
        n = 0
        for idx, r in day.sort_values(size_col, ascending=False).iterrows():
            if n >= cfg.MAX_NEW_TRADES_PER_DAY:
                break
            if per_bundle and open_until.get(r.bundle, -1) >= r.t_entry:
                continue
            keep.append(idx)
            n += 1
            ex = r.get(hold_col) if hold_col else None
            open_until[r.bundle] = float(ex) if ex is not None and ex == ex else float("inf")
    return df.loc[keep].sort_values("t_entry")


# ---------------------------------------------------------------- part (b): propagation

def propagation(b: dict, M: dict, H: dict) -> list[dict]:
    recs = []
    for a_id, b_id in b["pairs"]:
        sa, sb = series(a_id, b["source"]), series(b_id, b["source"])
        if sa is None or sb is None:
            continue
        g = grid_for([sa, sb])
        if len(g) < 120:
            continue
        P = {a_id: asof(g, *sa, max_age=cfg.PRICE_MAX_AGE_S), b_id: asof(g, *sb, max_age=cfg.PRICE_MAX_AGE_S)}
        for x, y in ((a_id, b_id), (b_id, a_id)):
            X, Y = P[x], P[y]
            k5 = cfg.JUMP_WINDOW_S // 60
            d_in, d_hold = cfg.TRADE_ENTRY_DELAY_S // 60, cfg.TRADE_HOLD_S // 60
            for i, jmp in en.jumps(g, X):
                if i + d_in + d_hold >= len(g) or np.isnan(Y[i]) or np.isnan(Y[i - k5]):
                    continue
                s = 1.0 if jmp > 0 else -1.0
                rec = {"kind": b["kind"], "source": b["source"], "event": b["event"], "bundle": f"{b['event']}|{b.get('template', '')}|{b.get('orient', '')}",
                       "jumper": x, "sibling": y, "sibling_q": M[y]["question"], "t": int(g[i]), "date": et_date(g[i]),
                       "weekend": is_weekend(g[i]), "segment": "OOS" if g[i] >= OOS else "IS", "jump_points": jmp,
                       "sibling_during_jump": s * (Y[i] - Y[i - k5]) * 100}
                for hz in cfg.HORIZONS_S:
                    m = hz // 60
                    rec[f"sibling_next_{m}m"] = s * (Y[i + m] - Y[i]) * 100 if i + m < len(Y) else float("nan")
                    rec[f"jumper_next_{m}m"] = s * (X[i + m] - X[i]) * 100 if i + m < len(X) else float("nan")
                pin, pout = Y[i + d_in], Y[i + d_in + d_hold]
                rec["sibling_entry_mid"] = pin
                if not (np.isnan(pin) or np.isnan(pout)) and cfg.ENTRY_BAND[0] <= pin <= cfg.ENTRY_BAND[1]:
                    f = (M[y]["fee_rate"], M[y]["fee_exponent"])
                    for c in cfg.COST_MULTIPLIERS:
                        e, pnl = en.taker_trade(pin, pout, jmp > 0, H[b["kind"]], f, c)
                        rec[f"entry_{c:g}x"], rec[f"pnl_{c:g}x"] = e, pnl
                    rec["t_entry"] = int(g[i + d_in])
                    rec["laggard"] = rec["sibling_during_jump"] < 0.5 * abs(jmp)
                recs.append(rec)
    return recs


# ---------------------------------------------------------------- statistics

def boot(df: pd.DataFrame, col: str) -> tuple[float, float, float, int, int]:
    d = df[df[col].notna()]
    if not len(d):
        return (float("nan"),) * 3 + (0, 0)
    by = d.groupby("date")[col].agg(["sum", "count"])
    m = float(d[col].mean())
    if len(by) < 5:
        return m, float("nan"), float("nan"), len(d), len(by)
    rng = np.random.default_rng(cfg.BOOT_SEED)
    pick = rng.integers(0, len(by), size=(cfg.N_BOOT, len(by)))
    s, n = by["sum"].to_numpy()[pick].sum(1), by["count"].to_numpy()[pick].sum(1)
    lo, hi = np.percentile(s / n, [2.5, 97.5])
    return m, float(lo), float(hi), len(d), len(by)


def perf(tr: pd.DataFrame, pnl_col: str, cap_col: str, t_col: str = "t_entry") -> dict:
    """Daily P&L over every calendar day of the span; capital base = the most capital opened on one day."""
    if not len(tr):
        return {}
    d = tr.assign(_d=pd.to_datetime(tr["date"]))
    daily_cap = d.groupby("_d")[cap_col].sum()
    K = float(daily_cap.max())
    pnl = d.groupby("_d")[pnl_col].sum()
    idx = pd.date_range(pnl.index.min(), pnl.index.max(), freq="D")
    pnl = pnl.reindex(idx, fill_value=0.0)
    r = pnl / K
    eq = K + pnl.cumsum()
    dd = (eq.cummax() - eq) / K                     # in units of the capital base (equity can go below zero)
    sd = r.std(ddof=1)
    months = r.groupby(r.index.to_period("M")).sum()
    years = max(len(idx) / 365.0, 1 / 365)
    return {"capital_base": K, "net_pnl": float(pnl.sum()), "sharpe": float(r.mean() / sd * math.sqrt(365)) if sd > 0 else float("nan"),
            "max_drawdown": float(dd.max()), "worst_month": float(months.min()), "turnover_per_year": float(d[cap_col].sum() / K / years),
            "days": len(idx), "equity": eq}


# ---------------------------------------------------------------- prints

_prints: dict[str, list[dict]] = {}


def prints_for(mid: str, cond: str, oldest: float, pt: ds.Throttle) -> tuple[list[dict], float]:
    f = CACHE / "prints" / f"{mid}.json"
    if mid not in _prints:
        if f.exists():
            _prints[mid] = json.loads(f.read_text())
        else:
            p = ds.pm_trades(cond, oldest, pt, max_pages=cfg.PRINT_PAGES) if cond else []
            p = [{k: x.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for x in p]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(p))
            _prints[mid] = p
    p = _prints[mid]
    first = min((float(x["timestamp"]) for x in p), default=float("inf"))
    return p, first


def verify_leg(mid: str, M: dict, side: str, px: float, at: float, pt: ds.Throttle) -> str:
    """'verified', 'not verified' or 'uncheckable' (the served prints start after the entry)."""
    p, first = prints_for(mid, M[mid].get("conditionId"), at, pt)
    if not p or first > at - cfg.PRINT_WINDOW_S:
        return "uncheckable"
    n, _ = _verify(p, side, px, at)
    return "verified" if n > 0 else "not verified"


def combine(states: list[str]) -> str:
    if "not verified" in states:
        return "not verified"
    if "uncheckable" in states:
        return "uncheckable"
    return "verified"


# ---------------------------------------------------------------- main

def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    hb = json.loads((HERE / "bundles.json").read_text())
    M = hb["markets"]
    out_of = json.loads((CACHE / "outcomes.json").read_text()) if (CACHE / "outcomes.json").exists() else {}
    out_of = {k: v for k, v in out_of.items() if v is not None}
    cal = calibrate()
    H = {k: cal[k]["h"] if k in cal else cfg.HALF_SPREAD_FLOOR for k in ("strike", "date", "negrisk")}
    (RESULTS / "calibration.json").write_text(json.dumps(cal, indent=1))
    print("half-spreads", H, flush=True)

    viol, expo, prop, coverage = [], [], [], {"strike": [0, 0], "date": [0, 0], "negrisk": [0, 0]}
    for b in hb["bundles"]:
        have = [series(i, b["source"]) is not None for i in b["legs"]]
        coverage[b["kind"]][0] += 1
        coverage[b["kind"]][1] += all(have)
        if b["kind"] == "negrisk":
            if not all(have):
                continue
            r, x = set_episodes(b, M, out_of, H["negrisk"])
            viol += r
            if x:
                expo.append({"kind": "negrisk", "bundle": b["event"], **x})
        else:
            for a_id, b_id in b["pairs"]:
                r, x = pair_episodes(b, a_id, b_id, M, out_of, H[b["kind"]])
                viol += r
                if x:
                    expo.append({"kind": b["kind"], "bundle": b["event"], "pair": f"{a_id}>{b_id}", "weekend_only": b.get("weekend_only", False), **x})
            prop += propagation(b, M, H)
    V, X, P = pd.DataFrame(viol), pd.DataFrame(expo), pd.DataFrame(prop)
    print(f"{len(V)} violation episodes, {len(P)} jumps; {time.time() - t_run:.0f}s", flush=True)
    V.drop(columns=[c for c in ("legs", "entry_px") if c in V], errors="ignore").to_csv(RESULTS / "episodes.csv", index=False)
    X.to_csv(RESULTS / "exposure.csv", index=False)
    P.to_csv(RESULTS / "jumps.csv", index=False)
    pd.to_pickle({"V": V, "P": P, "X": X, "H": H, "coverage": coverage}, CACHE / "run_state.pkl")

    # ---- trades: violation trade (primary exit: gap close or resolution; H: hold), capped
    no_prints = "--no-prints" in sys.argv
    pt = ds.Throttle(cfg.PULL_RATE)
    trades = []
    for c in cfg.COST_MULTIPLIERS:
        v = V[V.cost_mult == c].copy() if len(V) else V
        if len(v):
            v = cap(v, "edge", "t_exit")
            for _, r in v.iterrows():
                trades.append({"study": "violation", **{k: r[k] for k in ("kind", "event", "bundle", "cost_mult", "t_entry", "date", "weekend",
                                                                          "segment", "edge", "gap_points", "capital", "pnl_close", "pnl_hold",
                                                                          "settled_by", "broken")},
                               "side": r.get("side") if "side" in r else None, "rich": r.get("rich"), "cheap": r.get("cheap"),
                               "legs": r.get("legs"), "entry_px": r.get("entry_px"), "entry_rich": r.get("entry_rich"), "entry_cheap": r.get("entry_cheap")})
        p = P[P.get(f"pnl_{c:g}x", pd.Series(dtype=float)).notna()].copy() if len(P) and f"pnl_{c:g}x" in P else pd.DataFrame()
        if len(p):
            p = p.assign(abs_jump=p.jump_points.abs(), cost_mult=c)
            for variant, sub in (("P0", p), ("P1", p[p.laggard.astype(bool)])):
                sub = cap(sub.assign(t_entry=sub.t_entry.astype(int)), "abs_jump", per_bundle=False)
                for _, r in sub.iterrows():
                    e = r[f"entry_{c:g}x"]
                    trades.append({"study": variant, "kind": r.kind, "event": r.event, "bundle": r.bundle, "cost_mult": c, "t_entry": int(r.t_entry),
                                   "date": r.date, "weekend": r.weekend, "segment": r.segment, "jump_points": r.jump_points,
                                   "sibling": r.sibling, "side": "buy YES" if r.jump_points > 0 else "sell YES", "entry": e,
                                   "capital": e if r.jump_points > 0 else 1 - e, "pnl": r[f"pnl_{c:g}x"]})
    T = pd.DataFrame(trades)

    # ---- print check
    if len(T) and not no_prints:
        states = []
        for _, r in T.iterrows():
            at = float(r.t_entry)
            if r.study == "violation" and r.kind != "negrisk":
                s = combine([verify_leg(r.rich, M, "sell YES", float(r.entry_rich), at, pt),
                             verify_leg(r.cheap, M, "buy YES", float(r.entry_cheap), at, pt)])
            elif r.study == "violation":
                side = "buy YES" if r.side == "buy_yes" else "sell YES"
                s = combine([verify_leg(m, M, side, float(px), at, pt) for m, px in zip(r.legs, r.entry_px)])
            else:
                s = verify_leg(r.sibling, M, r.side, float(r.entry), at, pt)
            states.append(s)
        T["prints"] = states
    else:
        T["prints"] = "not checked"
    T.drop(columns=["legs", "entry_px"], errors="ignore").to_csv(RESULTS / "trades.csv", index=False)
    pd.to_pickle({"V": V, "P": P, "X": X, "H": H, "T": T, "coverage": coverage, "cal": cal}, CACHE / "run_state.pkl")
    print(f"done in {time.time() - t_run:.0f}s; {len(T)} trades", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
