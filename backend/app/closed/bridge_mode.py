"""Closed-market mode inside a bridge (docs/design.md, section 2).

Every bridge knows the NYSE session of each tick: a replay from the tick's RECORDED time (a replayed Saturday is a
Saturday), a live bridge from the wall clock. While the regular session is closed (after-hours, overnight, weekend,
holiday, and pre-market):

- **The equity algo holds.** The bridge's equity algo / engine is paused, not stepped (``bridges._hold_closed``): nothing
  is sent and the decision is reported as ``hold`` / ``session_closed``. (Stepping it and refusing its intents would put
  the algo into its wall-clock reject backoff, which freezes a replay.) ``BridgeIn.session_hold=false`` trades at any
  hour instead, except at a broker that takes orders only in the regular session (Webull paper,
  ``regular_session_only``): there the hold is forced (``broker_hold``) and only staged orders reach it, at 09:30 ET.
  An opportunity bridge's options algo is held the same way when that broker also takes its option combos
  (``options_supported``, WEBULL_OPTIONS=1); with option legs in the simulator it trades at any hour.
- **Closure and expected gap.** The PM move since the last regular close (closure tracker: the app's shared tracker for
  a live bridge, one local to the bridge for a replay) and the expected open gap with its 80% band and the number of
  closures behind the rate (``app.closed.gap``).
- **Evidence gate** (``app.closed.evidence.gate``): the gap is ``validated`` only when the market's own out-of-sample
  record passes R2, its own rate is the one used, AND that rate was estimated on the bridge's ticker (R2 tested SPY
  only; any other ticker is a proxy); everything else is an ``unvalidated estimate``.
- **Hedge B (default).** A staged equity order (``app.closed.staged``) is planned from the expected gap once it is
  adverse beyond ``min_gap_bp`` (10 bp), resized while still unapproved as the gap moves, and needs the user's
  approval (which names the quantity the user saw). A pending plan for the same proposal made elsewhere (``POST
  /staged/plan``) is adopted, never superseded. Approved, it executes at the first tradable moment per the broker's capability (pre-market when the broker
  supports extended hours, else the 09:30 open) on this bridge's ticks; the revert / resize rule runs on every tick. A
  replay sends it only at a FRESH recorded price: inside the regular session, once the recorded equity price has
  changed since the closure (the engine's fresh-close rule), never at a stale Friday close.
- **Hedge A (opt-in, an estimate).** Only when the proposal sets ``closed_pm_hedge``: the C++ ``closed_session_hedge``
  family sizes a simulated, labelled PM leg (no Polymarket trading account) and unwinds it at the open (handoff). R1
  found no evidence it reduces the open-gap loss, so it is never called protection.
- **Coverage** counts the PM and equity legs together: the bridge's own sells, resting staged sells and hedge A's leg
  (in equity shares) share one ``target_coverage`` cap. Hedge A's leg counts only when it is real (a PM trading
  account); while simulated it counts 0, so it never shrinks hedge B's real order.
- **P&L vs no hedge** over the closure: the holding marked from the last regular close, and what the carried equity
  hedge, the staged order and hedge A (estimate) added to it.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
import time
from collections import Counter
from typing import Any

from . import evidence as ev
from . import staged
from .gap import ExpectedGap, expected_gap_for, load_rates
from .session import ET, UTC, Session, check_supported, now_utc, session_at
from .tracker import ClosureState, ClosureTracker, market_key, tracker_for

HEDGE_A_FAMILY = "closed_session_hedge"
SKIP_RETRY_BP = 10.0      # after a skipped / refused plan, retry only once the gap is 10 bp more adverse
TIMELINE_MAX = 200
SEED_TIMEOUT_S = 8.0
HEDGE_A_FILLS_MAX = 200


def _iso(x: dt.datetime | None) -> str | None:
    return x.astimezone(UTC).isoformat().replace("+00:00", "Z") if x is not None else None


def _fin(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _pos(x: Any) -> float | None:
    v = _fin(x)
    return v if v is not None and v > 0 else None


def live_now(app) -> dt.datetime:
    """A live bridge's clock: ``app.state.staged_clock`` when set (tests pin it), else the wall clock."""
    clock = getattr(app.state, "staged_clock", None)
    return check_supported(clock()) if clock else now_utc()


def tick_time(bridge, app, t) -> dt.datetime | None:
    """Replay: the tick's recorded time (None when the row has none or it is outside the calendar's range, e.g. a
    synthetic test epoch); live: the wall clock."""
    if getattr(bridge, "effective_source", None) == "replay":
        rts = getattr(t, "recorded_ts_ns", None)
        if rts is None:
            return None
        try:  # the recording's ts_ns is nanoseconds by contract (never guessed from its magnitude)
            return check_supported(dt.datetime.fromtimestamp(int(rts) / 1e9, UTC))
        except (ValueError, TypeError, OverflowError, OSError):
            return None
    try:
        return live_now(app)
    except ValueError:
        return None


def session_view(s: Session | None) -> dict | None:
    if s is None:
        return None
    return {"at": _iso(s.at), "phase": s.phase, "closed": s.closed, "label": s.label,
            "next_open": _iso(s.next_open), "next_open_et": s.next_open.astimezone(ET).isoformat(),
            "next_premarket": _iso(s.next_extended_open),
            "next_premarket_et": s.next_extended_open.astimezone(ET).isoformat(),
            "last_close": _iso(s.last_close), "closure_kind": s.closure.kind if s.closure else None}


def closure_view(st: ClosureState | None) -> dict | None:
    if st is None:
        return None
    return {"pm_move_pp": st.move_pp, "since": _iso(st.close_at), "status": st.status, "p_close": st.p_close,
            "p_now": st.p_now, "high_pp": st.high_pp, "low_pp": st.low_pp, "n_points": st.n_points,
            "kind": st.session.closure.kind if st.session.closure else None}


def gap_view(g: ExpectedGap | None, evid: dict) -> dict | None:
    if g is None:
        return None
    validated, status, why = ev.gate(evid, g.label, g.ticker, g.basis_ticker, g.reasons)
    return {"bp": g.expected_gap_bp, "band": list(g.band_bp) if g.band_bp else None, "band_level": g.band_level,
            "n": g.n_closures, "rate_source": g.label, "rate_bp_per_pp": g.rate_bp_per_pp,
            "rate_band": list(g.band_rate), "validated": validated,
            "status": status, "evidence": why, "active": g.active,
            "oriented_move_pp": g.oriented_move_pp, "basis_ticker": g.basis_ticker, "reasons": list(g.reasons)}


# ------------------------------------------------------------------------------------------------------- hedge A


class HedgeA:
    """The opt-in PM leg: ``hedgecore.Algo('closed_session_hedge')`` on the bridge's oriented ticks, its fills simulated
    at the tick's YES ask (buy) / bid (sell), never sent anywhere. ``handoff_equity`` stays 0: the equity side at the
    open is hedge B's staged order and the bridge's own algo."""

    LABEL = ev.HEDGE_A_LABEL

    def __init__(self, hc, bridge, rate_bp_per_pp: float, rate_source: str) -> None:
        from ..bridges import _catalog_manifest
        fam = next((f for f in _catalog_manifest(hc)["families"] if f["id"] == HEDGE_A_FAMILY), None)
        if fam is None:
            raise ValueError(f"{HEDGE_A_FAMILY} is not in the compiled catalog")
        params = {p["name"]: float(p.get("default", p["grid"][0] if p.get("grid") else 0.0)) for p in fam["params"]}
        rate = min(100.0, max(0.0, float(rate_bp_per_pp)))
        params.update(coverage=float(bridge.proposal.target_coverage), rate_bp_per_pp=rate, handoff_equity=0.0)
        self.params = params
        self.rate_eff = rate * params.get("rate_scale", 1.0)
        self.rate_source = rate_source
        self.algo = hc.Algo(HEDGE_A_FAMILY, dict(params), {"shares_held": float(bridge.proposal.shares_held),
                                                           "equity": -float(bridge.broker_hedge or 0.0)})
        self.contracts = 0.0
        self.cash = 0.0          # signed USD paid for the leg (buys negative)
        self.mark: float | None = None
        self.s: float | None = None
        self.fills: list[dict] = []
        self.reasons: Counter[str] = Counter()
        self.last_signal: float | None = None
        self.simulated = True    # no Polymarket trading account: the leg is never real coverage
        self.liquidity_capped = 0  # PM orders the depth cap lowered

    def step(self, oriented: dict, ts_ns: int, now_ns: int, venue: int, under_px: float | None,
             tick_builder) -> dict | None:
        if under_px:
            self.s = under_px
        b, a = _fin(oriented.get("yes_bid")), _fin(oriented.get("yes_ask"))
        if b is not None and a is not None:
            self.mark = (b + a) / 2.0
        i = self.algo.on_tick(tick_builder(oriented, ts_ns, venue), now_ns)
        self.reasons[str(i.get("reason"))] += 1
        self.last_signal = _fin(i.get("signal"))
        if i.get("action") != "order":
            return None
        inst = str(i.get("instrument") or "")
        side = 1 if int(i.get("side") or 0) > 0 else -1
        qty = _fin(i.get("qty")) or 0.0
        if inst != "pred_yes" or qty <= 0:
            self.algo.on_reject(inst or "equity")  # the equity side belongs to hedge B / the bridge's algo
            return None
        px = (a if side > 0 else b)
        px = px if px is not None and 0.0 < px < 1.0 else self.mark
        if px is None or not 0.0 < px < 1.0:
            self.algo.on_reject("pred_yes")
            return None
        # participation: at most 50% of the book depth within 2 cents of the mid on the side taken
        from ..liquidity import gate as liquidity
        liq = liquidity.pm_check(oriented, "buy" if side > 0 else "sell", qty)
        capped_from = None
        if liq["status"] == "capped":
            self.liquidity_capped += 1
            capped_from, qty = qty, float(liq["allowed"])
            if qty <= 0:
                self.reasons[liquidity.LIQUIDITY_CAPPED] += 1
                self.algo.on_reject("pred_yes")
                return None
        self.algo.on_fill("pred_yes", side * qty, px)
        self.contracts += side * qty
        self.cash -= side * qty * px
        rec = {"instrument": "pred_yes", "side": "buy" if side > 0 else "sell", "qty": qty, "fill_px": px,
               "reason": str(i.get("reason")), "contracts": self.contracts, "simulated": True, "estimate": True,
               "label": "simulated PM leg (estimate, no Polymarket account)"}
        liquidity.tag(rec, liq)
        if capped_from is not None:
            rec["capped_from"] = capped_from
        self.fills.append(rec)
        del self.fills[:-HEDGE_A_FILLS_MAX]
        return rec

    def on_equity_fill(self, signed_qty: float, px: float) -> None:
        """Equity fills of this holding from elsewhere (the staged order): combined PM + equity coverage."""
        try:
            self.algo.on_fill("equity", float(signed_qty), float(px))
        except Exception:
            pass

    def equity_equiv_shares(self) -> float:
        """The leg in equity shares: contracts / (S * r_eff * 1e-2), the family's own sizing inverted."""
        if self.contracts <= 0 or not self.s or self.rate_eff <= 0:
            return 0.0
        return self.contracts / (self.s * self.rate_eff * 1e-2)

    def pnl(self) -> float | None:
        if self.mark is None:
            return None if self.contracts else self.cash
        return self.cash + self.contracts * self.mark

    def summary(self) -> dict:
        return {"enabled": True, "label": self.LABEL, "estimate": True, "family": HEDGE_A_FAMILY,
                "rate_bp_per_pp": self.params["rate_bp_per_pp"], "rate_source": self.rate_source,
                "contracts": self.contracts, "mark": self.mark, "pnl_usd": self.pnl(), "simulated": self.simulated,
                # coverage the leg counts toward the shared cap: 0 while simulated (not protection, never replaces
                # hedge B's real order); the simulated equivalent is shown separately for display only
                "equity_equiv_shares": 0.0 if self.simulated else self.equity_equiv_shares(),
                "sim_equity_equiv_shares": self.equity_equiv_shares(), "counts_toward_cap": not self.simulated,
                "fills": len(self.fills), "liquidity_capped": self.liquidity_capped,
                "last_fill": self.fills[-1] if self.fills else None, "signal_gap_bp": self.last_signal,
                "reasons": dict(self.reasons), "params": dict(self.params)}


# ---------------------------------------------------------------------------------------------------- closed mode


class ClosedMode:
    """Per-bridge closed-market state. ``on_tick`` is called once per tick by the bridge loop; it never raises into
    the loop (the bridge catches and reports)."""

    def __init__(self, bridge, app, hc=None, hedge_a: bool = False) -> None:
        self.bridge, self.app = bridge, app
        m = bridge.market
        self.source, self.mid, self.token = m.source, m.id, m.token_id
        self.key = market_key(m.source, m.id)
        self.hedging = getattr(bridge, "division", "hedge") == "hedge"
        self.hold_enabled = bool(getattr(bridge, "session_hold", True)) and self.hedging
        self.local = ClosureTracker()  # replays: their own history, never pruned against live ticks
        self.rates = load_rates()
        self.evidence = ev.market_evidence(self.source, self.mid, self.token)
        self.sess: Session | None = None
        self.state: ClosureState | None = None
        self.gap: ExpectedGap | None = None
        self.prev_closed: bool | None = None
        self.close_at: dt.datetime | None = None
        self.s_close: float | None = None
        self.s_close_source: str | None = None
        self.h_close = 0.0
        self.s_now: float | None = None
        self.last_regular_px: float | None = None
        self.last_closed_px: float | None = None
        self.stale_px: float | None = None    # the recorded price the trading day began on (a replay waits for a change)
        self.prev_px: float | None = None
        self.trading_day: dt.date | None = None
        self.fresh = False
        self.plan_id: str | None = None
        self.skip_gap: float | None = None
        self.plan_note: str | None = None
        self.user_cancelled = False
        self.gate_reported = False  # the EVIDENCE_GATE refusal was sent as an SSE event this closure
        self.seen: dict[str, tuple[str, int]] = {}
        self.last_gap: dict | None = None  # the latest active expected gap (kept after the open: the gap it expected)
        self.fills_since_close: list[tuple[float, float | None, str]] = []  # (signed short shares, px, source)
        self.timeline: list[dict] = []
        self.holds = 0
        self.seeded: set[float] = set()
        self.hedge_a: HedgeA | None = None
        self.hedge_a_error: str | None = None
        if hedge_a and self.hedging and hc is not None:
            g = self._rate_choice()
            try:
                self.hedge_a = HedgeA(hc, bridge, g[0], g[1])
            except Exception as e:  # the catalog / engine refused it: reported, never fatal
                self.hedge_a_error = f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------ helpers

    def _rate_choice(self) -> tuple[float, str]:
        from .gap import choose_rate, direction_sign
        r, own, _ = choose_rate(self.rates, self.source, self.mid, getattr(self.bridge.proposal, "ticker", None),
                                self.rate_token)
        dsign = direction_sign(self.bridge.direction)
        # The family's rate is per pp of the ADVERSE probability (the bridge's orientation). A positive oriented rate
        # costs the holder rate bp per adverse pp only when the research sign agrees with the bridge's direction;
        # a negative rate, or a direction the research contradicts, gives no leg (rate 0).
        if dsign is None or (own is not None and own.sign is not None and own.sign != dsign):
            return 0.0, r.label
        return max(0.0, r.rate_bp_per_pp), r.label

    @property
    def rate_token(self) -> str | None:
        """The token for the rate lookup: the market's own, else the studied market's token from the evidence file
        (gap_rates.json is keyed by slug and token, not by Polymarket id)."""
        return self.token or (self.evidence or {}).get("token_id")

    def tracker(self) -> ClosureTracker:
        return self.local if self.bridge.effective_source == "replay" else tracker_for(self.app)

    @property
    def broker_hold(self) -> bool:
        """The bridge's order broker takes orders only in the regular session (Webull paper refuses everything else
        with a 417): its equity algo must hold off-session whatever ``session_hold`` says. An opportunity bridge holds
        too when that broker also takes its option combos (``options_supported``, WEBULL_OPTIONS=1); with options in
        the simulator it trades at any hour. A replay sandbox is a sim."""
        try:
            b = self.bridge.order_broker() if hasattr(self.bridge, "order_broker") else None
        except Exception:
            return False
        if not bool(getattr(b, "regular_session_only", False)):
            return False
        return self.hedging or bool(getattr(b, "options_supported", False))

    @property
    def hold(self) -> bool:
        return (self.hold_enabled or self.broker_hold) and self.sess is not None and self.sess.closed

    def note(self, at: dt.datetime, event: str, detail: str | None = None, **extra) -> dict:
        row = {"at": _iso(at), "at_et": at.astimezone(ET).strftime("%a %Y-%m-%d %H:%M ET"), "event": event,
               "detail": detail, **extra}
        self.timeline.append(row)
        del self.timeline[:-TIMELINE_MAX]
        return row

    def pm_leg_shares(self) -> float:
        """Hedge A's PM leg in equity shares as COVERAGE (the shared target_coverage cap, hedge B's sizing). A
        simulated leg (no Polymarket trading account) is not coverage: it counts 0, so turning hedge A on never shrinks
        the real staged equity order. Its simulated equivalent is reported separately (``HedgeA.summary``)."""
        if self.hedge_a is None or self.hedge_a.simulated:
            return 0.0
        return self.hedge_a.equity_equiv_shares()

    # ------------------------------------------------------------------ the tick

    async def on_tick(self, t, oriented: dict, tick_builder=None) -> tuple[dict | None, list[tuple[str, dict]]]:
        """(the tick event's ``closed`` block, extra SSE events). A tick with no usable time leaves the mode idle."""
        out: list[tuple[str, dict]] = []
        at = tick_time(self.bridge, self.app, t)
        if at is None:
            return None, out
        sess = session_at(at)
        self.sess = sess
        closed = sess.closed
        tracker = self.tracker()
        tracker.observe(self.key, at, t.p)
        px = _pos(t.fields.get("under_px")) if getattr(t, "fields", None) else None
        if px is not None:
            self.s_now = px

        if closed and self.prev_closed is not True:  # a closure begins (or the bridge started inside one)
            self.close_at = sess.last_close
            self.rates = load_rates()
            self.evidence = ev.market_evidence(self.source, self.mid, self.token)
            self.plan_id, self.skip_gap, self.plan_note, self.user_cancelled = None, None, None, False
            self.gate_reported = False
            self.h_close = float(getattr(self.bridge, "broker_hedge", 0.0) or 0.0)
            self.fills_since_close = []
            if self.prev_closed is False and self.last_regular_px is not None:
                self.s_close, self.s_close_source = self.last_regular_px, "last regular-session tick"
            else:
                self.s_close, self.s_close_source = px, "first tick after the close (the bridge started closed)"
            row = self.note(at, "close", f"{sess.label}; PM YES {t.p:.3f}; equity "
                                         f"{self.s_close if self.s_close is not None else 'unknown'}",
                            phase=sess.phase)
            out.append(("session", {"event": "close", "session": session_view(sess), "timeline": row}))
            await self._seed(tracker, sess)
        elif not closed and self.prev_closed is True:  # the regular session opens: handoff
            row = self.note(at, "open", "regular session open: the equity algo resumes; staged orders execute at a "
                                        "fresh price; hedge A (if any) unwinds its PM leg")
            out.append(("handoff", {"event": "open", "session": session_view(sess), "timeline": row}))
        if closed:
            if px is not None:
                self.last_closed_px = px
        elif px is not None:
            self.last_regular_px = px
        # Fresh-price rule for a replay's staged order (the engine's rule for equity fills): on a trading day, from
        # the pre-market on, a recorded price counts only once it has changed since the day began, so an order is
        # never filled at the stale close the closure ended on.
        trading = sess.phase in ("pre_market", "regular")
        day = sess.at.astimezone(ET).date()
        if trading and self.trading_day != day:
            self.trading_day, self.stale_px, self.fresh = day, self.prev_px, False
        if trading and px is not None and (self.stale_px is None or px != self.stale_px):
            self.fresh = True
        if px is not None:
            self.prev_px = px
        self.prev_closed = closed

        self.state = tracker.state(self.key, at)
        self.gap = expected_gap_for(self.state, self.source, self.mid, ticker=self.bridge.proposal.ticker,
                                    direction=self.bridge.direction, token_id=self.rate_token, rates=self.rates)
        if self.gap.active:
            self.last_gap = {**(gap_view(self.gap, self.evidence) or {}), "at": _iso(at)}

        if self.hedge_a is not None and tick_builder is not None:
            rts = getattr(t, "recorded_ts_ns", None) if self.bridge.effective_source == "replay" else None
            ts = int(rts) if rts is not None else int(t.ts_ns)
            now = ts if rts is not None else time.time_ns()
            rec = self.hedge_a.step(oriented, ts, now, getattr(t, "venue", 0), px, tick_builder)
            if rec is not None:
                # the timeline keeps the leg's opening and its unwind at the open; every fill is an SSE event
                if rec["reason"] == "handoff" or abs(rec["contracts"]) - rec["qty"] <= 1e-9:
                    self.note(at, "hedge_a", f"{rec['side']} {rec['qty']:g} adverse YES @ {rec['fill_px']:.3f} "
                                             f"({rec['reason']}; simulated estimate, now {rec['contracts']:g})")
                out.append(("hedge_a", {**rec, "summary": self.hedge_a.summary()}))

        if self.hedging and closed:
            ev_row = self._maybe_plan(at)
            if ev_row is not None:
                out.append(("staged", ev_row))
        if self.hedging:
            out += await self._step_staged(at)
        return self.view(), out

    async def _seed(self, tracker: ClosureTracker, sess: Session) -> None:
        """A live Polymarket bridge started inside a closure has no price at the close: seed the shared tracker once
        per closure from the CLOB history (as GET /closed/expected-gap does)."""
        if self.bridge.effective_source == "replay" or self.source != "polymarket":
            return
        close_ts = sess.last_close.timestamp()
        if close_ts in self.seeded or tracker.has_close_anchor(self.key, sess.at):
            return
        self.seeded.add(close_ts)
        from .router import polymarket_points, seed_from_history
        fetcher = getattr(self.app.state, "closed_history_fetcher", None) or polymarket_points
        try:
            await asyncio.wait_for(seed_from_history(tracker, self.key, self.source, self.token or self.mid, sess.at,
                                                     fetcher), SEED_TIMEOUT_S)
        except Exception:
            pass

    # ------------------------------------------------------------------ hedge B

    def _plan_order(self):
        if not self.plan_id:
            return None
        try:
            return staged.book_for(self.app).get(self.plan_id)
        except KeyError:
            return None

    def _adopt(self, at: dt.datetime) -> dict | None:
        """A pending plan for this proposal on this bridge's clock made elsewhere (``POST /staged/plan``), possibly
        already approved by the user: adopt it as this closure's plan instead of planning a new one, which would
        supersede (cancel) it and ask for approval again."""
        if self.sess is None:
            return None
        clock = "replay" if self.bridge.effective_source == "replay" else "wall"
        day = self.sess.next_open.astimezone(ET).date().isoformat()  # a plan for THIS closure's session only
        pend = [o for o in staged.book_for(self.app).list(proposal_id=self.bridge.proposal_id)
                if o.status in ("staged", "approved", "working") and o.clock == clock
                and o.bridge_id in (None, self.bridge.id) and o.session_date == day]
        if not pend:
            return None
        o = max(pend, key=lambda x: x.planned_at or "")
        self.plan_id, self.plan_note = o.id, None
        self.seen[o.id] = (o.status, len(o.decisions))
        row = self.note(at, "plan_adopted", f"existing staged sell {o.qty} {o.ticker} ({o.status}) for the "
                                            f"{o.session_target.replace('_', ' ')} adopted; no new plan",
                        staged_id=o.id)
        return {"event": "adopted", "order": o.model_dump(), "timeline": row}

    def _maybe_plan(self, at: dt.datetime) -> dict | None:
        """Plan (or re-plan an unapproved) staged order from the expected gap. Returns an SSE payload when a plan was
        made."""
        g, st = self.gap, self.state
        if g is None or st is None or not g.active or g.expected_gap_bp is None or st.move_pp is None:
            return None
        prop = next((p for p in self.app.state.store.list() if p.id == self.bridge.proposal_id), None)
        if prop is None or prop.status != "approved" or prop.family != "hedge":
            return None
        gap_bp = g.expected_gap_bp
        if self.plan_id is None:
            adopted = self._adopt(at)
            if adopted is not None:
                return adopted
        cur = self._plan_order()
        if cur is not None:
            if cur.reason == "USER_CANCELLED":
                self.user_cancelled = True
            if cur.status in ("staged", "approved", "working", "filled"):
                # one plan per closure: staged.on_tick resizes it with the gap (an unapproved plan both ways, an
                # approved one within its approval) and cancels it on a full revert
                return None
        if self.user_cancelled:
            return None
        if gap_bp > -staged.DEFAULT_MIN_GAP_BP:
            return None
        if self.skip_gap is not None and gap_bp > self.skip_gap - SKIP_RETRY_BP:
            return None
        from fastapi import HTTPException
        body = staged.PlanIn(bridge_id=self.bridge.id, pm_move_pp=max(-100.0, min(100.0, st.move_pp)),
                             pm_leg_equiv_shares=self.pm_leg_shares())
        try:
            o = staged.plan_for(self.app, body, self.app.state.store)
        except HTTPException as e:
            self.skip_gap, self.plan_note = gap_bp, str(e.detail)
            row = self.note(at, "plan_refused", str(e.detail))
            code = str(e.detail).split(":", 1)[0]
            # the evidence gate is reported once per closure as an SSE event (the timeline keeps every refusal)
            if code == "EVIDENCE_GATE" and not self.gate_reported:
                self.gate_reported = True
                return {"event": "refused", "reason": code, "detail": str(e.detail), "timeline": row,
                        "evidence": gap_view(g, self.evidence)}
            return None
        gv = gap_view(g, self.evidence) or {}
        o.estimate["validated"], o.estimate["evidence"] = gv.get("validated"), gv.get("evidence")
        o.estimate["status"] = gv.get("status")
        o.label = (f"{ev.HEDGE_B_LABEL} Expected gap: {gv.get('status')}."
                   + (" OVERRIDE: this market's signal has not passed its out-of-sample test; staged only because "
                      "act_on_unvalidated is set." if o.evidence_gate == "override" else "")
                   + (f" {ev.HEDGE_B_PREMARKET_NOTE}" if o.session_target == "pre_market" else ""))
        if o.status == "skipped":
            self.skip_gap, self.plan_note = gap_bp, o.reason
            self.note(at, "plan_skipped", f"{o.reason}: gap {gap_bp:.1f} bp", staged_id=o.id)
            return None
        self.plan_id, self.plan_note = o.id, None
        self.seen[o.id] = (o.status, len(o.decisions))
        row = self.note(at, "plan", f"staged sell {o.qty} {o.ticker} for the {o.session_target.replace('_', ' ')} "
                                    f"({o.execute_at}); expected gap {gap_bp:.1f} bp, {gv.get('status')}; awaiting "
                                    "approval", staged_id=o.id)
        return {"event": "planned", "order": o.model_dump(), "timeline": row}

    async def _step_staged(self, at: dt.datetime) -> list[tuple[str, dict]]:
        replay = self.bridge.effective_source == "replay"
        st = self.state
        move = st.move_pp if (replay and st is not None) else None
        trading = self.sess is not None and self.sess.phase in ("pre_market", "regular")
        ref = (self.s_now if (self.fresh and trading) else None) if replay else None
        try:
            await staged.on_tick(self.app, self.bridge, at if replay else None, move, ref)
        except Exception as e:
            return [("error", {"message": f"staged order step failed: {type(e).__name__}", "source": "staged"})]
        out = []
        for o in staged.book_for(self.app).list(bridge_id=self.bridge.id):
            sig = (o.status, len(o.decisions))
            prev = self.seen.get(o.id)
            if prev == sig:
                continue
            self.seen[o.id] = sig
            if prev is None and o.status == "skipped":
                continue
            detail = f"{o.reason}: {o.decisions[-1].detail if o.decisions else ''}".strip()
            row = None
            if prev is None or prev[0] != o.status:  # the timeline keeps status changes; resizes are SSE events only
                row = self.note(at, f"staged_{o.status}", detail, staged_id=o.id, qty=o.qty,
                                filled_qty=o.filled_qty, fill_px=o.fill_px)
            out.append(("staged", {"event": o.status if row else "update", "reason": o.reason, "detail": detail,
                                   "order": o.model_dump(), "timeline": row}))
        return out

    # ------------------------------------------------------------------ views

    def on_staged_fill(self, signed_short: float, px: float | None) -> None:
        if self.hedge_a is not None and px:
            self.hedge_a.on_equity_fill(-signed_short, px)
        self.on_equity_fill(signed_short, px, "staged")

    def on_equity_fill(self, signed_short: float, px: float | None, source: str = "algo") -> None:
        """Every equity fill of this bridge (its algo's and its staged orders'), for the closure P&L."""
        if self.close_at is not None and signed_short:
            self.fills_since_close.append((float(signed_short), _pos(px), source))

    def pnl(self) -> dict | None:
        """P&L since the closure began, marked at the latest equity price (replay: recorded; live: the quote)."""
        if self.close_at is None or self.s_close is None or self.s_now is None:
            return None
        d = self.s_now - self.s_close
        shares = float(self.bridge.proposal.shares_held or 0.0)
        unhedged = shares * d
        carried = -self.h_close * d
        by = {"staged": [0.0, 0.0], "algo": [0.0, 0.0]}  # source -> [signed short shares, USD]
        unpriced = 0
        for q, px, src in self.fills_since_close:
            if px is None:
                unpriced += 1
                continue
            row = by.setdefault(src, [0.0, 0.0])
            row[0] += q
            row[1] += q * (px - self.s_now)  # a short sold at px, marked at the latest price
        ha = self.hedge_a.pnl() if self.hedge_a is not None else None
        staged_pnl, algo_pnl = by["staged"][1], by["algo"][1]
        hedges = carried + staged_pnl + algo_pnl + (ha or 0.0)
        return {"since": _iso(self.close_at), "s_close": self.s_close, "s_close_source": self.s_close_source,
                "s_now": self.s_now, "shares_held": shares, "unhedged_usd": unhedged,
                "carried_hedge_shares": self.h_close, "carried_hedge_usd": carried,
                "staged_short_shares": by["staged"][0], "staged_usd": staged_pnl,
                "algo_short_shares": by["algo"][0], "algo_usd": algo_pnl, "unpriced_fills": unpriced,
                "hedge_a_usd": ha, "hedge_a_estimate": self.hedge_a is not None,
                "hedged_usd": unhedged + hedges, "vs_no_hedge_usd": hedges,
                "price_source": "recorded" if self.bridge.effective_source == "replay" else "live quote",
                "price_note": ("replay: every leg is valued at the recorded prices of the replayed time (the "
                               "bridge's own fills may show today's quote; that is a labelled replay artifact, not "
                               "used here)") if self.bridge.effective_source == "replay" else None,
                "note": "Hedge B executes after the gap: it limits the move after the open, it cannot recover the gap "
                        "itself. Hedge A's leg is a simulated estimate."}

    def view(self) -> dict:
        """The compact block attached to every tick event."""
        return {"session": session_view(self.sess), "closure": closure_view(self.state),
                "expected_gap": gap_view(self.gap, self.evidence), "hold": self.hold}

    def summary(self) -> dict:
        sess = self.sess
        if sess is None and self.bridge.effective_source != "replay":
            try:
                sess = session_at(live_now(self.app))
            except ValueError:
                sess = None
        plan = self._plan_order()
        orders = staged.book_for(self.app).list(bridge_id=self.bridge.id)
        return {"session": session_view(sess), "closure": closure_view(self.state),
                "expected_gap": gap_view(self.gap, self.evidence),
                "closed_mode": {"hold": self.hold, "session_hold": self.hold_enabled,
                                "broker_hold": self.broker_hold, "holds": self.holds,
                                "evidence": self.evidence, "labels": ev.hedge_evidence(),
                                "plan": plan.model_dump() if plan is not None else None, "plan_note": self.plan_note,
                                "staged_orders": [{"id": o.id, "status": o.status, "qty": o.qty,
                                                   "filled_qty": o.filled_qty, "fill_px": o.fill_px,
                                                   "session_target": o.session_target, "execute_at": o.execute_at,
                                                   "reason": o.reason} for o in orders],
                                "pnl": self.pnl(), "last_expected_gap": self.last_gap,
                                "timeline": list(self.timeline[-50:]),
                                "hedge_a_error": self.hedge_a_error},
                "hedge_a": self.hedge_a.summary() if self.hedge_a is not None else
                {"enabled": False, "label": ev.HEDGE_A_LABEL, "equity_equiv_shares": 0.0,
                 "sim_equity_equiv_shares": 0.0, "counts_toward_cap": False}}
