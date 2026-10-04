"""S25 pure functions: the price of the hedge spread from two leg quotes, its payoff at expiry, the split rules, the four
outcome cells, the two-leg book and the risk statistics. No network, no files. Rules in METHOD.md."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Sequence

import numpy as np
import pandas as pd

from . import config as cfg

CELLS = ("never touched", "touched and finished beyond", "touched and came back", "finished beyond without a recorded touch")


# ---------------------------------------------------------------- the hedge leg

def usable(q: dict | None, at: float, open_epoch: float) -> bool:
    """A leg quote that can be traded at the hedge instant: an offer above zero, a bid of zero or more not above it,
    timestamped at or after the session's open and at or before the instant (one second of slack, as S21)."""
    if q is None:
        return False
    bid, ask, ts = float(q["bid"]), float(q["ask"]), float(q["ts"])
    if not (ask > 0 and ask >= bid >= 0):
        return False
    return open_epoch <= ts <= at + 1.0


def leg_prices(bid: float, ask: float, cost_mult: float) -> tuple[float, float]:
    """(price paid to buy, price received to sell) one leg. 1x: the ask and the bid. 2x: each a further half-spread
    against us; a sale is never below zero."""
    extra = (cost_mult - 1.0) * (ask - bid) / 2.0
    return ask + extra, max(0.0, bid - extra)


def unit_cost(direction: int, lo_bid: float, lo_ask: float, hi_bid: float, hi_ask: float, width: float, cost_mult: float = 1.0) -> dict:
    """The cost of one unit (1/width of a spread per share: pays $1 beyond the far strike), long leg bought, short leg
    sold. Up: long the call at k_lo, short the call at k_hi. Down: long the put at k_hi, short the put at k_lo."""
    long_bid, long_ask, short_bid, short_ask = (lo_bid, lo_ask, hi_bid, hi_ask) if direction > 0 else (hi_bid, hi_ask, lo_bid, lo_ask)
    buy, _ = leg_prices(long_bid, long_ask, cost_mult)
    _, sell = leg_prices(short_bid, short_ask, cost_mult)
    raw = (buy - sell) / width
    commission = cost_mult * 2.0 * cfg.OPTION_COMMISSION_PER_CONTRACT / (cfg.SHARES_PER_CONTRACT * width)
    mid = ((long_bid + long_ask) / 2.0 - (short_bid + short_ask) / 2.0) / width
    return {"quotes": max(0.0, raw), "commission": commission, "cost": max(0.0, raw) + commission, "mid": mid,
            "crossed": bool(raw < 0), "above_one": bool(raw > 1.0)}


def unit_payoff(direction: int, close: float, k_lo: float, k_hi: float) -> float:
    """What one unit pays at expiry: 0 short of the near strike, 1 beyond the far strike, linear between."""
    w = k_hi - k_lo
    x = (close - k_lo) / w if direction > 0 else (k_hi - close) / w
    return float(min(1.0, max(0.0, x)))


def hedge_pnl_points(h: float, payoff: float, cost: float) -> float:
    return 100.0 * h * (payoff - cost)


# ---------------------------------------------------------------- closes and splits

def split_between(splits: Sequence[dict], after_day: str, upto_day: str) -> bool:
    """A split with an execution date after `after_day` and on or before `upto_day` (ISO dates)."""
    return any(after_day < str(s["execution_date"]) <= upto_day for s in splits)


def later_split_factor(splits: Sequence[dict], day: str) -> float:
    """What the adjusted close of `day` should be as a multiple of the unadjusted one: the product of from/to over
    every split executed after `day`."""
    f = 1.0
    for s in splits:
        if str(s["execution_date"]) > day:
            f *= float(s["split_from"]) / float(s["split_to"])
    return f


def reconciles(adjusted: float, unadjusted: float, splits: Sequence[dict], day: str) -> bool:
    if not (adjusted > 0 and unadjusted > 0):
        return False
    return abs(adjusted / unadjusted / later_split_factor(splits, day) - 1.0) <= cfg.SPLIT_RECONCILE_TOL


def level_ratio_ok(close_on_anchor_day: float, level: float) -> bool:
    lo, hi = cfg.LEVEL_RATIO_BOUNDS
    return bool(level > 0 and close_on_anchor_day == close_on_anchor_day and lo <= close_on_anchor_day / level <= hi)


# ---------------------------------------------------------------- outcome cells

def finished_beyond(direction: int, close: float, level: float) -> bool:
    return bool(close >= level) if direction > 0 else bool(close <= level)


def cell(outcome: float, direction: int, close: float, level: float) -> str:
    touched, beyond = outcome >= 0.5, finished_beyond(direction, close, level)
    if touched:
        return CELLS[1] if beyond else CELLS[2]
    return CELLS[3] if beyond else CELLS[0]


# ---------------------------------------------------------------- statistics

def risk_stats(x: Sequence[float]) -> dict:
    """Per-market P&L in points: standard deviation (n - 1), worst and best market, skew, share of losing markets."""
    a = np.asarray(list(x), float)
    if len(a) == 0:
        return {"sd": float("nan"), "worst_market": float("nan"), "best_market": float("nan"), "skew": float("nan"), "share_losing": float("nan")}
    return {"sd": float(np.std(a, ddof=1)) if len(a) > 1 else float("nan"), "worst_market": float(a.min()), "best_market": float(a.max()),
            "skew": float(pd.Series(a).skew()) if len(a) > 2 else float("nan"), "share_losing": float((a < 0).mean())}


def _picks(n_keys: int) -> np.ndarray:
    return np.random.default_rng(cfg.BOOT_SEED).integers(0, n_keys, size=(cfg.N_BOOT, n_keys))


def boot_sd_ratio(a: Sequence[float], b: Sequence[float], events: Sequence) -> tuple[float, float, float]:
    """sd(a) / sd(b) over markets, and its 95% interval resampling events (each event carries all its markets)."""
    a, b, ev = np.asarray(a, float), np.asarray(b, float), np.asarray([str(e) for e in events])
    if len(a) < 2:
        return (float("nan"),) * 3
    point = float(np.std(a, ddof=1) / np.std(b, ddof=1)) if np.std(b, ddof=1) > 0 else float("nan")
    keys = sorted(set(ev))
    if len(keys) < cfg.MIN_EVENTS_FOR_INTERVAL:
        return point, float("nan"), float("nan")
    S = np.array([[np.sum(ev == k), a[ev == k].sum(), (a[ev == k] ** 2).sum(), b[ev == k].sum(), (b[ev == k] ** 2).sum()] for k in keys])
    T = S[_picks(len(keys))].sum(axis=1)                      # draws x 5
    n = T[:, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        va = (T[:, 2] - T[:, 1] ** 2 / n) / (n - 1.0)
        vb = (T[:, 4] - T[:, 3] ** 2 / n) / (n - 1.0)
        r = np.sqrt(va / vb)
    r = r[np.isfinite(r)]
    lo, hi = np.percentile(r, [2.5, 97.5])
    return point, float(lo), float(hi)


def boot_worst_month_diff(month_a: np.ndarray, month_b: np.ndarray) -> tuple[float, float, float, float]:
    """`month_a`, `month_b`: events x months matrices of P&L (dollars). Worst month of a minus worst month of b, its 95%
    interval resampling events, and the share of draws in which a's worst month is not worse than b's."""
    wa, wb = float(month_a.sum(axis=0).min()), float(month_b.sum(axis=0).min())
    if month_a.shape[0] < cfg.MIN_EVENTS_FOR_INTERVAL:
        return wa - wb, float("nan"), float("nan"), float("nan")
    pick = _picks(month_a.shape[0])
    da = month_a[pick].sum(axis=1).min(axis=1)
    db = month_b[pick].sum(axis=1).min(axis=1)
    lo, hi = np.percentile(da - db, [2.5, 97.5])
    return wa - wb, float(lo), float(hi), float((da >= db - 1e-12).mean())


# ---------------------------------------------------------------- the book (S18's function, copied, with legs)

def max_locked(trades: list[dict]) -> float:
    """S18's rule: the largest capital locked at one time; each leg locks its capital from its entry to its end."""
    ev = sorted([(t["entry_epoch"], t["capital"]) for t in trades] + [(t["end_epoch"], -t["capital"]) for t in trades], key=lambda e: (e[0], e[1]))
    cur = best = 0.0
    for _, c in ev:
        cur += c
        best = max(best, cur)
    return best


def month_of(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m")


def book_metrics(pnl: np.ndarray, K: float) -> dict:
    """S6/S18's `closure_metrics` on monthly P&L (copied): Sharpe on monthly returns on the capital base, maximum
    drawdown and worst month as fractions of the capital base; plus the worst month in dollars."""
    if K <= 0 or len(pnl) == 0:
        return {"sharpe": float("nan"), "max_drawdown": float("nan"), "worst_month": float("nan"), "total_return": float("nan"),
                "worst_month_dollars": float("nan"), "monthly_skew": float("nan"), "losing_months": 0}
    r = np.asarray(pnl, float) / K
    sd = float(np.std(r, ddof=1)) if len(r) > 2 else 0.0
    e = np.concatenate([[0.0], np.cumsum(r)])
    return {"sharpe": float(np.mean(r) / sd * math.sqrt(cfg.MONTHS_PER_YEAR)) if sd > 0 else float("nan"),
            "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)), "worst_month": float(r.min()), "total_return": float(e[-1]),
            "worst_month_dollars": float(np.min(pnl)), "monthly_skew": float(pd.Series(r).skew()) if sd > 0 and len(r) > 2 else float("nan"),
            "losing_months": int((np.asarray(pnl) < 0).sum())}


def book(legs: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """`legs`: one row per leg with market, event, segment, pnl and capital (dollars), entry_epoch, end_epoch. P&L is
    booked in the month (UTC, as S18) of the leg's end. Returns (monthly P&L of the whole sample, metrics by segment)."""
    s = legs.copy()
    s["month"] = s.end_epoch.map(month_of)
    months = sorted(pd.period_range(s.month.min(), s.month.max(), freq="M").strftime("%Y-%m")) if len(s) else []
    out = {}
    for seg in ("IS", "OOS", "ALL"):
        t = s if seg == "ALL" else s[s.segment == seg]
        ml = [m for m in months if t.month.min() <= m <= t.month.max()] if len(t) else []
        pc = np.array([t[t.month == m].pnl.sum() for m in ml])
        K = max_locked(t[["entry_epoch", "end_epoch", "capital"]].to_dict("records"))
        out[seg] = {**book_metrics(pc, K), "capital_base": K, "pnl": float(t.pnl.sum()), "months": len(ml), "markets": int(t.market.nunique()),
                    "capital_deployed": float(t.capital.sum())}
    monthly = s.groupby("month").pnl.sum().reindex(months).fillna(0.0) if len(s) else pd.Series(dtype=float)
    return monthly.rename_axis("month").reset_index(), out


def event_month_matrix(legs: pd.DataFrame, events: list[str], months: list[str]) -> np.ndarray:
    """events x months matrix of booked P&L in dollars."""
    m = np.zeros((len(events), len(months)))
    ei, mi = {e: i for i, e in enumerate(events)}, {x: i for i, x in enumerate(months)}
    for e, ep, p in zip(legs.event.astype(str), legs.end_epoch, legs.pnl):
        m[ei[e], mi[month_of(ep)]] += p
    return m
