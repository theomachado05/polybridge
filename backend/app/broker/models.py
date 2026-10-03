"""Broker data contract shared by SimBroker, WebullBroker and the routes."""
from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator, model_validator

Asset = Literal["equity", "option", "prediction"]
Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["filled", "open", "cancelled", "rejected"]

MULTIPLIER: dict[str, int] = {"equity": 1, "option": 100, "prediction": 1}  # option: shares per contract


class BrokerError(Exception):
    """A broker failure the API should report as a clean HTTP error, never a 500."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message, self.status_code = message, status_code


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    asset: Asset
    side: Side
    qty: float = Field(gt=0, allow_inf_nan=False)
    type: OrderType = "market"
    limit_px: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    client_order_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=64)
    tag: str | None = Field(default=None, max_length=64)  # bridge id
    # Reference price supplied by the caller: the bridge's last price (equity), the quote mid (option) or the
    # prediction-market book price on the side being taken (prediction legs).
    ref_px: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    # Half the quoted bid/ask spread around ref_px (e.g. an option leg's Massive quote). None: the broker applies its
    # configured fallback spread.
    ref_half_spread: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Where ref_px came from, reported as the order's price_source (default "supplied"); e.g. "recorded" for a replay
    # filled at the replayed price because no current quote was available.
    ref_source: str | None = Field(default=None, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    combo_id: str | None = Field(default=None, max_length=64)  # legs of one multi-leg option order share it
    note: str | None = Field(default=None, max_length=200)  # label copied to the Order (e.g. replay origin)
    # True: the order may trade outside the regular session (pre-market 04:00-09:30 ET, after-hours 16:00-20:00 ET).
    # Only honoured by a broker whose ``extended_hours`` capability is True; Webull needs a limit order for it.
    extended_hours: bool = False

    @field_validator("symbol")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("symbol must not be blank")
        return v

    @model_validator(mode="after")
    def _check(self) -> "OrderRequest":
        if self.asset != "prediction":
            self.symbol = self.symbol.upper()  # tickers and OCC option symbols; market ids stay as given
        if self.type == "limit" and self.limit_px is None:
            raise ValueError("limit orders need limit_px")
        if self.asset == "option" and self.qty != int(self.qty):
            raise ValueError("option quantities are whole contracts")
        if self.asset == "prediction":
            for px in (self.ref_px, self.limit_px):
                if px is not None and px > 1:
                    raise ValueError("prediction prices are probabilities in (0, 1]")
        return self


class Order(BaseModel):
    id: str
    client_order_id: str
    broker: str  # "sim" | "webull-paper"
    symbol: str
    asset: Asset
    side: Side
    qty: float
    type: OrderType
    limit_px: float | None = None
    status: OrderStatus
    filled_qty: float = 0.0
    fill_px: float | None = None
    fee: float = 0.0
    created_at: str
    filled_at: str | None = None
    tag: str | None = None
    price_source: str | None = None  # where the reference price came from
    reject_reason: str | None = None
    note: str | None = None  # e.g. "options routed to the simulator: Webull paper does not take them"
    combo_id: str | None = None  # multi-leg option order this leg belongs to


class Position(BaseModel):
    symbol: str
    asset: Asset
    qty: float  # signed: negative is short
    avg_px: float
    mark_px: float | None = None
    market_value: float | None = None  # signed, includes the option multiplier
    unrealized_pnl: float | None = None
    multiplier: int = 1
    broker: str = "sim"


class Account(BaseModel):
    broker: str
    cash: float
    equity: float
    buying_power: float
    currency: str = "USD"
    simulated: bool = True
    starting_cash: float | None = None
    realized_pnl: float | None = None
    fees_paid: float | None = None
    note: str | None = None


@runtime_checkable
class Broker(Protocol):
    name: str
    # Capability: the broker accepts equity orders with ``OrderRequest.extended_hours`` (pre-market / after-hours).
    # SimBroker True (simulated); WebullBroker True per the Webull OpenAPI docs (support_trading_session "ALL",
    # limit orders only). Callers read it with getattr(broker, "extended_hours", False) so a minimal fake still works.
    extended_hours: bool

    async def account(self) -> Account: ...
    async def positions(self) -> list[Position]: ...
    async def place_order(self, req: OrderRequest) -> Order: ...
    async def orders(self, status: str | None = None) -> list[Order]: ...
    async def cancel(self, order_id: str) -> Order: ...


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def finite(x: object) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
