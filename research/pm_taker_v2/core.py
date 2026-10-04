"""Pure pieces of the taker study (METHOD.md sections 1-5): universe rule, print conversion and thinning, the trade rule,
P&L and the day-cluster bootstrap. No network here, so everything runs on synthetic data."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from arbscan import implied
from arbscan.implied import Spread
from arbscan.parse import parse_pm_question

from . import config as C

ET = ZoneInfo(C.TZ)
UTC = timezone.utc


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def et(d: date, hm: tuple[int, int]) -> datetime:
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=ET)


def frame_row(m: dict, is_session: Callable[[date], bool]) -> tuple[dict | None, str]:
    """Section 1 without the expiry check. Returns (row, "") or (None, reason)."""
    th, why = parse_pm_question(m.get("q", ""))
    if th is None:
        return None, f"parse_{why}"
    if th.kind != "daily":
        return None, f"kind_{th.kind}"
    end = parse_iso(m["end"])
    d = end.astimezone(ET).date()
    if not (date.fromisoformat(C.RES_MIN) <= d <= date.fromisoformat(C.RES_MAX)):
        return None, "outside_window"
    prev = d - timedelta(days=1)
    if not is_session(d):
        return None, "resolution_not_session"
    if not is_session(prev):
        return None, "reopening_day"
    listed = parse_iso(m["start"]) if m.get("start") else None
    w0 = et(prev, C.WINDOW_START_HM)
    if listed is not None:
        w0 = max(w0, listed + timedelta(seconds=C.LISTING_LAG_SEC))
    w1 = et(prev, C.WINDOW_END_HM)
    tok = m.get("tok") or []
    return {"id": str(m["id"]), "cond": m["cond"], "tok": tok[0] if tok else "", "tk": th.ticker, "k": th.strike,
            "res_date": d.isoformat(), "trade_day": prev.isoformat(), "w0": int(w0.timestamp()), "w1": int(w1.timestamp()),
            "exp_close": int(et(d, C.EXPIRY_CLOSE_HM).timestamp()), "fees_listing": bool(m.get("fees")),
            "listed": m.get("start", ""), "empty_window": w0 >= w1}, ""


def yes_equiv(t: dict) -> tuple[float, str] | None:
    px, side, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
    if side not in ("BUY", "SELL"):
        return None
    if out == "yes":
        return px, side
    if out == "no":
        return 1.0 - px, ("BUY" if side == "SELL" else "SELL")
    return None


def thin(trades: list[dict], w0: int, w1: int) -> list[dict]:
    """Yes-equivalent prints inside [w0, w1], first Yes-buy and first Yes-sell per clock minute. The data-api lists
    newest first, so within one second a later list position is the earlier print."""
    rows = []
    for i, t in enumerate(trades):
        ts = t.get("timestamp")
        if ts is None:
            continue
        ts = int(ts)
        if not (w0 <= ts <= w1):
            continue
        ye = yes_equiv(t)
        if ye is None:
            continue
        rows.append((ts, -i, ye[0], ye[1], float(t.get("size") or 0.0), str(t.get("transactionHash", ""))))
    rows.sort()
    seen, out = set(), []
    for ts, _, px, side, size, tx in rows:
        key = (ts // 60, side)
        if key in seen:
            continue
        seen.add(key)
        out.append({"ts": ts, "px": px, "side": side, "size": size, "tx": tx})
    return out


def evaluable(p: dict) -> bool:
    if p["side"] == "BUY":
        return C.X_RANGE[0] - 1e-12 <= p["px"] <= C.BUY_EVAL_MAX + 1e-12
    return C.SELL_EVAL_MIN - 1e-12 <= p["px"] <= C.X_RANGE[1] + 1e-12


def spread_status(sp: Spread | None) -> str:
    if sp is None:
        return "no_spread"
    if sp.noarb_violation or (sp.p_hi - sp.p_lo) > C.BAND_MAX + 1e-12:
        return "unusable"
    if not (C.P_RANGE[0] - 1e-12 <= sp.p_mid <= C.P_RANGE[1] + 1e-12):
        return "unusable"
    return "ok"


def qualifies(side: str, px: float, p_mid: float, tau: float) -> bool:
    if side == "BUY":
        return px <= p_mid - tau + 1e-12
    return px >= p_mid + tau - 1e-12


def option_spread(chain: dict[float, str], k: float, quote_at: Callable[[str, int], object], t: int, exp_close: int) -> Spread | None:
    """Narrow call spread from the last NBBO of each leg at or before t - QUOTE_LAG_SEC (METHOD.md section 2)."""
    if not chain:
        return None
    snap = t - C.QUOTE_LAG_SEC
    t_years = max((exp_close - t) / (365.0 * 86400.0), 0.0)
    return implied.pick_spread(sorted(chain), k, lambda s: quote_at(chain[s], snap), t_years, snapshot_ts=snap,
                               max_age=C.LEG_MAX_AGE, rate=C.RATE)


def evaluate_market(prints: Iterable[dict], spread_at: Callable[[int], Spread | None],
                    taus: tuple[float, ...] = (C.TAUS_SECONDARY[0], C.TAU, C.TAUS_SECONDARY[1]),
                    tau_stop: float = C.TAU_STOP) -> tuple[list[dict], dict[float, dict]]:
    """Evaluate evaluable prints in time order until one qualifies at tau_stop. Returns (evaluated rows, first trade per tau)."""
    evals, trades = [], {}
    for p in prints:
        if not evaluable(p):
            continue
        sp = spread_at(p["ts"])
        st = spread_status(sp)
        row = dict(p, status=st, p_mid=None, p_lo=None, p_hi=None, k1=None, k2=None, stepped=None)
        if sp is not None:
            row.update(p_mid=sp.p_mid, p_lo=sp.p_lo, p_hi=sp.p_hi, k1=sp.k1, k2=sp.k2, stepped=sp.stepped)
        evals.append(row)
        if st != "ok":
            continue
        for tau in taus:
            if tau not in trades and qualifies(p["side"], p["px"], sp.p_mid, tau):
                trades[tau] = row
        if tau_stop in trades:
            break
    return evals, trades


def fee_per_share(price: float, enabled: bool, rate: float = C.FEE_RATE_DEFAULT, exponent: float = C.FEE_EXP_DEFAULT) -> float:
    if not enabled or not (0.0 < price < 1.0):
        return 0.0
    return rate * (price * (1.0 - price)) ** exponent


def fee_params(market: dict) -> tuple[bool, float, float]:
    sched = market.get("feeSchedule") or {}
    enabled = bool(market.get("feesEnabled", False))
    return enabled, float(sched.get("rate", C.FEE_RATE_DEFAULT) or C.FEE_RATE_DEFAULT), \
        float(sched.get("exponent", C.FEE_EXP_DEFAULT) or C.FEE_EXP_DEFAULT)


def net_pnl(side: str, px: float, y: int, tick: float, fee: Callable[[float], float]) -> float:
    """Per $1 contract. side BUY = we buy YES after a Yes-buy print at px; SELL = we buy NO after a Yes-sell print at px."""
    if side == "BUY":
        return y - (px + tick) - fee(px)
    q = 1.0 - px
    return (1 - y) - (q + tick) - fee(q)


def outcome_from_gamma(market: dict) -> int | None:
    def jl(x):
        import json
        if isinstance(x, list):
            return x
        try:
            return json.loads(x) if isinstance(x, str) else []
        except ValueError:
            return []
    outs = [str(o).lower() for o in jl(market.get("outcomes"))]
    prices = jl(market.get("outcomePrices"))
    if not prices:
        return None
    i = outs.index("yes") if "yes" in outs else 0
    try:
        p = float(prices[i])
    except (TypeError, ValueError, IndexError):
        return None
    if p >= C.Y_ONE:
        return 1
    if p <= C.Y_ZERO:
        return 0
    return None


def cluster_boot(values: np.ndarray, clusters: np.ndarray, draws: int = C.BOOT_DRAWS, seed: int = C.SEED) -> tuple[float, float]:
    """95% percentile CI of the pooled mean, resampling whole clusters."""
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return float("nan"), float("nan")
    keys, inv = np.unique(np.asarray(clusters), return_inverse=True)
    s = np.bincount(inv, weights=values, minlength=len(keys))
    n = np.bincount(inv, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    g = len(keys)
    for i in range(draws):
        idx = rng.integers(0, g, g)
        out[i] = s[idx].sum() / n[idx].sum()
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def verdict(n: int, days: int, lo: float, hi: float) -> str:
    if n < C.MIN_TRADES or days < C.MIN_DAYS:
        return "INSUFFICIENT"
    if lo > 0:
        return "PASS"
    if hi < 0:
        return "NEGATIVE"
    return "NULL"


def kill_projection(trades_kill: int, days_with_trade_kill: int, markets_kill: int, markets_all: int,
                    days_kill: int, days_all: int, evaluated_kill: int, no_spread_kill: int) -> dict:
    proj_trades = trades_kill * (markets_all / markets_kill) if markets_kill else 0.0
    proj_days = days_with_trade_kill * (days_all / days_kill) if days_kill else 0.0
    share = no_spread_kill / evaluated_kill if evaluated_kill else float("nan")
    reasons = []
    if proj_trades < C.MIN_TRADES:
        reasons.append("projected_trades_below_100")
    if proj_days < C.MIN_DAYS:
        reasons.append("projected_days_below_30")
    if evaluated_kill and share > C.KILL_NO_SPREAD_MAX:
        reasons.append("no_spread_share_above_30pct")
    return {"projected_trades": proj_trades, "projected_days": proj_days, "no_spread_share": share,
            "stop": bool(reasons), "reasons": reasons}


def mid_at(points: list[tuple[int, float]], ts: int, max_age: int = C.MID_MAX_AGE) -> float | None:
    best = None
    for t, p in points:
        if t <= ts and (best is None or t > best[0]):
            best = (t, p)
    if best is None or ts - best[0] > max_age:
        return None
    return best[1]


def mid_variant_trade(evals: list[dict], points: list[tuple[int, float]], tau: float = C.TAU) -> dict | None:
    """Secondary 6: same evaluated instants, PM mid from prices-history, first qualifying instant."""
    for r in evals:
        if r["status"] != "ok":
            continue
        m = mid_at(points, r["ts"])
        if m is None:
            continue
        if m <= r["p_mid"] - tau + 1e-12:
            return {"ts": r["ts"], "side": "BUY", "mid": m, "p_mid": r["p_mid"]}
        if m >= r["p_mid"] + tau - 1e-12:
            return {"ts": r["ts"], "side": "SELL", "mid": m, "p_mid": r["p_mid"]}
    return None


def brier(p: np.ndarray, y: np.ndarray) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        m = (p >= lo) & ((p < hi) if b < bins - 1 else (p <= hi))
        if m.any():
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_p": float(p[m].mean()), "freq_y": float(y[m].mean())})
    return out


def isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))
