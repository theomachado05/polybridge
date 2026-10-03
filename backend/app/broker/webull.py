"""WebullBroker: the Broker interface against the Webull OpenAPI paper (sandbox) trading endpoints.

Built from Webull's public developer docs and the Apache-2.0 official Python SDK (webull-openapi-python-sdk 3.0.2):
  host         api.sandbox.webull.com (sandbox, paper money) over https, and nothing else: WebullClient refuses any other
               host (production is api.webull.com), so an order placed here can only ever reach the paper sandbox.
  signing      HMAC-SHA256 (HMAC-SHA1 + MD5 body hash is the older documented variant, kept as an option).
               string to sign = path & sorted "k=v" of (x-app-key, x-signature-algorithm, x-signature-version,
               x-signature-nonce, x-timestamp, host, and the query params) [& UPPERCASE hex digest of the compact
               JSON body], percent-encoded; key = app_secret + "&"; signature = base64(HMAC(key, string)).
  endpoints    GET  /trading/accounts/list           GET  /trading/assets/balances/get
               GET  /trading/assets/positions/list   POST /trading/orders/place
               POST /trading/orders/cancel           GET  /trading/orders/get
               GET  /trading/orders/open-orders/list
  sessions     support_trading_session: "CORE" (regular hours 09:30-16:00 ET), "ALL" (regular plus pre-market and
               after-hours), "NIGHT" (overnight only) -- developer.webull.com/apis/docs/trade-api/stock. Webull takes
               only LIMIT orders outside the regular session, so an extended-hours market order is refused here
               before it is sent. OrderRequest.extended_hours=True sends "ALL"; everything else sends "CORE".
Equities go to Webull. Options and prediction legs go to the SimBroker and are labelled as such on the order.
Enabled only by get_broker() when BROKER=webull and WEBULL_APP_KEY / WEBULL_APP_SECRET are set."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import functools
import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .models import Account, BrokerError, Order, OrderRequest, Position, now_iso
from .sim import SimBroker

log = logging.getLogger(__name__)

SANDBOX_HOST = "https://api.sandbox.webull.com"
SANDBOX_HOSTNAME = "api.sandbox.webull.com"  # the only host this integration talks to (paper money)
# Hard deadline per HTTP request (connect + send + read). The longest chain inside one place_order is a split sell:
# positions + accounts/list + 2 x (orders/place + orders/get) = 6 requests, 24 s at most, which stays inside the
# bridge's BROKER_TIMEOUT_S (30 s), so the bridge never abandons a call that may still place an order.
TIMEOUT_S = 4.0
SIM_NOTE = "Routed to the simulator: Webull paper is only used for equities in this integration."
_LISTS = ("data", "accounts", "positions", "orders", "holdings", "items", "list", "results")


class WebullAPIError(BrokerError):
    """Webull answered with an error status. ``http_status`` is Webull's own status: a 4xx other than 429 means the
    request was understood and refused; a 5xx or 429 says nothing about whether an order was accepted."""

    def __init__(self, message: str, status_code: int = 502, http_status: int | None = None) -> None:
        super().__init__(message, status_code)
        self.http_status = http_status

    @property
    def refused(self) -> bool:
        return self.http_status is not None and 400 <= self.http_status < 500 and self.http_status != 429


class NotSandboxHost(ValueError):
    """WEBULL_BASE_URL names a host other than the Webull paper sandbox (real money is out of scope)."""


def check_sandbox_url(base_url: str) -> str:
    """The base URL when it is https://api.sandbox.webull.com (any path), else NotSandboxHost."""
    url = httpx.URL(base_url.rstrip("/"))
    if url.scheme != "https" or url.host != SANDBOX_HOSTNAME:
        raise NotSandboxHost(f"Webull base URL {url.scheme}://{url.host} is not the paper sandbox "
                             f"(https://{SANDBOX_HOSTNAME}); real-money hosts are refused")
    return str(url).rstrip("/")


def _dec(x: float) -> str:
    """Exact decimal text for a quantity or price: never scientific notation, never rounded to 6 digits."""
    return format(Decimal(repr(float(x))).normalize(), "f")


def _guard(fn):
    """Any unexpected failure while talking to or parsing Webull becomes a clean 502, never a 500."""
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except BrokerError:
            raise
        except Exception as e:
            log.warning("Webull %s failed: %s", fn.__name__, type(e).__name__)
            raise BrokerError(f"Webull response could not be processed ({type(e).__name__}).", 502) from e
    return wrapper


def body_json(body: Any) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def sign(*, app_key: str, app_secret: str, host: str, path: str, query: dict[str, Any] | None, body: Any,
         timestamp: str, nonce: str, algorithm: str = "HMAC-SHA256") -> dict[str, str]:
    """Signature headers for one request. `host` is the bare host name (no scheme)."""
    if algorithm not in ("HMAC-SHA256", "HMAC-SHA1"):
        raise ValueError(f"unsupported signature algorithm {algorithm}")
    params: dict[str, str] = {"x-app-key": app_key, "x-signature-algorithm": algorithm, "x-signature-version": "1.0",
                              "x-signature-nonce": nonce, "x-timestamp": timestamp, "host": host}
    for k, v in (query or {}).items():
        params[k] = f"{params[k]}&{v}" if k in params else str(v)
    s = path + "&" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    if body is not None:
        raw = body_json(body).encode()
        digest = hashlib.sha256(raw).hexdigest() if algorithm == "HMAC-SHA256" else hashlib.md5(raw).hexdigest()
        s += "&" + digest.upper()
    h = hashlib.sha256 if algorithm == "HMAC-SHA256" else hashlib.sha1
    sig = base64.b64encode(hmac.new((app_secret + "&").encode(), quote(s, safe="").encode(), h).digest()).decode()
    return {"x-app-key": app_key, "x-timestamp": timestamp, "x-signature-algorithm": algorithm,
            "x-signature-version": "1.0", "x-signature-nonce": nonce, "x-signature": sig, "x-version": "v3"}


class WebullClient:
    def __init__(self, app_key: str, app_secret: str, base_url: str = SANDBOX_HOST,
                 http: httpx.AsyncClient | None = None, algorithm: str = "HMAC-SHA256",
                 now: Callable[[], dt.datetime] | None = None, nonce: Callable[[], str] | None = None) -> None:
        self._key, self._secret, self.algorithm = app_key, app_secret, algorithm
        self.base_url = check_sandbox_url(base_url)  # never a production (real-money) host
        self.host = httpx.URL(self.base_url).host
        self._http = http
        self._now = now or (lambda: dt.datetime.now(dt.UTC))
        self._nonce = nonce or (lambda: uuid.uuid4().hex)

    async def request(self, method: str, path: str, query: dict | None = None, body: Any = None) -> Any:
        ts = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
        headers = sign(app_key=self._key, app_secret=self._secret, host=self.host, path=path, query=query, body=body,
                       timestamp=ts, nonce=self._nonce(), algorithm=self.algorithm)
        content = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = body_json(body).encode()  # the exact bytes that were hashed
        http = self._http or httpx.AsyncClient(timeout=TIMEOUT_S)
        try:
            r = await asyncio.wait_for(http.request(method, self.base_url + path, params=query or None, headers=headers,
                                                    content=content, timeout=TIMEOUT_S), TIMEOUT_S)
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            raise BrokerError(f"Webull request failed: {type(e).__name__}", 502) from e
        finally:
            if self._http is None:
                await http.aclose()
        try:
            payload = r.json() if r.content else None
        except ValueError:
            payload = None
        if r.status_code >= 400:
            msg = payload.get("message") or payload.get("msg") or payload.get("error_code") if isinstance(payload, dict) else None
            raise WebullAPIError(f"Webull {r.status_code}: {str(msg or r.text)[:200]}", 502, http_status=r.status_code)
        return payload


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in _LISTS:
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                inner = _rows(v)
                if inner:
                    return inner
    return []


def _row(payload: Any) -> dict:
    rows = _rows(payload)
    if rows:
        return rows[0]
    if isinstance(payload, dict):
        d = payload.get("data")
        return d if isinstance(d, dict) else payload
    return {}


def _num(d: dict, *names: str) -> float | None:
    for n in names:
        v = d.get(n)
        try:
            if v is not None and v != "":
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _str(d: dict, *names: str) -> str | None:
    for n in names:
        v = d.get(n)
        if v not in (None, ""):
            return str(v)
    return None


_STATUS = {"FILLED": "filled", "CANCELLED": "cancelled", "CANCELED": "cancelled", "FAILED": "rejected",
           "REJECTED": "rejected", "EXPIRED": "cancelled"}  # SUBMITTED / WORKING / PARTIAL_FILLED -> open


def order_from_webull(d: dict, fallback: Order | None = None) -> Order:
    cid = _str(d, "client_order_id") or (fallback.client_order_id if fallback else "")
    status = _STATUS.get((_str(d, "status", "order_status") or "").upper(), "open")
    side = (_str(d, "side") or (fallback.side if fallback else "buy")).lower()
    qty = _num(d, "total_quantity", "quantity", "qty") or (fallback.qty if fallback else 0.0)
    filled = _num(d, "filled_quantity", "filled_qty") or (qty if status == "filled" else 0.0)
    return Order(id=_str(d, "order_id") or (fallback.id if fallback else cid), client_order_id=cid, broker="webull-paper",
                 symbol=(_str(d, "symbol") or (fallback.symbol if fallback else "")).upper(), asset="equity",
                 side="sell" if side in ("sell", "short", "sell_short") else "buy", qty=qty,
                 type="limit" if (_str(d, "order_type") or "").upper().startswith("LIMIT") else "market",
                 limit_px=_num(d, "limit_price"), status=status, filled_qty=filled,
                 fill_px=_num(d, "filled_price", "avg_filled_price", "filled_avg_price", "fill_price", "avg_price",
                              "average_price"),
                 created_at=fallback.created_at if fallback else now_iso(),
                 filled_at=now_iso() if status == "filled" else None,
                 tag=fallback.tag if fallback else None, price_source="webull_paper",
                 note=fallback.note if fallback else None,
                 reject_reason=_str(d, "error_message", "reject_reason", "message") if status == "rejected" else None)


class WebullBroker:
    name = "webull-paper"

    def __init__(self, client: WebullClient, sim: SimBroker, account_id: str | None = None,
                 extended_hours: bool = True) -> None:
        self.client, self.sim = client, sim
        # Documented for US stocks (support_trading_session "ALL", limit orders). Whether the paper sandbox fills
        # pre-market orders is only known once a key is tried (W1 smoke test); WEBULL_EXTENDED_HOURS=0 turns it off.
        self.extended_hours = extended_hours
        self._account_id = account_id or None
        self._placed: dict[str, Order] = {}  # client_order_id -> last known state of orders placed through us
        # split sell: client_order_id -> its leg client ids (recorded BEFORE each leg is posted, so a split that
        # fails half way can still be reconciled by the parent id) and the parent's total quantity
        self._legs: dict[str, list[str]] = {}
        self._split_qty: dict[str, float] = {}

    async def _aid(self) -> str:
        if self._account_id is None:
            rows = _rows(await self.client.request("GET", "/trading/accounts/list"))
            ids = [x for r in rows if (x := _str(r, "account_id", "accountId"))]
            if not ids:
                raise BrokerError("Webull returned no paper accounts for these credentials.", 502)
            self._account_id = ids[0]
        return self._account_id

    # ---- account and positions --------------------------------------------------------------------
    @_guard
    async def account(self) -> Account:
        aid = await self._aid()
        payload = await self.client.request("GET", "/trading/assets/balances/get",
                                            {"account_id": aid, "total_asset_currency": "USD"})
        d = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(d, dict):
            d = _row(d)  # a list of one row, or nothing
        for k in ("account_currency_assets", "currency_assets"):  # per-currency breakdown: prefer USD
            sub = _rows(d.get(k))
            if sub:
                d = {**d, **next((s for s in sub if (_str(s, "currency") or "USD") == "USD"), sub[0])}
        cash = _num(d, "cash_balance", "total_cash_balance", "settled_cash", "cash", "account_cash")
        equity = _num(d, "total_net_liquidation_value", "net_liquidation_value", "net_liquidation", "total_asset",
                      "total_assets", "equity")
        bp = _num(d, "buying_power", "stock_buying_power", "day_buying_power", "overnight_buying_power")
        if cash is None and equity is None:
            raise BrokerError("Webull balance response had no cash or equity field.", 502)
        return Account(broker=self.name, cash=cash if cash is not None else 0.0,
                       equity=equity if equity is not None else (cash or 0.0),
                       buying_power=bp if bp is not None else (cash or 0.0), simulated=True,
                       note="Webull paper (simulated money). Options and prediction legs are simulated separately.")

    @_guard
    async def positions(self) -> list[Position]:
        aid = await self._aid()
        out: list[Position] = []
        for r in _rows(await self.client.request("GET", "/trading/assets/positions/list", {"account_id": aid})):
            sym, qty = _str(r, "symbol", "ticker"), _num(r, "quantity", "qty", "position")
            if not sym or qty is None or qty == 0:
                continue
            if (_str(r, "direction", "position_side") or "").upper() == "SHORT" and qty > 0:
                qty = -qty
            cost, last = _num(r, "cost_price", "avg_cost", "unit_cost", "cost"), _num(r, "last_price", "market_price", "last")
            out.append(Position(symbol=sym.upper(), asset="equity", qty=qty, avg_px=cost or 0.0, mark_px=last,
                                market_value=qty * last if last is not None else None,
                                unrealized_pnl=(last - cost) * qty if last is not None and cost is not None else None,
                                broker=self.name))
        return out + await self.sim.positions()  # simulated option / prediction legs, labelled broker="sim"

    # ---- orders -----------------------------------------------------------------------------------
    async def _held(self, symbol: str) -> float:
        try:
            return next((p.qty for p in await self.positions() if p.symbol == symbol and p.broker == self.name), 0.0)
        except BrokerError:
            return 0.0

    async def place_combo(self, reqs: list[OrderRequest]) -> list[Order]:
        """Multi-leg option orders always go to the simulator here (labelled SIM_NOTE on every leg)."""
        return await self.sim.place_combo(reqs)

    @_guard
    async def place_order(self, req: OrderRequest) -> Order:
        if req.asset != "equity":
            return await self.sim.place_order(req)  # the sim stamps SIM_NOTE on every order it takes here
        cid = req.client_order_id
        if (dup := self._placed.get(cid)) is not None:
            return dup
        if (legs := self._legs.get(cid)) is not None and (merged := self._merge(cid, legs)) is not None:
            return merged
        if req.side == "buy":
            return await self._submit(req, cid, "BUY", req.qty)
        held = max(await self._held(req.symbol), 0.0)  # long quantity only; a short is already negative
        if held >= req.qty:
            return await self._submit(req, cid, "SELL", req.qty)
        if held <= 0:
            return await self._submit(req, cid, "SHORT", req.qty)  # nothing long to sell: this opens a short (hedges)
        # Part long, part short (hold 50, sell 100): a SELL for what is held plus a SHORT for the rest. Each leg is
        # recorded under the parent id before it is posted: if a leg's POST fails (5xx Webull cannot confirm, or the
        # caller's timeout cancels mid-split), find_order(cid) still reaches the legs and reports what really filled.
        legs = self._legs[cid] = [f"{cid}-sell"]
        self._split_qty[cid] = req.qty
        sell = await self._submit(req, legs[0], "SELL", held)
        if sell.status != "rejected":
            legs.append(f"{cid}-short")
            await self._submit(req, legs[1], "SHORT", req.qty - held)
        return self._merge(cid, legs) or sell

    def _merge(self, cid: str, legs: list[str]) -> Order | None:
        """One Order summarising the SELL and SHORT legs of a split sell (the legs stay separate in orders()), under
        the parent client id (also its id, so cancel(cid) reaches every leg). A leg Webull never took counts as
        nothing traded; None when no leg is known at all."""
        got = [self._placed[c] for c in legs if c in self._placed]
        if not got:
            return None
        qty = self._split_qty.get(cid) or sum(o.qty for o in got)
        filled = sum(o.filled_qty for o in got)
        priced = [(o.filled_qty, o.fill_px) for o in got if o.filled_qty and o.fill_px is not None]
        status = ("open" if any(o.status == "open" for o in got)  # a leg may still trade: keep tracking it
                  else "rejected" if any(o.status == "rejected" for o in got)
                  else "filled" if len(got) == 2 and all(o.status == "filled" for o in got)
                  else "cancelled")  # done, but not all of it traded (a leg cancelled, or never taken by Webull)
        reason = next((o.reject_reason for o in got if o.status == "rejected"), None)
        if status == "rejected" and filled:
            reason = f"partial: {filled:g} of {qty:g} filled; {reason or 'a leg was rejected'}"
        return got[0].model_copy(update={
            "id": cid, "client_order_id": cid, "qty": qty, "filled_qty": filled, "status": status,
            "fill_px": sum(q * p for q, p in priced) / sum(q for q, _ in priced) if priced else None,
            "reject_reason": reason})

    async def _submit(self, req: OrderRequest, cid: str, side: str, qty: float) -> Order:
        """Place one equity order at Webull and (once) ask for its state; a refusal is a rejected order."""
        base = Order(id=cid, client_order_id=cid, broker=self.name, symbol=req.symbol, asset="equity", side=req.side,
                     qty=qty, type=req.type, limit_px=req.limit_px, status="open", created_at=now_iso(), tag=req.tag,
                     price_source="webull_paper", note=req.note)
        if req.extended_hours and (not self.extended_hours or req.type != "limit"):
            base.status = "rejected"
            base.reject_reason = ("extended_hours_disabled: WEBULL_EXTENDED_HOURS is off" if not self.extended_hours
                                  else "extended_hours_needs_limit: Webull takes only limit orders outside 09:30-16:00 ET")
            self._placed[cid] = base
            return base
        aid = await self._aid()
        item: dict[str, Any] = {
            "client_order_id": cid, "combo_type": "NORMAL", "symbol": req.symbol,
            "instrument_type": "EQUITY", "market": "US", "order_type": req.type.upper(),
            "quantity": _dec(qty), "support_trading_session": "ALL" if req.extended_hours else "CORE", "side": side,
            "time_in_force": "DAY", "entrust_type": "QTY"}
        if req.type == "limit":
            item["limit_price"] = _dec(req.limit_px)
        try:
            resp = await self.client.request("POST", "/trading/orders/place", body={"account_id": aid, "new_orders": [item]})
        except WebullAPIError as e:
            if e.refused:  # a 4xx: understood and refused, a rejected order, not a crash
                base.status, base.reject_reason = "rejected", e.message
                self._placed[cid] = base
                return base
            # 5xx / 429: the order may have been accepted anyway. Ask Webull; if it knows the order, report what it
            # says, otherwise raise so the caller tracks it as unconfirmed (never booked as "nothing traded").
            try:
                known = await self.find_order(cid, fallback=base)
            except BrokerError:
                known = None
            if known is None:
                raise
            return known
        base.id = _str(_row(resp), "order_id") or base.id
        self._placed[cid] = base
        try:  # paper orders usually fill at once; ask once, otherwise it is reported open
            base = await self._refresh(base)
        except BrokerError:
            pass
        return base

    async def find_order(self, client_order_id: str, fallback: Order | None = None) -> Order | None:
        """Webull's state of an order by our client_order_id, or None when Webull does not know it (never placed).
        Used to reconcile an order whose place call timed out or failed after it may have been accepted. A split sell
        is read leg by leg and reported as one merged order under its parent id (see ``_merge``)."""
        if (legs := self._legs.get(client_order_id)) is not None:
            for leg in list(legs):
                await self.find_order(leg)  # refreshes a known leg; asks Webull for one whose POST never confirmed
            return self._merge(client_order_id, legs)
        if (o := self._placed.get(client_order_id)) is not None:
            try:
                return await self._refresh(o)
            except BrokerError:
                return o
        try:
            d = await self.client.request("GET", "/trading/orders/get",
                                          {"account_id": await self._aid(), "client_order_id": client_order_id})
        except WebullAPIError as e:
            if e.refused:
                return None
            raise
        row = _row(d)
        if not (_str(row, "order_id") or _str(row, "status", "order_status")):
            return None
        o = order_from_webull(row, fallback=fallback or Order(
            id=client_order_id, client_order_id=client_order_id, broker=self.name, symbol="", asset="equity",
            side="buy", qty=0, type="market", status="open", created_at=now_iso()))
        self._placed[client_order_id] = o
        return o

    async def _refresh(self, o: Order) -> Order:
        aid = await self._aid()
        d = await self.client.request("GET", "/trading/orders/get", {"account_id": aid, "client_order_id": o.client_order_id})
        fresh = order_from_webull(_row(d), fallback=o)
        self._placed[o.client_order_id] = fresh
        return fresh

    @_guard
    async def orders(self, status: str | None = None) -> list[Order]:
        aid = await self._aid()
        merged: dict[str, Order] = dict(self._placed)
        try:
            for r in _rows(await self.client.request("GET", "/trading/orders/open-orders/list", {"account_id": aid})):
                o = order_from_webull(r, fallback=merged.get(_str(r, "client_order_id") or ""))
                merged[o.client_order_id] = o
        except BrokerError:
            pass
        pending = [o for o in merged.values() if o.status == "open"][:25]
        for o, res in zip(pending, await asyncio.gather(*(self._refresh(o) for o in pending), return_exceptions=True)):
            if not isinstance(res, Exception):
                merged[o.client_order_id] = res
        rows = list(merged.values()) + await self.sim.orders()
        rows = [o for o in rows if status is None or o.status == status]
        return sorted(rows, key=lambda o: o.created_at, reverse=True)

    @_guard
    async def cancel(self, order_id: str) -> Order:
        if order_id.startswith("sim-"):
            return await self.sim.cancel(order_id)
        if (legs := self._legs.get(order_id)) is not None:  # a split sell: cancel every leg that may still trade
            for leg in list(legs):
                if (o := self._placed.get(leg)) is not None and o.status != "open":
                    continue
                try:
                    await self.cancel(leg)
                except WebullAPIError as e:
                    if not e.refused:  # a 4xx: already done, or never taken by Webull (read again below)
                        raise
            if (merged := await self.find_order(order_id)) is None:
                raise BrokerError(f"Webull does not know order {order_id}.", 404)
            return merged
        local = next((o for o in self._placed.values() if order_id in (o.id, o.client_order_id)), None)
        cid = local.client_order_id if local else order_id
        await self.client.request("POST", "/trading/orders/cancel", body={"account_id": await self._aid(), "client_order_id": cid})
        base = local or Order(id=order_id, client_order_id=cid, broker=self.name, symbol="", asset="equity", side="buy",
                              qty=0, type="market", status="open", created_at=now_iso())
        base.status = "cancelled"
        self._placed[cid] = base
        return base
