from __future__ import annotations

import math
from typing import Any, Iterable

EQUITY_ADV_PCT_PER_DAY = 0.01
EQUITY_OPEN5_PCT_PER_ORDER = 0.10
OPTION_VOLUME_PCT = 0.10
OPTION_OI_PCT = 0.05
PM_DEPTH_PCT = 0.50
PM_DEPTH_BAND = 0.02
PM_BANDS = (0.01, 0.02, 0.05)
IMPACT_K = 1.0
ADV_SESSIONS = 20
OPEN5_SESSIONS = 20
SIGMA_SESSIONS = 20
LIQUIDATION_SESSIONS = 1
OPTION_MULT = 100

CAPS = {
    "equity": {"per_order": f"<= {EQUITY_OPEN5_PCT_PER_ORDER:.0%} of the opening 5-minute volume (median of the last "
                            f"{OPEN5_SESSIONS} sessions)",
               "per_day": f"<= {EQUITY_ADV_PCT_PER_DAY:.0%} of the {ADV_SESSIONS}-day average daily volume"},
    "option": {"per_order": f"<= {OPTION_VOLUME_PCT:.0%} of the contract's daily volume and <= {OPTION_OI_PCT:.0%} of "
                            "its open interest (every leg)"},
    "pm": {"per_order": f"<= {PM_DEPTH_PCT:.0%} of the book depth within {PM_DEPTH_BAND * 100:.0f} cents of the mid "
                        "(side taken)"},
}
COST_MODEL = {
    "formula": "cost_bp = half_spread_bp + k * sigma_daily * sqrt(q / ADV_shares) * 1e4",
    "k": IMPACT_K,
    "k_source": "square-root law; Toth et al. 2011 (Y ~ 0.5-1), Almgren et al. 2005 (~0.3-1): conservative end",
    "sigma_source": f"SD of the last {SIGMA_SESSIONS} daily close-to-close log returns (Massive daily bars)",
    "spread_source": "Massive last NBBO quote; else the Corwin-Schultz (2012) high-low estimate from daily bars",
}


def clean(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def fin(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def pos(x: Any) -> float | None:
    v = fin(x)
    return v if v is not None and v > 0 else None


def floor0(x: float | None) -> int | None:
    return None if x is None else max(0, int(math.floor(x + 1e-9)))


def daily_stats(bars: list[dict]) -> dict:
    rows = [b for b in bars if pos(b.get("v")) is not None and pos(b.get("c")) is not None]
    last = rows[-ADV_SESSIONS:]
    out: dict = {"n_sessions": len(last), "adv_shares": None, "adv_usd": None, "price": None, "sigma_daily": None,
                 "cs_spread_bp": None, "as_of_ms": int(last[-1]["t"]) if last and fin(last[-1].get("t")) else None}
    if not last:
        return out
    out["adv_shares"] = sum(float(b["v"]) for b in last) / len(last)
    out["adv_usd"] = sum(float(b["v"]) * (pos(b.get("vw")) or float(b["c"])) for b in last) / len(last)
    out["price"] = float(last[-1]["c"])
    closes = [float(b["c"]) for b in rows[-(SIGMA_SESSIONS + 1):]]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) >= 5:
        m = sum(rets) / len(rets)
        out["sigma_daily"] = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    out["cs_spread_bp"] = corwin_schultz_bp(last)
    return out


def corwin_schultz_bp(bars: list[dict]) -> float | None:
    k = 3 - 2 * math.sqrt(2)
    ests = []
    for a, b in zip(bars, bars[1:]):
        h1, l1, h2, l2 = pos(a.get("h")), pos(a.get("l")), pos(b.get("h")), pos(b.get("l"))
        if None in (h1, l1, h2, l2) or h1 < l1 or h2 < l2:
            continue
        beta = math.log(h1 / l1) ** 2 + math.log(h2 / l2) ** 2
        gamma = math.log(max(h1, h2) / min(l1, l2)) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
        s = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        ests.append(max(0.0, s))
    if not ests:
        return None
    return 1e4 * sum(ests) / len(ests)


def open5_median(bars: list[dict], open_ms_of_day) -> tuple[float | None, int]:
    vols = [float(b["v"]) for b in bars if pos(b.get("v")) is not None and fin(b.get("t")) is not None
            and open_ms_of_day(int(b["t"]))]
    vols = vols[-OPEN5_SESSIONS:]
    if not vols:
        return None, 0
    s = sorted(vols)
    n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    return med, n


def impact_bp(qty: float, adv_shares: float | None, sigma_daily: float | None, k: float = IMPACT_K) -> float | None:
    if adv_shares is None or adv_shares <= 0 or sigma_daily is None or qty < 0:
        return None
    return k * sigma_daily * math.sqrt(qty / adv_shares) * 1e4


def equity_cost_bp(qty: float, half_spread_bp: float | None, adv_shares: float | None,
                   sigma_daily: float | None) -> dict:
    imp = impact_bp(qty, adv_shares, sigma_daily)
    total = None if imp is None or half_spread_bp is None else half_spread_bp + imp
    return {"qty": qty, "half_spread_bp": half_spread_bp, "impact_bp": imp, "total_bp": total}


def equity_limits(adv_shares: float | None, open5_shares: float | None) -> dict:
    per_order = floor0(EQUITY_OPEN5_PCT_PER_ORDER * open5_shares) if open5_shares is not None else None
    per_day = floor0(EQUITY_ADV_PCT_PER_DAY * adv_shares) if adv_shares is not None else None
    cands = [(v, n) for v, n in ((per_order, "per_order_open5"), (per_day, "per_day_adv")) if v is not None]
    max_order, binding = (min(cands) if cands else (None, None))
    return {"per_order_shares": per_order, "per_day_shares": per_day, "max_order_shares": max_order,
            "max_position_shares": per_day * LIQUIDATION_SESSIONS if per_day is not None else None,
            "binding": binding}


def capacity_usd(max_shares: int | None, price: float | None, coverage: float) -> float | None:
    if max_shares is None or price is None or coverage <= 0:
        return None
    return max_shares * price / coverage


def equity_capacity(stats: dict, open5: float | None, spread_bp: float | None, coverage: float,
                    qty: float | None = None) -> dict:
    lim = equity_limits(stats.get("adv_shares"), open5)
    half = spread_bp / 2.0 if spread_bp is not None else None
    at = qty if qty is not None else lim["max_order_shares"]
    cost = equity_cost_bp(float(at), half, stats.get("adv_shares"), stats.get("sigma_daily")) if at is not None else None
    px = stats.get("price")
    at_open = capacity_usd(lim["max_order_shares"], px, coverage)
    daily = capacity_usd(lim["per_day_shares"], px, coverage)
    return {**lim, "est_cost_bp": cost["total_bp"] if cost else None, "cost": cost,
            "capacity": {"coverage": coverage, "hedge_shares_max": lim["max_order_shares"],
                         "book_usd": at_open, "book_usd_single_order_at_open": at_open,
                         "book_usd_within_one_session": daily,
                         "note": "the largest holding whose hedge (coverage x holding) fits one order at the open "
                                 "(10% of the opening 5-minute volume) and one session (1% of ADV)"}}


def option_limits(volume: float | None, open_interest: float | None) -> dict:
    by_vol = floor0(OPTION_VOLUME_PCT * volume) if volume is not None else None
    by_oi = floor0(OPTION_OI_PCT * open_interest) if open_interest is not None else None
    cands = [(v, n) for v, n in ((by_vol, "volume"), (by_oi, "open_interest")) if v is not None]
    if len(cands) < 2:
        return {"per_order_contracts": None, "by_volume": by_vol, "by_open_interest": by_oi, "binding": None}
    v, n = min(cands)
    return {"per_order_contracts": v, "by_volume": by_vol, "by_open_interest": by_oi, "binding": n}


def option_capacity(volume: float | None, open_interest: float | None, bid: float | None, ask: float | None,
                    mid: float | None, spot: float | None, delta: float | None, coverage: float) -> dict:
    lim = option_limits(volume, open_interest)
    half = (ask - bid) / 2.0 if bid is not None and ask is not None and ask >= bid else None
    spread_bp = (2 * half / mid * 1e4) if half is not None and mid else None
    c = lim["per_order_contracts"]
    shares = c * OPTION_MULT if c is not None else None
    dshares = shares * abs(delta) if shares is not None and delta is not None else None
    hedge = dshares if dshares is not None else shares
    return {**lim, "max_order_contracts": c, "spread_bp": spread_bp, "half_spread_usd_per_contract":
            half * OPTION_MULT if half is not None else None, "est_cost_bp": spread_bp / 2.0 if spread_bp is not None else None,
            "capacity": {"coverage": coverage, "contracts": c, "shares_equiv": shares, "delta_shares_equiv": dshares,
                         "book_usd": hedge * spot / coverage if hedge is not None and spot and coverage > 0 else None,
                         "note": "holding whose hedge (coverage x holding, delta-adjusted when the delta is known) fits "
                                 "one order inside both option caps"}}


Level = tuple[float, float]


def pm_depth(bids: Iterable[Level], asks: Iterable[Level], bands: Iterable[float] = PM_BANDS) -> dict:
    bids, asks = sorted(bids, key=lambda lv: -lv[0]), sorted(asks, key=lambda lv: lv[0])
    bb, ba = (bids[0][0] if bids else None), (asks[0][0] if asks else None)
    mid = (bb + ba) / 2.0 if bb is not None and ba is not None else None
    out: dict = {"mid": mid, "best_bid": bb, "best_ask": ba, "spread": (ba - bb) if mid is not None else None,
                 "buy": {}, "sell": {}}
    for band in bands:
        key = f"{round(band * 100)}c"
        if mid is None:
            out["buy"][key] = out["sell"][key] = None
            continue
        a = [(p, q) for p, q in asks if p <= mid + band + 1e-9]
        b = [(p, q) for p, q in bids if p >= mid - band - 1e-9]
        out["buy"][key] = {"contracts": sum(q for _, q in a), "usd": sum(p * q for p, q in a)}
        out["sell"][key] = {"contracts": sum(q for _, q in b), "usd": sum(p * q for p, q in b)}
    return out


def pm_cap(depth: dict, side: str) -> int | None:
    row = (depth.get(side) or {}).get(f"{round(PM_DEPTH_BAND * 100)}c")
    if not row:
        return None
    return floor0(PM_DEPTH_PCT * row["contracts"])


def walk_cost(levels: Iterable[Level], qty: float, mid: float | None, side: str) -> dict:
    lv = sorted(levels, key=lambda x: x[0] if side == "buy" else -x[0])
    left, cash, got = qty, 0.0, 0.0
    for p, q in lv:
        take = min(left, q)
        cash += take * p
        got += take
        left -= take
        if left <= 1e-12:
            break
    avg = cash / got if got > 0 else None
    cost_c = None if avg is None or mid is None else ((avg - mid) if side == "buy" else (mid - avg)) * 100
    return {"qty": qty, "filled": got, "avg_px": avg, "cost_cents": cost_c,
            "cost_bp": cost_c / 100 / mid * 1e4 if cost_c is not None and mid else None}


def book_levels(fields: dict, side: str, depth: int = 5) -> list[Level]:
    out = []
    for i in range(depth):
        p, q = fin(fields.get(f"{side}_px_{i}")), fin(fields.get(f"{side}_qty_{i}"))
        if p is not None and q is not None and q > 0 and 0 <= p <= 1:
            out.append((p, q))
    return out
