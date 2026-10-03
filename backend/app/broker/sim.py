"""SimBroker: a deterministic simulated account, persisted to a JSON file.

Fills
  equity      reference price (supplied, else the Massive last price) +/- half-spread, plus a per-share fee
  option      Massive option quote mid +/- half the quoted spread, plus a per-contract fee (100 shares per contract)
  prediction  the supplied prediction-market book price for the side taken (no extra spread), plus a fee
Short selling is allowed (hedges are short). Buying power is cash minus 150% of the short market value
(the proceeds stay locked as collateral plus 50% extra); an order that would push buying power below zero
is rejected, and so is any order that has no price. Everything is a pure function of the orders and the
reference prices: no randomness, no clock in the maths."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import MULTIPLIER, Account, Order, OrderRequest, Position, BrokerError, now_iso
from .quotes import NullQuotes, QuoteProvider

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".sim_account.json"
START_CASH = 1_000_000.0
MAX_ORDERS = 2000
SHORT_COLLATERAL = 1.5  # locked per $1 of short market value (proceeds + 50%)
EPS = 1e-9


@dataclass(frozen=True)
class Fees:
    equity_per_share: float = 0.005
    option_per_contract: float = 0.65
    prediction_per_contract: float = 0.0
    equity_half_spread_bps: float = 1.0  # when the price source has no bid/ask
    option_half_spread_pct: float = 0.02  # when an option price has no bid/ask


def _key(asset: str, symbol: str) -> str:
    return f"{asset}|{symbol}"


def _r(x: float) -> float:
    return round(x, 6)


class SimBroker:
    name = "sim"

    def __init__(self, path: Path | str | None = DEFAULT_PATH, quotes: QuoteProvider | None = None,
                 starting_cash: float = START_CASH, fees: Fees | None = None,
                 clock: Callable[[], str] = now_iso, order_note: str | None = None) -> None:
        self.path = Path(path) if path else None
        self.quotes: QuoteProvider = quotes or NullQuotes()
        self.fees = fees or Fees()
        self._clock = clock
        self.order_note = order_note  # label stamped on every order (e.g. why it is simulated)
        self._lock = asyncio.Lock()
        self._reset_state(starting_cash)
        self._load()

    # ---- state ------------------------------------------------------------------------------------
    def _reset_state(self, starting_cash: float) -> None:
        self.starting_cash = float(starting_cash)
        self.cash = float(starting_cash)
        self.seq = 0
        self.realized = 0.0
        self.fees_paid = 0.0
        self.pos: dict[str, dict] = {}
        self._orders: list[Order] = []
        self._refs: dict[str, float | None] = {}  # order id -> ref_px, for resting limit orders

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            s = json.loads(self.path.read_text())
            self.starting_cash, self.cash = float(s["starting_cash"]), float(s["cash"])
            self.seq, self.realized, self.fees_paid = int(s["seq"]), float(s["realized_pnl"]), float(s["fees_paid"])
            self.pos = {k: dict(v) for k, v in s["positions"].items()}
            self._orders = [Order(**o) for o in s["orders"]]
            self._refs = {k: v for k, v in s.get("refs", {}).items()}
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("sim account file unreadable (%s); starting from a fresh account", type(e).__name__)
            self._reset_state(self.starting_cash)

    def _save(self) -> None:
        if self.path is None:
            return
        state = {"version": 1, "starting_cash": self.starting_cash, "cash": self.cash, "seq": self.seq,
                 "realized_pnl": self.realized, "fees_paid": self.fees_paid, "positions": self.pos,
                 "orders": [o.model_dump() for o in self._orders], "refs": self._refs}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".sim_account.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.replace(tmp, self.path)
        except OSError as e:  # the in-memory account stays correct; only persistence is lost
            log.warning("could not persist the sim account: %s", e)

    # ---- maths ------------------------------------------------------------------------------------
    @staticmethod
    def _short_value(pos: dict[str, dict]) -> float:
        return sum(-p["qty"] * (p["mark_px"] or p["avg_px"]) * p["mult"] for p in pos.values() if p["qty"] < 0)

    @classmethod
    def _buying_power(cls, cash: float, pos: dict[str, dict]) -> float:
        return cash - SHORT_COLLATERAL * cls._short_value(pos)

    @staticmethod
    def _equity(cash: float, pos: dict[str, dict]) -> float:
        return cash + sum(p["qty"] * (p["mark_px"] or p["avg_px"]) * p["mult"] for p in pos.values())

    def _fee(self, asset: str, qty: float) -> float:
        per = {"equity": self.fees.equity_per_share, "option": self.fees.option_per_contract,
               "prediction": self.fees.prediction_per_contract}[asset]
        return _r(per * qty)

    @staticmethod
    def _settle(cash: float, pos: dict[str, dict], asset: str, symbol: str, side: str, qty: float,
                fill_px: float, mid: float, fee: float) -> tuple[float, float]:
        """Apply a fill to (cash, pos) in place; returns (new cash, realized P&L of the closing part)."""
        mult = MULTIPLIER[asset]
        signed = qty if side == "buy" else -qty
        cash += -signed * fill_px * mult - fee
        k, realized = _key(asset, symbol), 0.0
        p = pos.get(k)
        if p is None:
            pos[k] = {"symbol": symbol, "asset": asset, "qty": signed, "avg_px": fill_px, "mark_px": mid, "mult": mult}
            return cash, realized
        q = p["qty"]
        if q * signed > 0:  # adding to the same direction: weighted average cost
            p["avg_px"] = (abs(q) * p["avg_px"] + qty * fill_px) / (abs(q) + qty)
            p["qty"] = q + signed
        else:  # reducing or flipping
            closing = min(abs(q), qty)
            realized = (fill_px - p["avg_px"]) * closing * mult * (1 if q > 0 else -1)
            p["qty"] = q + signed
            if abs(p["qty"]) < EPS:
                del pos[k]
                return cash, realized
            if p["qty"] * q < 0:  # flipped through zero: the remainder opens at the fill price
                p["avg_px"] = fill_px
        p["mark_px"] = mid
        return cash, realized

    # ---- pricing ----------------------------------------------------------------------------------
    async def _price(self, req: OrderRequest) -> tuple[float, float, str] | str:
        """(mid, half_spread, source) or a reject reason."""
        a = req.asset
        if a == "prediction":
            # limit_px is the user's bound, never the book price: without ref_px there is nothing to fill against
            return ((req.ref_px, 0.0, "supplied_book_price") if req.ref_px
                    else "no_price: prediction legs need ref_px (the book price); limit_px is only a bound")
        if req.ref_px:
            mid, src, half = req.ref_px, "supplied", None
        else:
            q = await (self.quotes.equity(req.symbol) if a == "equity" else self.quotes.option(req.symbol))
            if q is None:
                return f"no_price: no Massive {'quote' if a == 'option' else 'last price'} for {req.symbol} and none supplied"
            mid, src, half = q.mid, q.source, q.half_spread
        if half is None:
            half = mid * (self.fees.equity_half_spread_bps / 1e4 if a == "equity" else self.fees.option_half_spread_pct)
        return mid, half, src

    @staticmethod
    def _fill_px(side: str, mid: float, half: float, asset: str) -> float:
        px = mid + half if side == "buy" else mid - half
        px = round(px, 4)
        if asset == "prediction":
            return min(max(px, 0.0001), 1.0)
        return max(px, 0.0001)

    @staticmethod
    def _marketable(typ: str, side: str, limit_px: float | None, fill_px: float) -> bool:
        if typ == "market":
            return True
        return limit_px >= fill_px if side == "buy" else limit_px <= fill_px

    # ---- execution --------------------------------------------------------------------------------
    def _try_fill(self, o: Order, ref_px: float | None, mid: float, half: float, source: str) -> bool:
        """Fill `o` (status open) at the given reference if marketable and affordable. Returns True if filled."""
        fill_px = self._fill_px(o.side, mid, half, o.asset)
        if not self._marketable(o.type, o.side, o.limit_px, fill_px):
            return False
        fee = self._fee(o.asset, o.qty)
        pre_bp = self._buying_power(self.cash, self.pos)
        pos2 = copy.deepcopy(self.pos)
        cash2, realized = self._settle(self.cash, pos2, o.asset, o.symbol, o.side, o.qty, fill_px, mid, fee)
        post_bp = self._buying_power(cash2, pos2)
        if post_bp < -EPS and post_bp < pre_bp - EPS:
            o.status, o.reject_reason = "rejected", "insufficient_buying_power"
            return False
        self.cash, self.pos = _r(cash2), pos2
        self.realized = _r(self.realized + realized)
        self.fees_paid = _r(self.fees_paid + fee)
        o.status, o.filled_qty, o.fill_px, o.fee = "filled", o.qty, fill_px, fee
        o.filled_at, o.price_source = self._clock(), source
        self._refs.pop(o.id, None)
        return True

    async def place_order(self, req: OrderRequest) -> Order:
        if (dup := self._by_client(req.client_order_id)) is not None:
            return dup
        priced = await self._price(req)
        async with self._lock:
            if (dup := self._by_client(req.client_order_id)) is not None:
                return dup
            self.seq += 1
            o = Order(id=f"sim-{self.seq:06d}", client_order_id=req.client_order_id, broker=self.name,
                      symbol=req.symbol, asset=req.asset, side=req.side, qty=req.qty, type=req.type,
                      limit_px=req.limit_px, status="open", created_at=self._clock(), tag=req.tag,
                      note=" | ".join(n for n in (req.note, self.order_note) if n) or None)
            self._orders.append(o)
            if isinstance(priced, str):
                o.status, o.reject_reason = "rejected", priced
            else:
                mid, half, src = priced
                o.price_source = src
                if self._try_fill(o, req.ref_px, mid, half, src):
                    self._sweep_symbol(o, mid, half, src)
                elif o.status == "open":
                    self._refs[o.id] = req.ref_px  # resting limit order
                    self._sweep_symbol(o, mid, half, src)
            if len(self._orders) > MAX_ORDERS:
                for old in self._orders[: len(self._orders) - MAX_ORDERS]:
                    self._refs.pop(old.id, None)
                self._orders = self._orders[-MAX_ORDERS:]
            self._save()
            return o.model_copy()

    def _sweep_symbol(self, just: Order, mid: float, half: float, src: str) -> None:
        """Resting limit orders in the same instrument get a chance to fill at the price just seen."""
        for o in self._orders:
            if o.status == "open" and o.id != just.id and (o.asset, o.symbol) == (just.asset, just.symbol):
                self._try_fill(o, None, mid, half, src)

    async def sweep(self, symbol: str, asset: str, mid: float, half_spread: float = 0.0) -> list[Order]:
        """Re-test resting limit orders in one instrument against a supplied price (tests, and callers with a feed)."""
        async with self._lock:
            probe = Order(id="", client_order_id="", broker=self.name, symbol=symbol, asset=asset, side="buy",
                          qty=1, type="market", status="open", created_at="")
            before = {o.id for o in self._orders if o.status == "filled"}
            self._sweep_symbol(probe, mid, half_spread, "supplied")
            self._save()
            return [o.model_copy() for o in self._orders if o.status == "filled" and o.id not in before]

    def _by_client(self, cid: str) -> Order | None:
        for o in reversed(self._orders):
            if o.client_order_id == cid:
                return o.model_copy()
        return None

    # ---- Broker protocol --------------------------------------------------------------------------
    async def account(self) -> Account:
        return Account(broker=self.name, cash=_r(self.cash), equity=_r(self._equity(self.cash, self.pos)),
                       buying_power=_r(max(0.0, self._buying_power(self.cash, self.pos))),
                       starting_cash=self.starting_cash, realized_pnl=self.realized, fees_paid=self.fees_paid,
                       note="Simulated account: fills are modelled, not real.")

    async def positions(self) -> list[Position]:
        out = []
        for p in sorted(self.pos.values(), key=lambda p: (p["asset"], p["symbol"])):
            mark = p["mark_px"] or p["avg_px"]
            out.append(Position(symbol=p["symbol"], asset=p["asset"], qty=p["qty"], avg_px=_r(p["avg_px"]),
                                mark_px=mark, market_value=_r(p["qty"] * mark * p["mult"]),
                                unrealized_pnl=_r((mark - p["avg_px"]) * p["qty"] * p["mult"]),
                                multiplier=p["mult"], broker=self.name))
        return out

    async def refresh_marks(self) -> None:
        """Re-mark equity and option positions to the latest Massive price; failures keep the old mark."""
        async def one(p: dict):
            q = await (self.quotes.equity(p["symbol"]) if p["asset"] == "equity" else self.quotes.option(p["symbol"]))
            return p, q
        targets = [p for p in self.pos.values() if p["asset"] in ("equity", "option")]
        res = await asyncio.gather(*(one(p) for p in targets), return_exceptions=True)
        async with self._lock:
            for r in res:
                if isinstance(r, Exception) or r[1] is None:
                    continue
                p, q = r
                if _key(p["asset"], p["symbol"]) in self.pos:
                    self.pos[_key(p["asset"], p["symbol"])]["mark_px"] = q.mid
            self._save()

    async def orders(self, status: str | None = None) -> list[Order]:
        rows = [o for o in self._orders if status is None or o.status == status]
        return [o.model_copy() for o in reversed(rows)]  # newest first

    async def cancel(self, order_id: str) -> Order:
        async with self._lock:
            o = next((o for o in self._orders if o.id == order_id or o.client_order_id == order_id), None)
            if o is None:
                raise BrokerError(f"No order {order_id}.", 404)
            if o.status != "open":
                raise BrokerError(f"Order {o.id} is {o.status}; only open orders can be cancelled.", 409)
            o.status = "cancelled"
            self._refs.pop(o.id, None)
            self._save()
            return o.model_copy()

    async def reset(self, starting_cash: float | None = None) -> Account:
        async with self._lock:
            self._reset_state(self.starting_cash if starting_cash is None else starting_cash)
            self._save()
        return await self.account()
