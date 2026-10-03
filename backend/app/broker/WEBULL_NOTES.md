# Webull paper integration notes

What the Webull OpenAPI offers for this integration, what we verified against the paper sandbox, and what stays
unverified. Researched 2026-10-03 (a Saturday: the market was closed, so no order was placed). Sources are listed at
the end. Every live check below was a read-only `GET` against `https://api.sandbox.webull.com` (`make webull-check`).

## Verified live (read-only, 2026-10-03)

| Call | Result |
|---|---|
| `GET /trading/accounts/list` | 5 accounts. In use: `WEBULL_ACCOUNT_ID` = `INDIVIDUAL_MARGIN` ("Individual Margin", type `MARGIN`). |
| `GET /trading/assets/balances/get` | cash $1,000,000, net liquidation $1,000,000, **no `buying_power` key**: `day_buying_power` 4,000,000 (4x), `overnight_buying_power` 2,000,000 (2x), `option_buying_power` 1,000,000, `maintenance_margin` 0, `open_margin_calls` [], `day_trades_left` "UNLIMITED". |
| `GET /trading/assets/positions/list` | `[]` (no positions). |
| `GET /trading/orders/open-orders/list` | `{"data": []}`. |
| `GET /trading/orders/historical-orders/list` | `{"data": []}`, both with no window and with `start_time`/`end_time` in `yyyy-MM-dd'T'HH:mm:ss.SSS'Z'` (accepted, 200). |
| `GET /trading/instruments/stocks/profiles/list?category=US_STOCK&symbols=SPY,AAPL,GME` | `shortable` true, `easy_to_borrow` true, `status` "OC" for all three; GME `marginable` false (100% margin), SPY / AAPL short margin 0.50, maintenance short 0.30. |
| `POST /trading/orders/place` (earlier, same day) | HTTP 417 "Orders cannot be placed at this time ... 9:30 a.m. - 4:00 p.m. ET" for a CORE limit: the sandbox takes orders only in the regular session. |

## 1. Balances and holdings

- `Account.buying_power` = Webull's explicit `buying_power` when present, else **`overnight_buying_power`** (a staged
  hedge is held through a closure, so the 4x intraday figure would overstate deployable capital), else the intraday
  figure. All of `day_buying_power`, `overnight_buying_power`, `option_buying_power`, `settled_cash`,
  `unsettled_cash`, `maintenance_margin`, `init_margin`, `used_margin`, `margin_excess`, `margin_ratio`,
  `open_margin_calls`, `day_trades_left` are passed through on `GET /account`.
- Positions: equity rows as before; `instrument_type: OPTION` rows with `legs` become one `Position` per leg with its
  OCC ticker (`O:SPY261016P00560000`), `multiplier` from `option_contract_multiplier`, and `strategy`. Every Webull row
  has `account: "Webull paper account"`; simulator rows `"Simulated account"`.
- `GET /positions?include_demo=true` appends the seeded demo portfolio as rows with `broker: "demo"`,
  `account: "demo holdings"` (default off: the list stays the broker's book). `GET /portfolio` keeps `holdings`
  (`holdings_label: "demo holdings"`) and adds `broker_account` (label "Webull paper account" | "Simulated account",
  the balances above and the broker positions) plus per holding `broker_qty`, `can_short`, `short_reason`.

## 2. Order history and reconciliation

- History endpoint (SDK `OrderOperationV3.list_order_history`, docs "List Order History"):
  `GET /trading/orders/historical-orders/list`, header `x-version: v3`, query `account_id`, `start_time`, `end_time`
  (`yyyy-MM-dd'T'HH:mm:ss.SSS'Z'`, UTC; default the last 7 days; history goes back to 2018-05-21), `pagination_key`
  (from the previous page; absent on the last page). Response `{data: [{client_order_id, combo_order_id, combo_type,
  orders: [...]}], pagination_key?}`. Webull warns the history "may not return the most recent order data in real time";
  order detail by `client_order_id` is the authority for an order in flight. (The older `x-version: v2` form used
  `start_date` / `end_date` / `page_size` / `last_client_order_id`; we send v3 only.)
- Our bounds: windows of 7 days, newest first; `GET /orders?days=` 1..30 (default 7); at most 5 pages per window,
  then `history_truncated` is set; one read cached 10 s. Rate limits (documented): history, open orders, order
  detail, balances, positions 2 requests / 2 s each; accounts/list 10 / 30 s; instrument profiles 60 / 60 s. The
  network client paces itself to these (`RateLimiter`).
- Open-orders and history payloads are groups `{..., orders: [...]}`: they are flattened (`_order_rows`). Before this
  change the open-orders list was read as if each group were one order (symbol / status missing).
- **Status mapping** (Webull -> ours; raw word kept on `Order.broker_status`):

  | Webull | ours |
  |---|---|
  | `PENDING`, `SUBMITTED`, `PENDING_CANCEL` | `open` |
  | `PARTIAL_FILLED` | `open` with `filled_qty` > 0 |
  | `FILLED` | `filled` |
  | `CANCELLED`, `CANCELED`, `EXPIRED` | `cancelled` (keeps any `filled_qty`) |
  | `FAILED`, `REJECTED` | `rejected` |
  | anything else / missing | `open` (keep tracking; never booked as done) |

- `Order.origin`: `polybridge` (placed through this app), `webull_open`, `webull_history` (e.g. placed in the Webull app).
- **Reconciliation** (`broker/reconcile.py`): every 15 s during the regular session one pass reads the open-orders list
  once, settles every order we placed that is still open locally (still open at Webull -> its partial fill; gone from
  the list -> its final state from order detail, at most 4 detail reads per pass, the rest next pass), refreshes open
  Webull option orders, and counts open orders placed elsewhere. One more pass runs right after the close (late fills),
  then it idles until the next regular open (re-checking at most every 5 min). Failures back off 15 / 30 / 60 / 120 s;
  a failing pass never stops the loop. It starts on the first broker request when `BROKER=webull`
  (`WEBULL_RECONCILE=0` turns auto-start off) and is controlled with `GET /broker/reconcile`,
  `POST /broker/reconcile/start|stop|run`; the router's shutdown hook stops it.

## 3. Options at Webull

- **Documented:** the Trading API supports US options through the same `POST /trading/orders/place` with
  `instrument_type: OPTION`, a `legs` array (`side`, `quantity`, `symbol` = underlying, `strike_price`,
  `option_expire_date`, `option_type` CALL/PUT, `market` US) and `option_strategy`: `SINGLE`, `COVERED_STOCK`,
  `VERTICAL`, `STRADDLE`, `STRANGLE`, `CALENDAR`, `BUTTERFLY`, `CONDOR`, `IRON_BUTTERFLY`, `IRON_CONDOR`,
  `COLLAR_WITH_STOCK`, `DIAGONAL`. Order types MARKET / LIMIT / STOP_LOSS / STOP_LOSS_LIMIT; TIF DAY / GTC;
  multi-leg strategies take `combo_type: NORMAL` only. The SDK (3.0.2) adds a `category: US_OPTION` header on option
  placement; the docs' examples do not, and we do not send it.
- **Not verified on the paper sandbox:** no document says the sandbox / paper account accepts option orders, the
  account's option approval level is not exposed, and with the market closed nothing could be tested (the sandbox
  417s every order outside 09:30-16:00 ET). Also unverified: whether a sell-to-open leg must be `SHORT` rather than
  `SELL`, and whether leg `quantity` is a ratio (we send ratio 1 with the order-level quantity = contracts).
- **What we built:** option placement behind the capability flag `options_supported` (`WEBULL_OPTIONS=1`, **default
  off**). Off: option legs go to the simulator with the existing label (`SIM_NOTE`). On: a single leg is a `SINGLE`
  order (MARKET, or LIMIT at its `limit_px`); a combo is mapped to `VERTICAL`, `STRADDLE`, `STRANGLE`, `CALENDAR` or
  `IRON_CONDOR` (equal quantities) and sent as one net LIMIT at the quoted mids plus the half-spreads (debit = BUY,
  credit = SELL); any other combination goes to the simulator, labelled why; a structure with no prices is refused,
  never sent at market. Webull reports one net fill price for a multi-leg order: each leg's `fill_px` is its quoted
  mid with the difference put on the first leg, so the legs' signed sum equals Webull's net
  (`price_source: webull_paper_net_allocated`). Cancel uses the combo client id. Tested with mocked HTTP only.
- **To turn it on:** during market hours, set `WEBULL_OPTIONS=1` and place one far-from-market single-leg limit
  through the API, read it back, cancel it; only then rely on it.

## 4. Short-sale readiness

- `GET /trading/instruments/stocks/profiles/list?category=US_STOCK&symbols=...` (up to 100 symbols) returns
  `shortable`, `easy_to_borrow`, `marginable`, `status` (`OC` tradable, `CO` liquidate only, `NT` not tradable) and
  the short margin ratios. No borrow rate or locate quantity is exposed.
- `broker.can_short(symbol)`: `True` (shortable, `OC`), `False` (not shortable, `CO` / `NT`, or a cash account:
  Webull shorts only in margin accounts), `None` (lookup failed or not listed). Cached 15 min. A hard-to-borrow name
  (`easy_to_borrow` false) is `True` with a warning in `reason`. `SimBroker.can_short` is `True` (simulated, no borrow
  model).
- Surfaced at `GET /broker/capabilities?symbols=SPY,TLT`, `GET /broker/shortable/{symbol}`, `GET /portfolio`
  (per holding) and `make webull-check`.
- Enforced: a SHORT (or the short leg of a split sell) of a symbol Webull lists as not shortable / `CO` / `NT` is
  refused before it is sent (`reject_reason` `not_shortable: ...`); an unknown answer never blocks (Webull itself
  refuses what it will not take, as a clean rejected order).

## Sources

- Webull Trading API overview, feature matrix and rate limits: https://developer.webull.com/apis/docs/trade-api/overview
- Options trading (strategies, multi-leg examples): https://developer.webull.com/apis/docs/trade-api/options
- Stock orders (`BUY` / `SELL` / `SHORT`): https://developer.webull.com/apis/docs/trade-api/stock
- List Order History: https://developer.webull.com/apis/docs/reference/order-history
- Open Orders: https://developer.webull.com/apis/docs/reference/order-open
- Order Detail: https://developer.webull.com/apis/docs/reference/order-detail
- Stock Instruments (shortable / easy_to_borrow): https://developer.webull.com/apis/docs/reference/instrument-list
- Account Balance / Positions / List: https://developer.webull.com/apis/docs/reference/account-balance,
  .../account-position, .../account-list
- Official Python SDK, Apache-2.0, `webull-openapi-python-sdk` 3.0.2 (PyPI): `webull/trade/trade/v3/order_operation_v3.py`
  (`list_order_history`, `list_order_open`), `webull/trade/request/v3/get_order_history_request_v2.py`,
  `webull/trade/request/v3/place_order_request.py`, `samples/trade/trade_client_v3.py` (option order example)
