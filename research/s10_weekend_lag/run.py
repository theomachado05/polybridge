"""S10: inside the weekend, does the oil event question move before the oil price market? (METHOD.md)

Run from `research/`:
    python -m s10_weekend_lag.run               # tests, event study, every variant, the print check
    python -m s10_weekend_lag.run --no-prints   # the same without pulling prints
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s6_monday_fade.run import closure_metrics, write_csv
from s8_open_referee.run import links as event_links
from s9_weekend_price_markets import run as s9

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s10_weekend_lag"
CACHE = HERE / ".cache"
S9_CACHE = RESEARCH / "s9_weekend_price_markets" / ".cache"


# ---------------------------------------------------------------- small pure pieces

def boot_mean(by: dict[str, list[float]]) -> tuple[float, float, float]:
    """Mean over all observations, 95% interval resampling the keys (weekends)."""
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


def fwd(S: np.ndarray, k: int) -> np.ndarray:
    """Index change from grid i to i + k: the mean over rows valid at both ends (NaN where none, or i + k off the grid)."""
    n = S.shape[1]
    out = np.full(n, np.nan)
    if k >= n or S.shape[0] == 0:
        return out
    d = S[:, k:] - S[:, :-k]
    cnt = np.isfinite(d).sum(axis=0)
    with np.errstate(invalid="ignore"):
        m = np.nansum(d, axis=0) / np.where(cnt > 0, cnt, 1)
    out[: n - k] = np.where(cnt > 0, m, np.nan)
    return out


def jumps(P: np.ndarray, sign: float, first: int) -> dict[int, float]:
    """Jumps of one series on the grid: {grid index: signed size in points}. P in points (0-100), unsigned. A jump at i is
    a change over a rule's window ending at i, from a reference price inside JUMP_REF_BAND; the largest firing change wins."""
    lo, hi = 100 * cfg.JUMP_REF_BAND[0], 100 * cfg.JUMP_REF_BAND[1]
    out = {}
    for i in range(first, len(P)):
        best = 0.0
        for win, thr in cfg.JUMP_RULES:
            k = win // cfg.BIN_S
            if i - k < 0:
                continue
            a, b = P[i - k], P[i]
            if not (np.isfinite(a) and np.isfinite(b)) or not (lo <= a <= hi):
                continue
            d = b - a
            if abs(d) >= thr and abs(d) > abs(best):
                best = d
        if best:
            out[i] = sign * best
    return out


def pick_signals(cands: dict[int, float], refractory_bins: int, last: int | None = None, cap: int | None = None) -> list[tuple[int, float]]:
    """Accept jumps in time order with a refractory gap; optionally only up to grid index `last`, and the first `cap`."""
    out, prev = [], -10**9
    for i in sorted(cands):
        if last is not None and i > last:
            break
        if i - prev >= refractory_bins:
            out.append((i, cands[i]))
            prev = i
            if cap is not None and len(out) >= cap:
                break
    return out


def fee(p: float, rate: float, exponent: float, c: float) -> float:
    return c * rate * (p * (1.0 - p)) ** exponent if 0.0 < p < 1.0 else 0.0


def trade(buy: bool, p_in: float, p_out: float, settled: bool, h: float, rate: float, exponent: float, c: float) -> tuple[float, float, float]:
    """(entry fill in YES terms, gross P&L per contract at mids, net P&L per contract)."""
    lo, hi = cfg.PRICE_CLIP
    entry = min(max(p_in + c * h if buy else p_in - c * h, lo), hi)
    if settled:
        out, out_fee = p_out, 0.0
    else:
        out = min(max(p_out - c * h if buy else p_out + c * h, lo), hi)
        out_fee = fee(out, rate, exponent, c)
    gross = (p_out - p_in) if buy else (p_in - p_out)
    pnl = (out - entry) if buy else (entry - out)
    return entry, gross, pnl - fee(entry, rate, exponent, c) - out_fee


def verify(prints: list[dict], buy: bool, entry: float, t_signal: float) -> tuple[int, float]:
    """Prints in [t_signal, t_signal + PRINT_WINDOW_S] at the assumed price or better on the side that proves the fill
    (S6's rule): a YES sale needs a taker who sold YES at or above our price; a YES purchase needs a taker who bought
    YES at or below it. NO prints are converted to YES terms."""
    n, size = 0, 0.0
    for t in prints:
        ts = t.get("timestamp")
        if ts is None or not (t_signal <= float(ts) <= t_signal + cfg.PRINT_WINDOW_S):
            continue
        px, sd, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
        if out == "yes":
            ypx, ysd = px, sd
        elif out == "no":
            ypx, ysd = 1.0 - px, ("BUY" if sd == "SELL" else "SELL")
        else:
            continue
        if (not buy and ysd == "SELL" and ypx >= entry - 1e-9) or (buy and ysd == "BUY" and ypx <= entry + 1e-9):
            n, size = n + 1, size + float(t.get("size", 0))
    return n, size


# ---------------------------------------------------------------- data

def questions() -> list[dict]:
    by_q: dict[str, dict] = {}
    for l in event_links():
        if l["ticker"] in cfg.OIL_TICKERS:
            q = by_q.setdefault(l["market"], {"source": l["source"], "d": 0, "question": l["question"]})
            q["d"] += l["direction"]
    out = []
    for mid, q in sorted(by_q.items()):
        f = (S5_CACHE if q["source"] == "S5" else d4.CACHE) / f"pm_{mid.split(':')[1]}.npz"
        if q["d"] == 0 or not f.exists():
            continue
        pm = np.load(f)
        if len(pm["t"]):
            out.append({"id": mid, "question": q["question"], "sign": float(np.sign(q["d"])), "t": pm["t"], "p": pm["p"].astype(float)})
    return out


def price_markets(asset_class: str) -> list[dict]:
    out = []
    for m in s9.universe()["markets"]:
        if m["asset_class"] != asset_class or m["sign"] == 0:
            continue
        f = S9_CACHE / f"pm_{m['id']}.npz"
        if not f.exists():
            continue
        pm = np.load(f)
        if len(pm["t"]):
            out.append({**{k: m[k] for k in ("id", "question", "sign", "fee_rate", "fee_exponent", "condition", "outcome")},
                        "closed": s9._ts(m.get("closed_time")), "t": pm["t"], "p": pm["p"].astype(float)})
    return out


def grid_matrix(series: list[dict], grid: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """(P unsigned points, S signed points, live series) on the grid, keeping only series live at the start."""
    P, live = [], []
    for s in series:
        v = 100.0 * asof(grid.astype(np.int64), s["t"], s["p"], cfg.PM_MAX_AGE_S)
        if np.isfinite(v[0]) and 100 * cfg.LIVE_BAND[0] <= v[0] <= 100 * cfg.LIVE_BAND[1]:
            P.append(v)
            live.append(s)
    if not P:
        return np.zeros((0, len(grid))), np.zeros((0, len(grid))), []
    P = np.vstack(P)
    return P, P * np.array([s["sign"] for s in live])[:, None], live


def index_change(live: list[dict], a: float, b: float) -> float:
    """Signed index change in points between two instants (minute resolution), over the series valid at both."""
    if not live:
        return float("nan")
    d = []
    for s in live:
        pa, pb = asof(np.array([a, b], dtype=np.int64), s["t"], s["p"], cfg.PM_MAX_AGE_S)
        if np.isfinite(pa) and np.isfinite(pb):
            d.append(s["sign"] * 100.0 * (pb - pa))
    return float(np.mean(d)) if d else float("nan")


# ---------------------------------------------------------------- one weekend

def weekend(w: dict, qs: list[dict], classes: dict[str, list[dict]]) -> dict:
    start, end = w["start"], w["entry"]
    grid = np.arange(start, end + 1, cfg.BIN_S)
    first = cfg.LOOKBACK_S // cfg.BIN_S
    Pq, Sq, live_q = grid_matrix(qs, grid)
    out = {"key": w["key"], "grid": grid, "live_q": live_q, "Sq": Sq, "classes": {}, "q_jumps": [], "p_jumps": {}}
    for c, ms in classes.items():
        Pp, Sp, live_p = grid_matrix(ms, grid)
        out["classes"][c] = {"P": Pp, "S": Sp, "live": live_p}
    # event-question jumps: the largest at each instant, one per 30 minutes
    cands: dict[int, tuple[float, str]] = {}
    for r, s in enumerate(live_q):
        for i, j in jumps(Pq[r], s["sign"], first).items():
            if i not in cands or abs(j) > abs(cands[i][0]):
                cands[i] = (j, s["id"])
    acc = pick_signals({i: v[0] for i, v in cands.items()}, cfg.REFRACTORY_S // cfg.BIN_S)
    out["q_jumps"] = [(i, j, cands[i][1]) for i, j in acc]
    for c, d in out["classes"].items():
        pc: dict[int, tuple[float, str]] = {}
        for r, s in enumerate(d["live"]):
            for i, j in jumps(d["P"][r], s["sign"], first).items():
                if i not in pc or abs(j) > abs(pc[i][0]):
                    pc[i] = (j, s["id"])
        acc = pick_signals({i: v[0] for i, v in pc.items()}, cfg.REFRACTORY_S // cfg.BIN_S)
        out["p_jumps"][c] = [(i, j, pc[i][1]) for i, j in acc]
    return out


# ---------------------------------------------------------------- tests

def leadlag_rows(W: list[dict], c: str) -> list[dict]:
    rows = []
    first = cfg.LOOKBACK_S // cfg.BIN_S
    for direction in ("event first", "price first", "same bin"):
        for h in (cfg.HORIZONS_S if direction != "same bin" else (cfg.BIN_S,)):
            k = h // cfg.BIN_S
            xs, ys, gs = [], [], []
            for wk in W:
                d = wk["classes"][c]
                if not len(wk["live_q"]) or not len(d["live"]):
                    continue
                xb, yb = fwd(wk["Sq"], 1), fwd(d["S"], 1)        # value at i: change over (i, i+1]
                xf, yf = fwd(wk["Sq"], k), fwd(d["S"], k)
                n = len(wk["grid"])
                for i in range(first, n):
                    back_x, back_y = xb[i - 1], yb[i - 1]       # the bin (t - 5 min, t]
                    if direction == "same bin":
                        xs.append(back_x), ys.append(back_y), gs.append(wk["key"])
                    elif i + k < n:
                        if direction == "event first":
                            xs.append(back_x), ys.append(yf[i]), gs.append(wk["key"])
                        else:
                            xs.append(back_y), ys.append(xf[i]), gs.append(wk["key"])
            r = en.clustered_slope(np.array(xs, float), np.array(ys, float), np.array(gs))
            rows.append({"class": c, "direction": direction, "horizon_min": h // 60, **r})
    return rows


def event_rows(W: list[dict], c: str) -> list[dict]:
    """One row per jump (both kinds), with the response of the other index."""
    rows = []
    for wk in W:
        d, grid = wk["classes"][c], wk["grid"]
        if not len(wk["live_q"]) or not len(d["live"]):
            continue
        end = grid[-1]
        for kind, js, resp in (("event first", wk["q_jumps"], d["live"]), ("price first", wk["p_jumps"][c], wk["live_q"])):
            for i, j, src in js:
                t = float(grid[i])
                r = {"class": c, "kind": kind, "weekend": wk["key"], "t": t, "source": src, "jump": j,
                     "pre15": np.sign(j) * index_change(resp, t - 900, t)}
                for h in cfg.HORIZONS_S:
                    ok = t + h <= end
                    r[f"r{h // 60}"] = np.sign(j) * index_change(resp, t, t + h) if ok else float("nan")
                    r[f"r{h // 60}_entry"] = np.sign(j) * index_change(resp, t + cfg.ENTRY_DELAY_S, t + cfg.ENTRY_DELAY_S + h) if ok else float("nan")
                rows.append(r)
    return rows


def event_summary(ev: pd.DataFrame) -> list[dict]:
    out = []
    cols = ["pre15"] + [f"r{h // 60}" for h in cfg.HORIZONS_S] + [f"r{h // 60}_entry" for h in cfg.HORIZONS_S]
    for (c, kind), g in ev.groupby(["class", "kind"]):
        for col in cols:
            s = g[g[col].notna()]
            m = boot_mean({k: list(v[col]) for k, v in s.groupby("weekend")})
            out.append({"class": c, "kind": kind, "measure": col, "n": len(s), "weekends": int(s.weekend.nunique()),
                        "mean": m[0], "ci_lo": m[1], "ci_hi": m[2], "mean_abs_jump": float(s.jump.abs().mean()) if len(s) else float("nan")})
    return out


# ---------------------------------------------------------------- trades

def make_trades(W: list[dict]) -> list[dict]:
    out = []
    last_bin = lambda wk: int((wk["grid"][-1] - cfg.LAST_SIGNAL_BEFORE_END_S - wk["grid"][0]) // cfg.BIN_S)  # noqa: E731
    for v in cfg.VARIANTS:
        for wk in W:
            d = wk["classes"][v.asset_class]
            sigs = [s for s in wk["q_jumps"] if s[0] <= last_bin(wk)][: cfg.MAX_SIGNALS_PER_WEEKEND]
            for i, j, src in sigs:
                t = float(wk["grid"][i])
                t_in = t + cfg.ENTRY_DELAY_S
                t_out = {"30m": t_in + 1800, "60m": t_in + 3600, "sunday 17:55": float(wk["grid"][-1])}[v.exit]
                cand = []
                for m in d["live"]:
                    p_in = float(asof(np.array([t_in], dtype=np.int64), m["t"], m["p"], cfg.PM_MAX_AGE_S)[0])
                    if np.isfinite(p_in) and cfg.ENTRY_BAND[0] <= p_in <= cfg.ENTRY_BAND[1]:
                        cand.append((abs(p_in - 0.5), m["id"], m, p_in))
                for _, _, m, p_in in sorted(cand, key=lambda x: (x[0], x[1]))[: cfg.MAX_MARKETS_PER_SIGNAL]:
                    p_out = float(asof(np.array([t_out], dtype=np.int64), m["t"], m["p"], cfg.PM_MAX_AGE_S)[0])
                    settled = False
                    if not np.isfinite(p_out):
                        if m["closed"] is not None and m["outcome"] is not None and m["closed"] <= t_out:
                            p_out, settled = float(m["outcome"]), True
                        else:
                            out.append({"variant": v.id, "dropped": True, "weekend": wk["key"], "market": m["id"]})
                            continue
                    buy = m["sign"] * j > 0
                    before = m["p"][(m["t"] >= t_in - 900) & (m["t"] <= t_in)]
                    for c in cfg.COST_MULTIPLIERS:
                        entry, gross, pnl = trade(buy, p_in, p_out, settled, cfg.HALF_SPREAD[v.asset_class], m["fee_rate"], m["fee_exponent"], c)
                        out.append({"variant": v.id, "dropped": False, "cost_mult": c, "weekend": wk["key"], "asset_class": v.asset_class,
                                    "exit_rule": v.exit, "signal_epoch": t, "signal_question": src, "jump_points": j, "market": m["id"],
                                    "question": m["question"], "market_sign": m["sign"], "side": "buy YES" if buy else "sell YES",
                                    "p_entry": p_in, "entry": entry, "exit_epoch": t_out, "p_exit": p_out, "settled": settled,
                                    "gross_points": 100.0 * gross, "cost_points": 100.0 * (gross - pnl), "net_points": 100.0 * pnl,
                                    "pnl": cfg.CONTRACTS * pnl, "capital": cfg.CONTRACTS * (entry if buy else 1.0 - entry),
                                    "flat_mid_15m": bool(len(before) > 1 and np.ptp(before) == 0), "condition": m["condition"]})
    return out


def load_prints(need: dict[str, tuple[str, list[float]]]) -> dict[str, dict]:
    """Public prints of each market near the signal instants, cached per market."""
    CACHE.mkdir(parents=True, exist_ok=True)
    pt, out = ds.Throttle(cfg.PRINT_RATE), {}
    for mid, (cond, at) in sorted(need.items()):
        f = CACHE / f"prints_{mid}.json"
        if f.exists():
            out[mid] = json.loads(f.read_text())
            continue
        rec = {"reach_oldest": None, "served": 0, "prints": []}
        try:
            raw = ds.pm_trades(cond, min(at) - 60, pt, max_pages=cfg.PRINT_PAGES)
            ts, ats = np.array([float(t.get("timestamp", 0)) for t in raw]), np.array(sorted(at))
            keep = [t for t, s in zip(raw, ts) if np.any((s >= ats - 60) & (s <= ats + cfg.PRINT_WINDOW_S + 60))]
            rec = {"reach_oldest": float(ts.min()) if len(ts) else None, "served": len(raw),
                   "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]}
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        out[mid] = rec
    return out


# ---------------------------------------------------------------- run

def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    qs = questions()
    classes = {c: price_markets(c) for c in ("crude", "gold")}
    cal = s9.calendar()
    W = [weekend(w, qs, classes) for w in cal]
    W = [wk for wk in W if len(wk["live_q"]) and any(len(d["live"]) for d in wk["classes"].values())]
    base = sorted(wk["key"] for wk in W if len(wk["classes"]["crude"]["live"]))
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(base)))
    oos_from = base[len(base) - n_oos]

    ll = leadlag_rows(W, "crude") + leadlag_rows(W, "gold")
    ev = pd.DataFrame(event_rows(W, "crude") + event_rows(W, "gold"))
    ev["segment"] = np.where(ev.weekend >= oos_from, "OOS", "IS")
    es = event_summary(ev)

    raw = make_trades(W)
    dropped = [t for t in raw if t["dropped"]]
    trades = [t for t in raw if not t["dropped"]]
    for t in trades:
        t["segment"] = "OOS" if t["weekend"] >= oos_from else "IS"

    prints: dict[str, dict] = {}
    if "--no-prints" not in sys.argv:
        need: dict[str, tuple[str, list[float]]] = {}
        for t in trades:
            need.setdefault(t["market"], (t["condition"], []))[1].append(t["signal_epoch"])
        prints = load_prints(need)
    for t in trades:
        rec = prints.get(t["market"])
        t["checkable"] = bool(rec is not None and rec.get("reach_oldest") is not None and rec["reach_oldest"] <= t["signal_epoch"])
        n, size = verify(rec["prints"], t["side"] == "buy YES", t["entry"], t["signal_epoch"]) if rec and rec["prints"] else (0, 0.0)
        t["verify_n"], t["verify_size"], t["verified"] = n, size, n > 0
        t["pnl_verified"] = t["pnl"] * min(size, cfg.CONTRACTS) / cfg.CONTRACTS if n else 0.0

    # weekends a variant could trade: those with live markets of its class and live questions
    live_by_class = {c: sorted(wk["key"] for wk in W if len(wk["classes"][c]["live"])) for c in classes}
    rows, eq = [], []
    for v in cfg.VARIANTS:
        wl_all = live_by_class[v.asset_class]
        segments = (("IS", [k for k in wl_all if k < oos_from]), ("OOS", [k for k in wl_all if k >= oos_from]), ("ALL", wl_all))
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
                bv = boot_mean({k: [t["net_points"] for t in ts if t["verified"]] for k, ts in by.items()})
                ver = [t for t in st if t["verified"]]
                chk = [t for t in st if t["checkable"]]
                rows.append({"segment": seg, "variant": v.id, "asset_class": v.asset_class, "exit": v.exit, "cost_mult": c,
                             "weekends": len(wl), "weekends_traded": len(by), "signals": len({(t["weekend"], t["signal_epoch"]) for t in st}),
                             "trades": len(st), "markets": len({t["market"] for t in st}),
                             "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0], "gross_ci_lo": g[1], "gross_ci_hi": g[2],
                             "mean_cost_points": float(np.mean([t["cost_points"] for t in st])) if st else float("nan"),
                             "cost_bp_of_capital": float(np.mean([t["cost_points"] / 100.0 * cfg.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                             "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"), "pnl": float(pc.sum()),
                             "best_weekend_pnl": float(pc.max()) if len(pc) else float("nan"), "worst_weekend_pnl": float(pc.min()) if len(pc) else float("nan"),
                             "settled_trades": sum(t["settled"] for t in st), "flat_mid_share": float(np.mean([t["flat_mid_15m"] for t in st])) if st else float("nan"),
                             "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)), **m,
                             "checkable_trades": len(chk), "verified_trades": len(ver),
                             "verified_share": len(ver) / len(st) if st else float("nan"),
                             "verified_share_of_checkable": sum(t["verified"] for t in chk) / len(chk) if chk else float("nan"),
                             "mean_net_points_verified": bv[0], "ci_lo_verified": bv[1], "ci_hi_verified": bv[2],
                             "pnl_verified": float(sum(t["pnl_verified"] for t in st))})
                if seg == "ALL":
                    pv = np.array([sum(t["pnl_verified"] for t in by.get(k, [])) for k in wl])
                    eq += [{"variant": v.id, "cost_mult": c, "weekend": k, "pnl": float(a), "pnl_verified": float(b_)}
                           for k, a, b_ in zip(wl, np.cumsum(pc), np.cumsum(pv))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in rows:
        peers = [x["daily_sharpe"] for x in rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["weekends"], len(cfg.VARIANTS), float(np.var(peers)), row["skew"],
                                                      row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")

    for t in trades:
        t.pop("condition", None)
        t.pop("dropped", None)
    write_csv(RESULTS / "leadlag.csv", ll)
    write_csv(RESULTS / "events.csv", ev.to_dict("records"))
    write_csv(RESULTS / "event_summary.csv", es)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    write_csv(RESULTS / "equity.csv", eq)
    meta = {"weekends_in_calendar": len(cal), "weekends_used": len(W), "weekends_crude": len(live_by_class["crude"]),
            "weekends_gold": len(live_by_class["gold"]), "first_weekend": base[0], "last_weekend": base[-1], "oos_from": oos_from,
            "oos_weekends_crude": n_oos, "event_questions": len(qs), "crude_markets": len(classes["crude"]), "gold_markets": len(classes["gold"]),
            "event_jumps_crude": int(((ev["class"] == "crude") & (ev.kind == "event first")).sum()),
            "price_jumps_crude": int(((ev["class"] == "crude") & (ev.kind == "price first")).sum()), "dropped_trades": len(dropped), "markets_checked_for_prints": len(prints),
            "print_errors": sum(1 for r in prints.values() if "error" in r), "run_seconds": round(time.time() - t_run, 1)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))

    print(json.dumps(meta))
    for r in ll:
        print(f"{r['class']:5} {r['direction']:11} {r['horizon_min']:3d}m n {r['n']:6d} slope {r['slope']:7.3f} t {r['t']:6.2f} wk {r.get('clusters', 0)}")
    for r in es:
        print(f"{r['class']:5} {r['kind']:11} {r['measure']:9} n {r['n']:4d} wk {r['weekends']:3d} mean {r['mean']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] |jump| {r['mean_abs_jump']:.1f}")
    print("seg var cost trades wk   net [ci]                gross  cost   hit  sharpe  maxDD chk  ver  ver_net  flat")
    for x in rows:
        print(f"{x['segment']:3} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:5d} {x['weekends_traded']:3d} {x['mean_net_points']:7.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] {x['mean_gross_points']:6.2f} {x['mean_cost_points']:5.2f} {x['hit_rate']:5.2f} "
              f"{x['sharpe']:6.2f} {x['max_drawdown']:6.3f} {x['checkable_trades']:4d} {x['verified_trades']:4d} {x['mean_net_points_verified']:7.2f} {x['flat_mid_share']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
