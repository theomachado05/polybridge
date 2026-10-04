"""S14: is the missing edge a link problem, a signal problem, or neither? (METHOD.md). A diagnostic on cached data.

Run from `research/`:  python -m s14_link_ceiling.run
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s6_monday_fade.run import write_csv
from s8_open_referee.run import links as all_links

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "s14_link_ceiling"


def slope_t(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Through-origin slope of y on x, its heteroskedasticity-robust t, and the number of sessions with x != 0."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n, sxx = int((x != 0).sum()), float(np.sum(x * x))
    if n < cfg.MIN_MOVES or sxx <= 0:
        return float("nan"), float("nan"), n
    b = float(np.sum(x * y) / sxx)
    se = math.sqrt(float(np.sum((x * (y - b * x)) ** 2))) / sxx
    return b, (b / se if se > 0 else float("nan")), n


def pick(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(continuation, reversal): links whose t is at least +T_PICK, at most -T_PICK."""
    return np.nan_to_num(t, nan=0.0) >= cfg.T_PICK, np.nan_to_num(t, nan=0.0) <= -cfg.T_PICK


def shares(t_after: np.ndarray, t_gap: np.ndarray) -> tuple[float, float, float]:
    """Share of links with after-open |t| >= 2, mean |t| of the top tenth, share with gap t >= 2 (links with a t only)."""
    a, g = np.abs(t_after[np.isfinite(t_after)]), t_gap[np.isfinite(t_gap)]
    k = max(1, int(math.ceil(cfg.TOP_SHARE * len(a)))) if len(a) else 0
    return (float(np.mean(a >= cfg.T_PICK)) if len(a) else float("nan"), float(np.sort(a)[-k:].mean()) if k else float("nan"),
            float(np.mean(g >= cfg.T_PICK)) if len(g) else float("nan"))


def build() -> tuple[list[dict], dict]:
    def npz(f: Path):
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz(S5_CACHE / "eq_SPY.npz"), npz(S5_CACHE / "day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = np.array(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    prev_cl = np.concatenate([[0], cl[:-1]]).astype(np.int64)
    weekend = np.concatenate([[False], (op[1:] - cl[:-1]) > 40 * 3600])
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(days)))
    oos = np.arange(len(days)) >= len(days) - n_oos
    spy = en.session_prices(spy_bars, sess)
    spy_open, spy_close = spy["px"][:, 0], spy["close"]
    spy_prev = np.concatenate([[np.nan], spy_close[:-1]])
    assets: dict[str, dict | None] = {}

    def asset(tk: str):
        if tk not in assets:
            assets[tk] = None
            for cache in (S5_CACHE, d4.CACHE):
                b, d = npz(cache / f"eq_{tk}.npz"), npz(cache / f"day_{tk}.npz")
                if b is None or d is None or len(b["t"]) == 0:
                    continue
                px = en.session_prices(b, sess)
                o, c = px["px"][:, 0], px["close"]
                prev = np.concatenate([[np.nan], c[:-1]])
                beta = en.betas(d, spy_day, list(days))
                assets[tk] = {"gap": 1e4 * ((o / prev - 1) - beta * (spy_open / spy_prev - 1)),
                              "after": 1e4 * ((c / o - 1) - beta * (spy_close / spy_open - 1))}
                break
        return assets[tk]

    out = []
    for l in all_links():
        a = asset(l["ticker"])
        pm = npz((S5_CACHE if l["source"] == "S5" else d4.CACHE) / f"pm_{l['market'].split(':')[1]}.npz")
        if a is None or pm is None or len(pm["t"]) == 0:
            continue
        pt, pp = pm["t"], pm["p"].astype(float)

        def p(at):
            return asof(np.asarray(at, dtype=np.int64), pt, pp, cfg.PM_MAX_AGE_S)

        p_prev, p_8, p_929 = p(prev_cl), p(op - cfg.EARLY_LATE_SPLIT_BEFORE_OPEN_S), p(op - 60)
        d = l["direction"]

        def logit(q):
            q = np.clip(q, *cfg.P_CLIP)
            return np.log(q / (1 - q))

        out.append({**l, "x": d * 100.0 * (p_929 - p_prev), "x_logit": d * (logit(p_929) - logit(p_prev)),
                    "x_early": d * 100.0 * (p_8 - p_prev), "x_late": d * 100.0 * (p_929 - p_8), "gap": a["gap"], "after": a["after"]})
    return out, {"days": days, "oos": oos, "weekend": weekend, "oos_from": str(days[len(days) - n_oos]), "sessions": len(days)}


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    panel, cal = build()
    days, oos, weekend = cal["days"], cal["oos"], cal["weekend"]
    rows, link_rows = [], []

    # ---- per-link slopes: in-sample (for the oracle) and whole sample (for the count)
    t_is, t_all, t_gap_all, t_gap_is = (np.full(len(panel), np.nan) for _ in range(4))
    for i, l in enumerate(panel):
        b_is, t_is[i], n_is = slope_t(l["x"][~oos], l["after"][~oos])
        _, t_gap_is[i], _ = slope_t(l["x"][~oos], l["gap"][~oos])
        b_all, t_all[i], n_all = slope_t(l["x"], l["after"])
        g_all, t_gap_all[i], _ = slope_t(l["x"], l["gap"])
        okx = np.isfinite(l["x"]) & np.isfinite(l["after"])
        sxx = float(np.sum(l["x"][okx] ** 2))
        link_rows.append({"market": l["market"], "question": l["question"], "ticker": l["ticker"], "direction": l["direction"], "source": l["source"],
                          "sessions_with_a_move": n_all, "largest_day_share_of_odds_variation": float(np.max(l["x"][okx] ** 2) / sxx) if sxx > 0 else float("nan"), "gap_slope": g_all, "gap_t": t_gap_all[i], "after_slope": b_all, "after_t": t_all[i],
                          "in_sample_sessions_with_a_move": n_is, "in_sample_after_slope": b_is, "in_sample_after_t": t_is[i],
                          "in_sample_gap_t": t_gap_is[i]})

    # ---- C1: the oracle link
    def pooled(idx: np.ndarray, mask: np.ndarray, y: str, flip: np.ndarray | None = None) -> dict:
        xs, ys, ds = [], [], []
        for i in np.flatnonzero(idx):
            s = 1.0 if flip is None else flip[i]
            xs.append(s * panel[i]["x"][mask]); ys.append(panel[i][y][mask]); ds.append(days[mask])
        if not xs:
            return {"n": 0, "slope": float("nan"), "se": float("nan"), "t": float("nan"), "links": 0}
        return {**en.clustered_slope(np.concatenate(xs), np.concatenate(ys), np.concatenate(ds)), "links": int(idx.sum())}

    cont, rev = pick(t_is)
    has = np.isfinite(t_is)
    k = max(1, int(math.ceil(cfg.TOP_SHARE * has.sum())))
    order = np.argsort(np.where(has, t_is, 0.0))
    top = np.zeros(len(panel), bool); top[order[-k:]] = True; top &= has
    bot = np.zeros(len(panel), bool); bot[order[:k]] = True; bot &= has
    sign = np.where(rev | bot, -1.0, 1.0)
    for name, idx, flip in (("links with in-sample after-open t >= +2 (continuation)", cont, None),
                            ("links with in-sample after-open t <= -2 (reversal)", rev, None),
                            ("both groups, reversal links flipped", cont | rev, sign),
                            ("top tenth by in-sample after-open t", top, None), ("bottom tenth by in-sample after-open t", bot, None),
                            ("top and bottom tenth, bottom flipped", top | bot, sign), ("every link", has, None)):
        rows.append({"test": "C1 oracle link", "group": name, "sample": "in-sample (where the links were picked)", "outcome": "after the open",
                     **pooled(idx, ~oos, "after", flip)})
        rows.append({"test": "C1 oracle link", "group": name, "sample": "out-of-sample", "outcome": "after the open", **pooled(idx, oos, "after", flip)})
    rows.append({"test": "C1 oracle link", "group": "every link", "sample": "out-of-sample", "outcome": "opening gap", **pooled(has, oos, "gap")})

    # ---- C2: more strong links than chance?
    obs = shares(t_all, t_gap_all)
    rng = np.random.default_rng(cfg.SHUFFLE_SEED)
    null = np.zeros((cfg.N_SHUFFLES, 3))
    valid = [np.isfinite(l["x"]) & np.isfinite(l["after"]) & np.isfinite(l["gap"]) for l in panel]
    for s in range(cfg.N_SHUFFLES):
        ta, tg = np.full(len(panel), np.nan), np.full(len(panel), np.nan)
        for i, l in enumerate(panel):
            v = valid[i]
            xs = rng.permutation(l["x"][v])
            _, ta[i], _ = slope_t(xs, l["after"][v])
            _, tg[i], _ = slope_t(xs, l["gap"][v])
        null[s] = shares(ta, tg)
    n_links_t = int(np.isfinite(t_all).sum())
    for j, (name, outcome) in enumerate((("share of links with |t| >= 2", "after the open"), ("mean |t| of the top tenth of links", "after the open"),
                                         ("share of links with t >= +2 (positive control)", "opening gap"))):
        rows.append({"test": "C2 count of strong links", "group": name, "outcome": outcome, "links": n_links_t, "observed": obs[j],
                     "shuffle_mean": float(null[:, j].mean()), "shuffle_p95": float(np.percentile(null[:, j], 95)),
                     "shuffle_max": float(null[:, j].max()), "share_of_shuffles_at_or_above": float(np.mean(null[:, j] >= obs[j]))})

    # ---- C3: other definitions of the signal
    D = np.concatenate([np.asarray(days)] * len(panel))
    W = np.concatenate([weekend] * len(panel))
    for col, name in (("x", "points, previous close to 09:29"), ("x_logit", "log-odds, previous close to 09:29"),
                      ("x_early", "points, previous close to 08:00 (early night)"), ("x_late", "points, 08:00 to 09:29 (late night)")):
        X = np.concatenate([l[col] for l in panel])
        for scope, m in (("all nights", np.ones(len(X), bool)), ("weekends and holidays", W)):
            for y, yname in (("gap", "opening gap"), ("after", "after the open")):
                Y = np.concatenate([l[y] for l in panel])
                rows.append({"test": "C3 signal definition", "group": name, "sample": scope, "outcome": yname,
                             **en.clustered_slope(X[m], Y[m], D[m])})

    write_csv(RESULTS / "tests.csv", rows)
    write_csv(RESULTS / "links.csv", link_rows)
    meta = {"links_in_panel": len(panel), "links_with_own_slope_whole_sample": n_links_t, "links_with_own_slope_in_sample": int(has.sum()),
            "sessions": cal["sessions"], "oos_from": cal["oos_from"], "continuation_links": int(cont.sum()), "reversal_links": int(rev.sum()),
            "tenth": int(k), "shuffles": cfg.N_SHUFFLES, "run_seconds": round(time.time() - t_run, 1)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    for r in rows:
        if r["test"].startswith("C2"):
            print(f"C2 | {r['group'][:46]:46} | {r['outcome']:14} | observed {r['observed']:.3f} shuffle mean {r['shuffle_mean']:.3f} p95 {r['shuffle_p95']:.3f} "
                  f"| shuffles at or above {r['share_of_shuffles_at_or_above']:.3f}")
        else:
            print(f"{r['test'][:2]} | {r['group'][:52]:52} | {r.get('sample', '')[:22]:22} | {r['outcome']:14} | links {r.get('links', ''):>4} n {r['n']:6d} "
                  f"slope {r['slope']:8.3f} t {r['t']:6.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
