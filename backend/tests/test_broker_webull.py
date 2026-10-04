import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
from urllib.parse import quote

import httpx
import pytest

import app.broker as broker_mod
from app.broker import BrokerError, OrderRequest, SimBroker, WebullBroker, WebullClient, get_broker
from app.broker.quotes import Quote
from app.broker.webull import SANDBOX_HOST, SIM_NOTE, sign
from tests.test_broker_support import FakeQuotes, run

# Vectors produced by the official Apache-2.0 SDK (webull-openapi-python-sdk 3.0.2, default_signature_composer)
# with a fixed timestamp and nonce, so our signer is checked against Webull's own implementation.
TS, NONCE, HOST = "2026-10-03T12:00:00Z", "nonce-123", "api.sandbox.webull.com"
POST_BODY = {"account_id": "ACC1", "new_orders": [{"client_order_id": "c1", "symbol": "AAPL", "quantity": "10"}]}
SDK_POST_SIG = "Ae7UA04yigWR/iEFlz0dKSCK4Cvky14zE91fXx0jER4="
SDK_GET_SIG = "NX5cVIW3RmZQo3QrwRFrZjRgE9GPj7xifmS9q+YGojs="


def test_signature_matches_the_official_sdk_for_a_post_with_a_body():
    h = sign(app_key="APPKEY", app_secret="SECRET", host=HOST, path="/trading/orders/place", query=None, body=POST_BODY,
             timestamp=TS, nonce=NONCE)
    assert h["x-signature"] == SDK_POST_SIG
    assert h["x-signature-algorithm"] == "HMAC-SHA256" and h["x-signature-version"] == "1.0" and h["x-version"] == "v3"
    assert h["x-app-key"] == "APPKEY" and h["x-timestamp"] == TS and h["x-signature-nonce"] == NONCE


def test_signature_matches_the_official_sdk_for_a_get_with_query_params():
    h = sign(app_key="APPKEY", app_secret="SECRET", host=HOST, path="/trading/assets/balances/get",
             query={"account_id": "ACC1", "total_asset_currency": "USD"}, body=None, timestamp=TS, nonce=NONCE)
    assert h["x-signature"] == SDK_GET_SIG


def test_hmac_sha1_variant_uses_md5_body_digest_per_the_older_docs():
    h = sign(app_key="K", app_secret="S", host=HOST, path="/p", query={"a": "1"}, body={"x": 1}, timestamp=TS,
             nonce=NONCE, algorithm="HMAC-SHA1")
    body_md5 = hashlib.md5(b'{"x":1}').hexdigest().upper()
    s = ("/p&a=1&host=api.sandbox.webull.com&x-app-key=K&x-signature-algorithm=HMAC-SHA1&x-signature-nonce=nonce-123"
         f"&x-signature-version=1.0&x-timestamp={TS}&{body_md5}")
    want = base64.b64encode(hmac.new(b"S&", quote(s, safe="").encode(), hashlib.sha1).digest()).decode()
    assert h["x-signature"] == want and h["x-signature-algorithm"] == "HMAC-SHA1"
    with pytest.raises(ValueError):
        sign(app_key="K", app_secret="S", host=HOST, path="/p", query=None, body=None, timestamp=TS, nonce=NONCE,
             algorithm="MD5")


# --- mocked Webull sandbox --------------------------------------------------------------------------

class Sandbox:
    """Records every request and answers like the Webull sandbox (field names per the public docs/SDK)."""

    def __init__(self, status="FILLED", place_error=None, held=0.0, history=None, open_groups=None, profiles=None):
        self.requests: list[httpx.Request] = []
        self.status, self.place_error, self.held = status, place_error, held
        self.qty: dict[str, str] = {}  # client_order_id -> quantity sent
        # Order list payloads in Webull's documented shape: groups {client_order_id, combo_type, orders: [...]}
        self.history = history or []  # list of pages; each page {"data": [...], "pagination_key"?}
        self.open_groups = open_groups or []
        self.profiles = profiles if profiles is not None else {}  # symbol -> profile row (default: shortable, ETB)

    def handler(self, r: httpx.Request) -> httpx.Response:
        self.requests.append(r)
        p = r.url.path
        if p == "/trading/accounts/list":
            return httpx.Response(200, json=[{"account_id": "ACC-PAPER-1", "account_type": "MARGIN"}])  # shorts need margin
        if p == "/trading/assets/balances/get":
            return httpx.Response(200, json={"total_asset_currency": "USD", "total_net_liquidation_value": "101500.5",
                                             "account_currency_assets": [{"currency": "USD", "cash_balance": "90000",
                                                                          "buying_power": "180000"}]})
        if p == "/trading/assets/positions/list":
            rows = [{"symbol": "AAPL", "quantity": str(self.held), "cost_price": "150", "last_price": "160"}] if self.held else []
            return httpx.Response(200, json={"data": {"holdings": rows}})
        if p == "/trading/orders/place":
            if self.place_error:
                return httpx.Response(400, json={"error_code": "INVALID", "message": self.place_error})
            item = json.loads(r.content)["new_orders"][0]
            self.qty[item["client_order_id"]] = item["quantity"]
            return httpx.Response(200, json={"data": {"client_order_id": item["client_order_id"], "order_id": "WB-1"}})
        if p == "/trading/orders/get":
            cid = r.url.params["client_order_id"]
            return httpx.Response(200, json={"data": {"order_id": "WB-1", "status": self.status,
                                                      "filled_quantity": self.qty.get(cid, "10"), "filled_price": "189.9",
                                                      "client_order_id": cid}})
        if p == "/trading/orders/open-orders/list":
            return httpx.Response(200, json={"data": self.open_groups})
        if p == "/trading/orders/historical-orders/list":
            key = r.url.params.get("pagination_key")
            i = int(key) if key else 0
            return httpx.Response(200, json=self.history[i] if i < len(self.history) else {"data": []})
        if p == "/trading/instruments/stocks/profiles/list":
            syms = r.url.params["symbols"].split(",")
            rows = [{"symbol": s, "status": "OC", "shortable": True, "easy_to_borrow": True, "marginable": True,
                     "margin_requirement_short": "0.5", **self.profiles.get(s, {})}
                    for s in syms if self.profiles.get(s, {}) is not None and s != "UNLISTED"]
            return httpx.Response(200, json={"data": rows})
        if p == "/trading/orders/cancel":
            return httpx.Response(200, json={"client_order_id": json.loads(r.content)["client_order_id"]})
        return httpx.Response(404, json={"message": "no route " + p})


def make(sandbox, tmp_path, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(sandbox.handler))
    client = WebullClient("APPKEY", "SECRET", http=http, now=lambda: dt.datetime(2026, 10, 3, 12, 0, 0, tzinfo=dt.UTC),
                          nonce=lambda: NONCE, **kw)
    sim = SimBroker(tmp_path / "s.json", FakeQuotes(option={"O:X270115C00001000": Quote(2.0, 0.1, "q")}), order_note=SIM_NOTE)
    return WebullBroker(client, sim)


def test_account_uses_the_first_paper_account_and_reads_balance(tmp_path):
    sb = Sandbox()

    async def go():
        b = make(sb, tmp_path)
        return await b.account()
    a = run(go())
    assert (a.broker, a.cash, a.equity, a.buying_power, a.currency) == ("webull-paper", 90000.0, 101500.5, 180000.0, "USD")
    bal = sb.requests[1]
    assert bal.method == "GET" and bal.url.params["account_id"] == "ACC-PAPER-1" and bal.url.host == HOST


def test_every_request_is_signed_and_the_signature_verifies(tmp_path):
    sb = Sandbox()

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="aapl", asset="equity", side="buy", qty=10,
                                                                 client_order_id="cid-1"))
    run(go())
    for r in sb.requests:
        h = r.headers
        body = json.loads(r.content) if r.content else None
        again = sign(app_key="APPKEY", app_secret="SECRET", host=r.url.host, path=r.url.path,
                     query=dict(r.url.params), body=body, timestamp=h["x-timestamp"], nonce=h["x-signature-nonce"])
        assert h["x-signature"] == again["x-signature"], r.url.path
        assert h["x-app-key"] == "APPKEY" and "SECRET" not in str(dict(h)) and h["x-version"] == "v3"
        if r.content:  # the bytes sent are the compact JSON that was hashed
            assert r.content == json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def test_equity_order_request_shape_and_fill_status(tmp_path):
    sb = Sandbox()

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="aapl", asset="equity", side="buy", qty=10,
                                                                 client_order_id="cid-1", tag="bridge-9"))
    o = run(go())
    place = next(r for r in sb.requests if r.url.path == "/trading/orders/place")
    assert place.method == "POST" and place.headers["content-type"] == "application/json"
    assert json.loads(place.content) == {"account_id": "ACC-PAPER-1", "new_orders": [{
        "client_order_id": "cid-1", "combo_type": "NORMAL", "symbol": "AAPL", "instrument_type": "EQUITY", "market": "US",
        "order_type": "MARKET", "quantity": "10", "support_trading_session": "CORE", "side": "BUY",
        "time_in_force": "DAY", "entrust_type": "QTY"}]}
    assert (o.broker, o.id, o.status, o.filled_qty, o.fill_px, o.tag) == ("webull-paper", "WB-1", "filled", 10, 189.9, "bridge-9")


def test_limit_order_carries_a_limit_price_and_open_status_is_reported(tmp_path):
    sb = Sandbox(status="SUBMITTED")

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=5,
                                                                 type="limit", limit_px=187.5, client_order_id="c2"))
    o = run(go())
    item = json.loads(next(r for r in sb.requests if r.url.path == "/trading/orders/place").content)["new_orders"][0]
    assert item["order_type"] == "LIMIT" and item["limit_price"] == "187.5" and item["quantity"] == "5"
    assert o.status == "open"


def _placed(sb):
    return [json.loads(r.content)["new_orders"][0] for r in sb.requests if r.url.path == "/trading/orders/place"]


def test_selling_more_than_held_is_a_short_and_selling_held_shares_is_a_sell(tmp_path):
    for held, qty, side in ((0.0, 10, "SHORT"), (-30.0, 10, "SHORT"), (50.0, 10, "SELL")):
        sb = Sandbox(held=held)

        async def go():
            return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=qty,
                                                                     client_order_id="s"))
        run(go())
        items = _placed(sb)
        assert [i["side"] for i in items] == [side] and items[0]["quantity"] == "10", (held, qty)


def test_a_sell_larger_than_the_long_position_is_split_into_a_sell_and_a_short(tmp_path):
    sb = Sandbox(held=4.0)
    b = make(sb, tmp_path)

    async def go():
        o = await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=10, client_order_id="s"))
        again = await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=10, client_order_id="s"))
        return o, again, await b.orders()
    o, again, rows = run(go())
    items = _placed(sb)  # the retry is idempotent: still only two orders at Webull
    assert [(i["side"], i["quantity"], i["client_order_id"]) for i in items] == [("SELL", "4", "s-sell"), ("SHORT", "6", "s-short")]
    assert o.status == "filled" and o.qty == 10 and o.filled_qty == 10 and o.client_order_id == "s"
    assert again.filled_qty == 10 and again.status == "filled"
    assert {r.client_order_id for r in rows} == {"s-sell", "s-short"}


def test_a_rejected_short_leg_is_reported_with_what_did_fill(tmp_path):
    class Half(Sandbox):
        def handler(self, r):
            if r.url.path == "/trading/orders/place" and json.loads(r.content)["new_orders"][0]["side"] == "SHORT":
                self.requests.append(r)
                return httpx.Response(400, json={"message": "not shortable"})
            return super().handler(r)
    sb = Half(held=4.0)

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=10))
    o = run(go())
    assert o.status == "rejected" and o.filled_qty == 4 and "partial: 4 of 10 filled" in o.reject_reason
    assert "not shortable" in o.reject_reason


def test_quantity_and_limit_price_are_exact_decimal_text(tmp_path):
    sb = Sandbox(status="SUBMITTED")

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="BRK.A", asset="equity", side="buy", qty=1234567,
                                                                 type="limit", limit_px=650123.45, client_order_id="big"))
    run(go())
    item = _placed(sb)[0]
    assert item["quantity"] == "1234567" and item["limit_price"] == "650123.45"
    from app.broker.webull import _dec
    assert [_dec(x) for x in (0.00001, 100.0, 0.1, 1e9, 187.5)] == ["0.00001", "100", "0.1", "1000000000", "187.5"]


def test_the_order_note_is_kept_on_a_webull_order(tmp_path):
    sb = Sandbox()

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=1,
                                                                 note="replay: test"))
    assert run(go()).note == "replay: test"


@pytest.mark.parametrize("balance", [{"data": [{"cash_balance": "5", "total_net_liquidation_value": "7"}]},
                                     {"data": None}, {"data": "oops"}, [1, 2], None])
def test_odd_balance_shapes_never_raise_a_non_broker_error(tmp_path, balance):
    def h(r):
        if r.url.path == "/trading/assets/balances/get":
            return httpx.Response(200, json=balance)
        return httpx.Response(200, json=[{"account_id": "A"}])

    async def go():
        b = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(h))), SimBroker(None))
        return await b.account()
    try:
        a = run(go())
        assert a.cash == 5.0 and a.equity == 7.0  # the list-of-one-row shape is understood
    except BrokerError as e:
        assert e.status_code == 502


def test_unexpected_parsing_errors_become_a_502_through_the_api(tmp_path, monkeypatch):
    import app.broker.webull as wb

    def explode(*a, **k):
        raise RuntimeError("surprise")
    monkeypatch.setattr(wb, "_rows", explode)

    async def go():
        b = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(Sandbox().handler))),
                         SimBroker(None))
        return await b.positions()
    with pytest.raises(BrokerError) as e:
        run(go())
    assert e.value.status_code == 502 and "RuntimeError" in e.value.message


def test_a_refused_order_is_a_rejected_order_not_an_exception(tmp_path):
    sb = Sandbox(place_error="insufficient buying power")

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=1))
    o = run(go())
    assert o.status == "rejected" and "insufficient buying power" in o.reject_reason and o.broker == "webull-paper"


def test_network_failure_is_a_clean_broker_error(tmp_path):
    def boom(r):
        raise httpx.ConnectError("down")

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        b = WebullBroker(WebullClient("K", "S", http=http), SimBroker(None), account_id="A")
        return await b.account()
    with pytest.raises(BrokerError) as e:
        run(go())
    assert e.value.status_code == 502 and "ConnectError" in e.value.message


def test_options_and_prediction_legs_route_to_the_sim_and_are_labelled(tmp_path):
    sb = Sandbox()

    async def go():
        b = make(sb, tmp_path)
        o = await b.place_order(OrderRequest(symbol="O:X270115C00001000", asset="option", side="buy", qty=2))
        p = await b.place_order(OrderRequest(symbol="poly-1", asset="prediction", side="buy", qty=100, ref_px=0.3))
        return o, p, await b.orders()
    o, p, orders = run(go())
    assert (o.broker, o.status, o.fill_px, o.note) == ("sim", "filled", 2.1, SIM_NOTE)
    assert (p.broker, p.status, p.note) == ("sim", "filled", SIM_NOTE)
    assert not any(r.url.path == "/trading/orders/place" for r in sb.requests)  # nothing went to Webull
    assert {x.id for x in orders} == {o.id, p.id}


def test_positions_list_webull_equities_plus_labelled_sim_legs(tmp_path):
    sb = Sandbox(held=7.0)

    async def go():
        b = make(sb, tmp_path)
        await b.place_order(OrderRequest(symbol="O:X270115C00001000", asset="option", side="buy", qty=1))
        return await b.positions()
    ps = run(go())
    by = {p.symbol: p for p in ps}
    assert by["AAPL"].broker == "webull-paper" and by["AAPL"].qty == 7 and by["AAPL"].unrealized_pnl == 70
    assert by["O:X270115C00001000"].broker == "sim"


def test_cancel_posts_the_client_order_id(tmp_path):
    sb = Sandbox(status="SUBMITTED")

    async def go():
        b = make(sb, tmp_path)
        o = await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=1, client_order_id="cx"))
        return await b.cancel(o.id)  # by Webull order id
    o = run(go())
    cancel = next(r for r in sb.requests if r.url.path == "/trading/orders/cancel")
    assert json.loads(cancel.content) == {"account_id": "ACC-PAPER-1", "client_order_id": "cx"}
    assert o.status == "cancelled"


def test_orders_merge_webull_and_sim_and_filter_by_status(tmp_path):
    sb = Sandbox()

    async def go():
        b = make(sb, tmp_path)
        await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=1, client_order_id="e1"))
        await b.place_order(OrderRequest(symbol="O:X270115C00001000", asset="option", side="buy", qty=1))
        return await b.orders(), await b.orders("filled"), await b.orders("open")
    allo, filled, opn = run(go())
    assert {o.broker for o in allo} == {"webull-paper", "sim"} and len(filled) == 2 and opn == []


def test_configured_account_id_skips_the_account_list(tmp_path):
    sb = Sandbox()

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(sb.handler))
        b = WebullBroker(WebullClient("K", "S", http=http), SimBroker(None), account_id="MINE")
        await b.account()
        await b.account()
    run(go())
    paths = [r.url.path for r in sb.requests]  # the list is read once, only for the account's type / class
    assert paths.count("/trading/accounts/list") == 1 and paths.count("/trading/assets/balances/get") == 2
    assert all(r.url.params["account_id"] == "MINE" for r in sb.requests if r.url.path != "/trading/accounts/list")


# --- the factory ------------------------------------------------------------------------------------

def test_factory_default_is_the_sim(monkeypatch):
    monkeypatch.setattr(broker_mod, "_env", lambda n: "")  # hermetic: a developer .env may say BROKER=webull
    broker_mod.reset_default_broker()
    try:
        assert get_broker().name == "sim"
    finally:
        broker_mod.reset_default_broker()


def test_factory_webull_needs_both_the_switch_and_both_keys(monkeypatch):
    monkeypatch.setattr(broker_mod, "_env", lambda n: {"BROKER": "webull", "WEBULL_APP_KEY": "k"}.get(n, ""))
    assert broker_mod.build_broker().name == "sim"  # secret missing: graceful fallback, no crash
    monkeypatch.setattr(broker_mod, "_env", lambda n: {"BROKER": "webull", "WEBULL_APP_KEY": "k", "WEBULL_APP_SECRET": "s"}.get(n, ""))
    b = broker_mod.build_broker()
    assert b.name == "webull-paper" and b.client.base_url == SANDBOX_HOST and b.client.host == HOST
    monkeypatch.setattr(broker_mod, "_env", lambda n: {"WEBULL_APP_KEY": "k", "WEBULL_APP_SECRET": "s"}.get(n, ""))
    assert broker_mod.build_broker().name == "sim"  # keys alone do not switch the broker


def test_factory_pins_app_state_broker():
    class S: pass
    class A: state = S()
    fake = SimBroker(None)
    A.state.broker = fake
    assert get_broker(A) is fake


# --- review fixes: sandbox-only host, 5xx after acceptance, find_order -------------------------------

@pytest.mark.parametrize("url", ["https://api.webull.com", "https://api.webull.com/", "http://api.sandbox.webull.com",
                                 "https://api.sandbox.webull.com.evil.example", "https://evil.example"])
def test_client_refuses_any_host_but_the_paper_sandbox(url):
    from app.broker.webull import NotSandboxHost
    with pytest.raises(NotSandboxHost):
        WebullClient("K", "S", url)
    assert WebullClient("K", "S", "https://api.sandbox.webull.com/").base_url == SANDBOX_HOST


def test_factory_falls_back_to_the_sim_for_a_production_webull_host(monkeypatch, caplog):
    env = {"BROKER": "webull", "WEBULL_APP_KEY": "k", "WEBULL_APP_SECRET": "s", "WEBULL_BASE_URL": "https://api.webull.com"}
    monkeypatch.setattr(broker_mod, "_env", lambda n: env.get(n, ""))
    with caplog.at_level("ERROR"):
        b = broker_mod.build_broker()
    assert b.name == "sim" and isinstance(b, SimBroker)
    assert any("not the paper sandbox" in r.getMessage() for r in caplog.records)


def _place_status_sandbox(code, known):
    sb = Sandbox()
    inner = sb.handler

    def handler(r):
        if r.url.path == "/trading/orders/place":
            sb.requests.append(r)
            item = json.loads(r.content)["new_orders"][0]
            sb.qty[item["client_order_id"]] = item["quantity"]
            return httpx.Response(code, json={"message": "gateway"})
        if r.url.path == "/trading/orders/get" and not known:
            sb.requests.append(r)
            return httpx.Response(404, json={"message": "order not found"})
        return inner(r)
    return sb, handler


@pytest.mark.parametrize("code", [500, 502, 429])
def test_5xx_or_429_on_place_reports_what_webull_knows_not_a_reject(tmp_path, code):
    sb, handler = _place_status_sandbox(code, known=True)

    async def go():
        b = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
                         SimBroker(None), account_id="A")
        return await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=10, client_order_id="c5"))
    o = run(go())
    assert o.status == "filled" and o.filled_qty == 10 and o.client_order_id == "c5"


def test_5xx_on_place_with_an_unknown_order_raises_instead_of_booking_a_reject(tmp_path):
    sb, handler = _place_status_sandbox(503, known=False)

    async def go():
        b = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
                         SimBroker(None), account_id="A")
        return await b.place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=10, client_order_id="c6"))
    with pytest.raises(BrokerError):
        run(go())


def test_4xx_on_place_is_still_a_rejected_order(tmp_path):
    sb = Sandbox(place_error="insufficient buying power")

    async def go():
        return await make(sb, tmp_path).place_order(OrderRequest(symbol="AAPL", asset="equity", side="buy", qty=10,
                                                                 client_order_id="c7"))
    o = run(go())
    assert o.status == "rejected" and "insufficient" in (o.reject_reason or "")


def test_find_order_reads_an_order_placed_elsewhere_by_client_id_and_none_when_unknown(tmp_path):
    sb = Sandbox()

    async def go():
        b = make(sb, tmp_path)
        found = await b.find_order("bridge-7")
        _, handler = _place_status_sandbox(500, known=False)
        b2 = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
                          SimBroker(None), account_id="A")
        return found, await b2.find_order("nope")
    found, missing = run(go())
    assert found is not None and found.status == "filled" and found.client_order_id == "bridge-7"
    assert missing is None


def test_fill_price_is_read_from_the_avg_price_key_too():
    from app.broker.webull import order_from_webull
    o = order_from_webull({"order_id": "1", "status": "FILLED", "filled_quantity": "5", "avg_price": "10.5",
                           "client_order_id": "c"})
    assert o.fill_px == 10.5


# --- review fix: a split sell whose second leg fails is still reconciled by the parent client id --------

class ShortLegFails(Sandbox):
    """Holds 4: a sell of 10 is SELL 4 (fills) + SHORT 6, whose POST answers 503. Webull does not know the SHORT leg
    (``short_known`` False) or took it anyway (True, it then fills)."""

    def __init__(self, short_known=False, **kw):
        super().__init__(held=4.0, **kw)
        self.short_known = short_known

    def handler(self, r):
        p = r.url.path
        if p == "/trading/orders/place" and json.loads(r.content)["new_orders"][0]["side"] == "SHORT":
            self.requests.append(r)
            item = json.loads(r.content)["new_orders"][0]
            if self.short_known:
                self.qty[item["client_order_id"]] = item["quantity"]
            return httpx.Response(503, json={"message": "gateway"})
        if p == "/trading/orders/get" and r.url.params["client_order_id"] not in self.qty:
            self.requests.append(r)
            return httpx.Response(404, json={"message": "order not found"})
        return super().handler(r)


def _sell10(cid="sp"):
    return OrderRequest(symbol="AAPL", asset="equity", side="sell", qty=10, client_order_id=cid)


def test_a_split_whose_short_leg_fails_unconfirmed_is_found_by_the_parent_id_with_what_filled(tmp_path):
    sb = ShortLegFails()
    b = make(sb, tmp_path)

    async def go():
        with pytest.raises(BrokerError):  # the caller tracks "sp" as unconfirmed
            await b.place_order(_sell10())
        return await b.find_order("sp")
    o = run(go())
    assert o is not None and o.client_order_id == "sp" and o.id == "sp"
    assert o.filled_qty == 4 and o.qty == 10  # the SELL leg filled; the SHORT leg never reached Webull
    assert o.status == "cancelled"  # done: nothing more can trade


def test_a_split_short_leg_webull_took_despite_the_5xx_is_counted(tmp_path):
    sb = ShortLegFails(short_known=True)
    b = make(sb, tmp_path)

    async def go():
        o = await b.place_order(_sell10())  # _submit asks Webull, which knows the SHORT leg: no exception
        return o, await b.find_order("sp")
    o, again = run(go())
    assert o.status == "filled" and o.filled_qty == 10 and again.filled_qty == 10


def test_a_split_interrupted_before_its_short_leg_answers_keeps_its_legs(tmp_path):
    sb = ShortLegFails()
    b = make(sb, tmp_path)

    async def boom(*a, **kw):
        raise asyncio.CancelledError()  # the bridge's wait_for cancels mid-split

    async def go():
        real = b._submit

        async def submit(req, cid, side, qty):
            if side == "SHORT":
                await boom()
            return await real(req, cid, side, qty)
        b._submit = submit
        with pytest.raises(asyncio.CancelledError):
            await b.place_order(_sell10())
        b._submit = real
        return await b.find_order("sp")
    o = run(go())
    assert b._legs["sp"] == ["sp-sell", "sp-short"]
    assert o.filled_qty == 4 and o.status == "cancelled"


def test_cancelling_a_split_parent_cancels_every_open_leg_and_reports_the_merged_order(tmp_path):
    sb = Sandbox(held=4.0, status="SUBMITTED")
    b = make(sb, tmp_path)

    async def go():
        o = await b.place_order(_sell10("sc"))
        assert o.status == "open" and o.id == "sc"
        sb.status = "CANCELLED"
        return await b.cancel(o.id)
    o = run(go())
    cancelled = [json.loads(r.content)["client_order_id"] for r in sb.requests if r.url.path == "/trading/orders/cancel"]
    assert cancelled == ["sc-sell", "sc-short"]
    assert o.client_order_id == "sc" and o.status == "cancelled"


def test_the_bridge_books_the_filled_sell_leg_of_a_split_whose_short_leg_failed(tmp_path):
    from types import SimpleNamespace

    from app import bridges
    from app.models import MarketRef

    sb = ShortLegFails()
    b = make(sb, tmp_path)
    prop = SimpleNamespace(id="p", ticker="AAPL", shares_held=100, target_coverage=0.5, family="hedge")
    bridge = bridges.Bridge(prop, "live", MarketRef(source="polymarket", id="m", token_id="t"), 1.0)
    req = _sell10("br-1")

    async def go():
        try:
            await b.place_order(req)
        except BrokerError:
            bridges._track_unconfirmed(bridge, b, req, "equity")
        return await bridges._settle_resting(bridge, None, b, "replace")
    assert run(go()) is True
    assert bridge.resting is None
    assert bridge.broker_hedge == 4.0 and bridge.account_hedge == 4.0  # never dropped as "unknown, nothing traded"


def test_account_serves_the_last_good_read_when_webull_rate_limits(tmp_path):
    """The nav polls /account on every page; a Webull 429 must not turn the header into a broker error."""
    calls = {"n": 0}

    def h(r):
        if r.url.path == "/trading/assets/balances/get":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, json={"cash_balance": 5.0, "total_net_liquidation_value": 7.0})
            return httpx.Response(429, json={"message": "Too many requests"})
        return httpx.Response(200, json=[{"account_id": "A"}])

    async def go():
        b = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(h))), SimBroker(None))
        first = await b.account()
        second = await b.account()
        b._last_account = (b._last_account[0] - 10_000, b._last_account[1])  # too old: the 429 comes through
        with pytest.raises(BrokerError):
            await b.account()
        return first, second
    first, second = run(go())
    assert first.cash == second.cash == 5.0
    assert "rate-limited" in (second.note or "") and "rate-limited" not in (first.note or "")


def test_account_without_a_good_read_still_reports_the_429(tmp_path):
    def h(r):
        if r.url.path == "/trading/assets/balances/get":
            return httpx.Response(429, json={"message": "Too many requests"})
        return httpx.Response(200, json=[{"account_id": "A"}])

    async def go():
        b = WebullBroker(WebullClient("K", "S", http=httpx.AsyncClient(transport=httpx.MockTransport(h))), SimBroker(None))
        await b.account()
    with pytest.raises(BrokerError):
        run(go())
