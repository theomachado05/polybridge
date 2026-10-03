import json

import pytest

from app.broker import BrokerError, OrderRequest, SimBroker
from app.broker.quotes import MassiveQuotes, Quote
from tests.test_broker_support import FakeQuotes, run

OCC = "O:ABNB270115C00150000"


def req(**kw):
    base = dict(symbol="ABNB", asset="equity", side="buy", qty=10, type="market", ref_px=100.0)
    base.update(kw)
    return OrderRequest(**base)


@pytest.fixture
def sim(tmp_path):
    return SimBroker(tmp_path / "acct.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "fake_last")},
                                                        option={OCC: Quote(2.0, 0.1, "fake_option_quote")}))


# --- fills, fees, cash ----------------------------------------------------------------------------

def test_starting_account(sim):
    a = run(sim.account())
    assert (a.broker, a.cash, a.equity, a.buying_power, a.currency) == ("sim", 1_000_000.0, 1_000_000.0, 1_000_000.0, "USD")


def test_equity_buy_fills_above_mid_with_per_share_fee(sim):
    o = run(sim.place_order(req()))
    assert o.status == "filled" and o.fill_px == 100.01  # 100 + 1 bp half-spread
    assert o.fee == 0.05 and o.price_source == "supplied" and o.id == "sim-000001"
    a = run(sim.account())
    assert a.cash == pytest.approx(1_000_000 - 1000.10 - 0.05)
    p = run(sim.positions())[0]
    assert (p.symbol, p.qty, p.avg_px, p.mark_px) == ("ABNB", 10, 100.01, 100.0)
    # marked at the mid, so the spread and fee show up as a loss immediately
    assert a.equity == pytest.approx(1_000_000 - 0.10 - 0.05)


def test_equity_sell_fills_below_mid(sim):
    run(sim.place_order(req(side="sell", ref_px=50.0, qty=4)))
    o = run(sim.orders())[0]
    assert o.fill_px == 49.995 and o.fee == 0.02


def test_equity_price_from_massive_last_when_not_supplied(sim):
    o = run(sim.place_order(req(symbol="spy", ref_px=None, qty=2)))
    assert o.status == "filled" and o.symbol == "SPY" and o.price_source == "fake_last"
    assert o.fill_px == round(500 * 1.0001, 4)


def test_no_price_is_rejected_and_account_untouched(sim):
    o = run(sim.place_order(req(symbol="ZZZZ", ref_px=None)))
    assert o.status == "rejected" and o.reject_reason.startswith("no_price")
    assert run(sim.account()).cash == 1_000_000.0 and run(sim.positions()) == []


def test_option_fills_at_quote_mid_plus_half_spread_with_contract_fee_and_multiplier(sim):
    o = run(sim.place_order(OrderRequest(symbol=OCC, asset="option", side="buy", qty=3)))
    assert o.status == "filled" and o.fill_px == 2.1 and o.price_source == "fake_option_quote"
    assert o.fee == pytest.approx(3 * 0.65)
    a = run(sim.account())
    assert a.cash == pytest.approx(1_000_000 - 2.1 * 3 * 100 - 1.95)
    p = run(sim.positions())[0]
    assert p.multiplier == 100 and p.market_value == pytest.approx(2.0 * 3 * 100)
    assert p.unrealized_pnl == pytest.approx((2.0 - 2.1) * 300)
    s = run(sim.place_order(OrderRequest(symbol=OCC, asset="option", side="sell", qty=3)))
    assert s.fill_px == 1.9  # sells at the bid
    assert run(sim.positions()) == []
    assert run(sim.account()).realized_pnl == pytest.approx((1.9 - 2.1) * 300)


def test_option_without_quote_or_price_is_rejected(sim):
    o = run(sim.place_order(OrderRequest(symbol="O:NOPE270115C00001000", asset="option", side="buy", qty=1)))
    assert o.status == "rejected" and "no_price" in o.reject_reason


def test_option_quantity_must_be_whole():
    with pytest.raises(ValueError):
        OrderRequest(symbol=OCC, asset="option", side="buy", qty=1.5)


def test_prediction_leg_fills_at_supplied_book_price_without_extra_spread(sim):
    o = run(sim.place_order(OrderRequest(symbol="poly-123", asset="prediction", side="buy", qty=500, ref_px=0.42)))
    assert o.symbol == "poly-123" and o.fill_px == 0.42 and o.fee == 0.0
    assert run(sim.account()).cash == pytest.approx(1_000_000 - 210.0)
    assert run(sim.orders())[0].price_source == "supplied_book_price"
    bad = run(sim.place_order(OrderRequest(symbol="poly-123", asset="prediction", side="buy", qty=1)))
    assert bad.status == "rejected"
    with pytest.raises(ValueError):
        OrderRequest(symbol="x", asset="prediction", side="buy", qty=1, ref_px=1.5)


# --- shorts ---------------------------------------------------------------------------------------

def test_short_then_cover_realises_the_pnl(sim):
    run(sim.place_order(req(side="sell", qty=100, ref_px=100.0)))  # short at 99.99
    p = run(sim.positions())[0]
    assert p.qty == -100 and p.avg_px == 99.99
    a = run(sim.account())
    assert a.cash == pytest.approx(1_000_000 + 9999.0 - 0.5)
    assert a.buying_power == pytest.approx(a.cash - 1.5 * 100 * 100.0)  # proceeds locked plus 50%
    run(sim.place_order(req(side="buy", qty=100, ref_px=90.0)))  # cover at 90.009
    assert run(sim.positions()) == []
    a = run(sim.account())
    assert a.realized_pnl == pytest.approx((99.99 - 90.009) * 100)
    assert a.cash == pytest.approx(1_000_000 + (99.99 - 90.009) * 100 - 1.0)
    assert a.equity == pytest.approx(a.cash) and a.fees_paid == pytest.approx(1.0)


def test_flipping_through_zero_opens_the_remainder_at_the_fill_price(sim):
    run(sim.place_order(req(qty=10, ref_px=100.0)))
    run(sim.place_order(req(side="sell", qty=25, ref_px=110.0)))
    p = run(sim.positions())[0]
    assert p.qty == -15 and p.avg_px == pytest.approx(109.989)


# --- buying power ---------------------------------------------------------------------------------

def test_insufficient_buying_power_rejects_a_buy(sim):
    o = run(sim.place_order(req(qty=10_000, ref_px=200.0)))  # $2M against $1M
    assert o.status == "rejected" and o.reject_reason == "insufficient_buying_power"
    assert run(sim.account()).cash == 1_000_000.0 and run(sim.positions()) == []
    ok = run(sim.place_order(req(qty=4_000, ref_px=200.0)))
    assert ok.status == "filled"


def test_insufficient_buying_power_rejects_an_oversized_short_but_never_a_cover(tmp_path):
    s = SimBroker(tmp_path / "a.json", starting_cash=10_000.0)
    assert run(s.place_order(req(side="sell", qty=100, ref_px=100.0))).status == "filled"  # $10k short uses $5k of power
    big = run(s.place_order(req(side="sell", qty=100, ref_px=100.0)))
    assert big.status == "rejected" and big.reject_reason == "insufficient_buying_power"
    # the stock rallies and the account is over-extended; closing the short is still allowed
    s.pos["equity|ABNB"]["mark_px"] = 300.0
    assert run(s.account()).buying_power == 0.0
    assert run(s.place_order(req(qty=100, ref_px=300.0))).status == "filled"


# --- limit orders, idempotency, cancel ------------------------------------------------------------

def test_limit_order_rests_then_fills_when_the_price_arrives(sim):
    o = run(sim.place_order(req(type="limit", limit_px=95.0)))
    assert o.status == "open" and run(sim.positions()) == []
    assert [x.id for x in run(sim.orders("open"))] == [o.id]
    # another order in the same name at a lower price sweeps the resting order
    run(sim.place_order(req(side="sell", qty=1, ref_px=94.0)))
    assert run(sim.orders("open")) == []
    assert run(sim.positions())[0].qty == 9  # 10 bought, 1 sold


def test_explicit_sweep_fills_marketable_resting_orders(sim):
    o = run(sim.place_order(req(type="limit", limit_px=95.0)))
    assert run(sim.sweep("ABNB", "equity", mid=99.0)) == []
    filled = run(sim.sweep("ABNB", "equity", mid=94.0))
    assert [f.id for f in filled] == [o.id] and filled[0].fill_px == 94.0


def test_cancel_open_order_and_errors(sim):
    o = run(sim.place_order(req(type="limit", limit_px=1.0)))
    assert run(sim.cancel(o.client_order_id)).status == "cancelled"
    with pytest.raises(BrokerError) as e:
        run(sim.cancel(o.id))
    assert e.value.status_code == 409
    with pytest.raises(BrokerError) as e:
        run(sim.cancel("sim-999999"))
    assert e.value.status_code == 404
    f = run(sim.place_order(req()))
    with pytest.raises(BrokerError):
        run(sim.cancel(f.id))  # filled orders cannot be cancelled


def test_client_order_id_is_idempotent(sim):
    a = run(sim.place_order(req(client_order_id="c-1")))
    b = run(sim.place_order(req(client_order_id="c-1")))
    assert a.id == b.id and len(run(sim.orders())) == 1
    assert run(sim.positions())[0].qty == 10  # not doubled


def test_orders_are_newest_first_and_filterable(sim):
    run(sim.place_order(req()))
    run(sim.place_order(req(symbol="XYZ", qty=1, ref_px=10.0, type="limit", limit_px=1.0)))
    assert [o.symbol for o in run(sim.orders())] == ["XYZ", "ABNB"]
    assert [o.status for o in run(sim.orders("filled"))] == ["filled"]


# --- persistence, determinism, reset --------------------------------------------------------------

def test_state_round_trips_through_the_json_file(tmp_path):
    path = tmp_path / "acct.json"
    a = SimBroker(path, FakeQuotes(option={OCC: Quote(2.0, 0.1, "q")}))
    run(a.place_order(req(side="sell", qty=100)))
    run(a.place_order(OrderRequest(symbol=OCC, asset="option", side="buy", qty=2)))
    run(a.place_order(req(type="limit", limit_px=1.0, qty=1, symbol="LMT")))
    b = SimBroker(path)  # a fresh process
    assert run(b.account()) == run(a.account())
    assert run(b.positions()) == run(a.positions())
    assert run(b.orders()) == run(a.orders())
    nxt = run(b.place_order(req(qty=1)))
    assert nxt.id == "sim-000004"  # the sequence continues
    assert run(b.cancel(run(b.orders("open"))[0].id)).status == "cancelled"  # resting orders survive a restart
    assert json.loads(path.read_text())["version"] == 1


def test_corrupt_state_file_starts_fresh_instead_of_crashing(tmp_path):
    path = tmp_path / "acct.json"
    path.write_text("{not json")
    s = SimBroker(path)
    assert run(s.account()).cash == 1_000_000.0
    run(s.place_order(req()))
    assert json.loads(path.read_text())["seq"] == 1  # rewritten cleanly


def test_same_orders_give_identical_state_and_ids(tmp_path):
    def play(name):
        s = SimBroker(tmp_path / name, clock=lambda: "T")
        for side, qty, px in (("sell", 50, 101.0), ("buy", 20, 99.0), ("sell", 80, 102.5), ("buy", 110, 100.0)):
            run(s.place_order(req(side=side, qty=qty, ref_px=px, client_order_id=f"{side}{qty}")))
        return run(s.account()), run(s.positions()), run(s.orders())
    assert play("a.json") == play("b.json")


def test_reset_restores_the_starting_account(sim, tmp_path):
    run(sim.place_order(req()))
    a = run(sim.reset())
    assert a.cash == 1_000_000.0 and run(sim.positions()) == [] and run(sim.orders()) == []
    assert run(SimBroker(tmp_path / "acct.json").account()).cash == 1_000_000.0  # and it is persisted
    assert run(sim.reset(250_000.0)).cash == 250_000.0
    assert run(sim.place_order(req())).id == "sim-000001"


def test_no_state_file_option_keeps_everything_in_memory():
    s = SimBroker(None)
    run(s.place_order(req()))
    assert len(run(s.orders())) == 1


# --- Massive quote provider (mocked HTTP) ---------------------------------------------------------

class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.payload


class _Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, params))
        for frag, payload in self.routes.items():
            if frag in url:
                return _Resp(payload)
        return _Resp({}, 404)


class _Client:
    def __init__(self, routes):
        self.session = _Session(routes)


def test_massive_quotes_equity_last_trade_and_prev_close_fallback():
    c = _Client({"/v2/last/trade/SPY": {"results": {"p": 501.25}}})
    q = run(MassiveQuotes(lambda: c).equity("SPY"))
    assert q.mid == 501.25 and q.source == "massive_last_trade"
    assert c.session.calls[0][0] == "https://api.massive.com/v2/last/trade/SPY"
    c2 = _Client({"/v2/aggs/ticker/QQQ/prev": {"results": [{"c": 400.0}]}})
    q2 = run(MassiveQuotes(lambda: c2).equity("QQQ"))
    assert q2.mid == 400.0 and q2.source == "massive_prev_close"
    assert run(MassiveQuotes(lambda: c2).equity("NOPE")) is None  # 404s degrade to None, never raise


def test_massive_quotes_option_mid_and_half_spread_then_prev_close():
    c = _Client({f"/v3/quotes/{OCC}": {"results": [{"bid_price": 1.9, "ask_price": 2.1}]}})
    q = run(MassiveQuotes(lambda: c).option(OCC))
    assert q.mid == pytest.approx(2.0) and q.half_spread == pytest.approx(0.1) and q.source == "massive_option_quote"
    assert c.session.calls[0][1] == {"order": "desc", "sort": "timestamp", "limit": 1}
    c2 = _Client({"/v3/quotes/": {"results": []}, "/v2/aggs/ticker/": {"results": [{"c": 3.3}]}})
    q2 = run(MassiveQuotes(lambda: c2).option(OCC))
    assert q2.mid == 3.3 and q2.half_spread is None and q2.source == "massive_option_prev_close"


def test_massive_quotes_without_a_key_return_none():
    assert run(MassiveQuotes(lambda: None).equity("SPY")) is None
    assert run(MassiveQuotes(lambda: None).option(OCC)) is None


def test_massive_quote_timeout_degrades_to_none(monkeypatch):
    import app.chain as chain
    import asyncio

    async def boom(fn, *a):
        raise asyncio.TimeoutError()
    monkeypatch.setattr(chain, "bounded", boom)
    assert run(MassiveQuotes(lambda: object()).equity("SPY")) is None
