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

MULTIPLIER: dict[str, int] = {"equity": 1, "option": 100, "prediction": 1}


class BrokerError(Exception):

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
    tag: str | None = Field(default=None, max_length=64)
    ref_px: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    ref_half_spread: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    ref_source: str | None = Field(default=None, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    combo_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=200)
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
            self.symbol = self.symbol.upper()
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
    broker: str
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
    price_source: str | None = None
    reject_reason: str | None = None
    note: str | None = None
    combo_id: str | None = None
    origin: str | None = None
    broker_status: str | None = None


class Position(BaseModel):
    symbol: str
    asset: Asset
    qty: float
    avg_px: float
    mark_px: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    multiplier: int = 1
    broker: str = "sim"
    account: str | None = None
    strategy: str | None = None


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
    account_type: str | None = None
    account_class: str | None = None
    account_label: str | None = None
    extended_hours: bool | None = None
    market_open: bool | None = None
    session: str | None = None
    next_open: str | None = None
    day_buying_power: float | None = None
    overnight_buying_power: float | None = None
    option_buying_power: float | None = None
    settled_cash: float | None = None
    unsettled_cash: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    maintenance_margin: float | None = None
    init_margin: float | None = None
    used_margin: float | None = None
    margin_excess: float | None = None
    margin_ratio: float | None = None
    open_margin_calls: list[str] | None = None
    day_trades_left: str | None = None
    options_supported: bool | None = None
    options_route: str | None = None


@runtime_checkable
class Broker(Protocol):
    name: str
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
