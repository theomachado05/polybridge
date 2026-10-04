import pytest
from fastapi.testclient import TestClient

from app.broker import SimBroker
from app.broker.quotes import Quote
from app.main import create_app
from tests.test_broker_support import FakeQuotes

OCC = "O:ABNB270115C00150000"


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.state.broker = SimBroker(tmp_path / "a.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "fake")},
                                                                  option={OCC: Quote(2.0, 0.1, "fake_opt")}))
    with TestClient(app) as c:
        yield c


def buy(client, **kw):
    body = {"symbol": "ABNB", "asset": "equity", "side": "buy", "qty": 10, "ref_px": 100.0, **kw}
    return client.post("/orders", json=body)


def test_account_starts_at_a_million(client):
    r = client.get("/account")
    assert r.status_code == 200
    j = r.json()
    session = {k: j.pop(k) for k in ("market_open", "session", "next_open")}
    assert isinstance(session["market_open"], bool) and session["session"] and session["next_open"].endswith("Z")
    assert (j.pop("options_supported"), j.pop("options_route")) == (True, "sim")
    j = {k: v for k, v in j.items() if v is not None}
    assert j | {"note": None, "account_type": None, "account_class": None, "account_label": None} == {"broker": "sim", "cash": 1_000_000.0, "equity": 1_000_000.0,
                                  "buying_power": 1_000_000.0, "currency": "USD", "simulated": True,
                                  "starting_cash": 1_000_000.0, "realized_pnl": 0.0, "fees_paid": 0.0, "note": None,
                                  "account_type": None, "account_class": None, "account_label": None,
                                  "extended_hours": True}


def test_post_order_fills_and_shows_in_positions_and_orders(client):
    r = buy(client, client_order_id="c1", tag="b1")
    assert r.status_code == 201
    o = r.json()
    assert o["status"] == "filled" and o["fill_px"] == 100.01 and o["broker"] == "sim" and o["tag"] == "b1"
    assert client.get("/positions").json()[0]["qty"] == 10
    assert client.get("/orders").json()[0]["id"] == o["id"]
    assert client.get("/orders", params={"status": "open"}).json() == []
    assert client.get("/orders", params={"status": "bogus"}).status_code == 422


def test_option_order_through_the_api_uses_the_mocked_quote(client):
    r = client.post("/orders", json={"symbol": OCC.lower(), "asset": "option", "side": "buy", "qty": 1})
    assert r.status_code == 201 and r.json()["fill_px"] == 2.1 and r.json()["symbol"] == OCC
    pos = client.get("/positions", params={"refresh": True}).json()[0]
    assert pos["multiplier"] == 100 and pos["mark_px"] == 2.0


def test_rejected_order_is_422_with_the_reason_and_leaves_the_account_alone(client):
    r = buy(client, qty=1_000_000)
    assert r.status_code == 422 and r.json()["detail"] == "insufficient_buying_power"
    assert client.get("/account").json()["cash"] == 1_000_000.0
    assert client.get("/orders", params={"status": "rejected"}).json()[0]["reject_reason"] == "insufficient_buying_power"
    assert buy(client, symbol="NOPE", ref_px=None).status_code == 422


def test_invalid_order_bodies_are_422(client):
    for bad in ({"qty": 0}, {"qty": -1}, {"side": "hold"}, {"type": "limit"}, {"symbol": "  "}, {"asset": "crypto"}):
        assert buy(client, **bad).status_code == 422, bad


def test_delete_cancels_open_orders_only(client):
    oid = buy(client, type="limit", limit_px=1.0).json()["id"]
    assert client.delete(f"/orders/{oid}").json()["status"] == "cancelled"
    assert client.delete(f"/orders/{oid}").status_code == 409
    assert client.delete("/orders/sim-424242").status_code == 404
    filled = buy(client).json()["id"]
    assert client.delete(f"/orders/{filled}").status_code == 409


def test_reset_account(client):
    buy(client)
    r = client.post("/account/reset")
    assert r.status_code == 200 and r.json()["cash"] == 1_000_000.0
    assert client.get("/positions").json() == [] and client.get("/orders").json() == []
    assert client.post("/account/reset", json={"starting_cash": 5000}).json()["cash"] == 5000.0
    assert client.post("/account/reset", json={"starting_cash": -1}).status_code == 422


def test_broker_failure_is_a_502_not_a_500(client):
    from app.broker import BrokerError

    async def boom():
        raise BrokerError("Webull request failed: ConnectError", 502)
    client.app.state.broker.account = boom
    r = client.get("/account")
    assert r.status_code == 502 and "ConnectError" in r.json()["detail"]


def test_refresh_also_re_marks_the_sim_behind_webull(tmp_path):
    import httpx
    from app.broker import WebullBroker, WebullClient

    quotes = FakeQuotes(option={OCC: Quote(2.0, 0.1, "q")})
    sim = SimBroker(tmp_path / "w.json", quotes)
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": {"holdings": []}})))
    app = create_app()
    app.state.broker = WebullBroker(WebullClient("K", "S", http=http), sim, account_id="A")
    with TestClient(app) as c:
        c.post("/orders", json={"symbol": OCC, "asset": "option", "side": "buy", "qty": 1})
        quotes.opt[OCC] = Quote(3.0, 0.1, "q")
        pos = c.get("/positions", params={"refresh": True}).json()
    assert [(p["broker"], p["mark_px"]) for p in pos] == [("sim", 3.0)]


def test_an_unexpected_broker_exception_is_a_502_not_a_500(tmp_path):
    class Broken:
        name = "broken"

        async def account(self):
            raise KeyError("boom")
    app = create_app()
    app.state.broker = Broken()
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/account")
    assert r.status_code == 502 and "KeyError" in r.json()["detail"]
