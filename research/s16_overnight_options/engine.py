"""S16 engine: events, controls, quote validity, the three trades, bootstrap, book metrics (METHOD.md sections 1 to 8).

Pure functions; no network. Prices are per share; one contract is 100 shares."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as cfg

KEYS = {cfg.PREV_CLOSE: "prev", cfg.T0931: "0931", cfg.T0935: "0935", cfg.T0945: "0945", cfg.T1000: "1000", cfg.T1030: "1030",
        cfg.CLOSE: "close"}


# ---------------------------------------------------------------- events and controls

def expand(mornings: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """One row per (ticker, day) with |x| >= threshold: the question with the largest |x| (ties: lowest market id).
    direction = sign(x) * the ticker's sign in the link."""
    rows = []
    for r in mornings.itertuples():
        if not abs(r.x) >= threshold:
            continue
        for tok in str(r.tickers).split():
            rows.append({"day": r.day, "ticker": tok[1:], "x": float(r.x), "direction": int(np.sign(r.x)) * (1 if tok[0] == "+" else -1),
                         "market": r.market, "question": r.question, "weekend": bool(r.weekend)})
    e = pd.DataFrame(rows)
    if e.empty:
        return e
    e["ax"] = e.x.abs()
    e["mid_num"] = e.market.str.split(":").str[1].astype(int)
    e = e.sort_values(["ticker", "day", "ax", "mid_num"], ascending=[True, True, False, True]).drop_duplicates(["ticker", "day"])
    return e.drop(columns=["ax", "mid_num"]).sort_values(["day", "ticker"]).reset_index(drop=True)


def match_controls(event_idx: list[int], quiet: set[int], used: set[int] | None = None,
                   max_dist: int = cfg.CONTROL_MAX_TRADING_DAYS) -> dict[int, int]:
    """Each event session (index into the session list) gets the nearest quiet session within max_dist trading days
    that is not yet used (ties: the earlier one). Events are served in date order. `used` is updated in place."""
    used = set() if used is None else used
    out: dict[int, int] = {}
    for e in sorted(event_idx):
        best = None
        for d in range(1, max_dist + 1):
            for c in (e - d, e + d):
                if c in quiet and c not in used:
                    best = c
                    break
            if best is not None:
                break
        if best is not None:
            used.add(best)
            out[e] = best
    return out


def oos_from(event_days: list[str], fraction: float = cfg.OOS_FRACTION) -> str:
    d = sorted(set(event_days))
    return d[len(d) - int(math.ceil(fraction * len(d)))]


# ---------------------------------------------------------------- quotes and trades

def put_ticker(call: str) -> str:
    """The put with the same expiry and strike (OCC symbol: ...YYMMDD C 00038000)."""
    assert call[-9] == "C", call
    return call[:-9] + "P" + call[-8:]


def valid_quote(q: dict | None, at: float, max_age: float, floor: float | None = None) -> bool:
    """bid > 0, ask >= bid, stamped at or before the instant, at most max_age old, and not before `floor`."""
    if not q:
        return False
    b, a, ts = q.get("bid") or 0.0, q.get("ask") or 0.0, q.get("ts") or 0.0
    if not (b > 0 and a >= b):
        return False
    if ts > at + 1e-6 or at - ts > max_age:
        return False
    return floor is None or ts >= floor


def widen(bid: float, ask: float, c: float) -> tuple[float, float]:
    m, h = (ask + bid) / 2, (ask - bid) / 2
    return max(m - c * h, 0.0), m + c * h


def trade(hyp: str, direction: int, entry: dict, exit_: dict, c: float | None) -> dict | None:
    """One trade of a hypothesis from the leg quotes at entry and exit: {"call": (bid, ask), "put": (bid, ask)}.
    c = cost multiplier (1 = the quoted spread and one commission per leg each way); c = None is mid to mid, no cost.
    Returns pnl per contract set (dollars), premium at the price traded, ret = pnl / premium."""
    if hyp == "H-dir":
        legs = ["call" if direction > 0 else "put"]
    else:
        legs = ["call", "put"]
    if any(entry.get(l) is None or exit_.get(l) is None for l in legs):
        return None
    long = hyp != "H-rich"
    if c is None:
        m1 = sum(sum(entry[l]) / 2 for l in legs)
        m2 = sum(sum(exit_[l]) / 2 for l in legs)
        if m1 <= 0:
            return None
        pnl = (m2 - m1) * 100 * (1 if long else -1)
        return {"pnl": pnl, "premium": m1 * 100, "ret": pnl / (m1 * 100)}
    e = [widen(*entry[l], c) for l in legs]
    x = [widen(*exit_[l], c) for l in legs]
    comm = 2 * len(legs) * c * cfg.COMMISSION
    if long:
        paid, got = sum(a for _, a in e), sum(b for b, _ in x)
        premium, pnl = paid * 100, (got - paid) * 100 - comm
    else:
        got, paid = sum(b for b, _ in e), sum(a for _, a in x)
        premium, pnl = got * 100, (got - paid) * 100 - comm
    if premium <= 0:
        return None
    return {"pnl": pnl, "premium": premium, "ret": pnl / premium}


def legs_at(rec: dict, key: str) -> dict:
    """{"call": (bid, ask) or None, "put": ...} of a record at an instant key ("0935", "close", ...)."""
    out = {}
    for leg, p in (("call", "c"), ("put", "p")):
        b, a = rec.get(f"{p}_bid_{key}"), rec.get(f"{p}_ask_{key}")
        out[leg] = (float(b), float(a)) if b is not None and a is not None and b == b and a == a else None
    return out


def rel_spread(q: dict, legs: list[str]) -> float:
    """Quoted spread of the legs as a share of their mid premium."""
    if any(q.get(l) is None for l in legs):
        return float("nan")
    mid = sum(sum(q[l]) / 2 for l in legs)
    return sum(q[l][1] - q[l][0] for l in legs) / mid if mid > 0 else float("nan")


# ---------------------------------------------------------------- inference and the book

def boot_mean(by: dict[str, list[float]], n_boot: int = cfg.N_BOOT, seed: int = cfg.BOOT_SEED) -> tuple[float, float, float]:
    """Mean over all trades with a 95% interval from resampling dates (S7's)."""
    keys = sorted(k for k, v in by.items() if v)
    allv = [x for k in keys for x in by[k]]
    if not allv:
        return (float("nan"),) * 3
    if len(keys) < 5:
        return (float(np.mean(allv)), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    sums, cnts = np.array([sum(by[k]) for k in keys]), np.array([len(by[k]) for k in keys])
    pick = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(np.mean(allv)), float(lo), float(hi)


def book(day_ret: np.ndarray, days: list[str]) -> dict:
    """Sharpe, drawdown, worst month of a daily return series (a day with no trade is zero)."""
    r = np.asarray(day_ret, float)
    sd = float(np.std(r, ddof=1)) if len(r) > 2 else 0.0
    e = np.concatenate([[0.0], np.cumsum(r)])
    months: dict[str, float] = {}
    for x, d in zip(r, days):
        months[d[:7]] = months.get(d[:7], 0.0) + float(x)
    return {"sharpe": float(np.mean(r) / sd * math.sqrt(cfg.DAYS_PER_YEAR)) if sd > 0 else float("nan"),
            "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)) if len(r) else float("nan"),
            "total_return": float(e[-1]), "worst_month": min(months.values()) if months else float("nan"), "sessions": len(r)}


def verdict(oos_n: int, oos_mean: float, oos_lo: float, oos_mean_2x: float, is_mean: float) -> tuple[str, list[tuple[str, bool, str]]]:
    """The pre-registered pass line of section 5. Returns the verdict and each line with its evidence."""
    def pct(v):
        return "n/a" if v != v else f"{100 * v:+.1f}%"

    lines = [
        ("(a) at least 30 out-of-sample trades", oos_n >= cfg.MIN_OOS_TRADES, f"{oos_n} trades"),
        ("(b) out-of-sample mean net return above zero, interval excluding zero (1x costs)",
         bool(oos_mean == oos_mean and oos_mean > 0 and oos_lo == oos_lo and oos_lo > 0), f"{pct(oos_mean)}, interval from {pct(oos_lo)}"),
        ("(c) out-of-sample mean above zero at 2x costs", bool(oos_mean_2x == oos_mean_2x and oos_mean_2x > 0), pct(oos_mean_2x)),
        ("(d) in-sample mean net return above zero", bool(is_mean == is_mean and is_mean > 0), pct(is_mean)),
    ]
    if all(ok for _, ok, _ in lines):
        return "pass (a lead, needs replication)", lines
    if not lines[0][1] and all(ok for _, ok, _ in lines[1:]):
        return "too few observations", lines
    return "fail", lines
