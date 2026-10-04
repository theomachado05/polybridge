from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s4_linked_assets.data import CACHE as S4_CACHE
from s6_monday_fade.run import closure_metrics, write_csv
from s9_weekend_price_markets.run import CACHE as S9_CACHE, calendar

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s12_resting_orders"
CACHE = HERE / ".cache"
S8_RESULTS = RESEARCH / "results" / "s8_open_referee"
S9_RESULTS = RESEARCH / "results" / "s9_weekend_price_markets"
S9_UNIVERSE = RESEARCH / "s9_weekend_price_markets" / "universe.json"
UTC = timezone.utc
EPS = 1e-9


def orders() -> pd.DataFrame:
    uni = {m["id"]: m for m in json.loads(S9_UNIVERSE.read_text())["markets"]}
    exits = {w["key"]: w["exit"] for w in calendar()}
    t9 = pd.read_csv(S9_RESULTS / "trades.csv")
    t9 = t9[(t9.variant == cfg.S9_VARIANT) & (t9.cost_mult == 1.0)]
    wk = pd.read_csv(S9_RESULTS / "weekends.csv").set_index(["weekend", "market"])
    rows = []
    for r in t9.itertuples():
        m = uni[str(r.market)]
        f = wk.loc[(r.weekend, r.market)]
        rows.append({"sample": "S9", "group": r.weekend, "segment": r.segment, "market": str(r.market), "condition": m["condition"],
                     "token": m["token"], "asset_class": r.asset_class, "question": r.question, "move_pp": r.weekend_move_pp,
                     "side": 1 if r.side == "sell YES" else -1, "t_in": float(r.entry_epoch), "mid_in": float(r.p_entry),
                     "t_exit": float(exits[r.weekend]), "mid_exit": float(r.p_out), "settled": bool(r.settled),
                     "half_spread": cfg.S9_HALF_SPREAD[r.asset_class], "fee_rate": float(f.fee_rate), "fee_exponent": float(f.fee_exponent),
                     "mid_source": str(S9_CACHE / f"pm_{r.market}.npz")})
    sess = en.sessions_from(np.load(S5_CACHE / "eq_SPY.npz")["t"]).set_index("day")
    mo = pd.read_csv(S8_RESULTS / "mornings.csv")
    mo = mo[(mo.x.abs() >= cfg.S8_MIN_MOVE_PP) & mo.p_0940.between(*cfg.S8_ENTRY_BAND)]
    for r in mo.itertuples():
        mid = r.market.split(":")[1]
        rows.append({"sample": "S8", "group": r.day, "segment": r.segment, "market": mid, "condition": None, "token": None,
                     "asset_class": "event", "question": r.question, "move_pp": r.x, "side": 1 if r.x > 0 else -1,
                     "t_in": float(r.entry_epoch), "mid_in": float(r.p_0940), "t_exit": float(sess.loc[r.day, "close"]),
                     "mid_exit": float(r.p_close), "settled": False, "half_spread": cfg.S8_HALF_SPREAD, "fee_rate": cfg.S8_FEE_RATE,
                     "fee_exponent": cfg.S8_FEE_EXPONENT,
                     "mid_source": str((S5_CACHE if r.source == "S5" else S4_CACHE) / f"pm_{mid}.npz")})
    return pd.DataFrame(rows)


def pm_trades(condition_id: str, oldest_needed: float, pt: ds.Throttle, page: int = 10000, max_pages: int = 2) -> tuple[list[dict], bool]:
    out: list[dict] = []
    for i in range(max_pages):
        d = ds.get_json(ds.DATA_API, {"market": condition_id, "limit": page, "offset": i * page, "takerOnly": "true"},
                        throttle=pt, allow=(400, 404))
        if not isinstance(d, list) or not d:
            return out, isinstance(d, list)
        out.extend(d)
        if len(d) < page:
            return out, True
        if float(d[-1].get("timestamp", 0)) < oldest_needed:
            return out, False
    return out, False


def keep_window(ts: np.ndarray, starts: np.ndarray, width: float) -> np.ndarray:
    starts = np.sort(starts)
    j = np.searchsorted(starts, ts, side="right") - 1
    ok = j >= 0
    out = np.zeros(len(ts), bool)
    out[ok] = ts[ok] - starts[j[ok]] <= width
    return out


def pull() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    od = orders()
    pt = ds.Throttle(cfg.PRINT_RATE)
    t0 = time.time()
    for (sample, mid), g in od.groupby(["sample", "market"]):
        f = CACHE / f"prints_{sample}_{mid}.json"
        if f.exists():
            continue
        rec = {"reach_oldest": None, "served": 0, "exhausted": False, "prints": []}
        try:
            c0 = g.condition.iloc[0]
            cond = c0 if isinstance(c0, str) and c0 else ds.get_json(f"{ds.GAMMA}/markets/{mid}", throttle=pt)["conditionId"]
            raw, exhausted = pm_trades(cond, float(g.t_in.min()), pt, max_pages=cfg.PRINT_PAGES)
            ts = np.array([float(t.get("timestamp", 0)) for t in raw])
            keep = keep_window(ts, np.concatenate([g.t_in.to_numpy(), g.t_exit.to_numpy()]), cfg.MAX_WINDOW_S) if len(ts) else np.zeros(0, bool)
            rec = {"condition": cond, "reach_oldest": float(ts.min()) if len(ts) else None, "served": len(raw), "exhausted": exhausted,
                   "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "outcomeIndex", "size")}
                              for t, k_ in zip(raw, keep) if k_]}
        except Exception as e:  # noqa: BLE001  (recorded, not fatal)
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        print(f"{time.time() - t0:6.0f}s {sample} {mid}: served {rec['served']}, kept {len(rec['prints'])}, exhausted {rec['exhausted']}"
              + (f", ERROR {rec['error']}" if "error" in rec else ""), flush=True)
    pull_deadline_mids(od, pt)


def pull_deadline_mids(od: pd.DataFrame, pt: ds.Throttle) -> None:
    f = CACHE / "s9_deadline_mids.json"
    have = json.loads(f.read_text()) if f.exists() else {}
    s9 = od[od["sample"] == "S9"]
    for (mid, tok, te), _ in s9.groupby(["market", "token", "t_exit"]):
        key = f"{mid}_{int(te)}"
        if key in have:
            continue
        a = datetime.fromtimestamp(te, UTC)
        b = datetime.fromtimestamp(te + max(v.window_min for v in cfg.VARIANTS) * 60 + 300, UTC)
        try:
            h = ds.pm_history({"token": tok}, a, b, pt)
            have[key] = {"t": h["t"].tolist(), "p": [float(x) for x in h["p"]]}
        except Exception as e:  # noqa: BLE001
            have[key] = {"t": [], "p": [], "error": str(e)[:200]}
    f.write_text(json.dumps(have))


def yes_terms(prints: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rows = []
    for t in prints:
        out, sd = str(t.get("outcome", "")).lower(), str(t.get("side", "")).upper()
        if out not in ("yes", "no") or sd not in ("BUY", "SELL") or t.get("timestamp") is None:
            continue
        px, s = float(t["price"]), (1 if sd == "BUY" else -1)
        if out == "no":
            px, s = 1.0 - px, -s
        rows.append((float(t["timestamp"]), px, s, float(t.get("size", 0) or 0)))
    rows.sort(key=lambda r: r[0])
    a = np.array(rows, dtype=float).reshape(-1, 4)
    return a[:, 0], a[:, 1], a[:, 2].astype(int), a[:, 3]


def post_price(mid: float, side: int, offset_ticks: int, tick: float = cfg.TICK) -> float:
    k = math.ceil(mid / tick - 1e-6) if side > 0 else math.floor(mid / tick + 1e-6)
    q = (k - side * offset_ticks) * tick
    return float(min(max(q, tick), 1.0 - tick))


def fill(ts: np.ndarray, px: np.ndarray, sd: np.ndarray, sz: np.ndarray, side: int, q: float, t0: float, window_s: float,
         size: float, allowance: float, shift: float = 0.0) -> tuple[float, float | None, float]:
    thr = q + side * shift
    m = (ts > t0) & (ts <= t0 + window_s) & (sd == side)
    at_q, steps = 0.0, []
    for t, p, s in zip(ts[m], px[m], sz[m]):
        if side * (p - thr) > EPS:
            add = s
        elif abs(p - thr) <= EPS:
            add = max(0.0, at_q + s - allowance) - max(0.0, at_q - allowance)
            at_q += s
        else:
            continue
        if add > 0:
            steps.append((t, add))
    qual = float(sum(a for _, a in steps))
    if size <= 0 or qual <= 0:
        return 0.0, None, qual
    target, cum = min(size, qual), 0.0
    for t, a in steps:
        cum += a
        if cum >= target - EPS:
            return min(1.0, qual / size), float(t), qual
    return min(1.0, qual / size), float(steps[-1][0]), qual


def fee(p: float, rate: float, exponent: float, c: float) -> float:
    return c * rate * (p * (1.0 - p)) ** exponent if 0.0 < p < 1.0 else 0.0


def simulate(o: dict, prints: tuple, v: cfg.Variant, c: float, mid_deadline: float) -> dict:
    ts, px, sd, sz = prints
    side, w = o["side"], v.window_min * 60.0
    shift = cfg.TICK if c > 1.0 else 0.0
    q = post_price(o["mid_in"], side, v.offset_ticks)
    frac, t_fill, qual = fill(ts, px, sd, sz, side, q, o["t_in"], w, cfg.CONTRACTS, cfg.QUEUE_ALLOWANCE, shift)
    rec = {"post_price": q, "fill_frac": frac, "filled": frac > 0, "fill_minutes": (t_fill - o["t_in"]) / 60.0 if t_fill else np.nan,
           "qual_volume": qual, "exit_how": "", "exit_price": np.nan, "exit_rest_frac": np.nan, "gross": 0.0, "net": 0.0}
    if frac <= 0:
        return rec
    T, h, mT = o["t_exit"], o["half_spread"], o["mid_exit"]
    gross = side * (q - mT)
    if o["settled"]:
        rec.update(exit_how="settled", exit_price=mT, gross=gross, net=gross)
        return rec
    if c > 1.0:
        net = gross - c * h - fee(mT, o["fee_rate"], o["fee_exponent"], c)
        rec.update(exit_how="cross at exit", exit_price=mT + side * c * h, gross=gross, net=net)
        return rec
    qx = post_price(mT, -side, 0)
    g, _, _ = fill(ts, px, sd, sz, -side, qx, T, w, frac * cfg.CONTRACTS, cfg.QUEUE_ALLOWANCE, 0.0)
    md = mid_deadline if np.isfinite(mid_deadline) else mT
    cross = side * (q - md) - h - fee(md, o["fee_rate"], o["fee_exponent"], c)
    net = g * side * (q - qx) + (1.0 - g) * cross
    how = "rest" if g >= 1.0 - EPS else ("rest + cross" if g > 0 else "cross at deadline")
    rec.update(exit_how=how, exit_price=g * qx + (1.0 - g) * (md + side * h), exit_rest_frac=g, gross=gross, net=net,
               deadline_mid=md, deadline_mid_missing=not np.isfinite(mid_deadline))
    return rec


def cboot(groups: list[str], vals: np.ndarray, wts: np.ndarray | None = None, seed: int = cfg.BOOT_SEED) -> tuple[float, float, float]:
    vals = np.asarray(vals, float)
    wts = np.ones(len(vals)) if wts is None else np.asarray(wts, float)
    if len(vals) == 0 or wts.sum() <= 0:
        return (float("nan"),) * 3
    keys = sorted(set(groups))
    idx = {k: i for i, k in enumerate(keys)}
    gi = np.array([idx[g] for g in groups])
    sv, sw = np.bincount(gi, wts * vals, len(keys)), np.bincount(gi, wts, len(keys))
    mean = float(sv.sum() / sw.sum())
    if len(keys) < 5:
        return mean, float("nan"), float("nan")
    pick = np.random.default_rng(seed).integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    num, den = sv[pick].sum(axis=1), sw[pick].sum(axis=1)
    ok = den > 0
    lo, hi = np.percentile(num[ok] / den[ok], [2.5, 97.5])
    return mean, float(lo), float(hi)


def cboot_diff(ga: list[str], a: np.ndarray, gb: list[str], b: np.ndarray, seed: int = cfg.BOOT_SEED) -> tuple[float, float, float]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return (float("nan"),) * 3
    keys = sorted(set(ga) | set(gb))
    idx = {k: i for i, k in enumerate(keys)}
    ia, ib = np.array([idx[g] for g in ga]), np.array([idx[g] for g in gb])
    sa, na = np.bincount(ia, a, len(keys)), np.bincount(ia, None, len(keys))
    sb, nb = np.bincount(ib, b, len(keys)), np.bincount(ib, None, len(keys))
    d = float(a.mean() - b.mean())
    if len(keys) < 5:
        return d, float("nan"), float("nan")
    pick = np.random.default_rng(seed).integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    NA, NB = na[pick].sum(axis=1), nb[pick].sum(axis=1)
    ok = (NA > 0) & (NB > 0)
    diffs = sa[pick].sum(axis=1)[ok] / NA[ok] - sb[pick].sum(axis=1)[ok] / NB[ok]
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return d, float(lo), float(hi)


def load_cache(od: pd.DataFrame) -> tuple[dict, dict]:
    prints = {}
    for (sample, mid), _ in od.groupby(["sample", "market"]):
        f = CACHE / f"prints_{sample}_{mid}.json"
        prints[(sample, mid)] = json.loads(f.read_text()) if f.exists() else None
    f = CACHE / "s9_deadline_mids.json"
    return prints, (json.loads(f.read_text()) if f.exists() else {})


def deadline_mid(o: dict, window_s: float, s9_extra: dict, npz_cache: dict) -> float:
    at = o["t_exit"] + window_s
    src = o["mid_source"]
    if src not in npz_cache:
        npz_cache[src] = dict(np.load(src)) if Path(src).exists() else {"t": np.zeros(0), "p": np.zeros(0)}
    d = npz_cache[src]
    t, p = d["t"].astype(float), d["p"].astype(float)
    if o["sample"] == "S9":
        x = s9_extra.get(f"{o['market']}_{int(o['t_exit'])}")
        if x and x["t"]:
            t, p = np.concatenate([t, np.array(x["t"], float)]), np.concatenate([p, np.array(x["p"], float)])
            t, i = np.unique(t, return_index=True)
            p = p[i]
    return float(asof(np.array([at]), t, p, cfg.PM_MAX_AGE_S)[0])


def main() -> int:
    if "--pull" in sys.argv:
        pull()
        return 0
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    od = orders()
    prints, s9_extra = load_cache(od)
    npz: dict = {}
    trades = []
    for o in od.to_dict("records"):
        rec = prints.get((o["sample"], o["market"]))
        reach = bool(rec and rec.get("reach_oldest") is not None and (rec.get("exhausted") or rec["reach_oldest"] <= o["t_in"]))
        yt = yes_terms(rec["prints"]) if rec else yes_terms([])
        m = o["side"] * (o["mid_in"] - o["mid_exit"])
        for v in cfg.VARIANTS:
            md = deadline_mid(o, v.window_min * 60.0, s9_extra, npz)
            for c in cfg.COST_MULTIPLIERS:
                base = {"sample": o["sample"], "variant": v.id, "cost_mult": c, "segment": o["segment"], "group": o["group"],
                        "market": o["market"], "question": o["question"], "asset_class": o["asset_class"], "move_pp": o["move_pp"],
                        "side": "sell YES" if o["side"] > 0 else "buy YES", "t_in": o["t_in"], "t_exit": o["t_exit"], "mid_in": o["mid_in"],
                        "mid_exit": o["mid_exit"], "settled": o["settled"], "reachable": reach, "mid_to_mid_points": 100.0 * m}
                if not reach:
                    trades.append({**base, "filled": False})
                    continue
                s = simulate(o, yt, v, c, md)
                q = s["post_price"]
                trades.append({**base, **s, "gross_points": 100.0 * s["gross"], "net_points": 100.0 * s["net"],
                               "cost_points": 100.0 * (s["gross"] - s["net"]),
                               "pnl": cfg.CONTRACTS * s["fill_frac"] * s["net"],
                               "capital": cfg.CONTRACTS * s["fill_frac"] * (q if o["side"] < 0 else 1.0 - q)})
    from .report import report
    report(od, trades, prints, t_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
