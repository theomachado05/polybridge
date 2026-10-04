from __future__ import annotations

import asyncio
import datetime as dt
import math
from typing import Any

from ..cache import TTLCache
from . import bs
from . import chain as ch
from . import quotes as qt
from .implied import RISK_FREE
from .live import greeks_for
from .mark import est_half_spread

HEDGE_TTL_S = 30.0
EXPIRY_SLACK_DAYS = 75
OPTION_FEE_PER_CONTRACT = 0.65
STOCK_FEE_PER_SHARE = 0.0035
BORROW_RATE_GC = 0.0030
STOCK_HALF_SPREAD_BP = 1.0
REG_T_INITIAL = 0.50
MAINT_SHORT = 0.30
SSR_DROP_PCT = -10.0
MOVES = (-0.30, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)
STRATEGIES = ("short_stock", "protective_put", "collar", "put_spread")
LABEL = ("hedge cost comparison at executable prices from the last Massive quotes; an estimate, not advice; option "
         "orders here are simulated")
LABEL_BROKER = ("hedge cost comparison at executable prices from the last Massive quotes; an estimate, not advice; "
                "option orders go to the Webull paper account (WEBULL_OPTIONS=1), regular session only")
SIM_OPTIONS_CAVEAT = "Option fills in this app are simulated (Webull paper routes option combos to its simulator)."
BROKER_OPTIONS_CAVEAT = ("Option orders go to the Webull paper account (WEBULL_OPTIONS=1) as one net limit at the quoted "
                         "mids +/- half-spreads, accepted 09:30-16:00 ET only; fills are Webull's paper fills (paper "
                         "money), and its support for option orders on the paper sandbox is unverified.")


def label_for(options_at_broker: bool) -> str:
    return LABEL_BROKER if options_at_broker else LABEL


_CACHE = TTLCache(HEDGE_TTL_S)


def _bp(x: float | None, notional: float) -> float | None:
    if x is None or not math.isfinite(x) or not notional:
        return None
    return x / notional * 1e4


def nearest(ks: list[float], target: float, below: float | None = None) -> float | None:
    c = [k for k in ks if below is None or k < below]
    return min(c, key=lambda k: (abs(k - target), k)) if c else None


def pick_expiry(expiries: list[str], target: dt.date, now: dt.datetime) -> tuple[str | None, bool]:
    live = [e for e in expiries if qt.years_to_expiry(e, now) > 0]
    after = [e for e in live if dt.date.fromisoformat(e) >= target]
    if after:
        return after[0], True
    return (live[-1], False) if live else (None, False)


def leg_quote(q: ch.OptionQuote, side: int, contracts: int, *, spot: float, now: dt.datetime, market: dict,
              nbbo: dict | None) -> dict:
    q = qt.apply_nbbo(q, nbbo)
    quoted = math.isfinite(q.bid) and math.isfinite(q.ask)
    half = (q.ask - q.bid) / 2.0 if quoted else est_half_spread(q.mid, q.open_interest)
    exec_px = q.mid + side * half if math.isfinite(q.mid) else math.nan
    exec_px = max(exec_px, 0.0) if math.isfinite(exec_px) else exec_px
    stale, why = qt.is_stale(q.updated_ns, market, now)
    flags, grade = qt.liquidity_flags(bid=q.bid, ask=q.ask, mid=q.mid, oi=q.open_interest, volume=q.volume,
                                      contracts=contracts, quoted=quoted, stale=stale)
    T = qt.years_to_expiry(q.expiry, now)
    g = greeks_for(q, spot, T)
    return {"ticker": q.ticker, "right": q.kind, "strike": q.strike, "expiry": q.expiry,
            "side": "buy" if side > 0 else "sell", "sign": side, "contracts": contracts,
            "bid": q.bid if quoted else None, "ask": q.ask if quoted else None, "mid": q.mid,
            "half_spread": half, "exec_px": exec_px, "spread_source": "nbbo" if quoted else "estimated",
            "mark_source": q.mark_source, "iv": g["iv"], "iv_source": g["iv_source"], "delta": g["delta"],
            "greeks_source": g["greeks_source"], "open_interest": q.open_interest, "volume": q.volume,
            "updated_ns": q.updated_ns, "stale": stale, "stale_reason": why,
            "liquidity": grade, "liquidity_flags": flags}


def leg_value_at(leg: dict, S: float, t_left: float, r: float = RISK_FREE) -> float:
    call = leg["right"] == "call"
    if t_left <= 0:
        return bs.intrinsic(S, leg["strike"], call)
    iv = leg.get("iv")
    if iv is None or not math.isfinite(iv) or iv <= 0:
        return bs.intrinsic(S, leg["strike"], call)
    return bs.price(S, leg["strike"], t_left, r, iv, call)


def option_strategy(name: str, legs: list[dict], *, shares: int, spot: float, notional: float, contracts: int,
                    t_left: float, horizon_days: int) -> dict:
    mult = 100.0 * contracts
    fees = OPTION_FEE_PER_CONTRACT * contracts * len(legs)
    net_exec = sum(lg["sign"] * lg["exec_px"] for lg in legs)
    net_mid = sum(lg["sign"] * lg["mid"] for lg in legs)
    upfront = net_exec * mult + fees
    friction = (net_exec - net_mid) * mult + fees
    deltas = [lg["delta"] for lg in legs]
    have_delta = all(d is not None and math.isfinite(d) for d in deltas)
    delta_eq = -sum(lg["sign"] * lg["delta"] for lg in legs) * mult if have_delta else None
    grades = [lg["liquidity"] for lg in legs]
    put = next(lg for lg in legs if lg["right"] == "put" and lg["sign"] > 0)
    kp = put["strike"]
    out: dict[str, Any] = {
        "available": True, "reason": None, "legs": legs, "contracts": contracts, "covered_shares": int(mult),
        "net_premium_per_share": net_exec, "net_premium_mid_per_share": net_mid,
        "upfront_usd": upfront, "upfront_bp": _bp(upfront, notional),
        "expected_cost_usd": friction, "expected_cost_bp": _bp(friction, notional),
        "fees_usd": fees, "delta_equivalent_shares": delta_eq,
        "hedge_ratio": delta_eq / shares if shares and delta_eq is not None else None,
        "liquidity": qt.worst_grade(grades),
        "liquidity_flags": sorted({f for lg in legs for f in lg["liquidity_flags"]}),
        "spread_source": "nbbo" if all(lg["spread_source"] == "nbbo" for lg in legs) else "estimated",
        "execution": {"order": "single-leg limit" if len(legs) == 1 else f"{len(legs)}-leg combo limit (all or none)",
                      "limit_mid": net_mid, "limit_worst": net_exec,
                      "suggested_limit": net_mid + 0.25 * (net_exec - net_mid),
                      "when": "regular session 09:30-16:00 ET; spreads are widest in the first and last 15 minutes"},
        "capital": {"cash_upfront_usd": max(upfront, 0.0), "margin_initial_usd": 0.0,
                    "note": "premium paid in cash; no margin needed"},
    }
    prem = net_exec + fees / mult
    if name == "protective_put":
        out["protection"] = {"floor_price": kp, "floor_pct": kp / spot - 1, "ends_at": None,
                             "max_loss_pct_at_expiry": (kp - spot - prem) / spot,
                             "note": "losses below the put strike are covered down to zero"}
        out["upside"] = {"cap_price": None, "note": "full upside, less the premium"}
        out["breakeven_price"] = spot + prem
    elif name == "collar":
        call = next(lg for lg in legs if lg["right"] == "call")
        kc = call["strike"]
        out["protection"] = {"floor_price": kp, "floor_pct": kp / spot - 1, "ends_at": None,
                             "max_loss_pct_at_expiry": (kp - spot - prem) / spot,
                             "note": "losses below the put strike are covered down to zero"}
        out["upside"] = {"cap_price": kc, "cap_pct": kc / spot - 1,
                         "max_gain_pct_at_expiry": (kc - spot - prem) / spot,
                         "note": "gains above the call strike go to the call buyer"}
        out["zero_cost_gap_per_share"] = net_exec
        out["capital"] = {"cash_upfront_usd": max(upfront, 0.0), "margin_initial_usd": 0.0,
                          "note": ("the short call is covered by the long shares (no extra margin while the shares "
                                   "are held); a net credit is received in cash")}
    elif name == "put_spread":
        short = next(lg for lg in legs if lg["sign"] < 0)
        ks = short["strike"]
        out["protection"] = {"floor_price": kp, "floor_pct": kp / spot - 1, "ends_at": ks,
                             "ends_at_pct": ks / spot - 1, "max_payout_usd": (kp - ks) * mult,
                             "note": f"covers the fall from {kp:g} to {ks:g} only; below {ks:g} losses resume"}
        out["upside"] = {"cap_price": None, "note": "full upside, less the premium"}
        out["breakeven_price"] = spot + prem
        out["capital"] = {"cash_upfront_usd": max(upfront, 0.0), "margin_initial_usd": 0.0,
                          "note": "defined-risk debit spread: the debit is the whole requirement"}
    out["scenarios"] = [
        {"move": mv, "price": spot * (1 + mv),
         "pnl_usd": shares * spot * mv + sum(lg["sign"] * leg_value_at(lg, spot * (1 + mv), t_left) for lg in legs)
         * mult - upfront}
        for mv in MOVES]
    for s in out["scenarios"]:
        s["pnl_pct"] = s["pnl_usd"] / notional
    out["horizon_note"] = (f"options repriced at the {horizon_days}-day horizon by Black–Scholes at each leg's IV"
                           if t_left > 0 else "options valued at intrinsic (the horizon reaches expiry)")
    return out


def short_stock(*, shares: int, spot: float, notional: float, horizon_days: int, borrow_rate: float,
                borrow_assumed: bool, spot_info: dict, dividends: dict) -> dict:
    qty = shares
    b, a = spot_info.get("bid"), spot_info.get("ask")
    if b and a:
        half, half_src = (a - b) / 2.0, "stock_quote"
    else:
        half, half_src = spot * STOCK_HALF_SPREAD_BP / 1e4, "assumed_1bp"
    borrow = qty * spot * borrow_rate * horizon_days / 365.0
    spread = 2 * half * qty
    fees = 2 * STOCK_FEE_PER_SHARE * qty
    cost = borrow + spread + fees
    flags = ["borrow_rate_assumed"] if borrow_assumed else []
    cp = spot_info.get("change_pct")
    if cp is not None and cp <= SSR_DROP_PCT:
        flags.append("ssr_uptick_rule_active")
    div_cash = None
    if dividends.get("status") in ("declared", "projected") and dividends.get("amount"):
        div_cash = dividends["amount"] * qty
        flags.append("dividend_owed_on_short")
    return {
        "available": True, "reason": None, "shares_short": qty, "covered_shares": qty,
        "delta_equivalent_shares": float(qty), "hedge_ratio": 1.0,
        "upfront_usd": 0.0, "upfront_bp": 0.0,
        "expected_cost_usd": cost, "expected_cost_bp": _bp(cost, notional),
        "cost_breakdown": {"borrow_usd": borrow, "borrow_rate_annual": borrow_rate,
                           "borrow_rate_source": "assumed easy-to-borrow (general collateral)" if borrow_assumed
                           else "caller-supplied", "spread_round_trip_usd": spread, "half_spread": half,
                           "half_spread_source": half_src, "fees_usd": fees},
        "dividend": {**dividends, "cash_owed_usd": div_cash,
                     "note": "a short pays the dividend; the long receives it, so the hedged position nets to zero"},
        "liquidity": "liquid" if not flags or flags == ["borrow_rate_assumed"] else "thin",
        "liquidity_flags": flags,
        "protection": {"floor_price": spot, "floor_pct": 0.0, "ends_at": None,
                       "note": "locks in today's price for the hedged shares (gains and losses cancel)"},
        "upside": {"cap_price": spot, "cap_pct": 0.0, "note": "all upside on the hedged shares is given up"},
        "capital": {"cash_upfront_usd": 0.0, "margin_initial_usd": REG_T_INITIAL * qty * spot,
                    "margin_maintenance_usd": MAINT_SHORT * qty * spot,
                    "note": ("Reg T initial 50% of the short's value on top of the proceeds; at most brokers the long "
                             "shares in the same margin account cover it (short against the box), otherwise it needs "
                             "cash or collateral; needs a margin account and a borrow locate")},
        "execution": {"order": "sell short, limit at or near the bid", "when": "regular session 09:30-16:00 ET "
                      "(Webull paper orders are accepted only then)"},
        "scenarios": [{"move": mv, "price": spot * (1 + mv), "pnl_usd": -cost, "pnl_pct": -cost / notional}
                      for mv in MOVES],
        "horizon_note": "shares hedged one for one: price moves cancel; only the costs remain",
    }


def contracts_for(name: str, shares: int) -> int:
    n = shares // 100
    return n if name == "collar" else max(1, n)


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def caveats(market: dict, covers: bool, dividends: dict, expiry: str | None, strategies: dict,
            options_at_broker: bool = False) -> list[str]:
    out = []
    if market.get("market_open") is False:
        out.append("Market closed: quotes are the last session's close. Executable prices at the next open will "
                   "differ; option orders fill only 09:30-16:00 ET.")
    if expiry and not covers:
        out.append(f"No listed expiry covers the full horizon; {expiry} is the latest before it, so the option hedges "
                   "would need to be rolled (another round of spread and fees).")
    if dividends.get("status") in ("declared", "projected") and expiry and (dividends.get("ex_date") or "9999") <= expiry:
        out.append(f"Ex-dividend {dividends['ex_date']} ({dividends['status']}) before expiry: a short call in the "
                   "collar that is in the money then may be assigned early (American exercise); the short stock "
                   "pays the dividend.")
    out.append("US single-stock options are American: a short leg (collar call, spread's short put) can be assigned "
               "before expiry, leaving the position unbalanced until rebalanced.")
    out.append("Expected cost = friction only (spread crossed + fees, plus borrow for short stock). Index and "
               "single-stock puts usually trade above later realised volatility, so the true expected cost of buying "
               "protection is higher; the upfront premium is the most a put or put spread can cost.")
    out.append("Borrow fees are not published by Massive or Webull paper; the short-stock borrow is an assumed "
               "easy-to-borrow rate. Hard-to-borrow names can cost 5-50%+ a year and borrows can be recalled.")
    out.append("A short against the box or a tight collar can be a constructive sale for tax purposes (IRC 1259); "
               "not tax advice.")
    out.append(BROKER_OPTIONS_CAVEAT if options_at_broker else SIM_OPTIONS_CAVEAT)
    if any((strategies.get(s) or {}).get("liquidity") == "illiquid" for s in STRATEGIES):
        out.append("At least one strategy is graded illiquid: expect to pay more than the quoted spread, or to be "
                   "unable to exit at a fair price.")
    return out


async def hedge_quote(ticker: str, shares: int, horizon_days: int, protection_pct: float, *, client,
                      borrow_rate: float | None = None, now: dt.datetime | None = None,
                      options_at_broker: bool = False) -> dict:
    key = (ticker, shares, horizon_days, round(protection_pct, 6), borrow_rate, bool(options_at_broker))
    if now is not None:
        return await _compute(ticker, shares, horizon_days, protection_pct, client=client, borrow_rate=borrow_rate,
                              now=now, options_at_broker=options_at_broker)
    try:
        res, _ = await _CACHE.get_or_set(key, lambda: _compute(ticker, shares, horizon_days, protection_pct,
                                                               client=client, borrow_rate=borrow_rate, now=None,
                                                               options_at_broker=options_at_broker))
        if not res.get("available"):
            _CACHE._data.pop(key, None)
        return res
    except Exception as e:  # noqa: BLE001
        return {"ticker": ticker, "available": False, "reason": f"hedge quote failed ({type(e).__name__})",
                "label": label_for(options_at_broker)}


async def _compute(ticker: str, shares: int, horizon_days: int, protection_pct: float, *, client,
                   borrow_rate: float | None, now: dt.datetime | None, options_at_broker: bool = False) -> dict:
    now = now or qt.now_utc()
    market = qt.market_state(now)
    base: dict[str, Any] = {"ticker": ticker, "shares": shares, "horizon_days": horizon_days,
                            "protection_pct": protection_pct, "label": label_for(options_at_broker),
                            "options_route": "webull-paper" if options_at_broker else "simulator",
                            "market": {k: v for k, v in market.items() if k != "last_close_s"},
                            "market_open": market.get("market_open"), "as_of": now.isoformat()}
    if client is None:
        return {**base, "available": False, "reason": "MASSIVE_API_KEY not set",
                "strategies": {s: _unavailable("MASSIVE_API_KEY not set") for s in STRATEGIES}}
    try:
        return await _compute_inner(base, ticker, shares, horizon_days, protection_pct, client, borrow_rate, now,
                                    market)
    except Exception as e:  # noqa: BLE001 - never a 500
        return {**base, "available": False, "reason": f"hedge quote failed ({type(e).__name__})",
                "strategies": {s: _unavailable("internal error") for s in STRATEGIES}}


async def _compute_inner(base, ticker, shares, horizon_days, protection_pct, client, borrow_rate, now, market):
    today = now.astimezone(qt.ET).date()
    target = today + dt.timedelta(days=horizon_days)
    spot_info, _ = await qt.get_spot(client, ticker, market.get("market_open"))
    spot = qt.fnum(spot_info.get("price"))
    lo = max(0.01, 1 - 2 * protection_pct - 0.05)
    hi = 1 + max(0.30, 3 * protection_pct)
    notes: list[str] = []
    chain = None
    cache_stale = False
    try:
        chain, cache_stale = await ch.get_chain(
            ticker, expiry_from=today + dt.timedelta(days=1), expiry_to=target + dt.timedelta(days=EXPIRY_SLACK_DAYS),
            strike_min=spot * lo if math.isfinite(spot) else None,
            strike_max=spot * hi if math.isfinite(spot) else None, client=client)
    except Exception as e:  # noqa: BLE001
        notes.append(f"option chain unavailable ({type(e).__name__})")
    spot_src = spot_info.get("source")
    if chain is not None and math.isfinite(chain.spot) and chain.spot > 0:
        spot, spot_src = chain.spot, "massive_option_snapshot"
    if not math.isfinite(spot) or spot <= 0:
        reason = "no underlying price (Massive stock and option snapshots gave none)"
        return {**base, "available": False, "reason": reason,
                "strategies": {s: _unavailable(reason) for s in STRATEGIES}, "notes": notes}
    notional = shares * spot
    contracts = shares // 100
    dividends_task = asyncio.create_task(qt.get_dividends(client, ticker, today, target))
    strategies: dict[str, dict] = {}
    exp, covers = (None, False)
    if chain is not None:
        exp, covers = pick_expiry(chain.expiries(), target, now)
    opt_reason = None
    legs_sel: dict[str, list[tuple[ch.OptionQuote, int]]] = {}
    if chain is None:
        opt_reason = notes[-1] if notes else "option chain unavailable"
    elif exp is None:
        opt_reason = "no listed options in the expiry / strike window"
    else:
        sl = chain.slice(exp)
        puts = {k: v["put"] for k, v in sl.items() if "put" in v and math.isfinite(v["put"].mid)}
        calls = {k: v["call"] for k, v in sl.items() if "call" in v and math.isfinite(v["call"].mid)}
        kp = nearest(sorted(puts), spot * (1 - protection_pct), below=spot * 1.0001) or nearest(sorted(puts),
                                                                                              spot * (1 - protection_pct))
        if kp is None:
            opt_reason = f"no priced puts listed for {exp}"
        else:
            p = puts[kp]
            legs_sel["protective_put"] = [(p, 1)]
            otm_calls = [c for k, c in calls.items() if k > spot]
            if otm_calls:
                c = min(otm_calls, key=lambda c: (abs(c.mid - p.mid), -c.strike))
                legs_sel["collar"] = [(p, 1), (c, -1)]
            ks = nearest(sorted(puts), spot * (1 - 2 * protection_pct), below=kp)
            if ks is not None:
                legs_sel["put_spread"] = [(p, 1), (puts[ks], -1)]
    want = sorted({q.ticker for legs in legs_sel.values() for q, _ in legs})
    nbbos = await qt.get_nbbos(client, want) if want else {}
    dividends = await dividends_task
    t_left = qt.years_to_expiry(exp, now + dt.timedelta(days=horizon_days)) if exp else 0.0
    for name in ("protective_put", "collar", "put_spread"):
        if name not in legs_sel:
            why = opt_reason or {"collar": "no out-of-the-money call listed to fund the put",
                                 "put_spread": "no lower put strike listed for the short leg"}.get(name, "unavailable")
            strategies[name] = _unavailable(why)
            continue
        n = contracts_for(name, shares)
        if n == 0:
            strategies[name] = _unavailable("a collar needs at least 100 shares so the short call is covered "
                                            "(a naked short call has unlimited risk)")
            continue
        legs = [leg_quote(q, side, n, spot=spot, now=now, market=market, nbbo=nbbos.get(q.ticker))
                for q, side in legs_sel[name]]
        if any(not math.isfinite(lg["exec_px"]) for lg in legs):
            strategies[name] = _unavailable("a leg has no usable price")
            continue
        strategies[name] = option_strategy(name, legs, shares=shares, spot=spot, notional=notional,
                                           contracts=n, t_left=max(t_left, 0.0), horizon_days=horizon_days)
        if n * 100 > shares:
            strategies[name]["liquidity_flags"].append("over_hedged")
            strategies[name]["over_hedge_note"] = (f"1 contract covers 100 shares against {shares} held: the extra "
                                                   "puts are a net bearish position")
    br = BORROW_RATE_GC if borrow_rate is None else borrow_rate
    strategies["short_stock"] = short_stock(shares=shares, spot=spot, notional=notional, horizon_days=horizon_days,
                                            borrow_rate=br, borrow_assumed=borrow_rate is None, spot_info=spot_info,
                                            dividends=dividends)
    strategies = {s: strategies[s] for s in STRATEGIES}
    ranking = sorted((s for s in STRATEGIES if strategies[s].get("available")),
                     key=lambda s: strategies[s]["expected_cost_bp"])
    if contracts * 100 != shares:
        notes.append(f"{shares} shares -> {max(contracts, 1)} contract(s) per option leg (whole contracts of 100, "
                     "never more short calls than shares held); short stock hedges every share")
    unhedged = [{"move": mv, "price": spot * (1 + mv), "pnl_usd": notional * mv, "pnl_pct": mv} for mv in MOVES]
    fresh = ch.staleness(chain, cache_stale) if chain is not None else None
    if fresh is not None:
        fresh["legs_with_nbbo"] = sum(1 for v in nbbos.values() if v)
        fresh["legs"] = len(want)
    return qt.clean({
        **base, "available": any(strategies[s].get("available") for s in STRATEGIES), "reason": None,
        "spot": {"price": spot, "source": spot_src, "updated_ns": spot_info.get("updated_ns"),
                 "change_pct": spot_info.get("change_pct")},
        "notional_usd": notional, "expiry": exp, "dte": (dt.date.fromisoformat(exp) - today).days if exp else None,
        "expiry_covers_horizon": covers if exp else None,
        "contracts": {s: contracts_for(s, shares) for s in ("protective_put", "collar", "put_spread")},
        "strategies": strategies,
        "ranking": {"by": "expected_cost_bp (friction if fairly priced; ignores upside given up and protection depth)",
                    "order": ranking, "cheapest": ranking[0] if ranking else None},
        "unhedged_scenarios": unhedged, "dividends": dividends,
        "assumptions": {"risk_free": RISK_FREE, "option_fee_per_contract": OPTION_FEE_PER_CONTRACT,
                        "stock_fee_per_share": STOCK_FEE_PER_SHARE, "borrow_rate_annual": br,
                        "borrow_rate_assumed": borrow_rate is None, "reg_t_initial": REG_T_INITIAL,
                        "maintenance_short": MAINT_SHORT,
                        "estimated_half_spread": "max($0.025, 4% of mid) with OI >= 500, else max($0.025, 8%)",
                        "liquidity_thresholds": {"oi_low": qt.OI_LOW, "oi_thin": qt.OI_THIN,
                                                 "spread_wide": qt.SPREAD_WIDE,
                                                 "spread_very_wide": qt.SPREAD_VERY_WIDE,
                                                 "size_vs_oi": qt.SIZE_VS_OI}},
        "caveats": caveats(market, covers, dividends, exp, strategies,
                           options_at_broker=base.get("options_route") == "webull-paper"),
        "notes": notes, "freshness": fresh,
        "options_reason": opt_reason,
    })


def reset_cache() -> None:
    global _CACHE
    _CACHE = TTLCache(HEDGE_TTL_S)
