"""Opportunity at the open (closed-market mode, plan item 6; task P4).

While equities are closed the prediction market keeps trading, but listed option prices stay where Friday's close
left them. This module:

1. **Friday-close snapshot.** For a threshold market (one ``options.match.match_question`` maps to an underlying,
   strike and date), store the options-implied P(YES) at the last regular close, the PM YES price, and the quotes of
   both vertical spreads around the threshold (the YES-equivalent and the NO-equivalent structure).
2. **Monday-open comparison.** ``evaluate`` compares the weekend PM move with the option move (zero until the options
   reprice at the open). If the options have not caught up (the residual move is large enough, the option level is
   still on the far side of the PM price, and a buy at the spread's ask would still sit on the right side of the PM
   price), the decision is ``stage`` with a reason code; every other outcome has its own reason code.
3. **Staged option trade for 09:30.** A debit vertical spread (bounded risk: the debit), sized under
   ``max_contracts`` and ``max_notional``. It needs approval, executes only inside the window after the next regular
   open, re-checks the comparison against the open's own option quotes (cancels if the options caught up or the PM
   reverted), refuses quotes not updated since the open, and fills all legs or none through the existing multi-leg
   options fill path (``SimBroker.place_combo``: Massive quote mid +/- half spread, per-contract fee). Simulated.

Labels: every number is an estimate (options-implied, risk-neutral), fills are simulated, nothing here claims an edge.
``supported`` means only that the data exist (an option estimate at the close and PM prices at the close and now);
the R3 study (``research_status``) decides whether the UI may say more than "estimate".

All time logic takes an explicit ``now`` (UTC), so a replay passes the tick's own time.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import json
import logging
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..chain import make_client
from ..models import OPP_DEFAULT_MAX_CONTRACTS, OPP_DEFAULT_MAX_NOTIONAL
from ..options import chain as ch
from ..options.enrich import refresh
from ..options.fills import structure_legs, structure_quote
from ..options.implied import implied_for_threshold, jsonable
from ..options.match import match_question, why_no_match
from . import session as sc

log = logging.getLogger(__name__)

PM_LATE_NOTE = "PM price recorded at snapshot time, after the close (pass pm_yes for the price at the close)"
LABEL = ("Opportunity at the open: PM price vs the Friday-close options-implied estimate (risk-neutral, not a "
         "measured probability); option fills are simulated; not a measured edge")
SIM_NOTE = "simulated: opportunity at the open (Massive quote mid +/- half spread, per-contract fee)"
TAG = "closed-opportunity"

MIN_PM_MOVE = 0.03          # weekend PM move (probability points) below which nothing is staged
MIN_GAP = 0.03              # residual move (PM move minus option move) below which the options count as caught up
EXEC_WINDOW_S = 30 * 60     # a staged trade executes only within 30 minutes after the regular open
DEFAULT_CONTRACTS = 1
OPTION_FALLBACK_HALF = 0.02  # same 2% fallback half spread as the bridge option path when a leg has no quote
REPO = Path(__file__).resolve().parents[3]
DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".closed_opportunity.json"
# R3 output: research/open_options/report.py writes research/results/open_options/stats.json with
# verdict PASS | NULL | SAMPLE TOO SMALL; the other locations are kept for a result written by hand.
R3_RESULT_DIRS = ("research/results/open_options", "research/results/r3_options_catchup",
                  "research/results/options_catchup", "research/results/r3")
R3_RESULT_FILES = ("stats.json", "tests.json", "summary.json", "result.json")
R3_VERDICTS = {"PASS": "supported", "NULL": "null", "SAMPLE TOO SMALL": "insufficient"}
# Total open risk across every opportunity trade (staged, approved, or executed and not yet expired): the per-trade
# caps alone would let each snapshot carry its own full-size trade. Same figure as the per-trade default.
BOOK_MAX_NOTIONAL = OPP_DEFAULT_MAX_NOTIONAL

STATUSES = ("staged", "approved", "executed", "cancelled", "expired", "rejected")
ACTIVE = ("staged", "approved")

REASONS: dict[str, str] = {
    # snapshot / data availability
    "unsupported_question": "not a threshold question with listed options",
    "no_options_key": "MASSIVE_API_KEY not set: no option data",
    "no_option_chain": "no listed options near the threshold and date, or Massive is unavailable",
    "no_option_estimate": "the option chain gives no usable estimate at this threshold and date",
    "market_open": "equities are in the regular session: a close snapshot is taken while they are closed",
    "no_snapshot": "no Friday-close option snapshot for this market",
    "no_pm_close": "no PM price recorded at the close",
    "pm_unavailable": "no current live PM price (a bundled or recorded price is never used for a decision)",
    # comparison
    "pm_move_small": "the PM barely moved since the close",
    "gap_small": "the PM move is too small relative to the option estimate to act on",
    "options_caught_up": "the options repriced at the open and absorbed the PM move",
    "options_already_past_pm": "the option estimate is already at or beyond the PM price",
    "gap_within_spread": "buying the spread at its ask would cost at least the PM price: no gap after costs",
    "expiry_before_open": "the matched option expiry is before the next open",
    "expiry_changed": "the open's nearest listed expiry differs from the snapshot's; not comparable",
    "stage_yes_spread": "PM moved up while equities were closed and the options have not caught up: buy the "
                        "YES-equivalent debit spread at the open",
    "stage_no_spread": "PM moved down while equities were closed and the options have not caught up: buy the "
                       "NO-equivalent debit spread at the open",
    # staging / execution
    "no_structure_price": "the spread legs have no price",
    "legs_not_listed": "a spread leg is not listed in the chain",
    "cap_used_up": "the approved max_contracts / max_notional leave room for no whole contract",
    "book_cap_used_up": "the total cap across opportunity trades leaves room for no whole contract",
    "snapshot_in_use": "a staged, approved or executed trade uses this close snapshot; it cannot be replaced",
    "awaiting_approval": "staged; needs approval before it can execute",
    "approved": "approved; executes in the window after the next regular open",
    "before_open": "the regular session has not opened yet",
    "missed_open_window": "the execution window after the open has passed",
    "not_approved_in_window": "not approved before the execution window ended",
    "quotes_not_updated_since_open": "the option quotes have not updated since the open (delayed or stale feed)",
    "pm_reverted": "the PM reverted before the open; the staged trade no longer holds",
    "no_broker": "no broker that takes multi-leg option orders",
    "broker_error": "the broker failed",
    "broker_rejected": "the simulated broker rejected the combo",
    "filled": "filled (simulated) at the open",
    "cancelled_by_user": "cancelled by the user",
    # the gates every order passes (docs/design.md sections 6, 10 and 11)
    "evidence_unvalidated": "R3 (do options catch up at the open?) does not support this signal: a trade is staged "
                            "only with ack_unvalidated: true, an explicit acknowledgement that it acts on an "
                            "unvalidated estimate",
    "liquidity_capped": "a leg's participation cap (10% of its volume, 5% of its open interest) leaves room for no "
                        "whole contract",
    "capital_budget": "the capital budget (gross / per-event hedge exposure, buying power) refuses this trade's risk, "
                      "or the account cannot be read (fail closed)",
}
EVIDENCE_LABEL = "unvalidated (acknowledged)"  # R3 is NULL: every staged trade says so


# ------------------------------------------------------------------------------------------------------ helpers


def _fin(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _iso(t: dt.datetime | None) -> str | None:
    return sc._iso(t) if t is not None else None


def _reason(code: str) -> dict:
    return {"reason_code": code, "reason": REASONS.get(code, code)}


def _market_key(market: dict) -> str:
    if market.get("source") and market.get("id"):
        return f"{market['source']}:{market['id']}"
    q = str(market.get("question") or "")
    return "q:" + hashlib.sha1(f"{q}|{market.get('end_date') or ''}".encode()).hexdigest()[:12]


def _leg_row(q: ch.OptionQuote | None) -> dict | None:
    if q is None:
        return None
    return ch._clean({"ticker": q.ticker, "kind": q.kind, "strike": q.strike, "expiry": q.expiry, "bid": q.bid,
                      "ask": q.ask, "mid": q.mid, "mark_source": q.mark_source, "iv": q.iv, "delta": q.delta,
                      "updated_ns": q.updated_ns})


def _quote_from_row(r: dict) -> ch.OptionQuote:
    nan = math.nan
    f = lambda k: _fin(r.get(k)) if _fin(r.get(k)) is not None else nan  # noqa: E731
    return ch.OptionQuote(ticker=str(r.get("ticker") or ""), kind=str(r.get("kind")), strike=float(r["strike"]),
                          expiry=str(r.get("expiry")), bid=f("bid"), ask=f("ask"), mid=f("mid"),
                          mark_source=r.get("mark_source"), iv=f("iv"), delta=f("delta"),
                          updated_ns=r.get("updated_ns"))


def close_chain(snap: dict) -> ch.Chain:
    """The snapshot's stored legs as a Chain (network-free), so structure pricing reuses options.fills."""
    rows = [r for r in (snap.get("legs") or []) if r and _fin(r.get("strike")) is not None]
    return ch.Chain(underlying=str(snap.get("underlying_used") or ""), fetched_at=0.0,
                    quotes=[_quote_from_row(r) for r in rows], source="friday_close_snapshot")


def yes_structure(direction: str) -> str:
    """Debit vertical spread paying when YES: call spread for 'above K', put spread for 'below K'."""
    return "call_spread" if direction == "above" else "put_spread"


def no_structure(direction: str) -> str:
    return "put_spread" if direction == "above" else "call_spread"


def option_fee(broker=None) -> float:
    """Per-contract option fee: the simulator's own when given, else its default."""
    from ..broker.sim import Fees, SimBroker
    sim = broker if isinstance(broker, SimBroker) else getattr(broker, "sim", None)
    fee = _fin(getattr(getattr(sim, "fees", None), "option_per_contract", None))
    return fee if fee is not None else Fees().option_per_contract


def price_structure(chain: ch.Chain, kind: str, expiry: str, k_lo: float, k_hi: float,
                    fee_per_contract: float | None = None) -> dict:
    """{kind, legs, quote, debit, unit_risk, unit_cost, max_payoff} for buying one spread. ``debit`` is the per-share
    price paid (mid + half spread, the documented 2%-per-leg fallback when a leg has no quote); ``unit_risk`` = debit
    x 100 is the most one spread can lose on the premium; ``unit_cost`` adds the per-contract fee on every leg and is
    what the caps size against. Missing legs or prices give ``reason_code``."""
    fee = option_fee() if fee_per_contract is None else float(fee_per_contract)
    legs = structure_legs(chain, kind, expiry, k_lo, k_hi) or []
    out: dict[str, Any] = {"kind": kind, "expiry": expiry, "k_lo": k_lo, "k_hi": k_hi, "width": k_hi - k_lo,
                           "legs": [], "quote": None, "debit": None, "unit_risk": None, "unit_cost": None,
                           "fee_per_contract": fee, "max_payoff": round((k_hi - k_lo) * 100, 4)}
    if not legs or any(q is None for _, q in legs):
        return {**out, **_reason("legs_not_listed")}
    out["legs"] = [{"sign": s, "kind": q.kind, "strike": q.strike, "ticker": q.ticker} for s, q in legs]
    qt = structure_quote(legs)
    out["quote"] = jsonable({k: v for k, v in qt.items() if k != "legs"})
    mid = _fin(qt.get("mid"))
    if mid is None or mid <= 0:
        return {**out, **_reason("no_structure_price")}
    half = _fin(qt.get("half_spread"))
    if half is None:
        half = sum(OPTION_FALLBACK_HALF * q.mid for _, q in legs)
    out["debit"] = round(mid + half, 6)
    out["unit_risk"] = round(out["debit"] * 100, 4)
    out["unit_cost"] = round(out["unit_risk"] + fee * len(legs), 4)
    return out


def size(contracts: int, max_contracts: int, max_notional: float, unit_cost: float | None,
         book_room: float | None = None) -> tuple[int, str | None]:
    """Whole contracts under every cap; (qty, binding cap or None). ``unit_cost`` is one spread's debit x 100 plus
    its leg fees; ``book_room`` is what the total cap across opportunity trades still allows (None: no book cap)."""
    if unit_cost is None or unit_cost <= 0:
        return 0, "max_notional"
    by_notional = math.floor(max_notional / unit_cost + 1e-9)
    by_book = math.floor(max(book_room, 0.0) / unit_cost + 1e-9) if book_room is not None else math.inf
    qty = int(max(min(contracts, max_contracts, by_notional, by_book), 0))
    cap = None
    if qty < contracts:
        cap = ("max_contracts" if max_contracts <= min(by_notional, by_book) else
               "max_notional" if by_notional <= by_book else "book_notional")
    return qty, cap


def research_status(root: Path | None = None) -> dict:
    """R3 (do options catch up at the Monday open?). ``pending`` until a result file exists. The study's own
    ``stats.json`` carries ``verdict``: PASS -> ``supported``, NULL -> ``null`` (no Opportunity claim), SAMPLE TOO
    SMALL -> ``insufficient``. An explicit boolean ``supported`` overrides the verdict. Only ``supported`` lets the
    UI say more than "estimate"."""
    root = REPO if root is None else root
    for d in R3_RESULT_DIRS:
        for name in R3_RESULT_FILES:
            p = root / d / name
            if not p.is_file():
                continue
            try:
                j = json.loads(p.read_text())
            except (OSError, ValueError):
                return {"id": "R3", "status": "unreadable", "path": str(p.relative_to(root)), "supports_claim": False}
            j = j if isinstance(j, dict) else {}
            sup, verdict = j.get("supported"), j.get("verdict")
            if sup is True or sup is False:
                status = "supported" if sup else "null"
            else:
                status = R3_VERDICTS.get(str(verdict).strip().upper(), "reported") if verdict is not None else \
                    "reported"
            return {"id": "R3", "status": status, "verdict": verdict, "path": str(p.relative_to(root)),
                    "supports_claim": status == "supported"}
    return {"id": "R3", "status": "pending", "path": None, "supports_claim": False}


# ------------------------------------------------------------------------------------------------- the snapshot


def build_snapshot(market: dict, match, chain: ch.Chain | None, *, now: Any, pm_yes: float | None,
                   cache_stale: bool = False, underlying_used: str | None = None, strike_used: float | None = None,
                   approx: bool = False, reason_code: str | None = None) -> dict:
    """A close snapshot record from a matched market and the chain fetched for it (network-free)."""
    t = sc.to_utc(now)
    s = sc.session_at(t)
    close = s.last_close
    nxt = s.next_open
    snap: dict[str, Any] = {
        "id": None, "key": _market_key(market), "market": dict(market), "label": LABEL,
        "close_day": close.astimezone(sc.ET).date().isoformat(), "close_at": _iso(close),
        "next_open": _iso(nxt), "next_open_et": nxt.astimezone(sc.ET).isoformat(),
        "taken_at": _iso(t), "taken_phase": s.phase, "lag_after_close_s": round((t - close).total_seconds(), 1),
        "pm_yes": _fin(pm_yes), "pm_recorded_at": _iso(t) if _fin(pm_yes) is not None else None,
        "match": match.to_dict(), "direction": match.direction,
        "underlying_used": underlying_used or match.underlying, "strike_used": strike_used or match.strike,
        "approx": approx, "option": None, "legs": [], "freshness": None, "available": False, "notes": [],
    }
    if snap["pm_yes"] is not None and snap["lag_after_close_s"] > 15 * 60:
        snap["notes"].append(PM_LATE_NOTE)
    if chain is None:
        snap.update(_reason(reason_code or "no_option_chain"))
        return snap
    as_of = close.astimezone(sc.ET).date()
    res = implied_for_threshold(chain, float(snap["strike_used"]), match.expiry,
                                above=match.direction == "above", as_of=as_of)
    prob = _fin(res.get("prob"))
    snap["option"] = jsonable({k: res.get(k) for k in ("prob", "lo", "hi", "method", "expiry", "expiry_gap_days",
                                                       "expiry_gap_ok", "k_lo", "k_hi", "delta", "iv")})
    snap["option"]["notes"] = list(res.get("notes") or [])
    snap["freshness"] = ch.staleness(chain, cache_stale)
    if chain.truncated:
        snap["notes"].append("chain truncated at the page limit; expiries or strikes may be missing")
    if approx or snap["underlying_used"] != match.underlying:
        snap["notes"].append(f"proxy {snap['underlying_used']} used (approximate scaling)")
    exp, k_lo, k_hi = res.get("expiry"), res.get("k_lo"), res.get("k_hi")
    if exp and k_lo is not None and k_hi is not None:
        sl = chain.slice(exp)
        snap["legs"] = [r for r in (_leg_row((sl.get(float(k)) or {}).get(kind))
                                    for k in (k_lo, k_hi) for kind in ("call", "put")) if r]
    ok = prob is not None and bool(res.get("expiry_gap_ok")) and bool(snap["legs"])
    snap["available"] = ok
    snap.update(_reason("no_option_estimate") if not ok else {"reason_code": None, "reason": None})
    return snap


async def fetch_chain(und: str, k: float, expiry: Any, fallback: tuple[str, float] | None, level: float,
                      *, as_of: dt.date, client) -> tuple[ch.Chain, bool, str, float, bool] | None:
    """Chain for the matched threshold (primary underlying, then the scaled proxy). None when nothing is listed."""
    attempts = [(und, k, False)]
    if fallback:
        attempts.append((fallback[0], round(level * fallback[1], 6), True))
    for u, kk, approx in attempts:
        got = await refresh(u, kk, expiry, as_of=as_of, client=client)
        if got is not None:
            return got[0], got[1], u, kk, approx
    return None


async def take_snapshot(market: dict, *, now: Any, pm_yes: float | None, client=None,
                        allow_open: bool = False) -> dict:
    """Match the market question and snapshot the option-implied estimate at the last close. Returns the record (not
    yet stored); an unsupported question or an open market gives ``supported: False`` and a reason code."""
    t = sc.to_utc(now)
    s = sc.session_at(t)
    base = {"market": dict(market), "label": LABEL, "supported": False, "available": False}
    if s.equities_open and not allow_open:
        return {**base, **_reason("market_open")}
    q = market.get("question")
    as_of = s.last_close.astimezone(sc.ET).date()
    m = match_question(q, market.get("end_date"), as_of=as_of) if q else None
    if m is None:
        why = why_no_match(q or "", market.get("end_date"), as_of=as_of) if q else "market not found (no question)"
        return {**base, **_reason("unsupported_question"), "detail": why}
    client = client if client is not None else make_client()
    if client is None:
        return build_snapshot(market, m, None, now=t, pm_yes=pm_yes, reason_code="no_options_key")
    got = await fetch_chain(m.underlying, m.strike, m.expiry, m.fallback, m.level, as_of=as_of, client=client)
    if got is None:
        return build_snapshot(market, m, None, now=t, pm_yes=pm_yes, reason_code="no_option_chain")
    chain, stale, und, k, approx = got
    return build_snapshot(market, m, chain, now=t, pm_yes=pm_yes, cache_stale=stale, underlying_used=und,
                          strike_used=k, approx=approx)


def implied_now(snap: dict, chain: ch.Chain | None, *, now: Any, cache_stale: bool = False) -> dict | None:
    """The options-implied estimate from a chain fetched at (or after) the open, for the snapshot's threshold. Adds
    ``since_open``: True when every leg of both spreads was updated at or after the next open."""
    if chain is None or not snap.get("match"):
        return None
    t = sc.to_utc(now)
    m = snap["match"]
    res = implied_for_threshold(chain, float(snap["strike_used"]), m["expiry"], above=snap["direction"] == "above",
                                as_of=t.astimezone(sc.ET).date())
    out = jsonable({k: res.get(k) for k in ("prob", "lo", "hi", "method", "expiry", "expiry_gap_ok", "k_lo",
                                            "k_hi")})
    out["notes"] = list(res.get("notes") or [])
    snap_exp = (snap.get("option") or {}).get("expiry")
    out["same_expiry"] = res.get("expiry") == snap_exp
    out["available"] = _fin(res.get("prob")) is not None and bool(res.get("expiry_gap_ok")) and out["same_expiry"]
    open_ns = int(sc.to_utc(snap["next_open"]).timestamp() * 1e9)
    sl = chain.slice(snap_exp) if snap_exp else {}
    strikes = [k for k in ((snap.get("option") or {}).get("k_lo"), (snap.get("option") or {}).get("k_hi"))
               if k is not None]
    quotes = [q for k in strikes for q in (sl.get(float(k)) or {}).values()]
    out["since_open"] = bool(quotes) and all(q.updated_ns is not None and q.updated_ns >= open_ns for q in quotes)
    out["freshness"] = ch.staleness(chain, cache_stale)
    return out


# ---------------------------------------------------------------------------------------------- the comparison


def evaluate(snap: dict | None, pm_now: float | None, opt_now: dict | None = None, *,
             min_pm_move: float = MIN_PM_MOVE, min_gap: float = MIN_GAP) -> dict:
    """Compare the weekend PM move with the option move. Pure. ``decision`` is ``stage`` or ``none``; ``supported``
    is True when the data exist (option estimate at the close, PM prices at the close and now)."""
    opt = (snap or {}).get("option") or {}
    d: dict[str, Any] = {
        "decision": "none", "supported": False, "side": None, "structure": None,
        "pm_close": _fin((snap or {}).get("pm_yes")), "pm_now": _fin(pm_now), "pm_move": None,
        "opt_close": _fin(opt.get("prob")), "opt_close_band": [_fin(opt.get("lo")), _fin(opt.get("hi"))],
        "opt_now": None, "opt_ref": None, "opt_ref_source": None, "opt_move": None, "residual": None,
        "level_gap": None, "catch_up": None, "thresholds": {"min_pm_move": min_pm_move, "min_gap": min_gap},
        "label": "estimate (options-implied, risk-neutral); not a measured edge",
    }

    def done(code: str) -> dict:
        d.update(_reason(code))
        return d

    if snap is None:
        return done("no_snapshot")
    if not snap.get("available"):
        return done(snap.get("reason_code") or "no_option_estimate")
    if d["pm_close"] is None:
        return done("no_pm_close")
    if d["pm_now"] is None:
        return done("pm_unavailable")
    d["supported"] = True
    pm_move = d["pm_now"] - d["pm_close"]
    opt_ref, src, band = d["opt_close"], "friday_close", d["opt_close_band"]
    if opt_now is not None:
        d["opt_now"] = _fin(opt_now.get("prob"))
        if not opt_now.get("same_expiry", True):
            return done("expiry_changed")
        if opt_now.get("available") and d["opt_now"] is not None:
            opt_ref, src, band = d["opt_now"], "open", [_fin(opt_now.get("lo")), _fin(opt_now.get("hi"))]
    opt_move = opt_ref - d["opt_close"]
    residual = pm_move - opt_move
    level_gap = d["pm_now"] - opt_ref
    d.update(pm_move=round(pm_move, 6), opt_ref=opt_ref, opt_ref_source=src, opt_move=round(opt_move, 6),
             residual=round(residual, 6), level_gap=round(level_gap, 6), band=band,
             catch_up=round(opt_move / pm_move, 4) if src == "open" and abs(pm_move) > 1e-12 else None)
    if abs(pm_move) < min_pm_move:
        return done("pm_move_small")
    sgn = 1.0 if pm_move > 0 else -1.0
    if sgn * residual < min_gap:
        return done("options_caught_up" if src == "open" else "gap_small")
    if sgn * level_gap <= 0:
        return done("options_already_past_pm")
    lo, hi = band
    if (sgn > 0 and hi is not None and d["pm_now"] <= hi) or (sgn < 0 and lo is not None and d["pm_now"] >= lo):
        return done("gap_within_spread")
    exp = opt.get("expiry")
    if exp and snap.get("next_open") and exp < snap["next_open_et"][:10]:
        return done("expiry_before_open")
    side = "yes" if sgn > 0 else "no"
    d.update(decision="stage", side=side,
             structure=yes_structure(snap["direction"]) if side == "yes" else no_structure(snap["direction"]))
    return done("stage_yes_spread" if side == "yes" else "stage_no_spread")


# ------------------------------------------------------------------------------------------- the staged trade


def _event(trade: dict, now: Any, status: str, code: str, **extra) -> None:
    ev = {"at": _iso(sc.to_utc(now)), "status": status, **_reason(code), **extra}
    last = trade["events"][-1] if trade.get("events") else None
    if last and last["status"] == status and last["reason_code"] == code and not extra:
        last["at"], last["count"] = ev["at"], last.get("count", 1) + 1  # a repeated hold: one row, counted
        return
    trade.setdefault("events", []).append(ev)


def stage_trade(snap: dict, decision: dict, *, now: Any, contracts: int = DEFAULT_CONTRACTS,
                max_contracts: int = OPP_DEFAULT_MAX_CONTRACTS,
                max_notional: float = OPP_DEFAULT_MAX_NOTIONAL, book_room: float | None = None) -> dict:
    """A staged (unapproved) option trade for the next open, priced at the close (fees included). ``book_room`` is
    what the total cap across opportunity trades still allows. Raises ValueError(reason_code) when the decision is
    not ``stage`` or the spread cannot be priced or sized."""
    if decision.get("decision") != "stage":
        raise ValueError(decision.get("reason_code") or "no_snapshot")
    opt = snap["option"]
    est = price_structure(close_chain(snap), decision["structure"], opt["expiry"], float(opt["k_lo"]),
                          float(opt["k_hi"]))
    if est.get("reason_code"):
        raise ValueError(est["reason_code"])
    qty, cap = size(contracts, max_contracts, max_notional, est["unit_cost"], book_room)
    if qty <= 0:
        raise ValueError("book_cap_used_up" if cap == "book_notional" else "cap_used_up")
    t = sc.to_utc(now)
    op = sc.to_utc(snap["next_open"])
    trade = {
        "id": f"opp-{uuid.uuid4().hex[:10]}", "snapshot_id": snap["id"], "market": snap["market"],
        "underlying": snap["underlying_used"], "status": "staged", "label": LABEL, "simulated": True,
        "approval_required": True, "created_at": _iso(t), "not_before": _iso(op),
        "not_before_et": op.astimezone(sc.ET).isoformat(),
        "window_end": _iso(op + dt.timedelta(seconds=EXEC_WINDOW_S)),
        "side": decision["side"], "structure": est, "decision": decision,
        "contracts": int(contracts), "max_contracts": int(max_contracts), "max_notional": float(max_notional),
        "qty_estimate": qty, "cap_estimate": cap, "notional_estimate": round(qty * est["unit_cost"], 2),
        "snapshot_taken_at": snap.get("taken_at"),
        "execution": None, "events": [],
    }
    _event(trade, t, "staged", "awaiting_approval")
    return trade


def review_trade(trade: dict, snap: dict | None, pm_now: float | None, *, now: Any) -> dict:
    """Before the open: cancel a staged or approved trade the PM no longer supports (revert rule). Returns the new
    decision. Leaves the trade alone when the PM is unavailable."""
    t = sc.to_utc(now)
    dec = evaluate(snap, pm_now)
    if trade["status"] not in ACTIVE or dec["reason_code"] == "pm_unavailable":
        return dec
    if t >= sc.to_utc(trade["window_end"]):
        code = "missed_open_window" if trade["status"] == "approved" else "not_approved_in_window"
        trade["status"] = "expired"
        _event(trade, t, "expired", code)
        return dec
    if t < sc.to_utc(trade["not_before"]) and (dec["decision"] != "stage" or dec["side"] != trade["side"]):
        trade["status"] = "cancelled"
        _event(trade, t, "cancelled", "pm_reverted", detail=dec["reason_code"])
    return dec


async def execute_trade(trade: dict, snap: dict, *, now: Any, pm_now: float | None, chain: ch.Chain | None,
                        broker, cache_stale: bool = False, book_room: float | None = None, app=None) -> dict:
    """Execute an approved trade at the open, simulated, all legs or none. Mutates ``trade`` (status, events,
    execution) and returns {"outcome": executed|held|cancelled|expired|rejected|refused, reason_code, ...}.
    ``held`` keeps the trade approved so a later call retries inside the window. ``book_room``: what the total cap
    across opportunity trades allows this trade (its own staged estimate excluded). The simulated orders carry the
    decision time (``now``) in their note, since the broker stamps its own wall clock. Before the combo is sent the
    trade passes the option participation caps (every leg <= 10% of its volume and <= 5% of its open interest; cut to
    the cap, refused at 0) and, when ``app`` is given, the capital budget at the account the legs fill in (its max loss,
    the debit plus fees; refused on a breach or an unreadable account)."""
    t = sc.to_utc(now)

    def out(outcome: str, code: str, **extra) -> dict:
        return {"outcome": outcome, **_reason(code), "trade_id": trade["id"], **extra}

    if trade["status"] == "staged":
        if t >= sc.to_utc(trade["window_end"]):
            trade["status"] = "expired"
            _event(trade, t, "expired", "not_approved_in_window")
            return out("expired", "not_approved_in_window")
        return out("refused", "awaiting_approval")
    if trade["status"] != "approved":
        return out("refused", trade["events"][-1]["reason_code"] if trade.get("events") else trade["status"],
                   status=trade["status"])
    if t < sc.to_utc(trade["not_before"]):
        return out("held", "before_open")
    if t >= sc.to_utc(trade["window_end"]):
        trade["status"] = "expired"
        _event(trade, t, "expired", "missed_open_window")
        return out("expired", "missed_open_window")
    if chain is None:
        _event(trade, t, "approved", "no_option_chain")
        return out("held", "no_option_chain")
    now_est = implied_now(snap, chain, now=t, cache_stale=cache_stale)
    if not now_est or not now_est.get("since_open"):
        _event(trade, t, "approved", "quotes_not_updated_since_open")
        return out("held", "quotes_not_updated_since_open", opt_now=now_est)
    if not now_est.get("same_expiry"):
        trade["status"] = "cancelled"
        _event(trade, t, "cancelled", "expiry_changed")
        return out("cancelled", "expiry_changed", opt_now=now_est)
    if not now_est.get("available"):
        _event(trade, t, "approved", "no_option_estimate")
        return out("held", "no_option_estimate", opt_now=now_est)
    if pm_now is None:
        _event(trade, t, "approved", "pm_unavailable")
        return out("held", "pm_unavailable")
    dec = evaluate(snap, pm_now, now_est)
    if dec["decision"] != "stage" or dec["side"] != trade["side"]:
        code = dec["reason_code"] if dec["reason_code"] in ("options_caught_up", "expiry_changed") else "pm_reverted"
        trade["status"] = "cancelled"
        _event(trade, t, "cancelled", code, detail=dec["reason_code"])
        trade["execution"] = {"decision": dec}
        return out("cancelled", code, decision=dec)
    st = trade["structure"]
    live = price_structure(chain, st["kind"], st["expiry"], float(st["k_lo"]), float(st["k_hi"]),
                           fee_per_contract=option_fee(broker))
    if live.get("reason_code"):
        trade["status"] = "rejected"
        _event(trade, t, "rejected", live["reason_code"])
        return out("rejected", live["reason_code"])
    qty, cap = size(trade["contracts"], trade["max_contracts"], trade["max_notional"], live["unit_cost"], book_room)
    if qty <= 0:
        code = "book_cap_used_up" if cap == "book_notional" else "cap_used_up"
        trade["status"] = "rejected"
        _event(trade, t, "rejected", code)
        return out("rejected", code, unit_cost=live["unit_cost"], book_room=book_room)
    place = _combo_target(broker)
    if place is None:
        trade["status"] = "rejected"
        _event(trade, t, "rejected", "no_broker")
        return out("rejected", "no_broker")
    from ..broker.models import OrderRequest
    from ..liquidity import gate as liquidity
    sl = chain.slice(st["expiry"])
    quotes = [(sl.get(float(lg["strike"])) or {}).get(lg["kind"]) for lg in live["legs"]]
    lq = liquidity.option_check(quotes, qty)
    gates = {"liquidity": {k: v for k, v in lq.items() if k != "allowed"}}
    if lq["status"] == "capped":
        if int(lq["allowed"]) <= 0:
            trade["status"] = "rejected"
            _event(trade, t, "rejected", "liquidity_capped", leg=lq.get("leg"), limit_qty=lq.get("limit_qty"))
            trade["execution"] = {"gates": gates}
            return out("rejected", "liquidity_capped", liquidity=gates["liquidity"])
        qty, cap = int(lq["allowed"]), "liquidity_capped"
    if app is not None:
        chk = await _capital(app, place, broker, trade, qty * float(live["unit_cost"]))
        gates["capital"] = chk
        if chk.get("refused"):
            trade["status"] = "rejected"
            _event(trade, t, "rejected", "capital_budget", detail=chk.get("detail"))
            trade["execution"] = {"gates": gates}
            return out("rejected", "capital_budget", capital=chk)
    reqs = []
    for i, (lg, q) in enumerate(zip(live["legs"], quotes)):
        mid = _fin(getattr(q, "mid", None))
        b, a = _fin(getattr(q, "bid", None)), _fin(getattr(q, "ask", None))
        half = (a - b) / 2.0 if b is not None and a is not None and a >= b else None
        reqs.append(OrderRequest(symbol=lg["ticker"], asset="option", side="buy" if lg["sign"] > 0 else "sell",
                                 qty=qty, type="market", ref_px=mid if mid and mid > 0 else None,
                                 ref_half_spread=half if mid and mid > 0 else None,
                                 client_order_id=f"{trade['id']}-L{i}", tag=TAG, combo_id=trade["id"],
                                 note=f"{SIM_NOTE}; decided at {_iso(t)}"))
    try:
        orders = await asyncio.wait_for(place(reqs), 10.0)
    except Exception as e:
        log.warning("opportunity combo failed: %s", type(e).__name__)
        _event(trade, t, "approved", "broker_error", detail=type(e).__name__)
        return out("held", "broker_error", detail=type(e).__name__)
    filled = bool(orders) and all(o.status == "filled" for o in orders)
    legs = [{"ticker": o.symbol, "side": o.side, "qty": o.qty, "status": o.status, "fill_px": o.fill_px,
             "fee": o.fee, "order_id": o.id, "price_source": o.price_source, "reject_reason": o.reject_reason}
            for o in orders]
    net = sum((1 if o.side == "buy" else -1) * float(o.fill_px) for o in orders) if filled else None
    trade["execution"] = {
        "at": _iso(t), "qty": qty, "cap": cap, "decision": dec, "opt_now": now_est, "live_quote": live,
        "legs": legs, "net_debit": round(net, 6) if net is not None else None,
        "cost": round(net * 100 * qty + sum(o.fee for o in orders), 2) if net is not None else None,
        "broker": orders[0].broker if orders else None, "simulated": True, "fill_model": SIM_NOTE,
        # The broker stamps its own wall clock on the orders; in a replay that differs from ``at`` (the tick time).
        "broker_filled_at": orders[0].filled_at if orders else None, "book_room": book_room, "gates": gates,
    }
    if filled:
        trade["status"] = "executed"
        _event(trade, t, "executed", "filled", qty=qty)
        return out("executed", "filled", execution=trade["execution"])
    trade["status"] = "rejected"
    why = next((o.reject_reason for o in orders if o.reject_reason), None)
    _event(trade, t, "rejected", "broker_rejected", detail=why)
    return out("rejected", "broker_rejected", detail=why)


async def _capital(app, place, broker, trade: dict, risk_usd: float) -> dict:
    """The capital budget for the trade's max loss, checked at the account the legs fill in (the simulator behind
    Webull paper, since ``_combo_target`` sends the combo there). Fails closed when the check itself fails."""
    from ..capital import service as cap
    from ..capital.budget import CAPITAL_BUDGET
    acct = getattr(place, "__self__", None) or broker
    try:
        chk = await cap.check(app, broker=acct, event=cap.event_key(trade.get("market")), add_notional=risk_usd,
                              add_margin=risk_usd)
    except Exception as e:
        return {"refused": True, "reason": CAPITAL_BUDGET, "detail": f"capital check failed ({type(e).__name__})"}
    row = {k: chk.get(k) for k in ("ok", "enforced", "checked", "scope", "note", "reason")}
    row["risk_usd"] = round(risk_usd, 2)
    if cap.refused(chk):
        row.update(refused=True, detail=cap.refusal_text(chk))
    return row


def _combo_target(broker):
    """The simulator's multi-leg fill (Webull paper routes options to its sim anyway)."""
    if broker is None:
        return None
    from ..broker.sim import SimBroker
    sim = broker if isinstance(broker, SimBroker) else getattr(broker, "sim", None)
    return getattr(sim, "place_combo", None) if sim is not None else getattr(broker, "place_combo", None)


# --------------------------------------------------------------------------------------------------- the store


class OpportunityBook:
    """Snapshots and staged trades, persisted to one JSON file (a Friday snapshot must survive a weekend restart)."""

    def __init__(self, path: Path | str | None = DEFAULT_PATH) -> None:
        self.path = Path(path) if path else None
        self.lock = asyncio.Lock()
        self.snapshots: dict[str, dict] = {}
        self.trades: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            s = json.loads(self.path.read_text())
            self.snapshots = {k: dict(v) for k, v in (s.get("snapshots") or {}).items()}
            self.trades = {k: dict(v) for k, v in (s.get("trades") or {}).items()}
        except (OSError, ValueError, AttributeError) as e:
            log.warning("opportunity book unreadable (%s); starting empty", type(e).__name__)
            self.snapshots, self.trades = {}, {}

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".closed_opportunity.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump({"version": 1, "snapshots": self.snapshots, "trades": self.trades}, f)
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not persist the opportunity book: %s", e)

    @staticmethod
    def snapshot_id(key: str, close_day: str) -> str:
        return "snap-" + hashlib.sha1(f"{key}|{close_day}".encode()).hexdigest()[:12]

    def in_use(self, snapshot_id: str) -> dict | None:
        """The staged, approved or executed trade that uses this snapshot, if any."""
        return next((t for t in self.trades.values()
                     if t["snapshot_id"] == snapshot_id and t["status"] in (*ACTIVE, "executed")), None)

    def put_snapshot(self, snap: dict, *, pm_explicit: bool = False) -> dict:
        """Store the snapshot for this market and close; the id is stable per (market, close day).

        A repeat for the same close refreshes the option block but never moves the baseline the weekend move is
        measured from: the first PM close price (and when it was recorded) is kept unless the caller supplies one
        explicitly (``pm_explicit``). A snapshot that a staged, approved or executed trade uses is never replaced:
        ValueError("snapshot_in_use")."""
        sid = self.snapshot_id(snap["key"], snap["close_day"])
        if self.in_use(sid) is not None:
            raise ValueError("snapshot_in_use")
        snap = {**copy.deepcopy(snap), "id": sid}
        old = self.snapshots.get(sid)
        if old is not None:
            snap["revision"] = int(old.get("revision") or 1) + 1
            snap["first_taken_at"] = old.get("first_taken_at") or old.get("taken_at")
            if not pm_explicit and _fin(old.get("pm_yes")) is not None:
                snap["pm_yes"] = old["pm_yes"]
                snap["pm_source"] = old.get("pm_source")
                snap["pm_recorded_at"] = old.get("pm_recorded_at") or old.get("taken_at")
                notes = [n for n in snap.get("notes") or [] if n != PM_LATE_NOTE]
                if PM_LATE_NOTE in (old.get("notes") or []):
                    notes.append(PM_LATE_NOTE)
                notes.append(f"options re-snapshotted at {snap.get('taken_at')}; PM close price kept from "
                             f"{snap['pm_recorded_at']}")
                snap["notes"] = notes
        self.snapshots[sid] = snap
        self.save()
        return snap

    def exposure(self, now: Any, exclude: str | None = None) -> float:
        """Open risk across opportunity trades: the staged estimate of every staged or approved trade plus the cost
        of every executed trade whose spread has not expired (a debit spread's most-lost is its cost until expiry)."""
        today = sc.to_utc(now).astimezone(sc.ET).date().isoformat()
        tot = 0.0
        for t in self.trades.values():
            if t["id"] == exclude:
                continue
            if t["status"] in ACTIVE:
                tot += _fin(t.get("notional_estimate")) or 0.0
            elif t["status"] == "executed" and str((t.get("structure") or {}).get("expiry") or "") >= today:
                tot += _fin((t.get("execution") or {}).get("cost")) or 0.0
        return round(tot, 2)

    def book_room(self, now: Any, exclude: str | None = None, cap: float | None = None) -> float:
        """What the total cap (``BOOK_MAX_NOTIONAL`` unless ``cap``) still allows."""
        cap = BOOK_MAX_NOTIONAL if cap is None else cap
        return round(max(cap - self.exposure(now, exclude), 0.0), 2)

    def latest_for(self, key: str) -> dict | None:
        rows = [s for s in self.snapshots.values() if s.get("key") == key]
        return max(rows, key=lambda s: (s.get("close_day") or "", s.get("taken_at") or "")) if rows else None

    def active_trade(self, snapshot_id: str) -> dict | None:
        return next((t for t in self.trades.values() if t["snapshot_id"] == snapshot_id and t["status"] in ACTIVE),
                    None)

    def put_trade(self, trade: dict) -> dict:
        self.trades[trade["id"]] = trade
        self.save()
        return trade


def snapshot_view(snap: dict, pm_now: float | None = None, opt_now: dict | None = None) -> dict:
    """A snapshot plus its comparison (what the UI card shows)."""
    dec = evaluate(snap, pm_now, opt_now)
    return {**snap, "supported": dec["supported"], "comparison": dec}
