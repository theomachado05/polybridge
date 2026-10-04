"""Deterministic contractual, causal execution and collateral primitives.

These are tested on synthetic cases. No historical execution is inferred from a
midpoint, outcome label or public trade print. A full dataset adapter is deliberately
not fabricated when the required observations do not exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

import numpy as np

from . import config as cfg


class EvidenceError(ValueError):
    """A required observation is absent, noncausal or invalid."""


def payoff_floor(payoffs: Iterable[Iterable[float]], weights=None) -> float:
    """Minimum contractual payout across ALL certified states, including refunds."""
    a = np.asarray(list(payoffs), dtype=float)
    if a.ndim != 2 or not a.shape[0] or not a.shape[1]:
        raise EvidenceError("empty or malformed terminal state matrix")
    if not np.isfinite(a).all() or (a < 0).any() or (a > 1).any():
        raise EvidenceError("invalid payout per $1 contract")
    w = np.ones(a.shape[1]) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != (a.shape[1],) or not np.isfinite(w).all() or (w < 0).any():
        raise EvidenceError("invalid nonnegative basket weights")
    return float(np.min(a @ w))


def implication_payoffs() -> tuple[tuple[int, int], ...]:
    """A=>B, buying YES(B), NO(A): states (A,B)=(0,0),(0,1),(1,1)."""
    return ((0, 1), (1, 1), (1, 0))


@dataclass(frozen=True)
class Proof:
    basket_id: str
    family: str
    tokens: tuple[str, ...]
    captured_at: float
    complete_rules: tuple[str, ...]
    source_refs: tuple[str, ...]
    payouts: tuple[tuple[float, ...], ...]
    completeness_certificate: str
    exceptional_states_reviewed: bool

    def validate(self, at: float) -> float:
        if not self.basket_id or not self.family or not self.tokens:
            raise EvidenceError("missing basket identity")
        if not math.isfinite(self.captured_at) or self.captured_at > at:
            raise EvidenceError("contract rules not observed before entry")
        if len(set(self.tokens)) != len(self.tokens):
            raise EvidenceError("duplicate token in basket")
        if len(self.complete_rules) != len(self.tokens) or not all(self.complete_rules):
            raise EvidenceError("full contract rules missing")
        if len(self.source_refs) != len(self.tokens) or not all(self.source_refs):
            raise EvidenceError("contract source references missing")
        if not self.completeness_certificate or not self.exceptional_states_reviewed:
            raise EvidenceError("state completeness/refund review missing")
        if any(len(row) != len(self.tokens) for row in self.payouts):
            raise EvidenceError("payoff matrix does not match contract legs")
        floor = payoff_floor(self.payouts)
        if floor < 1 - 1e-12:
            raise EvidenceError("basket payoff floor below $1")
        return floor


@dataclass(frozen=True)
class FeeTerms:
    coefficient: float
    exponent: float
    rounding_quantum: float
    rounding: str
    captured_at: float
    source: str

    def validate(self, at: float):
        if not self.source or not math.isfinite(self.captured_at) or self.captured_at > at:
            raise EvidenceError("missing contemporaneous fee terms")
        if not all(math.isfinite(x) for x in
                   (self.coefficient, self.exponent, self.rounding_quantum)):
            raise EvidenceError("nonfinite fee term")
        if self.coefficient < 0 or self.exponent <= 0 or self.rounding_quantum <= 0:
            raise EvidenceError("invalid fee term")
        if self.rounding not in ("nearest", "up"):
            raise EvidenceError("unknown fee rounding rule")

    def charge(self, matched: list[tuple[float, float]]) -> float:
        # Aggregate raw matched-price fees, then round once per modeled order.
        raw = sum(q * self.coefficient * (p * (1 - p)) ** self.exponent for p, q in matched)
        z = raw / self.rounding_quantum
        units = math.ceil(z - 1e-12) if self.rounding == "up" else math.floor(z + .5)
        return units * self.rounding_quantum


@dataclass(frozen=True)
class Book:
    token: str
    venue: str
    received_at: float
    venue_at: float
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    tick: float
    min_size: float
    fees: FeeTerms
    accepting_orders: bool = True

    def validate(self, at: float):
        if not self.token or not self.venue or not self.accepting_orders:
            raise EvidenceError("missing identity or market closed to orders")
        if not math.isfinite(at) or not all(math.isfinite(x) for x in
                                         (self.received_at, self.venue_at)):
            raise EvidenceError("invalid book timestamp")
        if self.received_at > at or at - self.received_at > cfg.MAX_BOOK_AGE_S:
            raise EvidenceError("future or stale local book")
        lag = self.received_at - self.venue_at
        if lag < 0 or lag > cfg.MAX_VENUE_LAG_S:
            raise EvidenceError("future or stale venue timestamp")
        if not self.bids or not self.asks:
            raise EvidenceError("one-sided or empty book")
        if not math.isfinite(self.tick) or self.tick <= 0 or not math.isfinite(self.min_size) or self.min_size <= 0:
            raise EvidenceError("tick/minimum order size absent")
        for levels, ascending in ((self.asks, True), (self.bids, False)):
            last = None
            for p, q in levels:
                if not math.isfinite(p) or not math.isfinite(q) or not 0 <= p <= 1 or q <= 0:
                    raise EvidenceError("malformed quote level")
                if abs(p / self.tick - round(p / self.tick)) > 1e-7:
                    raise EvidenceError("quote not on contract tick")
                if last is not None and ((ascending and p <= last) or (not ascending and p >= last)):
                    raise EvidenceError("unsorted or duplicate quote levels")
                last = p
        if self.bids[0][0] > self.asks[0][0]:
            raise EvidenceError("crossed book")
        self.fees.validate(at)


def synchronized(books: list[Book], at: float):
    if not books or len({b.token for b in books}) != len(books):
        raise EvidenceError("empty basket or duplicate leg")
    for b in books:
        b.validate(at)
    if max(b.received_at for b in books) - min(b.received_at for b in books) > cfg.MAX_LEG_SKEW_S:
        raise EvidenceError("cross-leg clock skew")


@dataclass(frozen=True)
class Fill:
    token: str
    venue: str
    at: float
    side: str
    qty: float
    vwap: float
    cash_delta: float
    fee: float
    spread_cost: float
    tick_cost: float


def walk(book: Book, qty: float, side: str, cost_mult: float, partial: bool = False) -> Fill:
    """10% of each displayed level; FOK entries, partial liquidation if requested."""
    book.validate(book.received_at)
    if cost_mult not in cfg.COST_MULTIPLIERS:
        raise EvidenceError("unregistered cost multiplier")
    if side not in ("BUY", "SELL") or not math.isfinite(qty) or qty <= 0:
        raise EvidenceError("invalid order")
    if qty < book.min_size - 1e-12:
        raise EvidenceError("order below venue minimum")
    remaining, matched = qty, []
    levels = book.asks if side == "BUY" else book.bids
    for p, q in levels:
        take = min(remaining, q * cfg.LEVEL_PARTICIPATION)
        if take > 1e-12:
            matched.append((p, take))
            remaining -= take
        if remaining <= 1e-12:
            break
    if remaining > 1e-9 and not partial:
        raise EvidenceError("FOK fails: participation-limited depth is insufficient")
    done = qty - remaining
    if done < book.min_size - 1e-12:
        raise EvidenceError("executable quantity below venue minimum")
    notional = sum(p * q for p, q in matched)
    mid = .5 * (book.asks[0][0] + book.bids[0][0])
    spread = abs(notional - done * mid)
    fee = cost_mult * book.fees.charge(matched)
    adverse_tick = cost_mult * done * book.tick
    extra_spread = (cost_mult - 1) * spread
    cash = -(notional + extra_spread + fee + adverse_tick) if side == "BUY" else \
        notional - extra_spread - fee - adverse_tick
    return Fill(book.token, book.venue, book.received_at, side, done, notional / done,
                cash, fee, cost_mult * spread, adverse_tick)


def first_execution_book(books: Iterable[Book], token: str, submitted_at: float) -> Book:
    """Choose the first causal response, never a later cheaper/more liquid one."""
    lo = submitted_at + cfg.LEG_LATENCY_S
    hi = submitted_at + cfg.MAX_EXECUTION_WAIT_S
    candidates = sorted((b for b in books if b.token == token and lo <= b.received_at <= hi),
                        key=lambda b: b.received_at)
    if not candidates:
        raise EvidenceError("missing execution-time book in registered latency window")
    book = candidates[0]
    book.validate(book.received_at)
    return book


def funding(collateral: float, start: float, end: float, cost_mult: float) -> float:
    if collateral < 0 or end < start or not all(math.isfinite(v) for v in (collateral, start, end)):
        raise EvidenceError("invalid collateral lock interval")
    if cost_mult not in cfg.COST_MULTIPLIERS:
        raise EvidenceError("unregistered funding scenario")
    return collateral * cfg.FUNDING_RATE * cost_mult * (end - start) / (cfg.ANNUAL_DAYS * 86400)


def basket_signal(proof: Proof, first: list[Book], second: list[Book], first_at: float,
                  second_at: float, deadline: float, qty: float, cost_mult: float) -> float:
    floor = proof.validate(first_at)
    if second_at - first_at < cfg.CONFIRM_MIN_GAP_S:
        raise EvidenceError("signal not confirmed at a subsequent observation")
    if deadline < second_at or deadline - second_at > cfg.MAX_A_DEADLINE_DAYS * 86400:
        raise EvidenceError("deadline outside frozen entry horizon")
    projected_release = deadline + cfg.PROJECTED_RELEASE_DELAY_DAYS * 86400
    net_edges = []
    for books, at in ((first, first_at), (second, second_at)):
        synchronized(books, at)
        if tuple(b.token for b in books) != proof.tokens:
            raise EvidenceError("book legs differ from certified manifest order")
        cost = -sum(walk(b, qty, "BUY", cost_mult).cash_delta for b in books)
        carry = funding(cost, at, projected_release, cost_mult)
        net_edges.append(floor - (cost + carry) / qty)
    if min(net_edges) < cfg.MIN_NET_EDGE - 1e-12:
        raise EvidenceError("net edge below frozen threshold at one confirmation")
    return net_edges[-1]


@dataclass(frozen=True)
class SourceObservation:
    released_at: float | None
    first_observed_at: float | None
    captured_rules_at: float
    official_source: str
    release_content_hash: str
    winner_token: str | None
    mechanically_unambiguous: bool

    def entry_at(self) -> float:
        if self.released_at is None or self.first_observed_at is None or \
                not all(math.isfinite(v) for v in (self.released_at, self.first_observed_at)):
            raise EvidenceError("official publication/first-observed timestamps missing")
        if self.first_observed_at < self.released_at:
            raise EvidenceError("source observed before it was released")
        if not math.isfinite(self.captured_rules_at) or self.captured_rules_at > self.first_observed_at:
            raise EvidenceError("source rule not captured before source observation")
        if not self.official_source or not self.release_content_hash or not self.winner_token:
            raise EvidenceError("official source/content/side provenance missing")
        if not self.mechanically_unambiguous:
            raise EvidenceError("ambiguous source: eligibility failure retained in audit")
        return max(self.released_at, self.first_observed_at) + cfg.SOURCE_ENTRY_DELAY_S


def carry_signal(source: SourceObservation, book: Book, qty: float, cost_mult: float) -> float:
    at = source.entry_at()
    book.validate(at)
    if book.token != source.winner_token:
        raise EvidenceError("winner side was not derived from archived source")
    fill = walk(book, qty, "BUY", cost_mult)
    cost = -fill.cash_delta
    edge = 1 - (cost + funding(cost, at, at + cfg.PROJECTED_RELEASE_DELAY_DAYS * 86400, cost_mult)) / qty
    if edge < cfg.MIN_NET_EDGE - 1e-12:
        raise EvidenceError("publication carry does not beat costs and projected lockup")
    return edge


@dataclass
class Lot:
    lot_id: str
    family: str
    token: str
    venue: str
    qty: float
    collateral: float
    entered_at: float
    last_funding_at: float


@dataclass
class Portfolio:
    cost_mult: float
    cash: dict[str, float]
    lots: dict[str, Lot] = field(default_factory=dict)
    financing: float = 0.0
    turnover: float = 0.0

    @property
    def locked(self) -> float:
        return sum(l.collateral for l in self.lots.values())

    def advance(self, at: float):
        charges = [(lot, funding(lot.collateral, lot.last_funding_at, at, self.cost_mult))
                   for lot in self.lots.values()]
        for lot, charge in charges:
            self.cash[lot.venue] -= charge
            self.financing += charge
            lot.last_funding_at = at

    def buy(self, fill: Fill, lot_id: str, family: str):
        if fill.side != "BUY" or lot_id in self.lots or not family:
            raise EvidenceError("invalid or duplicate position")
        self.advance(fill.at)
        cost = -fill.cash_delta
        family_locked = sum(l.collateral for l in self.lots.values() if l.family == family)
        if cost > self.cash.get(fill.venue, 0) + 1e-12:
            raise EvidenceError("insufficient venue cash; unredeemed winners cannot fund entry")
        if self.locked + cost > cfg.CAPITAL * cfg.MAX_LOCKED_FRACTION + 1e-12:
            raise EvidenceError("portfolio collateral limit exceeded")
        if family_locked + cost > cfg.CAPITAL * cfg.MAX_FAMILY_FRACTION + 1e-12:
            raise EvidenceError("family collateral limit exceeded")
        self.cash[fill.venue] -= cost
        self.lots[lot_id] = Lot(lot_id, family, fill.token, fill.venue, fill.qty, cost, fill.at, fill.at)
        self.turnover += fill.qty * fill.vwap

    def sell(self, fill: Fill, lot_id: str):
        if lot_id not in self.lots or fill.side != "SELL":
            raise EvidenceError("sell without position")
        lot = self.lots[lot_id]
        if fill.token != lot.token or fill.venue != lot.venue or fill.qty > lot.qty + 1e-9:
            raise EvidenceError("sell mismatch/short position")
        self.advance(fill.at)
        fraction = fill.qty / lot.qty
        self.cash[fill.venue] += fill.cash_delta
        self.turnover += fill.qty * fill.vwap
        lot.collateral *= 1 - fraction
        lot.qty -= fill.qty
        if lot.qty <= 1e-9:
            del self.lots[lot_id]

    def redeem(self, lot_id: str, at: float, observed_release_at: float,
               payout_per_share: float, redemption_cost: float):
        if lot_id not in self.lots:
            raise EvidenceError("redemption without position")
        if not all(math.isfinite(v) for v in (at, observed_release_at, payout_per_share, redemption_cost)) or \
                at < observed_release_at or not 0 <= payout_per_share <= 1 or redemption_cost < 0:
            raise EvidenceError("unreleased collateral or invalid redemption cash flow")
        self.advance(at)
        lot = self.lots.pop(lot_id)
        self.cash[lot.venue] += lot.qty * payout_per_share - redemption_cost

    def equity(self, at: float, liquidation_books: dict[str, Book]) -> float:
        self.advance(at)
        liquidation = 0.0
        for lot in self.lots.values():
            book = liquidation_books.get(lot.token)
            if book is None:
                raise EvidenceError("missing daily liquidation mark")
            book.validate(at)
            if book.venue != lot.venue:
                raise EvidenceError("mark from a different venue")
            liquidation += walk(book, lot.qty, "SELL", self.cost_mult).cash_delta
        return sum(self.cash.values()) + liquidation


def sequential_entry(proof: Proof, streams: list[Book], at: float, qty: float,
                     cost_mult: float, portfolio: Portfolio, deadline: float) -> dict:
    """Exercise deterministic FOK/abort/unwind mechanics on causal book streams.

    Caller must pass a previously approved basket_signal. This primitive does
    not certify the whole strategy: it stress-tests the key legging cash flows.
    Missing observations raise EvidenceError rather than becoming an assumed fill.
    """
    floor = proof.validate(at)
    if not 0 < qty <= cfg.TARGET_UNITS or not at <= deadline <= at + cfg.MAX_A_DEADLINE_DAYS * 86400:
        raise EvidenceError("quantity/deadline outside frozen rule")
    projected_release = deadline + cfg.PROJECTED_RELEASE_DELAY_DAYS * 86400
    submitted, bought = at, []
    for i, token in enumerate(proof.tokens):
        book = first_execution_book(streams, token, submitted)
        try:
            fill = walk(book, qty, "BUY", cost_mult)
            # Recheck the economics of the whole proposed basket at this leg's
            # fill time. Future quotes never enter the remaining-leg estimate.
            prospective = [fill]
            for remaining_token in proof.tokens[i + 1:]:
                causal = [b for b in streams if b.token == remaining_token and b.received_at <= book.received_at]
                if not causal:
                    raise EvidenceError("missing causal remaining-leg quote for economics recheck")
                last = max(causal, key=lambda b: b.received_at)
                last.validate(book.received_at)
                prospective.append(walk(last, qty, "BUY", cost_mult))
            committed = sum(portfolio.lots[k].collateral for k in bought)
            total_cost = committed - sum(f.cash_delta for f in prospective)
            if floor - (total_cost + funding(total_cost, book.received_at, projected_release, cost_mult)) / qty < cfg.MIN_NET_EDGE:
                raise EvidenceError("later-leg economics no longer meet frozen edge")
            venue_need = {}
            for planned in prospective:
                venue_need[planned.venue] = venue_need.get(planned.venue, 0) - planned.cash_delta
            if any(cost > portfolio.cash.get(venue, 0) for venue, cost in venue_need.items()):
                raise EvidenceError("remaining basket exceeds venue cash")
            family_locked = sum(l.collateral for l in portfolio.lots.values() if l.family == proof.family)
            new_cost = -sum(f.cash_delta for f in prospective)
            if portfolio.locked + new_cost > cfg.CAPITAL * cfg.MAX_LOCKED_FRACTION or \
                    family_locked + new_cost > cfg.CAPITAL * cfg.MAX_FAMILY_FRACTION:
                raise EvidenceError("remaining basket exceeds collateral limits")
            lot_id = f"{proof.basket_id}:{i}"
            portfolio.buy(fill, lot_id, proof.family)
        except EvidenceError as exc:
            unwinds, residual = [], []
            for lot_id in bought:
                lot = portfolio.lots[lot_id]
                unwind_book = first_execution_book(streams, lot.token, book.received_at)
                try:
                    exit_fill = walk(unwind_book, lot.qty, "SELL", cost_mult, partial=True)
                    portfolio.sell(exit_fill, lot_id)
                    unwinds.append(exit_fill)
                except EvidenceError:
                    # Insufficient displayed bid/minimum-size means residual
                    # exposure, not a free unwind; daily marks remain mandatory.
                    residual.append(lot_id)
                if lot_id in portfolio.lots and lot_id not in residual:
                    residual.append(lot_id)
            return {"status": "legging_failure", "reason": str(exc),
                    "filled_legs": len(bought), "unwinds": unwinds, "residual_lots": residual}
        bought.append(lot_id)
        submitted = fill.at
    return {"status": "complete_simulated", "filled_legs": len(bought),
            "unwinds": [], "residual_lots": bought}


def daily_metrics(times: Iterable[float], equities: Iterable[float], initial_equity: float,
                  entry_dates: int) -> dict:
    t, e = np.asarray(list(times), float), np.asarray(list(equities), float)
    if len(t) != len(e) or len(t) < 2 or not np.isfinite(t).all() or not np.isfinite(e).all():
        raise EvidenceError("insufficient or invalid daily equity observations")
    if np.any(np.diff(t) != 86400) or np.any(np.mod(t, 86400) != 0):
        raise EvidenceError("daily marks must be contiguous 00:00 UTC calendar days")
    if initial_equity <= 0 or (e <= 0).any():
        raise EvidenceError("invalid or bankrupt equity path")
    r = np.diff(np.r_[initial_equity, e]) / np.r_[initial_equity, e[:-1]]
    sd = np.std(r, ddof=1)
    sharpe = float(np.mean(r) / sd * np.sqrt(cfg.ANNUAL_DAYS)) if sd > 0 else float("nan")
    peak = np.maximum.accumulate(np.r_[initial_equity, e])[1:]
    drawdown = (peak - e) / peak
    months = t.astype("datetime64[s]").astype("datetime64[M]").astype(str)
    returns_month = {m: float(np.prod(1 + r[months == m]) - 1) for m in set(months)}
    rng = np.random.default_rng(cfg.BOOT_SEED)
    pick = rng.integers(0, len(r), size=(cfg.BOOT_DRAWS, len(r)))
    boot_means = r[pick].mean(axis=1)
    ci = np.quantile(boot_means, [.025, .975])
    boot_sd = r[pick].std(axis=1, ddof=1)
    boot_sharpe = np.divide(boot_means * np.sqrt(cfg.ANNUAL_DAYS), boot_sd,
                            out=np.full(cfg.BOOT_DRAWS, np.nan), where=boot_sd > 0)
    finite_sharpe = boot_sharpe[np.isfinite(boot_sharpe)]
    sci = np.quantile(finite_sharpe, [.025, .975]) if len(finite_sharpe) >= .95 * cfg.BOOT_DRAWS else [np.nan, np.nan]
    sample_ok = len(e) >= cfg.MIN_OOS_DAILY_OBS and entry_dates >= cfg.MIN_OOS_ENTRY_DATES
    return {"pnl": float(e[-1] - initial_equity), "sharpe": sharpe,
            "daily_observations": len(e), "independent_entry_dates": entry_dates,
            "max_drawdown": float(np.max(drawdown)), "worst_month": min(returns_month.values()),
            "mean_daily_ci_low": float(ci[0]), "mean_daily_ci_high": float(ci[1]),
            "sharpe_ci_low": float(sci[0]), "sharpe_ci_high": float(sci[1]),
            "sample_gate": sample_ok, "bug_audit_required": bool(sharpe > 3),
            "numerical_gate": bool(sample_ok and sharpe >= cfg.TARGET_SHARPE and ci[0] > 0
                                   and e[-1] > initial_equity)}
