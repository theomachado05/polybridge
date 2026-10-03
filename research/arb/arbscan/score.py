"""Score one (PM market, snapshot) row against an option chain. Pure given a quote function, so it runs on synthetic chains."""
from __future__ import annotations

import math
from typing import Callable

from . import implied
from .implied import Quote

PM_MAX_AGE_SEC = 900            # a resolved PM price older than 15 minutes is stale


def score_row(*, pm: dict, strike: float, chain: dict[float, str], get_quote: Callable[[str], Quote | None],
              snap_ts: float, expiry_close_ts: float | None, clean: bool, live: bool, fee, meta: dict | None = None) -> dict:
    """`pm` keys: mid, bid, ask, bid_size, ask_size, age_s (None = live), spread_assumed (bool).
    `chain` maps listed call strike -> option ticker. Returns a flat dict (CSV row)."""
    row = dict(meta or {})
    mid = pm.get("mid")
    row.update(strike=strike, live=live, clean=clean, pm_mid=mid, pm_bid=pm.get("bid"), pm_ask=pm.get("ask"),
               pm_bid_size=pm.get("bid_size"), pm_ask_size=pm.get("ask_size"), pm_age_s=pm.get("age_s"),
               pm_spread_assumed=bool(pm.get("spread_assumed")))
    age = pm.get("age_s")
    fresh = live or (age is not None and age <= PM_MAX_AGE_SEC)
    informative = mid is not None and implied.INFORMATIVE[0] <= mid <= implied.INFORMATIVE[1]
    row.update(fresh=fresh, informative=informative)
    if mid is None:
        return {**row, "status": "no_pm_price", "label": "not_scored"}
    if not fresh:
        return {**row, "status": "pm_stale", "label": "not_scored"}
    if not informative:
        return {**row, "status": "pm_extreme", "label": "not_scored"}
    if not chain:
        return {**row, "status": "no_chain", "label": "not_scored"}

    strikes = sorted(chain)
    t_years = max(((expiry_close_ts or snap_ts) - snap_ts) / (365.0 * 86400.0), 0.0)
    max_age = None if live else implied.STALE_OPTION_SEC
    qfn = lambda s: get_quote(chain[s])  # noqa: E731
    nar = implied.pick_spread(strikes, strike, qfn, t_years, extra=0, snapshot_ts=snap_ts, max_age=max_age)
    if nar is None:
        return {**row, "status": "no_chain", "label": "not_scored"}
    wid = implied.pick_spread(strikes, strike, qfn, t_years, extra=1, snapshot_ts=snap_ts, max_age=max_age)

    bid, ask = pm["bid"], pm["ask"]
    size = _min_size(pm)
    e = implied.edges(nar, strike, bid, ask, fee, size)
    b1, a1 = max(0.01, mid - 0.01), min(0.99, mid + 0.01)
    # sensitivity for rows whose PM spread is assumed: what if the PM book were one tick wide on each side
    edge_1tick = implied.edges(nar, strike, b1, a1, fee, size)["edge"] if pm.get("spread_assumed") else None
    edge_wide = implied.edge_for_trade(wid, e["trade"], bid, ask, fee, size) if wid is not None else None
    q_ts = [q.ts for q in (nar.q1, nar.q2) if not math.isnan(q.ts)]
    opt_age = snap_ts - min(q_ts) if q_ts else None
    options_open = opt_age is not None and opt_age <= implied.STALE_OPTION_SEC
    width_sens = abs(nar.p_mid - wid.p_mid) if wid is not None else None
    legs_have_size = not math.isnan(nar.min_leg_size) and nar.min_leg_size >= 1
    touch = pm.get("bid_size") if e["trade"].startswith("A") else pm.get("ask_size")
    label = implied.classify(clean=clean, informative=informative, fresh=fresh, p_mid_narrow=nar.p_mid, p_lo=nar.p_lo,
                             p_hi=nar.p_hi, pm_mid=mid, edge=e["edge"], edge_wide_same_trade=edge_wide, live=live,
                             options_open=options_open, pm_size_at_touch=touch, width=nar.width,
                             legs_have_size=legs_have_size)
    if label == "gap_executable" and pm.get("spread_assumed"):
        label = "gap_robust"          # defensive: an assumed spread can never be executable
    gap_vs_bounds = 0.0 if nar.p_lo <= mid <= nar.p_hi else (mid - nar.p_hi if mid > nar.p_hi else mid - nar.p_lo)
    row.update(status="scored", label=label, k1=nar.k1, k2=nar.k2, width=nar.width, stepped=nar.stepped,
               p_mid=nar.p_mid, p_lo=nar.p_lo, p_hi=nar.p_hi, raw_mid=nar.raw_mid, noarb_violation=nar.noarb_violation,
               wide_k1=getattr(wid, "k1", None), wide_k2=getattr(wid, "k2", None), p_mid_wide=getattr(wid, "p_mid", None),
               width_sens=width_sens, coarse=bool(width_sens is not None and width_sens > implied.COARSE_WIDTH_SENS),
               mid_gap=mid - nar.p_mid, gap_vs_bounds=gap_vs_bounds, trade=e["trade"], edge=e["edge"], edge_1tick=edge_1tick,
               edge_A=e["edge_A"], edge_B=e["edge_B"], edge_wide=edge_wide, strip_loss=e["strip_loss"],
               opt_leg_min_size=nar.min_leg_size, opt_quote_age_s=opt_age, options_open=options_open,
               pm_touch_size=touch, hedge_shares_per_contract=100 * nar.width)
    return row


def _min_size(pm: dict) -> float | None:
    s = [x for x in (pm.get("bid_size"), pm.get("ask_size")) if x is not None and not math.isnan(x)]
    return min(s) if s else None
