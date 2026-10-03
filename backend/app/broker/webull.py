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
               GET  /trading/orders/open-orders/list GET  /trading/orders/historical-orders/list
               GET  /trading/instruments/stocks/profiles/list   (shortable / easy_to_borrow / margin ratios)
               Order list payloads are groups {combo_type, combo_order_id, orders: [...]}: flattened by _order_rows.
  rate limits  balances, positions, order history, open orders and order detail: 2 requests / 2 s each; accounts/list
               10 / 30 s; instrument profiles 60 / 60 s (developer.webull.com/apis/docs/trade-api/overview). The
               network client spaces its own calls to stay inside them (RateLimiter).
  statuses     Webull PENDING / SUBMITTED / PARTIAL_FILLED -> open (filled_qty carries a partial fill), FILLED ->
               filled, CANCELLED (and CANCELED / EXPIRED) -> cancelled, FAILED (and REJECTED) -> rejected. The raw
               word is kept on Order.broker_status. See WEBULL_NOTES.md.
  sessions     support_trading_session: "CORE" (regular hours 09:30-16:00 ET), "ALL" (regular plus pre-market and
               after-hours), "NIGHT" (overnight only) -- developer.webull.com/apis/docs/trade-api/stock. Webull takes
               only LIMIT orders outside the regular session, so an extended-hours market order is refused here
               before it is sent. OrderRequest.extended_hours=True sends "ALL"; everything else sends "CORE".
  market hours The PAPER SANDBOX refuses every order outside 09:30-16:00 ET (tested Sat 2026-10-03: HTTP 417 "Orders
               cannot be placed at this time. Please try again during normal market hours 9:30 a.m. - 4:00 p.m. ET",
               even a CORE limit). So the ``extended_hours`` capability is False by default here
               (WEBULL_EXTENDED_HOURS=1 turns it on), and that refusal is a rejected order with reject_reason
               MARKET_CLOSED_REASON, never a crash: the staged-order book reads it as "held for the next regular
               session". Cancelling an order Webull reports as not present (417 "Order not present") is a clean
               rejected Order whose reason starts with "not_found:", never an exception.
Equities go to Webull. Prediction legs always go to the SimBroker. Option orders go to the SimBroker (labelled) unless
``options_supported`` is on (WEBULL_OPTIONS=1): Webull documents single- and multi-leg US option orders on the same
place endpoint, but the paper sandbox's option support is unverified (WEBULL_NOTES.md), so it is off by default.
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
import re
import time
import uuid
from collections import deque
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
MARKET_CLOSED = "market_closed"
MARKET_CLOSED_REASON = f"{MARKET_CLOSED}: Webull paper accepts orders 09:30-16:00 ET"
NOT_FOUND = "not_found"
NOT_SHORTABLE = "not_shortable"
_LISTS = ("data", "accounts", "positions", "orders", "holdings", "items", "list", "results")
ACCOUNT_LABEL = "Webull paper account"  # Position.account for rows held at Webull

HISTORY_PATH = "/trading/orders/historical-orders/list"
OPEN_PATH = "/trading/orders/open-orders/list"
DETAIL_PATH = "/trading/orders/get"
PROFILES_PATH = "/trading/instruments/stocks/profiles/list"
# Order history is read in bounded windows: one request covers at most HISTORY_WINDOW_DAYS (Webull's own default
# period), GET /orders looks back HISTORY_DEFAULT_DAYS unless asked (at most HISTORY_MAX_DAYS), and each window reads
# at most HISTORY_MAX_PAGES pages (pagination_key) before it stops and says so (history_truncated).
HISTORY_WINDOW_DAYS = 7
HISTORY_DEFAULT_DAYS = 7
HISTORY_MAX_DAYS = 30
HISTORY_MAX_PAGES = 5
HISTORY_CACHE_S = 10.0  # the history endpoint allows 2 calls / 2 s: repeated GET /orders reuse one read
OPEN_MAX_PAGES = 3
DETAIL_BUDGET = 4  # order-detail reads per reconcile pass / GET /orders (2 / 2 s each at Webull)
SHORT_CACHE_S = 900.0  # shortability per symbol is re-read every 15 minutes
# Documented per-path limits (requests, seconds).
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "/trading/assets/balances/get": (2, 2.0), "/trading/assets/positions/list": (2, 2.0),
    HISTORY_PATH: (2, 2.0), OPEN_PATH: (2, 2.0), DETAIL_PATH: (2, 2.0),
    "/trading/accounts/list": (10, 30.0), PROFILES_PATH: (60, 60.0)}
_OCC = re.compile(r"^(?:O:)?([A-Z][A-Z0-9.]{0,6}?)(\d{6})([CP])(\d{8})$")


class WebullAPIError(BrokerError):
    """Webull answered with an error status. ``http_status`` is Webull's own status: a 4xx other than 429 means the
    request was understood and refused; a 5xx or 429 says nothing about whether an order was accepted."""

    def __init__(self, message: str, status_code: int = 502, http_status: int | None = None) -> None:
        super().__init__(message, status_code)
        self.http_status = http_status

    @property
    def refused(self) -> bool:
        return self.http_status is not None and 400 <= self.http_status < 500 and self.http_status != 429


def market_closed_refusal(e: "WebullAPIError") -> bool:
    """Webull's "Orders cannot be placed at this time ... normal market hours" refusal (HTTP 417 on the sandbox)."""
    t = e.message.lower()
    return e.refused and ("cannot be placed at this time" in t or "normal market hours" in t
                          or (e.http_status == 417 and "market hours" in t))


def not_present_refusal(e: "WebullAPIError") -> bool:
    """Webull does not know the order (417 "Order not present" on a cancel; a 404 / "not found" variant too)."""
    t = e.message.lower()
    return e.refused and ("not present" in t or "not found" in t or "not exist" in t or e.http_status == 404)


def is_market_closed(order: Order | None) -> bool:
    """True for an order the broker refused only because the regular session is not on (retry at the next open)."""
    return (order is not None and order.status == "rejected" and order.filled_qty <= 0
            and (order.reject_reason or "").startswith(MARKET_CLOSED))


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


class RateLimiter:
    """Keeps each path inside Webull's documented limit (n requests per window seconds): a call that would exceed it
    waits for the oldest call in the window to age out. Paths without a documented limit are not delayed."""

    def __init__(self, limits: dict[str, tuple[int, float]] | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Any] = asyncio.sleep) -> None:
        self.limits = RATE_LIMITS if limits is None else limits
        self._clock, self._sleep = clock, sleep
        self._calls: dict[str, deque[float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.waited_s = 0.0  # total time spent waiting (reported by the reconciler)

    async def acquire(self, path: str) -> None:
        lim = self.limits.get(path)
        if lim is None:
            return
        n, window = lim
        lock = self._locks.setdefault(path, asyncio.Lock())
        async with lock:
            q = self._calls.setdefault(path, deque())
            while True:
                now = self._clock()
                while q and now - q[0] >= window:
                    q.popleft()
                if len(q) < n:
                    q.append(now)
                    return
                wait = window - (now - q[0]) + 0.01
                self.waited_s += wait
                await self._sleep(wait)


class WebullClient:
    def __init__(self, app_key: str, app_secret: str, base_url: str = SANDBOX_HOST,
                 http: httpx.AsyncClient | None = None, algorithm: str = "HMAC-SHA256",
                 now: Callable[[], dt.datetime] | None = None, nonce: Callable[[], str] | None = None,
                 limiter: RateLimiter | None | bool = None) -> None:
        self._key, self._secret, self.algorithm = app_key, app_secret, algorithm
        self.base_url = check_sandbox_url(base_url)  # never a production (real-money) host
        self.host = httpx.URL(self.base_url).host
        self._http = http
        self._now = now or (lambda: dt.datetime.now(dt.UTC))
        self._nonce = nonce or (lambda: uuid.uuid4().hex)
        # The real network client paces itself to Webull's documented limits; an injected (mocked) transport is not
        # paced unless a limiter is passed. limiter=False turns pacing off.
        if limiter is None:
            limiter = RateLimiter() if http is None else False
        self.limiter: RateLimiter | None = limiter or None

    def now(self) -> dt.datetime:
        return self._now()

    async def request(self, method: str, path: str, query: dict | None = None, body: Any = None) -> Any:
        if self.limiter is not None:
            await self.limiter.acquire(path)
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


# Webull order status -> ours. Documented values (order detail / open orders / history): PENDING, SUBMITTED,
# CANCELLED, FILLED, FAILED, PARTIAL_FILLED. CANCELED / EXPIRED / REJECTED / PENDING_CANCEL are accepted too.
_STATUS = {"FILLED": "filled", "CANCELLED": "cancelled", "CANCELED": "cancelled", "FAILED": "rejected",
           "REJECTED": "rejected", "EXPIRED": "cancelled"}  # PENDING / SUBMITTED / PARTIAL_FILLED / other -> open
STATUS_MAP_DOC = {"PENDING": "open", "SUBMITTED": "open", "PARTIAL_FILLED": "open (filled_qty > 0)",
                  "PENDING_CANCEL": "open", "FILLED": "filled", "CANCELLED": "cancelled", "CANCELED": "cancelled",
                  "EXPIRED": "cancelled", "FAILED": "rejected", "REJECTED": "rejected"}


def map_status(raw: str | None) -> str:
    return _STATUS.get((raw or "").upper(), "open")


def _iso(d: dict, at_key: str, ms_key: str) -> str | None:
    """Webull's ISO time (``*_time_at``) or epoch milliseconds (``*_time``) as our ISO-8601 UTC text."""
    v = _str(d, at_key)
    if v:
        try:
            t = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.UTC)
            return t.astimezone(dt.UTC).isoformat(timespec="milliseconds")
        except ValueError:
            pass
    ms = _num(d, ms_key)
    if ms and ms > 0:
        return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).isoformat(timespec="milliseconds")
    return None


def occ_symbol(leg: dict) -> str | None:
    """A Webull option leg {symbol, option_expire_date, option_type, strike_price|option_exercise_price} as the OCC
    ticker the rest of the app uses ('O:AAPL261023P00300000'); None when a field is missing."""
    und = _str(leg, "symbol", "underlying_symbol")
    exp = _str(leg, "option_expire_date")
    typ = (_str(leg, "option_type") or "").upper()
    k = _num(leg, "strike_price", "option_exercise_price")
    if not und or not exp or typ not in ("CALL", "PUT") or k is None:
        return None
    try:
        d = dt.date.fromisoformat(exp[:10])
    except ValueError:
        return None
    if _OCC.match(und.upper()):
        return "O:" + und.upper().removeprefix("O:")
    return f"O:{und.upper()}{d:%y%m%d}{typ[0]}{int(round(k * 1000)):08d}"


def parse_occ(symbol: str) -> dict | None:
    """'O:AAPL261023P00300000' -> {underlying, expiry (yyyy-mm-dd), right ('CALL'|'PUT'), strike}; None otherwise."""
    m = _OCC.match((symbol or "").strip().upper())
    if not m:
        return None
    und, ymd, cp, k = m.groups()
    try:
        exp = dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    return {"underlying": und, "expiry": exp.isoformat(), "right": "CALL" if cp == "C" else "PUT",
            "strike": int(k) / 1000.0}


def _order_rows(payload: Any) -> list[dict]:
    """Order rows from an open-orders / history / detail payload. Webull returns groups
    ``{client_order_id, combo_order_id, combo_type, orders: [...]}``: each group is flattened to its orders (the group's
    combo_order_id / combo_type are kept as ``_combo_order_id`` / ``_combo_type``, its client id fills a missing one).
    A plain order row (older shape, or a mock) is returned as is."""
    groups: Any = payload
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), (list, dict)):
            groups = payload["data"]
        elif isinstance(payload.get("orders"), list):
            groups = [payload]
    if isinstance(groups, dict):
        groups = [groups]
    if not isinstance(groups, list):
        return []
    out: list[dict] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        inner = g.get("orders")
        if isinstance(inner, list) and inner:
            for o in inner:
                if isinstance(o, dict):
                    row = {"_combo_order_id": g.get("combo_order_id"), "_combo_type": g.get("combo_type"), **o}
                    if not row.get("client_order_id") and g.get("client_order_id"):
                        row["client_order_id"] = g["client_order_id"]
                    out.append(row)
        else:
            out.append(g)
    return out


def _order_row(payload: Any) -> dict:
    rows = _order_rows(payload)
    return rows[0] if rows else _row(payload)


def order_from_webull(d: dict, fallback: Order | None = None, origin: str | None = None) -> Order:
    cid = _str(d, "client_order_id") or (fallback.client_order_id if fallback else "") or _str(d, "order_id") or ""
    raw = _str(d, "status", "order_status")
    status = map_status(raw)
    side = (_str(d, "side") or (fallback.side if fallback else "buy")).lower()
    qty = _num(d, "total_quantity", "quantity", "qty") or (fallback.qty if fallback else 0.0)
    filled = _num(d, "filled_quantity", "filled_qty") or (qty if status == "filled" else 0.0)
    legs = d.get("legs") if isinstance(d.get("legs"), list) else []
    is_option = (_str(d, "instrument_type") or "").upper() == "OPTION" or bool(legs) or (
        fallback is not None and fallback.asset == "option")
    symbol = _str(d, "symbol") or (fallback.symbol if fallback else "")
    note = fallback.note if fallback else None
    if is_option and len(legs) == 1 and (occ := occ_symbol(legs[0])):
        symbol = occ
    elif is_option and len(legs) > 1 and not note:
        note = f"Webull multi-leg option order ({_str(d, 'option_strategy') or 'strategy ?'}, {len(legs)} legs)"
    px = _num(d, "filled_price", "avg_filled_price", "filled_avg_price", "fill_price", "avg_price", "average_price")
    return Order(id=_str(d, "order_id") or (fallback.id if fallback else cid), client_order_id=cid, broker="webull-paper",
                 symbol=symbol.upper(), asset="option" if is_option else "equity",
                 side="sell" if side in ("sell", "short", "sell_short") else "buy", qty=qty,
                 type="limit" if (_str(d, "order_type") or "").upper().startswith("LIMIT") else "market",
                 limit_px=_num(d, "limit_price"), status=status, filled_qty=filled,
                 fill_px=px if px else None,  # Webull reports 0 / null before anything traded
                 created_at=(fallback.created_at if fallback else None) or _iso(d, "place_time_at", "place_time")
                 or now_iso(),
                 filled_at=(_iso(d, "filled_time_at", "filled_time") or (fallback.filled_at if fallback else None)
                            or now_iso()) if status == "filled" else None,
                 tag=fallback.tag if fallback else None, price_source="webull_paper",
                 note=note, combo_id=fallback.combo_id if fallback else None,
                 origin=(fallback.origin if fallback and fallback.origin else origin), broker_status=raw,
                 reject_reason=_str(d, "error_message", "reject_reason", "message") if status == "rejected" else None)


def _wb_time(t: dt.datetime) -> str:
    """Webull's history time format: yyyy-MM-dd'T'HH:mm:ss.SSS'Z' (UTC)."""
    t = t.astimezone(dt.UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false", "1", "0", "yes", "no"):
        return v.strip().lower() in ("true", "1", "yes")
    return None


def short_verdict(info: dict | None) -> bool | None:
    """True / False / None from one instrument profile: not shortable, or status CO (liquidate only) / NT (not
    tradable) -> False; shortable -> True; anything else (missing, lookup failed) -> None (unknown)."""
    if not info:
        return None
    if info.get("shortable") is False or info.get("status") in ("CO", "NT"):
        return False
    if info.get("shortable") is True:
        return True
    return None


class WebullBroker:
    name = "webull-paper"

    def __init__(self, client: WebullClient, sim: SimBroker, account_id: str | None = None,
                 extended_hours: bool = False, options_supported: bool = False) -> None:
        self.client, self.sim = client, sim
        # Documented for US stocks (support_trading_session "ALL", limit orders), but the paper sandbox refuses every
        # order outside 09:30-16:00 ET (417, tested 2026-10-03), so it is off by default; WEBULL_EXTENDED_HOURS=1 turns
        # it on (e.g. if the sandbox starts accepting pre-market limits).
        self.extended_hours = extended_hours
        # Webull documents single- and multi-leg US option orders on /trading/orders/place; the paper sandbox's
        # support is unverified (WEBULL_NOTES.md), so option orders stay in the simulator unless WEBULL_OPTIONS=1.
        self.options_supported = options_supported
        self._account_id = account_id or None
        self._account_row: dict | None = None  # the accounts/list row of the account in use (type / class / label)
        self._placed: dict[str, Order] = {}  # client_order_id -> last known state of orders placed through us
        # split sell: client_order_id -> its leg client ids (recorded BEFORE each leg is posted, so a split that
        # fails half way can still be reconciled by the parent id) and the parent's total quantity
        self._legs: dict[str, list[str]] = {}
        self._split_qty: dict[str, float] = {}
        # multi-leg option orders placed at Webull: combo client id -> {"legs": [Order], "signs": [+1|-1],
        # "refs": [mid], "side": "BUY"|"SELL", "qty": float}. Webull knows only the combo client id.
        self._combos: dict[str, dict] = {}
        self._external: dict[str, Order] = {}  # open at Webull but not placed through this app (e.g. the Webull app)
        self._history_cache: dict[int, tuple[float, list[Order], bool]] = {}
        self.history_truncated = False
        self._short_cache: dict[str, tuple[float, dict]] = {}
        self.transitions: deque[dict] = deque(maxlen=100)  # order state changes seen by reconcile(), newest last

    @property
    def regular_session_only(self) -> bool:
        """True while orders are accepted only during the regular session (09:30-16:00 ET): the sandbox default."""
        return not self.extended_hours

    async def _aid(self) -> str:
        if self._account_id is None:
            rows = _rows(await self.client.request("GET", "/trading/accounts/list"))
            ids = [x for r in rows if (x := _str(r, "account_id", "accountId"))]
            if not ids:
                raise BrokerError("Webull returned no paper accounts for these credentials.", 502)
            self._account_id = ids[0]
            self._account_row = next(r for r in rows if _str(r, "account_id", "accountId") == ids[0])
        return self._account_id

    async def account_info(self) -> dict:
        """{account_type, account_class, account_label} of the account in use, from accounts/list (read once; empty
        when Webull does not list it or the call fails: the balance never depends on it)."""
        aid = await self._aid()
        if self._account_row is None:
            try:
                rows = _rows(await self.client.request("GET", "/trading/accounts/list"))
            except BrokerError:
                return {}
            self._account_row = next((r for r in rows if _str(r, "account_id", "accountId") == aid), {})
        r = self._account_row or {}
        typ = _str(r, "account_type")
        return {"account_type": typ.lower() if typ else None, "account_class": _str(r, "account_class"),
                "account_label": _str(r, "account_label")}

    # ---- account and positions --------------------------------------------------------------------
    @_guard
    async def account(self) -> Account:
        aid = await self._aid()
        payload = await self.client.request("GET", "/trading/assets/balances/get",
                                            {"account_id": aid, "total_asset_currency": "USD"})
        top = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(top, dict):
            top = _row(top)  # a list of one row, or nothing
        d = dict(top)
        for k in ("account_currency_assets", "currency_assets"):  # per-currency breakdown: prefer USD
            sub = _rows(top.get(k))
            if sub:
                d = {**d, **next((s for s in sub if (_str(s, "currency") or "USD") == "USD"), sub[0])}
        cash = _num(d, "cash_balance", "total_cash_balance", "settled_cash", "cash", "account_cash")
        equity = _num(d, "total_net_liquidation_value", "net_liquidation_value", "net_liquidation", "total_asset",
                      "total_assets", "equity")
        day_bp, night_bp = _num(d, "day_buying_power"), _num(d, "overnight_buying_power")
        # buying_power: an explicit figure when Webull gives one, else the OVERNIGHT figure (a hedge staged over a
        # closure is held overnight, so the 4x intraday figure would overstate what it can deploy), else intraday.
        bp = _num(d, "buying_power", "stock_buying_power")
        bp_from = "Webull's buying power figure"
        if bp is None:
            bp = night_bp if night_bp is not None else day_bp
            bp_from = "the overnight figure" if night_bp is not None else "the intraday figure"
        if cash is None and equity is None:
            raise BrokerError("Webull balance response had no cash or equity field.", 502)
        calls = top.get("open_margin_calls")
        calls_l = [str(c.get("type") or c) if isinstance(c, dict) else str(c) for c in calls] \
            if isinstance(calls, list) else None
        info = await self.account_info()
        hours = ("orders accepted 09:30-16:00 ET only" if self.regular_session_only
                 else "extended-hours limit orders enabled (WEBULL_EXTENDED_HOURS)")
        opts = ("option orders go to Webull paper (WEBULL_OPTIONS)" if self.options_supported
                else "options and prediction legs are simulated separately")
        return Account(broker=self.name, cash=cash if cash is not None else 0.0,
                       equity=equity if equity is not None else (cash or 0.0),
                       buying_power=bp if bp is not None else (cash or 0.0), simulated=True,
                       extended_hours=self.extended_hours, **info,
                       day_buying_power=day_bp, overnight_buying_power=night_bp,
                       option_buying_power=_num(d, "option_buying_power"),
                       settled_cash=_num(d, "settled_cash"), unsettled_cash=_num(d, "unsettled_cash"),
                       market_value=_num(top, "total_market_value") if _num(top, "total_market_value") is not None
                       else _num(d, "market_value"),
                       unrealized_pnl=_num(top, "total_unrealized_profit_loss", "unrealized_profit_loss"),
                       maintenance_margin=_num(d, "maintenance_margin"), init_margin=_num(d, "init_margin"),
                       used_margin=_num(d, "used_margin"), margin_excess=_num(d, "margin_excess"),
                       margin_ratio=_num(d, "margin_ratio"), open_margin_calls=calls_l,
                       day_trades_left=_str(top, "day_trades_left"),
                       options_supported=self.options_supported,
                       options_route=self.name if self.options_supported else self.sim.name,
                       note=f"Webull paper (simulated money; {hours}; {opts}). buying_power is {bp_from}.")

    async def broker_positions(self) -> list[Position]:
        """Positions held at Webull only (equities, and option legs when Webull holds any), labelled
        "Webull paper account"."""
        aid = await self._aid()
        out: list[Position] = []
        for r in _rows(await self.client.request("GET", "/trading/assets/positions/list", {"account_id": aid})):
            legs = r.get("legs") if isinstance(r.get("legs"), list) else []
            if (_str(r, "instrument_type") or "").upper() == "OPTION" and legs:
                out.extend(self._option_positions(r, legs))
                continue
            sym, qty = _str(r, "symbol", "ticker"), _num(r, "quantity", "qty", "position")
            if not sym or qty is None or qty == 0:
                continue
            if (_str(r, "direction", "position_side") or "").upper() == "SHORT" and qty > 0:
                qty = -qty
            cost, last = _num(r, "cost_price", "avg_cost", "unit_cost", "cost"), _num(r, "last_price", "market_price", "last")
            upl = (last - cost) * qty if last is not None and cost is not None else _num(r, "unrealized_profit_loss")
            out.append(Position(symbol=sym.upper(), asset="equity", qty=qty, avg_px=cost or 0.0, mark_px=last,
                                market_value=qty * last if last is not None else None, unrealized_pnl=upl,
                                broker=self.name, account=ACCOUNT_LABEL))
        return out

    def _option_positions(self, r: dict, legs: list) -> list[Position]:
        strat = _str(r, "option_strategy")
        single = len(legs) == 1
        out = []
        for leg in legs:
            if not isinstance(leg, dict) or not (occ := occ_symbol(leg)):
                continue
            qty = _num(leg, "quantity")
            if not qty:
                continue
            mult = int(_num(leg, "option_contract_multiplier") or 100)
            cost, last = (_num(r, "cost_price"), _num(r, "last_price")) if single else (None, None)
            out.append(Position(symbol=occ, asset="option", qty=qty, avg_px=cost or 0.0, mark_px=last,
                                market_value=qty * last * mult if last is not None else None,
                                unrealized_pnl=_num(r, "unrealized_profit_loss") if single else None,
                                multiplier=mult, broker=self.name, account=ACCOUNT_LABEL, strategy=strat))
        return out

    @_guard
    async def positions(self) -> list[Position]:
        return await self.broker_positions() + await self.sim.positions()  # + simulated legs, broker="sim"

    # ---- shortability -----------------------------------------------------------------------------
    async def short_info(self, symbols: list[str]) -> dict[str, dict]:
        """Instrument profiles for equity symbols (GET /trading/instruments/stocks/profiles/list, 100 per call, cached
        15 min): {symbol: {shortable, easy_to_borrow, marginable, status, margin_requirement_short,
        maintenance_margin_short, checked_at} or {shortable: None, reason}}. Never raises."""
        want = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip() and ":" not in s
                                  and not _OCC.match(s.strip().upper())))
        now = time.monotonic()
        out: dict[str, dict] = {}
        missing = []
        for s in want:
            hit = self._short_cache.get(s)
            if hit is not None and now - hit[0] < SHORT_CACHE_S:
                out[s] = hit[1]
            else:
                missing.append(s)
        for i in range(0, len(missing), 100):
            batch = missing[i:i + 100]
            try:
                rows = _rows(await self.client.request("GET", PROFILES_PATH,
                                                       {"category": "US_STOCK", "symbols": ",".join(batch)}))
            except Exception as e:  # BrokerError, or a malformed payload: unknown, retried on the next call
                why = e.message if isinstance(e, BrokerError) else type(e).__name__
                for s in batch:
                    out[s] = {"symbol": s, "shortable": None, "reason": f"instrument lookup failed: {why}"[:160]}
                continue
            by = {(_str(r, "symbol") or "").upper(): r for r in rows}
            checked = now_iso()
            for s in batch:
                r = by.get(s)
                if r is None:
                    info = {"symbol": s, "shortable": None, "reason": "not listed by Webull instrument profiles",
                            "checked_at": checked}
                else:
                    info = {"symbol": s, "shortable": _bool(r.get("shortable")),
                            "easy_to_borrow": _bool(r.get("easy_to_borrow")), "marginable": _bool(r.get("marginable")),
                            "status": _str(r, "status"),
                            "margin_requirement_short": _num(r, "margin_requirement_short"),
                            "maintenance_margin_short": _num(r, "maintenance_margin_short"), "checked_at": checked}
                self._short_cache[s] = (now, info)
                out[s] = info
        return out

    async def short_status(self, symbols: list[str]) -> dict[str, dict]:
        """Per symbol: {can_short: True|False|None, reason, ...profile}. A cash account cannot short anything; an
        instrument Webull lists as not shortable, liquidate-only (CO) or not tradable (NT) cannot be shorted; a
        hard-to-borrow (easy_to_borrow false) but shortable name is True with a warning in reason."""
        infos = await self.short_info(symbols)
        try:
            acct_type = (await self.account_info()).get("account_type")
        except BrokerError:
            acct_type = None
        out = {}
        for s, info in infos.items():
            v = short_verdict(info)
            if acct_type == "cash":
                v, reason = False, "cash account: Webull allows short sales only in a margin account"
            elif v is False:
                reason = ("Webull lists it as not shortable" if info.get("shortable") is False
                          else f"Webull status {info.get('status')} (CO liquidate only / NT not tradable)")
            elif v is True:
                reason = ("shortable, easy to borrow" if info.get("easy_to_borrow") is not False
                          else "shortable but hard to borrow (borrow fees / recall risk)")
            else:
                reason = info.get("reason") or "shortability unknown"
            out[s] = {**info, "can_short": v, "reason": reason, "account_type": acct_type}
        return out

    async def can_short(self, symbol: str) -> bool | None:
        """True: Webull says this account can short the symbol now; False: it cannot (not shortable, CO / NT, or a cash
        account); None: unknown (lookup failed, not listed). Borrow can change intraday; cached 15 min."""
        sym = symbol.strip().upper()
        return (await self.short_status([sym])).get(sym, {}).get("can_short")

    async def _short_block(self, symbol: str) -> str | None:
        """Why a SHORT of ``symbol`` must not be sent (instrument evidence only), else None. Unknown never blocks:
        Webull itself refuses what it will not take (a clean rejected order)."""
        info = (await self.short_info([symbol])).get(symbol.upper())
        if short_verdict(info) is False:
            why = ("Webull lists it as not shortable" if info.get("shortable") is False
                   else f"Webull status {info.get('status')}")
            return f"{NOT_SHORTABLE}: {symbol.upper()} cannot be sold short ({why})"
        return None

    # ---- orders -----------------------------------------------------------------------------------
    async def _held(self, symbol: str) -> float:
        try:
            return next((p.qty for p in await self.broker_positions() if p.symbol == symbol), 0.0)
        except Exception:
            return 0.0

    async def place_combo(self, reqs: list[OrderRequest]) -> list[Order]:
        """Multi-leg option orders go to the simulator (labelled SIM_NOTE on every leg) unless options_supported, when
        a structure Webull names (SINGLE, VERTICAL, STRADDLE, STRANGLE, CALENDAR, IRON_CONDOR) is sent as one Webull
        multi-leg order; any other structure still goes to the simulator, labelled why."""
        if not self.options_supported or not reqs:
            return await self.sim.place_combo(reqs)
        strategy = option_strategy(reqs)
        if strategy is None:
            note = "Routed to the simulator: Webull has no option_strategy for this leg combination."
            return [o.model_copy(update={"note": note}) for o in await self.sim.place_combo(reqs)]
        return await self._submit_option(reqs, strategy)

    @_guard
    async def place_order(self, req: OrderRequest) -> Order:
        if req.asset == "option" and self.options_supported:
            return (await self._submit_option([req], "SINGLE"))[0]
        if req.asset != "equity":
            return await self.sim.place_order(req)  # the sim stamps SIM_NOTE on every order it takes here
        cid = req.client_order_id
        if (dup := self._placed.get(cid)) is not None:
            if not is_market_closed(dup):
                return dup
            del self._placed[cid]  # refused only because the session was closed: Webull never took it, send again
        if (legs := self._legs.get(cid)) is not None and (merged := self._merge(cid, legs)) is not None:
            if not is_market_closed(merged):
                return merged
            for leg in legs:
                self._placed.pop(leg, None)
            del self._legs[cid]
        if req.side == "buy":
            return await self._submit(req, cid, "BUY", req.qty)
        held = max(await self._held(req.symbol), 0.0)  # long quantity only; a short is already negative
        if held >= req.qty:
            return await self._submit(req, cid, "SELL", req.qty)
        block = await self._short_block(req.symbol)  # Webull says this name cannot be shorted: never send the SHORT
        if held <= 0:
            if block:
                return self._refuse(req, cid, req.qty, block)
            return await self._submit(req, cid, "SHORT", req.qty)  # nothing long to sell: this opens a short (hedges)
        # Part long, part short (hold 50, sell 100): a SELL for what is held plus a SHORT for the rest. Each leg is
        # recorded under the parent id before it is posted: if a leg's POST fails (5xx Webull cannot confirm, or the
        # caller's timeout cancels mid-split), find_order(cid) still reaches the legs and reports what really filled.
        legs = self._legs[cid] = [f"{cid}-sell"]
        self._split_qty[cid] = req.qty
        sell = await self._submit(req, legs[0], "SELL", held)
        if sell.status != "rejected":
            legs.append(f"{cid}-short")
            if block:
                self._refuse(req, legs[1], req.qty - held, block)
            else:
                await self._submit(req, legs[1], "SHORT", req.qty - held)
        return self._merge(cid, legs) or sell

    def _refuse(self, req: OrderRequest, cid: str, qty: float, reason: str) -> Order:
        o = Order(id=cid, client_order_id=cid, broker=self.name, symbol=req.symbol, asset="equity", side=req.side,
                  qty=qty, type=req.type, limit_px=req.limit_px, status="rejected", created_at=now_iso(), tag=req.tag,
                  price_source="webull_paper", note=req.note, reject_reason=reason, origin="polybridge")
        self._placed[cid] = o
        return o

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
                     price_source="webull_paper", note=req.note, origin="polybridge")
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
                base.status = "rejected"
                base.reject_reason = MARKET_CLOSED_REASON if market_closed_refusal(e) else e.message
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

    # ---- options at Webull (options_supported only) -----------------------------------------------
    async def _submit_option(self, reqs: list[OrderRequest], strategy: str) -> list[Order]:
        """One Webull option order: a single leg (SINGLE) or a multi-leg structure, all legs or none. Market legs with
        no limit price are sent as one net LIMIT at the quoted mids +/- half-spreads (Webull's multi-leg examples are
        limits); a structure with no price at all is refused here, never sent at market."""
        cid = reqs[0].combo_id or reqs[0].client_order_id
        if (known := self._combos.get(cid)) is not None and not is_market_closed(known["legs"][0]):
            return [o.model_copy() for o in known["legs"]]
        signs = [1 if r.side == "buy" else -1 for r in reqs]
        legs_px = []
        for r in reqs:
            px = r.limit_px if r.type == "limit" else r.ref_px
            legs_px.append((px, r.ref_half_spread or 0.0))
        qty = reqs[0].qty
        base = [Order(id=f"{cid}#{i}" if len(reqs) > 1 else cid, client_order_id=r.client_order_id, broker=self.name,
                      symbol=r.symbol, asset="option", side=r.side, qty=r.qty, type=r.type, limit_px=r.limit_px,
                      status="open", created_at=now_iso(), tag=r.tag, price_source="webull_paper", note=r.note,
                      combo_id=cid if len(reqs) > 1 else r.combo_id, origin="polybridge")
                for i, r in enumerate(reqs)]
        meta = {"legs": base, "signs": signs, "refs": [p for p, _h in legs_px], "qty": qty, "strategy": strategy}
        self._combos[cid] = meta

        def refuse(reason: str) -> list[Order]:
            for o in base:
                o.status, o.reject_reason = "rejected", reason
            return [o.model_copy() for o in base]

        occs = [parse_occ(r.symbol) for r in reqs]
        if any(o is None for o in occs):
            return refuse("not_an_occ_symbol: Webull option legs need OCC tickers")
        if len(reqs) > 1 and any(r.qty != qty for r in reqs):
            return refuse("ratio_not_supported: Webull multi-leg legs must have equal quantities here")
        single = len(reqs) == 1
        if single and reqs[0].type == "market":
            order_type, side, limit = "MARKET", "BUY" if signs[0] > 0 else "SELL", None
        else:
            if any(p is None for p, _h in legs_px):
                return refuse("no_price: a Webull option limit needs every leg's price (limit_px or quote ref_px)")
            net = sum(s * p for s, (p, _h) in zip(signs, legs_px))
            slack = 0.0 if all(r.type == "limit" for r in reqs) else sum(h for _p, h in legs_px)
            side = "BUY" if net >= 0 else "SELL"  # BUY = net debit, SELL = net credit
            limit = round(abs(net) + slack, 2) if side == "BUY" else round(max(abs(net) - slack, 0.01), 2)
            order_type = "LIMIT"
        und = occs[0]["underlying"]
        item: dict[str, Any] = {
            "client_order_id": cid, "combo_type": "NORMAL", "option_strategy": strategy, "order_type": order_type,
            "quantity": _dec(qty), "side": side, "time_in_force": "DAY", "entrust_type": "QTY",
            "instrument_type": "OPTION", "market": "US", "symbol": und,
            "legs": [{"side": "BUY" if s > 0 else "SELL", "quantity": _dec(r.qty / qty), "symbol": o["underlying"],
                      "strike_price": _dec(o["strike"]), "option_expire_date": o["expiry"], "instrument_type": "OPTION",
                      "option_type": o["right"], "market": "US"} for s, r, o in zip(signs, reqs, occs)]}
        if limit is not None:
            item["limit_price"] = _dec(limit)
            for o in base:
                o.note = (o.note + "; " if o.note else "") + f"Webull {strategy} net {side.lower()} limit {limit:.2f}"
        meta["side"] = side
        try:
            await self.client.request("POST", "/trading/orders/place", body={"account_id": await self._aid(),
                                                                             "new_orders": [item]})
        except WebullAPIError as e:
            if e.refused:
                return refuse(MARKET_CLOSED_REASON if market_closed_refusal(e) else e.message)
            try:
                return await self._refresh_combo(cid)
            except BrokerError:
                raise e
        try:
            return await self._refresh_combo(cid)
        except BrokerError:
            return [o.model_copy() for o in base]

    async def _refresh_combo(self, cid: str) -> list[Order]:
        """Read a Webull option order by its client id and spread its state over our legs. Webull reports one net
        fill price for a multi-leg order: each leg's fill_px is its quoted mid, with the difference to the net fill
        put on the first leg, so the signed sum of leg prices equals Webull's net (price_source says so)."""
        meta = self._combos[cid]
        d = await self.client.request("GET", DETAIL_PATH, {"account_id": await self._aid(), "client_order_id": cid})
        row = _order_row(d)
        if not (_str(row, "order_id") or _str(row, "status", "order_status")):
            raise BrokerError(f"Webull does not know option order {cid}.", 404)
        raw = _str(row, "status", "order_status")
        status = map_status(raw)
        total = _num(row, "total_quantity", "quantity") or meta["qty"]
        filled = _num(row, "filled_quantity") or (total if status == "filled" else 0.0)
        frac = min(filled / total, 1.0) if total else 0.0
        net = _num(row, "filled_price", "avg_filled_price")
        legs: list[Order] = meta["legs"]
        pxs: list[float | None] = [None] * len(legs)
        if net and frac > 0:
            if len(legs) == 1:
                pxs = [net]
            else:
                signed_net = net if meta.get("side", "BUY") == "BUY" else -net
                refs = [r if r is not None else 0.0 for r in meta["refs"]]
                resid = signed_net - sum(s * r for s, r in zip(meta["signs"], refs))
                pxs = [max(r + (meta["signs"][0] * resid if i == 0 else 0.0), 0.0001) for i, r in enumerate(refs)]
        oid = _str(row, "order_id")
        fresh = []
        for i, (o, px) in enumerate(zip(legs, pxs)):
            fresh.append(o.model_copy(update={
                "id": (f"{oid}#{i}" if len(legs) > 1 else oid) if oid else o.id,
                "status": status, "filled_qty": o.qty * frac, "fill_px": px, "broker_status": raw,
                "price_source": "webull_paper" if len(legs) == 1 else "webull_paper_net_allocated",
                "filled_at": (_iso(row, "filled_time_at", "filled_time") or now_iso()) if status == "filled" else None,
                "reject_reason": _str(row, "error_message", "reject_reason", "message") if status == "rejected" else None}))
        meta["legs"] = fresh
        return [o.model_copy() for o in fresh]

    # ---- order lookup -----------------------------------------------------------------------------
    async def find_order(self, client_order_id: str, fallback: Order | None = None) -> Order | None:
        """Webull's state of an order by our client_order_id, or None when Webull does not know it (never placed).
        Used to reconcile an order whose place call timed out or failed after it may have been accepted. A split sell
        is read leg by leg and reported as one merged order under its parent id (see ``_merge``)."""
        if (legs := self._legs.get(client_order_id)) is not None:
            for leg in list(legs):
                await self.find_order(leg)  # refreshes a known leg; asks Webull for one whose POST never confirmed
            return self._merge(client_order_id, legs)
        if (o := self._placed.get(client_order_id)) is not None:
            if o.status == "rejected" and (o.reject_reason or "").startswith(NOT_SHORTABLE):
                return o  # refused here, never sent: Webull has nothing to say about it
            try:
                return await self._refresh(o)
            except BrokerError:
                return o
        try:
            d = await self.client.request("GET", DETAIL_PATH,
                                          {"account_id": await self._aid(), "client_order_id": client_order_id})
        except WebullAPIError as e:
            if e.refused:
                return None
            raise
        row = _order_row(d)
        if not (_str(row, "order_id") or _str(row, "status", "order_status")):
            return None
        o = order_from_webull(row, fallback=fallback or Order(
            id=client_order_id, client_order_id=client_order_id, broker=self.name, symbol="", asset="equity",
            side="buy", qty=0, type="market", status="open", created_at=now_iso()))
        self._placed[client_order_id] = o
        return o

    async def _refresh(self, o: Order) -> Order:
        aid = await self._aid()
        d = await self.client.request("GET", DETAIL_PATH, {"account_id": aid, "client_order_id": o.client_order_id})
        fresh = order_from_webull(_order_row(d), fallback=o)
        self._placed[o.client_order_id] = fresh
        return fresh

    async def open_orders(self) -> list[Order]:
        """Webull's open orders (paginated, at most OPEN_MAX_PAGES pages), as Orders; ours keep their local fields."""
        aid = await self._aid()
        out: list[Order] = []
        key = None
        for _ in range(OPEN_MAX_PAGES):
            q = {"account_id": aid, **({"pagination_key": key} if key else {})}
            payload = await self.client.request("GET", OPEN_PATH, q)
            for r in _order_rows(payload):
                cid = _str(r, "client_order_id") or ""
                if cid in self._combos:
                    continue  # our multi-leg option order: read through _refresh_combo
                out.append(order_from_webull(r, fallback=self._placed.get(cid), origin="webull_open"))
            key = payload.get("pagination_key") if isinstance(payload, dict) else None
            if not key:
                break
        return out

    async def order_history(self, days: int = HISTORY_DEFAULT_DAYS) -> list[Order]:
        """Webull order history for the last ``days`` (1..HISTORY_MAX_DAYS), read newest window first in windows of
        HISTORY_WINDOW_DAYS with at most HISTORY_MAX_PAGES pages each (start_time / end_time in
        yyyy-MM-dd'T'HH:mm:ss.SSS'Z', pagination_key). Cached HISTORY_CACHE_S. Webull notes the history may lag the
        newest orders: callers prefer the open-orders list and order detail for orders still in flight."""
        days = max(1, min(int(days), HISTORY_MAX_DAYS))
        hit = self._history_cache.get(days)
        if hit is not None and time.monotonic() - hit[0] < HISTORY_CACHE_S:
            self.history_truncated = hit[2]
            return list(hit[1])
        aid = await self._aid()
        end = self.client.now()
        start = end - dt.timedelta(days=days)
        rows: dict[str, Order] = {}
        truncated = False
        we = end
        while we > start:
            ws = max(start, we - dt.timedelta(days=HISTORY_WINDOW_DAYS))
            key = None
            for page in range(HISTORY_MAX_PAGES):
                q = {"account_id": aid, "start_time": _wb_time(ws), "end_time": _wb_time(we),
                     **({"pagination_key": key} if key else {})}
                payload = await self.client.request("GET", HISTORY_PATH, q)
                for r in _order_rows(payload):
                    cid = _str(r, "client_order_id") or _str(r, "order_id") or ""
                    if cid and cid not in rows:  # newest window first: the first row seen for an id wins
                        rows[cid] = order_from_webull(r, fallback=self._placed.get(cid), origin="webull_history")
                key = payload.get("pagination_key") if isinstance(payload, dict) else None
                if not key:
                    break
                if page == HISTORY_MAX_PAGES - 1:
                    truncated = True
            we = ws
        out = list(rows.values())
        self.history_truncated = truncated
        self._history_cache[days] = (time.monotonic(), out, truncated)
        return list(out)

    def _settle(self, cid: str, fresh: Order, why: str, transitions: list[dict] | None = None) -> None:
        """Record ``fresh`` as the state of a tracked order and note a change of status or filled quantity."""
        old = self._placed.get(cid)
        self._placed[cid] = fresh
        if old is not None and (old.status, old.filled_qty) != (fresh.status, fresh.filled_qty):
            t = {"client_order_id": cid, "order_id": fresh.id, "symbol": fresh.symbol, "side": fresh.side,
                 "from": old.status, "to": fresh.status, "filled_qty": fresh.filled_qty, "fill_px": fresh.fill_px,
                 "broker_status": fresh.broker_status, "via": why, "at": now_iso()}
            self.transitions.append(t)
            if transitions is not None:
                transitions.append(t)

    async def reconcile(self, detail_budget: int = DETAIL_BUDGET) -> dict:
        """One reconciliation pass: read Webull's open orders once, settle every order we placed that is still open
        locally (still open at Webull -> its partial fill; gone from the open list -> its final state by order detail,
        at most ``detail_budget`` reads per pass, the rest next pass), refresh open multi-leg option orders, and note
        open orders placed outside this app. Raises BrokerError when the open-orders list cannot be read."""
        opn = await self.open_orders()
        by_cid = {o.client_order_id: o for o in opn}
        transitions: list[dict] = []
        tracked = [(cid, o) for cid, o in list(self._placed.items()) if o.status == "open"]
        deferred = 0
        for cid, o in tracked:
            if cid in by_cid:
                self._settle(cid, by_cid[cid], "open_orders", transitions)
            elif detail_budget > 0:
                detail_budget -= 1
                try:
                    d = await self.client.request("GET", DETAIL_PATH, {"account_id": await self._aid(),
                                                                       "client_order_id": cid})
                    row = _order_row(d)
                    if _str(row, "order_id") or _str(row, "status", "order_status"):
                        self._settle(cid, order_from_webull(row, fallback=o), "order_detail", transitions)
                except BrokerError:
                    deferred += 1
            else:
                deferred += 1
        for cid, meta in list(self._combos.items()):
            if meta["legs"] and meta["legs"][0].status == "open" and detail_budget > 0:
                detail_budget -= 1
                before = meta["legs"][0]
                try:
                    after = (await self._refresh_combo(cid))[0]
                except BrokerError:
                    deferred += 1
                    continue
                if (before.status, before.filled_qty) != (after.status, after.filled_qty):
                    t = {"client_order_id": cid, "order_id": after.id, "symbol": after.symbol, "side": after.side,
                         "from": before.status, "to": after.status, "filled_qty": after.filled_qty,
                         "fill_px": after.fill_px, "broker_status": after.broker_status, "via": "order_detail",
                         "at": now_iso()}
                    self.transitions.append(t)
                    transitions.append(t)
        self._external = {o.client_order_id: o for o in opn if o.client_order_id not in self._placed}
        if transitions:
            self._history_cache.clear()
        return {"checked": len(tracked), "open_at_webull": len(opn), "updated": len(transitions),
                "transitions": transitions, "external_open": len(self._external), "deferred": deferred}

    @_guard
    async def orders(self, status: str | None = None, days: int = HISTORY_DEFAULT_DAYS) -> list[Order]:
        """Webull order history (last ``days``) + Webull open orders + orders placed through us + simulated legs.
        Freshness wins: an order still open locally takes its final state from history or order detail; the open-
        orders list beats history (which may lag)."""
        merged: dict[str, Order] = dict(self._external)
        try:
            hist = await self.order_history(days)
        except BrokerError:
            hist = []
        for o in hist:
            cid = o.client_order_id
            if cid in self._combos:
                continue  # our multi-leg option order: its legs are listed below
            mine = self._placed.get(cid)
            if mine is not None and mine.status == "open" and o.status != "open":
                self._settle(cid, o, "history")
            merged[cid] = self._placed.get(cid) or o
        for cid, o in self._placed.items():
            merged[cid] = o
        open_ids: set[str] = set()
        try:
            for o in await self.open_orders():
                open_ids.add(o.client_order_id)
                if o.client_order_id in self._placed:
                    self._settle(o.client_order_id, o, "open_orders")
                merged[o.client_order_id] = o
        except BrokerError:
            pass
        pending = [o for cid, o in self._placed.items() if o.status == "open" and cid not in open_ids][:DETAIL_BUDGET]
        for o in pending:  # sequential: order detail allows 2 calls / 2 s
            try:
                merged[o.client_order_id] = await self._refresh(o)
            except BrokerError:
                pass
        for meta in self._combos.values():
            for leg in meta["legs"]:
                merged[f"combo:{leg.client_order_id}"] = leg
        rows = list(merged.values()) + await self.sim.orders()
        rows = [o for o in rows if status is None or o.status == status]
        return sorted(rows, key=lambda o: o.created_at, reverse=True)

    @_guard
    async def cancel(self, order_id: str) -> Order:
        if order_id.startswith("sim-"):
            return await self.sim.cancel(order_id)
        combo = next((cid for cid, m in self._combos.items()
                      if order_id == cid or any(order_id in (o.id, o.client_order_id) for o in m["legs"])), None)
        if combo is not None:  # a Webull option order: cancel it whole (Webull knows only the combo client id)
            try:
                await self.client.request("POST", "/trading/orders/cancel",
                                          body={"account_id": await self._aid(), "client_order_id": combo})
            except WebullAPIError as e:
                if not not_present_refusal(e):
                    raise
            try:
                legs = await self._refresh_combo(combo)
            except BrokerError:
                legs = [o.model_copy(update={"status": "cancelled"}) for o in self._combos[combo]["legs"]]
                self._combos[combo]["legs"] = legs
            return next((o for o in legs if order_id in (o.id, o.client_order_id)), legs[0])
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
        base = local or Order(id=order_id, client_order_id=cid, broker=self.name, symbol="", asset="equity", side="buy",
                              qty=0, type="market", status="open", created_at=now_iso())
        try:
            await self.client.request("POST", "/trading/orders/cancel",
                                      body={"account_id": await self._aid(), "client_order_id": cid})
        except WebullAPIError as e:
            if not not_present_refusal(e):
                raise
            return await self._not_present(base, cid)
        base.status = "cancelled"
        self._placed[cid] = base
        return base

    async def _not_present(self, base: Order, cid: str) -> Order:
        """Cancel answered "Order not present": nothing rests at Webull under this id. A finished order we placed is
        reported as it finished (it may have filled meanwhile); otherwise a clean rejected Order with reason
        "not_found: ...", never an exception."""
        if base.client_order_id in self._placed:
            try:
                fresh = await self._refresh(base)
            except BrokerError:
                fresh = None
            if fresh is not None and fresh.status != "open":
                return fresh
        gone = base.model_copy(update={"status": "rejected", "reject_reason":
                                       f"{NOT_FOUND}: Webull reports order {cid} not present (nothing to cancel)"})
        if cid in self._placed:
            self._placed[cid] = gone
        return gone


def option_strategy(reqs: list[OrderRequest]) -> str | None:
    """Webull's option_strategy for these legs, or None when Webull has no name for the combination (equal quantities
    only): 1 leg SINGLE; 2 legs same expiry same right different strikes VERTICAL; same expiry call + put same strike
    STRADDLE, different strikes STRANGLE; same right same strike different expiries CALENDAR; 4 legs one expiry, two
    puts and two calls IRON_CONDOR."""
    occs = [parse_occ(r.symbol) for r in reqs]
    if not reqs or any(o is None for o in occs) or len({o["underlying"] for o in occs}) != 1:
        return None
    if len({r.qty for r in reqs}) != 1:
        return None
    if len(reqs) == 1:
        return "SINGLE"
    exps, rights, strikes = {o["expiry"] for o in occs}, [o["right"] for o in occs], [o["strike"] for o in occs]
    if len(reqs) == 2:
        a, b = occs
        if a["expiry"] == b["expiry"]:
            if a["right"] == b["right"] and a["strike"] != b["strike"]:
                return "VERTICAL"
            if a["right"] != b["right"]:
                return "STRADDLE" if a["strike"] == b["strike"] else "STRANGLE"
        elif a["right"] == b["right"] and a["strike"] == b["strike"]:
            return "CALENDAR"
        return None
    if len(reqs) == 4 and len(exps) == 1 and sorted(rights) == ["CALL", "CALL", "PUT", "PUT"] \
            and len(set(strikes)) == 4:
        return "IRON_CONDOR"
    return None
