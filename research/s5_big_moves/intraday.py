"""S5b, exploratory (METHOD.md amendment 2): inside the regular session, do the odds move first or the equity?
Same links and cached data as S5; 5-minute bins.

Run from `research/`:  python -m s5_big_moves.intraday
"""
from __future__ import annotations

import csv
import json
import sys

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s4_linked_assets import engine as en

from . import config as cfg
from .run import CACHE, RESULTS, cost_bp, merge_links

BAR_S = 300
HORIZONS = ((1, "5 min"), (3, "15 min"), (6, "30 min"), (12, "60 min"))
ODDS_JUMP_PP, EQUITY_JUMP_BP = 3.0, 50.0
HOLD_BINS = 6
PM_MAX_AGE_S = 1800


def session_bars(bars: dict, sess: pd.DataFrame, nb: int) -> np.ndarray:
    """(sessions, nb) close-to-close returns of each 5-minute bar; the first bar is open to close. NaN where a bar
    or the bar before it is missing."""
    out = np.full((len(sess), nb), np.nan)
    t, o, c = bars["t"], bars["o"], bars["c"]
    pos = {int(x): i for i, x in enumerate(t)}
    for i, op in enumerate(sess.open.to_numpy()):
        prev = None
        for j in range(nb):
            k = pos.get(int(op + j * BAR_S))
            if k is None:
                prev = None
                continue
            base = o[k] if j == 0 else prev
            if base is not None and base > 0:
                out[i, j] = c[k] / base - 1.0
            prev = c[k]
    return out


def forward_sum(a: np.ndarray, h: int) -> np.ndarray:
    """Sum of the next h bins of each row (bins j+1 .. j+h), NaN if any is missing or runs past the session."""
    n, m = a.shape
    out = np.full((n, m), np.nan)
    for j in range(m - h):
        out[:, j] = a[:, j + 1: j + 1 + h].sum(axis=1)
    return out


def boot(v: np.ndarray, g: np.ndarray) -> tuple[float, float, float]:
    ok = np.isfinite(v)
    v, g = v[ok], g[ok]
    return en.date_bootstrap({d: list(v[g == d]) for d in np.unique(g)}) if len(v) else (float("nan"),) * 3


def main() -> int:
    links, _ = merge_links()

    def npz(name):
        f = CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = np.array(sess.day)
    nb = int((sess.close - sess.open).max() // BAR_S)
    r_spy = session_bars(spy_bars, sess, nb)
    bounds = sess.open.to_numpy()[:, None] + np.arange(nb + 1)[None, :] * BAR_S
    in_session = bounds[:, 1:] <= sess.close.to_numpy()[:, None]
    cache: dict[str, dict | None] = {}
    E, D, DAY, TK, LINK = [], [], [], [], []
    for li, l in enumerate(links):
        if l["ticker"] not in cache:
            b, d = npz(f"eq_{l['ticker']}.npz"), npz(f"day_{l['ticker']}.npz")
            cache[l["ticker"]] = None if b is None or d is None or len(b["t"]) == 0 else {
                "r": session_bars(b, sess, nb), "beta": en.betas(d, spy_day, list(days))}
        a, pm = cache[l["ticker"]], npz(f"pm_{l['market'].split(':')[1]}.npz")
        if a is None or pm is None or len(pm["t"]) == 0:
            continue
        p = asof(bounds.ravel().astype(np.int64), pm["t"], pm["p"].astype(float), PM_MAX_AGE_S).reshape(bounds.shape)
        d = l["direction"] * 100.0 * np.diff(p, axis=1)
        e = 1e4 * (a["r"] - a["beta"][:, None] * r_spy)
        d[~in_session], e[~in_session] = np.nan, np.nan
        alive = np.isfinite(d).any(axis=1)
        E.append(e[alive]); D.append(d[alive]); DAY.append(days[alive])
        TK.append(np.full(alive.sum(), l["ticker"])); LINK.append(np.full(alive.sum(), li))
    E, D, DAY, TK, LINK = np.vstack(E), np.vstack(D), np.concatenate(DAY), np.concatenate(TK), np.concatenate(LINK)
    day2 = np.repeat(DAY[:, None], E.shape[1], axis=1)
    ok = np.isfinite(E) & np.isfinite(D)
    out: dict = {"link_sessions": int(E.shape[0]), "bins": int(ok.sum()), "bins_with_odds_change": int((ok & (D != 0)).sum()),
                 "links": int(len(np.unique(LINK))), "dates": int(len(np.unique(DAY)))}
    rows = []
    c = en.clustered_slope(D[ok], E[ok], day2[ok])
    rows.append({"test": "same 5 minutes: equity on odds", "unit": "bp per point", **c})
    odds_jump, eq_jump = ok & (np.abs(D) >= ODDS_JUMP_PP), ok & (np.abs(E) >= EQUITY_JUMP_BP)
    out["odds_jumps"], out["equity_jumps"] = int(odds_jump.sum()), int(eq_jump.sum())
    m = boot((np.sign(D) * E)[odds_jump], day2[odds_jump])
    rows.append({"test": f"odds jump of {ODDS_JUMP_PP:.0f}+ points: equity in the same 5 minutes", "unit": "bp, signed by the odds", "n": int(odds_jump.sum()),
                 "mean": m[0], "ci_lo": m[1], "ci_hi": m[2], "dates": int(len(np.unique(day2[odds_jump])))})
    m = boot((np.sign(E) * D)[eq_jump], day2[eq_jump])
    rows.append({"test": f"equity jump of {EQUITY_JUMP_BP:.0f}+ bp: odds in the same 5 minutes", "unit": "points, signed by the equity", "n": int(eq_jump.sum()),
                 "mean": m[0], "ci_lo": m[1], "ci_hi": m[2], "dates": int(len(np.unique(day2[eq_jump])))})
    for h, lab in HORIZONS:
        fe, fd = forward_sum(E, h), forward_sum(D, h)
        a = ok & np.isfinite(fe)
        b = ok & np.isfinite(fd)
        rows.append({"test": f"odds first: equity over the next {lab} on this bin's odds move", "unit": "bp per point",
                     **en.clustered_slope(D[a], fe[a], day2[a])})
        rows.append({"test": f"equity first: odds over the next {lab} on this bin's equity move", "unit": "points per 100 bp",
                     **en.clustered_slope(E[b] / 100.0, fd[b], day2[b])})
        j = odds_jump & np.isfinite(fe)
        m = boot((np.sign(D) * fe)[j], day2[j])
        rows.append({"test": f"odds jump of {ODDS_JUMP_PP:.0f}+ points: equity over the next {lab}", "unit": "bp, signed by the odds", "n": int(j.sum()),
                     "mean": m[0], "ci_lo": m[1], "ci_hi": m[2], "dates": int(len(np.unique(day2[j])))})
        j = eq_jump & np.isfinite(fd)
        m = boot((np.sign(E) * fd)[j], day2[j])
        rows.append({"test": f"equity jump of {EQUITY_JUMP_BP:.0f}+ bp: odds over the next {lab}", "unit": "points, signed by the equity", "n": int(j.sum()),
                     "mean": m[0], "ci_lo": m[1], "ci_hi": m[2], "dates": int(len(np.unique(day2[j])))})

    # the odds-first trade: enter at the next bin's open after an odds jump, hold 30 minutes, one position per ticker
    fe = forward_sum(E, HOLD_BINS)
    trades = []
    cand = np.argwhere(odds_jump & np.isfinite(fe))
    order = np.lexsort((cand[:, 1], DAY[cand[:, 0]]))
    busy: dict[tuple[str, str], int] = {}
    for i, j in cand[order]:
        key = (TK[i], DAY[i])
        if busy.get(key, -1) >= j:
            continue
        busy[key] = j + HOLD_BINS
        beta = cache[TK[i]]["beta"][np.searchsorted(days, DAY[i])]
        gross = float(np.sign(D[i, j]) * fe[i, j])
        for cm in cfg.COST_MULTIPLIERS:
            cost = cost_bp(TK[i], float(beta), cm)
            trades.append({"cost_mult": cm, "day": DAY[i], "ticker": TK[i], "bin": int(j), "odds_jump_pp": float(D[i, j]), "gross_bp": gross,
                           "cost_bp": cost, "net_bp": gross - cost})
    tm = []
    for cm in cfg.COST_MULTIPLIERS:
        t = [x for x in trades if x["cost_mult"] == cm]
        g = np.array([x["day"] for x in t])
        b = boot(np.array([x["net_bp"] for x in t]), g)
        gb = boot(np.array([x["gross_bp"] for x in t]), g)
        tm.append({"cost_mult": cm, "trades": len(t), "tickers": len({x["ticker"] for x in t}), "dates": len(set(g)), "mean_net_bp": b[0],
                   "ci_lo": b[1], "ci_hi": b[2], "mean_gross_bp": gb[0], "gross_ci_lo": gb[1], "gross_ci_hi": gb[2],
                   "hit_rate": float(np.mean([x["net_bp"] > 0 for x in t])) if t else float("nan"),
                   "mean_cost_bp": float(np.mean([x["cost_bp"] for x in t])) if t else float("nan")})
    out["trade"] = tm

    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(RESULTS / "intraday.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    (RESULTS / "intraday.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "trade"}))
    for r in rows:
        if "slope" in r:
            print(f"{r['test'][:74]:74} | n {r['n']:7d} slope {r['slope']:7.3f} t {r['t']:6.2f} ({r['unit']})")
        else:
            print(f"{r['test'][:74]:74} | n {r['n']:7d} mean {r['mean']:7.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] ({r['unit']})")
    for t in tm:
        print(f"trade {t['cost_mult']:.0f}x: {t['trades']} trades, {t['tickers']} tickers, {t['dates']} dates, net {t['mean_net_bp']:.1f} bp "
              f"[{t['ci_lo']:.1f},{t['ci_hi']:.1f}], gross {t['mean_gross_bp']:.1f} [{t['gross_ci_lo']:.1f},{t['gross_ci_hi']:.1f}], hit {t['hit_rate']:.2f}")
    return 0


def reversal() -> int:
    """Amendment 3: after an overnight move in odds, do the odds give some back once the stock market is open?"""
    links, _ = merge_links()
    spy_bars = dict(np.load(CACHE / "eq_SPY.npz"))
    sess = en.sessions_from(spy_bars["t"])
    days = np.array(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    weekend = np.concatenate([[False], (op[1:] - cl[:-1]) > 40 * 3600])
    X, Y1, Y2, G, W = [], [], [], [], []
    for mid in sorted({l["market"] for l in links}):
        f = CACHE / f"pm_{mid.split(':')[1]}.npz"
        if not f.exists():
            continue
        pm = np.load(f)
        if len(pm["t"]) == 0:
            continue
        pt, pp = pm["t"], pm["p"].astype(float)
        p_sig, p_close = asof((op - 60).astype(np.int64), pt, pp, PM_MAX_AGE_S), asof(cl.astype(np.int64), pt, pp, PM_MAX_AGE_S)
        prev = np.concatenate([[np.nan], p_close[:-1]])
        x = 100.0 * (p_sig - prev)
        y1 = 100.0 * (p_close - p_sig)
        y2 = 100.0 * (np.concatenate([p_sig[1:], [np.nan]]) - p_sig)
        ok = np.isfinite(x) & np.isfinite(y1)
        X.append(x[ok]); Y1.append(y1[ok]); Y2.append(y2[ok]); G.append(days[ok]); W.append(weekend[ok])
    X, Y1, Y2, G, W = (np.concatenate(a) for a in (X, Y1, Y2, G, W))
    rows = []
    for scope, m in (("all closures", np.ones(len(X), bool)), ("weekends only", W)):
        for name, y in (("09:29 to the close", Y1), ("09:29 to the next 09:29", Y2)):
            k = m & np.isfinite(y)
            rows.append({"scope": scope, "window": name, "kind": "slope, points per point", **en.clustered_slope(X[k], y[k], G[k])})
            for thr in (5.0, 10.0):
                j = k & (np.abs(X) >= thr)
                b = boot((np.sign(X) * y)[j], G[j])
                rows.append({"scope": scope, "window": name, "kind": f"after an overnight move of {thr:.0f}+ points", "n": int(j.sum()),
                             "dates": int(len(np.unique(G[j]))), "mean_abs_move": float(np.abs(X[j]).mean()) if j.any() else float("nan"),
                             "mean": b[0], "ci_lo": b[1], "ci_hi": b[2]})
    keys: list[str] = []
    for r in rows:
        for k_ in r:
            if k_ not in keys:
                keys.append(k_)
    with open(RESULTS / "reversal.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("market-days", len(X), "| markets", len({l['market'] for l in links}))
    for r in rows:
        if "slope" in r:
            print(f"{r['scope']:14} | {r['window']:24} | slope {r['slope']:7.3f} t {r['t']:6.2f} n {r['n']}")
        else:
            print(f"{r['scope']:14} | {r['window']:24} | {r['kind']:42} | n {r['n']:4d} dates {r['dates']:3d} mean {r['mean']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}] (move {r['mean_abs_move']:.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(reversal() if "reversal" in sys.argv else main())
