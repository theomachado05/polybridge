from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from . import budget as b

log = logging.getLogger(__name__)
ACCOUNT_TTL_S = 10.0
ACCOUNT_TIMEOUT_S = 8.0


def event_key(market: Any) -> str | None:
    if market is None:
        return None
    src, mid = getattr(market, "source", None), getattr(market, "id", None)
    if src is None and isinstance(market, dict):
        src, mid = market.get("source"), market.get("id")
    return f"{src}:{mid}" if src and mid else None


def _price(app, ticker: str | None, *cands: Any) -> float | None:
    for c in cands:
        v = b.fin(c)
        if v is not None and v > 0:
            return v
    if not ticker:
        return None
    try:
        from ..liquidity.service import service_for
        raw, _ = service_for(app).cached_equity(ticker)
    except Exception:
        raw = None
    return b.fin((raw or {}).get("price"))


NO_PRICE = "no_price"


async def order_price(app, broker, ticker: str | None, *cands: Any) -> tuple[float | None, str | None]:
    for c in cands:
        v = b.fin(c)
        if v is not None and v > 0:
            return v, "order"
    px = _price(app, ticker)
    if px is not None and px > 0:
        return px, "massive_cached"
    if broker is None or not ticker:
        return None, None
    tk = ticker.upper()
    read = getattr(broker, "broker_positions", None) or getattr(broker, "positions", None)
    if read is not None:
        try:
            for p in await asyncio.wait_for(read(), ACCOUNT_TIMEOUT_S) or []:
                mark = b.fin(getattr(p, "mark_px", None))
                if getattr(p, "asset", None) == "equity" and str(getattr(p, "symbol", "")).upper() == tk and mark \
                        and mark > 0:
                    return mark, "broker_position"
        except Exception:
            pass
    sim = broker if hasattr(broker, "quotes") else getattr(broker, "sim", None)
    quotes = getattr(sim, "quotes", None)
    if quotes is not None:
        try:
            q = await asyncio.wait_for(quotes.equity(tk), ACCOUNT_TIMEOUT_S)
            mid = b.fin(getattr(q, "mid", None)) if q is not None else None
            if mid is not None and mid > 0:
                return mid, "quote"
        except Exception:
            pass
    return None, None


def _no_price(scope: str) -> dict:
    if scope != "account":
        return {"ok": True, "enforced": False, "checked": False, "scope": scope,
                "note": "replay sandbox: no price for this order, so its notional is unknown; not checked (no account "
                        "capital at risk)"}
    return {"ok": False, "enforced": True, "checked": False, "scope": scope, "reason": b.CAPITAL_BUDGET,
            "breaches": [{"kind": NO_PRICE,
                          "detail": "no price to size the budget (no tick or bridge price, no cached Massive price, no "
                                    "broker mark or quote): an exposure-increasing order whose notional is unknown "
                                    "is refused at the account"}]}


async def account_snapshot(app, broker, refresh: bool = False) -> dict:
    if broker is None:
        return {"checked": False, "read_ok": False, "error": "no broker"}
    cache = getattr(app.state, "capital_accounts", None)
    if cache is None:
        cache = app.state.capital_accounts = {}
    key = id(broker)
    now = time.monotonic()
    hit = cache.get(key)
    if hit is not None and not refresh and now - hit[0] < ACCOUNT_TTL_S:
        return {**hit[1], "age_s": round(now - hit[0], 1)}
    if not hasattr(broker, "account"):
        snap = {"checked": False, "read_ok": False, "broker": getattr(broker, "name", None),
                "error": "the broker has no account read"}
        cache[key] = (now, snap)
        return snap
    try:
        acct = await asyncio.wait_for(broker.account(), ACCOUNT_TIMEOUT_S)
    except Exception as e:
        snap = {"checked": True, "read_ok": False, "broker": getattr(broker, "name", None),
                "error": f"account read failed ({getattr(e, 'message', None) or type(e).__name__})"}
        if hit is not None and hit[1].get("read_ok"):
            if now - hit[0] < 6 * ACCOUNT_TTL_S:
                return {**hit[1], "age_s": round(now - hit[0], 1), "stale": True, "error": snap["error"]}
        return snap
    eq = b.fin(getattr(acct, "equity", None))
    if acct is None or eq is None:
        snap = {"checked": False, "read_ok": False, "broker": getattr(broker, "name", None),
                "error": "the broker returned no account equity"}
        cache[key] = (now, snap)
        return snap
    short = 0.0
    try:
        pos = await asyncio.wait_for(broker.positions(), ACCOUNT_TIMEOUT_S)
        for p in pos or []:
            if getattr(p, "asset", None) == "equity" and (b.fin(getattr(p, "qty", None)) or 0.0) < 0:
                px = b.fin(getattr(p, "mark_px", None)) or b.fin(getattr(p, "avg_px", None)) or 0.0
                short += abs(float(p.qty)) * px
    except Exception:
        short = None
    snap = {"checked": True, "read_ok": True, "broker": getattr(acct, "broker", None) or getattr(broker, "name", None),
            "equity": eq, "cash": b.fin(getattr(acct, "cash", None)),
            "buying_power": b.fin(getattr(acct, "buying_power", None)), "short_notional": short,
            "account_type": getattr(acct, "account_type", None), "account_label": getattr(acct, "account_label", None)}
    cache[key] = (now, snap)
    return {**snap, "age_s": 0.0}


def bp_basis(broker) -> str:
    from ..broker import SimBroker
    return "margin" if isinstance(broker, SimBroker) else "notional"


def exposures(app, exclude_staged: str | None = None) -> dict:
    events: dict[str, dict] = {}
    unpriced: list[str] = []

    def row(key: str | None) -> dict:
        k = key or "unattributed"
        return events.setdefault(k, {"event": k, "equity_hedge_usd": 0.0, "equity_hedge_shares": 0.0,
                                     "staged_pending_usd": 0.0, "option_risk_usd": 0.0, "proposals": []})

    for br in list((getattr(app.state, "bridges", None) or {}).values()):
        key = event_key(getattr(br, "market", None))
        r = row(key)
        pid = getattr(br, "proposal_id", None)
        if pid and pid not in r["proposals"]:
            r["proposals"].append(pid)
        sandboxed = bool(br._sandboxed()) if hasattr(br, "_sandboxed") else False
        shares = max(0.0, float(getattr(br, "account_hedge", 0.0) or 0.0))
        rest = getattr(br, "resting", None)
        if not sandboxed and isinstance(rest, dict) and rest.get("side") == "sell" and \
                (rest.get("instrument") or "equity") == "equity" and not rest.get("inherited"):
            shares += max(0.0, (b.fin(rest.get("qty")) or 0.0) - (b.fin(rest.get("hedged", rest.get("applied"))) or 0.0))
        if shares > 0:
            px = _price(app, getattr(getattr(br, "proposal", None), "ticker", None), getattr(br, "last_under_px", None))
            if px is None:
                unpriced.append(pid or "?")
            else:
                r["equity_hedge_usd"] += shares * px
                r["equity_hedge_shares"] += shares
        if not sandboxed and getattr(br, "division", None) == "opportunity":
            r["option_risk_usd"] += abs(float(getattr(br, "opt_pos", 0.0) or 0.0)) * float(
                getattr(br, "opt_risk_per_unit", 0.0) or 0.0)
    try:
        from ..closed.staged import book_for
        pend = book_for(app).pending()
    except Exception:
        pend = []
    for o in pend:
        if o.clock != "wall" or o.status not in ("approved", "working") or o.side != "sell" or o.id == exclude_staged:
            continue
        rem = max(0.0, o.qty - o.filled_qty)
        if rem <= 0:
            continue
        px = _price(app, o.ticker, o.ref_px)
        r = row(_staged_event(o))
        if o.proposal_id not in r["proposals"]:
            r["proposals"].append(o.proposal_id)
        if px is None:
            unpriced.append(o.id)
        else:
            r["staged_pending_usd"] += rem * px
    for r in events.values():
        r["total_usd"] = r["equity_hedge_usd"] + r["staged_pending_usd"] + r["option_risk_usd"]
    eq = sum(r["equity_hedge_usd"] for r in events.values())
    st = sum(r["staged_pending_usd"] for r in events.values())
    op = sum(r["option_risk_usd"] for r in events.values())
    return {"gross_usd": eq + st + op, "equity_usd": eq, "staged_usd": st, "option_usd": op, "events": events,
            "unpriced": unpriced}


def _staged_event(o) -> str | None:
    return o.market_key


async def check(app, *, broker, event: str | None, add_notional: float | None, add_margin: float | None,
                scope: str = "account", sandbox_gross: float = 0.0, exclude_staged: str | None = None) -> dict:
    lim = b.limits(app)
    if add_notional is not None and add_notional <= 0 and (add_margin or 0.0) <= 0:
        return {"ok": True, "enforced": False, "checked": False, "scope": scope, "note": "reduces exposure"}
    if add_notional is None and scope != "account":
        return _no_price(scope)
    snap = await account_snapshot(app, broker)
    if not snap.get("checked"):
        return {"ok": True, "enforced": False, "checked": False, "scope": scope,
                "note": f"capital not checked: {snap.get('error')}"}
    if add_notional is None:
        return _no_price(scope)
    if add_margin is None:
        add_margin = lim["reg_t_initial"] * add_notional
    if scope == "account":
        ex = exposures(app, exclude_staged=exclude_staged)
        gross = max(ex["gross_usd"], (snap.get("short_notional") or 0.0) + ex["staged_usd"] + ex["option_usd"])
        event_now = (ex["events"].get(event or "unattributed") or {}).get("total_usd", 0.0)
    else:
        gross = event_now = sandbox_gross
    res = b.evaluate(equity=snap.get("equity") if snap.get("read_ok") else None,
                     buying_power=snap.get("buying_power"), gross_now=gross, event_now=event_now,
                     add_notional=add_notional, add_margin=add_margin, bp_basis=bp_basis(broker), lim=lim,
                     event=event)
    enforced = scope == "account"
    out = {**res, "enforced": enforced, "checked": True, "scope": scope, "limits": lim,
           "account": {k: snap.get(k) for k in ("broker", "equity", "buying_power", "age_s", "stale")}}
    if not res["ok"]:
        out["reason"] = b.CAPITAL_BUDGET
        if not enforced:
            out["note"] = ("replay sandbox: evaluated against the throwaway simulator, not enforced (no account "
                           "capital at risk); the same order at the account would be refused")
    return out


def refused(chk: dict) -> bool:
    return bool(chk.get("enforced")) and not chk.get("ok", True)


def tag(rec: dict, chk: dict) -> None:
    rec["capital"] = {k: chk.get(k) for k in ("ok", "enforced", "checked", "scope", "breaches", "note", "reason",
                                              "add_notional", "add_margin") if k in chk}
    if not chk.get("ok", True):
        rec.setdefault("gates", []).append({"reason": b.CAPITAL_BUDGET, "enforced": bool(chk.get("enforced")),
                                            "breaches": [x.get("kind") for x in chk.get("breaches") or []]})


def refusal_text(chk: dict) -> str:
    return "capital_budget: " + "; ".join(x.get("detail", x.get("kind", "")) for x in chk.get("breaches") or [])


async def snapshot(app, broker) -> dict:
    lim = b.limits(app)
    snap = await account_snapshot(app, broker, refresh=True)
    ex = exposures(app)
    eq = snap.get("equity") if snap.get("read_ok") else None
    broker_short = snap.get("short_notional")
    equity_hedge = max(ex["equity_usd"], broker_short or 0.0)
    gross = equity_hedge + ex["staged_usd"] + ex["option_usd"]
    m_init = lim["reg_t_initial"] * equity_hedge + ex["option_usd"]
    m_maint = lim["reg_t_maintenance"] * equity_hedge + ex["option_usd"]
    breaches = []
    events = []
    for r in sorted(ex["events"].values(), key=lambda x: -x["total_usd"]):
        lim_usd = lim["max_event_pct"] * eq if eq is not None else None
        use = r["total_usd"] / lim_usd if lim_usd else None
        events.append({**r, "limit_usd": lim_usd, "use_pct": use})
        if lim_usd is not None and r["total_usd"] > lim_usd + 1e-6:
            breaches.append({"kind": "event_exposure", "event": r["event"], "after_usd": r["total_usd"],
                             "limit_usd": lim_usd})
    g_lim = lim["max_gross_hedge_pct"] * eq if eq is not None else None
    if g_lim is not None and gross > g_lim + 1e-6:
        breaches.append({"kind": "gross_hedge_notional", "after_usd": gross, "limit_usd": g_lim})
    if eq is not None and m_maint > eq + 1e-6:
        breaches.append({"kind": "maintenance_margin", "after_usd": m_maint, "limit_usd": eq,
                         "detail": "maintenance requirement above account equity: a margin call"})
    bp = snap.get("buying_power")
    if bp is not None and bp < 0:
        breaches.append({"kind": "buying_power", "after_usd": bp, "limit_usd": 0.0})
    if snap.get("checked") and not snap.get("read_ok"):
        breaches.append({"kind": "account_unreadable", "detail": snap.get("error")})
    return {"broker": snap.get("broker") or getattr(broker, "name", None), "account_read": snap.get("read_ok", False),
            "account_checked": bool(snap.get("checked")), "account_stale": bool(snap.get("stale")),
            "account_age_s": snap.get("age_s"),
            "account_error": snap.get("error"), "account_type": snap.get("account_type"),
            "account_label": snap.get("account_label"), "equity": eq, "cash": snap.get("cash"),
            "buying_power": bp, "buying_power_basis": bp_basis(broker), "limits": lim,
            "gross_hedge_notional": gross, "gross_limit_usd": g_lim,
            "gross_use_pct": gross / g_lim if g_lim else None,
            "equity_hedge_usd": equity_hedge, "attributed_equity_hedge_usd": ex["equity_usd"],
            "broker_short_notional": broker_short, "staged_pending_usd": ex["staged_usd"],
            "option_risk_usd": ex["option_usd"],
            "margin": {"initial_required": m_init, "maintenance_required": m_maint,
                       "excess_over_maintenance": (eq - m_maint) if eq is not None else None,
                       "rule": "Reg T 50% initial / 30% maintenance on short equity; option structures at their "
                               f"premium or max loss (short puts: {lim['short_put_mode'].replace('_', '-')})"},
            "events": events, "breaches": breaches, "unpriced": ex["unpriced"],
            "note": "account scope: replay sandboxes are excluded (they trade a throwaway simulator); orders that "
                    "would breach a budget are refused with reason capital_budget"}
