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
    # Where this row came from: "polybridge" (placed through this app), "webull_open" (Webull's open-orders list) or
    # "webull_history" (Webull's order history, e.g. an order placed in the Webull app). None for the simulator.
    origin: str | None = None
    broker_status: str | None = None  # the broker's own status word (Webull: PENDING, SUBMITTED, PARTIAL_FILLED, ...)


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
    # Which book the row belongs to, in words the UI shows as is: "Webull paper account", "Simulated account" or
    # "demo holdings" (the seeded demo portfolio, never held at any broker).
    account: str | None = None
    strategy: str | None = None  # Webull option position strategy (SINGLE, VERTICAL, ...) for an option leg


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
    # Webull: the account in use as accounts/list names it (e.g. "margin", "INDIVIDUAL_MARGIN", "Individual Margin")
    account_type: str | None = None
    account_class: str | None = None
    account_label: str | None = None
    extended_hours: bool | None = None  # the broker's extended-hours capability (Broker.extended_hours)
    # Set by GET /account from the NYSE session clock: is the regular session (09:30-16:00 ET) on right now, and the
    # session label / next regular open. Webull paper takes orders only while market_open is True.
    market_open: bool | None = None
    session: str | None = None
    next_open: str | None = None
    # Capital and margin as the broker reports them (Webull margin accounts; None when not reported). buying_power is
    # the conservative figure a hedge held overnight can use (Webull: overnight buying power), day_buying_power the
    # intraday (4x) figure, option_buying_power what option orders may use.
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
    # Capabilities: may this broker place option orders itself (False: option legs go to the simulator, labelled), and
    # where option orders go right now ("webull-paper" or "sim").
    options_supported: bool | None = None
    options_route: str | None = None


@runtime_checkable
class Broker(Protocol):
    name: str
    # Capability: the broker accepts equity orders with ``OrderRequest.extended_hours`` (pre-market / after-hours).
    # SimBroker True (simulated); WebullBroker False by default (the paper sandbox refuses every order outside
    # 09:30-16:00 ET; WEBULL_EXTENDED_HOURS=1 sends "ALL" limit orders per the OpenAPI docs). Callers read it with getattr(broker, "extended_hours", False) so a minimal fake still works.
    extended_hours: bool
    # Optional capabilities, read with getattr so a minimal fake still works:
    #   options_supported: bool          the broker itself places option orders (WebullBroker: WEBULL_OPTIONS=1)
    #   async can_short(symbol) -> bool | None   True shortable, False not (instrument or account), None unknown

    async def account(self) -> Account: ...
    async def positions(self) -> list[Position]: ...
    async def place_order(self, req: OrderRequest) -> Order: ...
    async def orders(self, status: str | None = None) -> list[Order]: ...
    async def cancel(self, order_id: str) -> Order: ...


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def finite(x: object) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
