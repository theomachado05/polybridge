"""Per-event measurements (METHOD.md sections 3-5). Pure given a quote function, so it runs on synthetic chains."""
from __future__ import annotations

import math
from typing import Callable

from arbscan import implied
from arbscan.costs import commission_per_share
from arbscan.implied import Quote, Spread

PM_MAX_AGE = 900
PM_RANGE = (0.05, 0.95)
OPT_RANGE = (0.02, 0.98)
MOVE_MIN = 0.03
BIG_MOVE = 0.05
PLACEHOLDER = 0.5
OPEN_MAX_AGE = 900
COARSE = 0.05


def pm_at(points: list[tuple[float, float]], ts: float, max_age: float = PM_MAX_AGE) -> float | None:
    """Last (t, p) at or before ts, at most max_age seconds old."""
    best = None
    for t, p in points:
        if t <= ts and (best is None or t > best[0]):
            best = (t, p)
    if best is None or ts - best[0] > max_age:
        return None
    return float(best[1])


def kalshi_mid_at(candles: list[dict], ts: float, max_age: float = PM_MAX_AGE) -> float | None:
    from arbscan.datasrc import kalshi_bid_ask_at
    ba = kalshi_bid_ask_at(candles, ts, max_age)
    return None if ba is None else (ba["bid"] + ba["ask"]) / 2


def pm_filter(pm_close: float | None, pm_open: float | None) -> str:
    """Filters 1-3 of METHOD.md section 3. '' = passes."""
    if pm_close is None or pm_open is None:
        return "f1_no_pm_price"
    if not (PM_RANGE[0] <= pm_close <= PM_RANGE[1]):
        return "f1_pm_close_extreme"
    if abs(pm_close - PLACEHOLDER) < 1e-9 or abs(pm_open - PLACEHOLDER) < 1e-9:
        return "f2_placeholder_050"
    if abs(pm_open - pm_close) < MOVE_MIN - 1e-12:
        return "f3_move_below_3pt"
    return ""


def spread_at(chain: dict[float, str], strike: float, get_quote: Callable[[str, float], Quote | None], snap_ts: float,
              exp_close_ts: float, max_age: float = implied.STALE_OPTION_SEC, floor_ts: float | None = None,
              extra: int = 0, pair: tuple[float, float] | None = None) -> Spread | None:
    """Call-spread probability at snap_ts (arbscan rules). `floor_ts`: leg quotes stamped before it are invalid.
    `pair`: price exactly these two strikes (no stepping) instead of picking."""
    t_years = max((exp_close_ts - snap_ts) / (365.0 * 86400.0), 0.0)

    def q(k: float) -> Quote | None:
        x = get_quote(chain[k], snap_ts)
        if x is None or (floor_ts is not None and not math.isnan(x.ts) and x.ts < floor_ts):
            return None
        return x

    if pair is not None:
        if pair[0] not in chain or pair[1] not in chain:
            return None
        q1, q2 = q(pair[0]), q(pair[1])
        if q1 is None or q2 is None or not q1.valid(snap_ts, max_age) or not q2.valid(snap_ts, max_age):
            return None
        return Spread(pair[0], pair[1], q1, q2, t_years)
    if not chain:
        return None
    return implied.pick_spread(sorted(chain), strike, q, t_years, extra=extra, snapshot_ts=snap_ts, max_age=max_age)


def opt_filter(oc: Spread | None, oo: Spread | None) -> str:
    """Filter 4. '' = passes."""
    if oc is None or oo is None:
        return "f4_no_option_spread"
    if not (OPT_RANGE[0] <= oc.p_mid <= OPT_RANGE[1]):
        return "f4_opt_close_extreme"
    if oc.noarb_violation or oo.noarb_violation:
        return "f4_noarb_violation"
    return ""


def event_metrics(pm_close: float, pm_open: float, oc: Spread, oo: Spread) -> dict:
    """dPM, dOpt, s, G, cost, G_net (METHOD.md section 4)."""
    d_pm = pm_open - pm_close
    d_opt = oo.p_mid - oc.p_mid
    s = 1 if d_pm > 0 else -1
    g = s * (d_pm - d_opt)
    half = (oo.p_hi - oo.p_mid) if s > 0 else (oo.p_mid - oo.p_lo)
    comm = commission_per_share(oo.width)
    return dict(d_pm=d_pm, d_opt=d_opt, s=s, G=g, cost_half=half, cost_comm=comm, G_net=g - half - comm)


def follow_through(s: int, oo: Spread, oe: Spread | None, pm_open: float, pm_eod: float | None) -> dict:
    """Secondary 1: same strike pair priced at the end of the reopening day."""
    out = dict(F=None, rt_pnl=None, pm_follow=None)
    if pm_eod is not None:
        out["pm_follow"] = s * (pm_eod - pm_open)
    if oe is None:
        return out
    comm = commission_per_share(oo.width)
    out["F"] = s * (oe.p_mid - oo.p_mid)
    out["rt_pnl"] = (oe.p_lo - oo.p_hi if s > 0 else oo.p_lo - oe.p_hi) - 2 * comm
    return out


def trade_prints_in(trades: list[dict], t0: float, t1: float) -> bool | None:
    """True/False whether a print falls in [t0, t1]; None when the fetched history does not reach back to t0."""
    ts = [float(t["timestamp"]) for t in trades if t.get("timestamp") is not None]
    if any(t0 <= x <= t1 for x in ts):
        return True
    if not ts or min(ts) > t0:
        return None
    return False
