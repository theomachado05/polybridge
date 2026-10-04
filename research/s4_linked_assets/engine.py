"""S4 engine: sessions, as-of odds, betas, the walk-forward data gate, signals and trades (METHOD.md sections 1 to 6).

Pure functions on arrays; no network. Times are epoch seconds UTC."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof

from . import config as cfg

ET = "America/New_York"
BAR_S = 300
BIN_BARS = cfg.GATE_BIN_MIN * 60 // BAR_S


# ---------------------------------------------------------------- sessions and prices

def sessions_from(spy_t: np.ndarray) -> pd.DataFrame:
    """One row per session, from SPY's regular 5-minute bars: day, open and close instants."""
    day = pd.to_datetime(spy_t, unit="s", utc=True).tz_convert(ET).strftime("%Y-%m-%d")
    g = pd.DataFrame({"day": day, "t": spy_t}).groupby("day").t.agg(["min", "max"])
    return pd.DataFrame({"day": g.index, "open": g["min"].to_numpy(), "close": g["max"].to_numpy() + BAR_S}).reset_index(drop=True)


def session_prices(bars: dict, sess: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per session: the price at the open, at every 30-minute boundary and at the close, plus early volume.
    The open is the first bar's open and is used only if that bar starts within 10 minutes of the open. Later
    boundaries use the last bar close before the boundary (a thin ticker can skip a bar)."""
    n = len(sess)
    nb = int((sess.close - sess.open).max() // (BIN_BARS * BAR_S))
    px = np.full((n, nb + 1), np.nan)
    close = np.full(n, np.nan)
    vol5 = np.full(n, np.nan)
    vol30 = np.full(n, np.nan)
    t, o, c, v, vw = (bars[k] for k in ("t", "o", "c", "v", "vw"))
    for i, (op, cl) in enumerate(zip(sess.open.to_numpy(), sess.close.to_numpy())):
        a, b = np.searchsorted(t, op), np.searchsorted(t, cl)
        if b <= a or t[a] - op > 600:
            continue
        px[i, 0] = o[a]
        ends = t[a:b] + BAR_S
        for k in range(1, int((cl - op) // (BIN_BARS * BAR_S)) + 1):
            j = np.searchsorted(ends, op + k * BIN_BARS * BAR_S, side="right") - 1
            if j >= 0:
                px[i, k] = c[a + j]
        close[i] = c[b - 1]
        first = t[a:b] < op + BAR_S
        early = t[a:b] < op + BIN_BARS * BAR_S
        vol5[i] = float(np.sum(v[a:b][first] * vw[a:b][first]))
        vol30[i] = float(np.sum(v[a:b][early] * vw[a:b][early]))
    return {"px": px, "close": close, "vol5": vol5, "vol30": vol30}


def betas(day_asset: dict, day_spy: dict, days: list[str]) -> np.ndarray:
    """OLS beta of daily close-to-close returns on SPY's over the sessions strictly before each day."""
    a = pd.Series(day_asset["c"], index=day_asset["day"]).pct_change()
    s = pd.Series(day_spy["c"], index=day_spy["day"]).pct_change()
    df = pd.concat([a.rename("a"), s.rename("s")], axis=1).dropna()
    idx = df.index.to_numpy()
    out = np.ones(len(days))
    for i, d in enumerate(days):
        w = df.iloc[max(0, np.searchsorted(idx, d) - cfg.BETA_LOOKBACK): np.searchsorted(idx, d)]
        if len(w) >= cfg.BETA_MIN and w.s.var() > 0:
            out[i] = float(np.cov(w.a, w.s)[0, 1] / w.s.var())
    return out


# ---------------------------------------------------------------- one link

@dataclass
class LinkDays:
    """Per session, for one (market, ticker, direction) link. Moves in odds are in pp and signed by the direction;
    equity moves are excess returns in bp."""
    x_night: np.ndarray       # previous close to 09:29
    x_next_night: np.ndarray  # this close to the next 09:29
    x_next_24h: np.ndarray    # this close to the next close
    e_gap: np.ndarray         # previous close to open
    e_day: np.ndarray         # open to close
    e_10: np.ndarray          # open to 10:00
    sxx: np.ndarray           # data gate: per-session sums over 30-minute bins with a non-zero change in odds
    sxy: np.ndarray
    nbin: np.ndarray


def link_days(pm_t: np.ndarray, pm_p: np.ndarray, direction: int, sess: pd.DataFrame, asset: dict, spy: dict,
              beta: np.ndarray) -> LinkDays:
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    n = len(sess)

    def p(at):
        return asof(np.asarray(at, dtype=np.int64), pm_t, pm_p, cfg.PM_MAX_AGE_S)

    p_sig, p_close = p(op - 60), p(cl)
    prev_close = np.concatenate([[np.nan], p_close[:-1]])
    x_night = direction * 100.0 * (p_sig - prev_close)
    x_next_night = direction * 100.0 * (np.concatenate([p_sig[1:], [np.nan]]) - p_close)
    x_next_24h = direction * 100.0 * (np.concatenate([p_close[1:], [np.nan]]) - p_close)

    def ret(px_a, px_b):
        return px_b / px_a - 1.0

    a_open, s_open = asset["px"][:, 0], spy["px"][:, 0]
    a_prev, s_prev = np.concatenate([[np.nan], asset["close"][:-1]]), np.concatenate([[np.nan], spy["close"][:-1]])
    e_gap = 1e4 * (ret(a_prev, a_open) - beta * ret(s_prev, s_open))
    e_day = 1e4 * (ret(a_open, asset["close"]) - beta * ret(s_open, spy["close"]))
    e_10 = 1e4 * (ret(a_open, asset["px"][:, 1]) - beta * ret(s_open, spy["px"][:, 1]))

    nb = asset["px"].shape[1] - 1
    sxx, sxy, nbin = np.zeros(n), np.zeros(n), np.zeros(n, dtype=int)
    bounds = op[:, None] + np.arange(nb + 1)[None, :] * BIN_BARS * BAR_S
    pb = p(bounds.ravel()).reshape(bounds.shape)
    for k in range(nb):
        dp = direction * 100.0 * (pb[:, k + 1] - pb[:, k])
        r = 1e4 * (ret(asset["px"][:, k], asset["px"][:, k + 1]) - beta * ret(spy["px"][:, k], spy["px"][:, k + 1]))
        ok = np.isfinite(dp) & np.isfinite(r) & (dp != 0) & (bounds[:, k + 1] <= cl)
        sxx += np.where(ok, dp * dp, 0.0)
        sxy += np.where(ok, dp * r, 0.0)
        nbin += ok.astype(int)
    return LinkDays(x_night, x_next_night, x_next_24h, e_gap, e_day, e_10, sxx, sxy, nbin)


def gate(sxx: np.ndarray, sxy: np.ndarray, nbin: np.ndarray) -> dict[str, np.ndarray]:
    """Walk-forward data gate. Entry i uses sessions strictly before i: bins, sessions, the through-origin slope
    (bp per pp), its t-statistic with errors clustered by session, and whether the link is confirmed."""
    def before(a):
        return np.concatenate([[0.0], np.cumsum(a)[:-1]])

    Sxx, Sxy = before(sxx), before(sxy)
    A, B, C = before(sxy * sxy), before(sxy * sxx), before(sxx * sxx)
    bins, sessions = before(nbin), before(nbin > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(Sxx > 0, Sxy / Sxx, np.nan)
        var = (A - 2 * slope * B + slope * slope * C) / (Sxx * Sxx)
        t = np.where(var > 0, slope / np.sqrt(var), np.nan)
    ok = (bins >= cfg.GATE_MIN_BINS) & (sessions >= cfg.GATE_MIN_SESSIONS) & (slope > 0) & (t >= cfg.GATE_MIN_T)
    return {"bins": bins, "sessions": sessions, "slope": slope, "t": t, "confirmed": ok}


# ---------------------------------------------------------------- trades

def cost_bp(ticker: str, beta: float, mult: float) -> float:
    """Round trip, bp of the equity notional: two sides on the equity and two on the SPY hedge."""
    c = cfg.COST_LIQUID if ticker in cfg.LIQUID else cfg.COST_OTHER
    return mult * (2 * c + abs(beta) * 2 * cfg.COST_SPY)


def pick(signals: pd.DataFrame) -> pd.DataFrame:
    """One day's signals (ticker, x): those with |x| at or above the threshold, at most MAX_POSITIONS, largest first."""
    s = signals[np.abs(signals.x) >= cfg.X_MIN_PP]
    return s.reindex(s.x.abs().sort_values(ascending=False).index).head(cfg.MAX_POSITIONS)


def trade_bp(x: float, e_move_bp: float, ticker: str, beta: float, mult: float) -> tuple[float, float]:
    """(gross, net) return of one trade in bp of the equity notional: long the equity when the odds moved for it."""
    gross = math.copysign(1.0, x) * e_move_bp
    return gross, gross - cost_bp(ticker, beta, mult)


def day_metrics(pnl_by_day: np.ndarray, days: list[str], traded: float) -> dict:
    r = pnl_by_day / cfg.CAPITAL
    sd = float(np.std(r, ddof=1)) if len(r) > 2 else 0.0
    e = np.concatenate([[0.0], np.cumsum(r)])
    months: dict[str, float] = {}
    for x, d in zip(r, days):
        months[d[:7]] = months.get(d[:7], 0.0) + float(x)
    years = max(len(r) / cfg.DAYS_PER_YEAR, 1e-9)
    daily_sharpe = float(np.mean(r) / sd) if sd > 0 else float("nan")
    return {"sharpe": daily_sharpe * math.sqrt(cfg.DAYS_PER_YEAR) if sd > 0 else float("nan"), "daily_sharpe": daily_sharpe,
            "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)), "total_return": float(e[-1]),
            "worst_month": min(months.values()) if months else float("nan"),
            "worst_month_label": min(months, key=months.get) if months else "", "turnover_ann": traded / cfg.CAPITAL / years,
            "skew": float(pd.Series(r).skew()) if len(r) > 2 and sd > 0 else 0.0,
            "kurtosis": float(pd.Series(r).kurt() + 3) if len(r) > 3 and sd > 0 else 3.0}


def date_bootstrap(by_date: dict[str, list[float]], n_boot: int = cfg.N_BOOT, seed: int = cfg.BOOT_SEED) -> tuple[float, float, float]:
    """Mean per trade and its 95% interval, resampling dates."""
    keys = sorted(k for k, v in by_date.items() if v)
    allv = [x for k in keys for x in by_date[k]]
    if not allv:
        return (float("nan"),) * 3
    if len(keys) < 5:
        return (float(np.mean(allv)), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    sums, cnts = np.array([sum(by_date[k]) for k in keys]), np.array([len(by_date[k]) for k in keys])
    pick_ = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    means = sums[pick_].sum(axis=1) / cnts[pick_].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(np.mean(allv)), float(lo), float(hi)


def clustered_slope(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> dict:
    """Through-origin slope of y on x with errors clustered by group, and the share of same-sign pairs."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, g = x[ok], y[ok], groups[ok]
    nz = (x != 0) & (y != 0)
    sxx = float(np.sum(x * x))
    if sxx <= 0:
        return {"n": int(len(x)), "slope": float("nan"), "se": float("nan"), "t": float("nan"), "sign_agree": float("nan"), "n_nonzero": 0}
    b = float(np.sum(x * y) / sxx)
    s = pd.Series(x * (y - b * x)).groupby(pd.Series(g).to_numpy()).sum()
    se = float(np.sqrt(np.sum(s.to_numpy() ** 2)) / sxx)
    return {"n": int(len(x)), "slope": b, "se": se, "t": b / se if se > 0 else float("nan"),
            "sign_agree": float(np.mean(np.sign(x[nz]) == np.sign(y[nz]))) if nz.any() else float("nan"), "n_nonzero": int(nz.sum()),
            "clusters": int(s.size)}
