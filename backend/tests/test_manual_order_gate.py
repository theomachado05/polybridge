"""POST /orders (the manual route) passes the same liquidity caps and capital budget as the bridges and staged plans,
refusing (409) instead of cutting, and failing closed when the budget cannot be checked."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.broker import SimBroker
from app.broker.quotes import Quote
from app.liquidity.service import service_for
from app.main import create_app
from tests.test_broker_support import FakeQuotes

OCC = "O:SPY261218P00650000"


@pytest.fixture
def app(tmp_path):
    a = create_app()
    a.state.broker = SimBroker(tmp_path / "a.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "fake")},
                                                                option={OCC: Quote(2.0, 0.1, "fake_opt")}))
    return a


def order(c, **kw):
    return c.post("/orders", json={"symbol": "SPY", "asset": "equity", "side": "sell", "qty": 10, **kw})


def test_an_equity_order_over_the_participation_cap_is_refused_not_cut(app):
    service_for(app).set_equity("SPY", {"price": 500.0, "adv_shares": 1_000_000, "open5_median_shares": 2_000})
    with TestClient(app) as c:
        r = order(c, qty=201)  # 10% of the opening five-minute volume = 200
        assert r.status_code == 409 and r.json()["detail"].startswith("LIQUIDITY_CAPPED")
        assert "200" in r.json()["detail"]
        assert c.get("/orders").json() == []  # nothing reached the broker
        assert order(c, qty=200, side="buy").status_code == 201


def test_manual_orders_count_toward_the_per_day_participation_cap(app):
    service_for(app).set_equity("SPY", {"price": 500.0, "adv_shares": 30_000, "open5_median_shares": 2_000_000})
    with TestClient(app) as c:  # 1% of ADV = 300 shares per session, summed over both sides
        assert order(c, qty=200, side="buy").status_code == 201
        r = order(c, qty=150, side="buy")
        assert r.status_code == 409 and "at most 100 shares" in r.json()["detail"]


def test_a_short_that_breaches_the_capital_budget_is_refused(app):
    with TestClient(app) as c:  # per-event (unattributed) budget = 20% of $1M = $200k = 400 SPY at $500
        r = order(c, qty=500)
        assert r.status_code == 409 and r.json()["detail"].startswith("CAPITAL_BUDGET")
        assert c.get("/positions").json() == []
        assert order(c, qty=300).status_code == 201


def test_a_long_buy_and_a_short_cover_are_not_budget_checked(app):
    with TestClient(app) as c:
        assert order(c, qty=300).status_code == 201
        assert order(c, qty=300, side="buy").status_code == 201  # only reduces the short
        assert order(c, qty=1_000, side="buy").status_code == 201  # a long buy: the broker's cash check applies
        assert order(c, qty=1_000).status_code == 201  # sells the long: opens nothing


def test_an_unreadable_account_refuses_an_exposure_increasing_order(app):
    async def boom():
        raise RuntimeError("down")

    app.state.broker.account = boom
    with TestClient(app) as c:
        r = order(c, qty=10)
        assert r.status_code == 409 and r.json()["detail"].startswith("CAPITAL_BUDGET")
        assert order(c, qty=10, side="buy").status_code == 201  # a long buy is not a hedge exposure


def test_a_short_with_no_price_is_refused_fail_closed(app):
    with TestClient(app) as c:
        r = order(c, symbol="QQQ", qty=1)
        assert r.status_code == 409 and "no price" in r.json()["detail"]


def test_option_orders_pass_the_option_caps_and_the_premium_budget(app, monkeypatch):
    svc = service_for(app)
    cap = {"n": 5}

    async def view(*_a, **_k):
        return {"available": True, "max_order_contracts": cap["n"]}

    monkeypatch.setattr(svc, "option", view)
    with TestClient(app) as c:
        r = c.post("/orders", json={"symbol": OCC, "asset": "option", "side": "buy", "qty": 6})
        assert r.status_code == 409 and r.json()["detail"].startswith("LIQUIDITY_CAPPED")
        assert c.post("/orders", json={"symbol": OCC, "asset": "option", "side": "buy", "qty": 5}).status_code == 201
        cap["n"] = 50
        # selling a put to open ties up its cash-secured strike: 4 x $650 x 100 = $260k > the $200k event budget
        r = c.post("/orders", json={"symbol": OCC, "asset": "option", "side": "sell", "qty": 9})
        assert r.status_code == 409 and r.json()["detail"].startswith("CAPITAL_BUDGET")
