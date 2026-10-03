"""Liquidity and capacity (app/liquidity): the caps and cost model, the Massive / venue-book service (mocked HTTP), the
routes (never a 500), and the liquidity gate on every order path (bridge equity orders, staged hedge B, option legs,
hedge A's PM leg)."""
from __future__ import annotations

import asyncio
import datetime as dt
import math
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.liquidity import gate, model as m
from app.liquidity import service as svc_mod
from app.liquidity.service import LiquidityService, service_for
from app.main import create_app

ET = ZoneInfo("America/New_York")


# ------------------------------------------------------------------------------------------------- the model


def test_equity_caps_are_10pct_of_the_opening_five_minutes_and_1pct_of_adv():
    lim = m.equity_limits(adv_shares=2_000_000, open5_shares=50_000)
    assert (lim["per_order_shares"], lim["per_day_shares"], lim["max_order_shares"]) == (5_000, 20_000, 5_000)
    assert lim["binding"] == "per_order_open5" and lim["max_position_shares"] == 20_000
    lim = m.equity_limits(adv_shares=100_000, open5_shares=50_000)  # a thin name: the daily cap binds
    assert (lim["max_order_shares"], lim["binding"]) == (1_000, "per_day_adv")
    assert m.equity_limits(None, None)["max_order_shares"] is None


def test_cost_is_half_spread_plus_square_root_impact():
    c = m.equity_cost_bp(10_000, half_spread_bp=1.0, adv_shares=1_000_000, sigma_daily=0.02)
    assert c["impact_bp"] == pytest.approx(1.0 * 0.02 * math.sqrt(0.01) * 1e4)  # 20 bp
    assert c["total_bp"] == pytest.approx(21.0)
    assert m.equity_cost_bp(10, None, 1e6, 0.02)["total_bp"] is None  # no spread: no total, never invented


def test_capacity_is_the_holding_whose_hedge_fits_one_order_at_the_open():
    cap = m.equity_capacity({"adv_shares": 1e6, "price": 100.0, "sigma_daily": 0.01}, 20_000, 2.0, coverage=0.5)
    assert cap["max_order_shares"] == 2_000
    assert cap["capacity"]["book_usd"] == pytest.approx(2_000 * 100.0 / 0.5)
    assert cap["capacity"]["book_usd_within_one_session"] == pytest.approx(10_000 * 100.0 / 0.5)
    assert cap["est_cost_bp"] == pytest.approx(1.0 + 1e4 * 0.01 * math.sqrt(2_000 / 1e6))


def test_corwin_schultz_and_daily_stats():
    bars = [{"v": 1e6, "vw": 100.0, "c": 100.0 + i * 0.1, "h": 101.0 + i * 0.1, "l": 99.0 + i * 0.1, "t": i}
            for i in range(25)]
    st = m.daily_stats(bars)
    assert st["n_sessions"] == 20 and st["adv_shares"] == 1e6 and st["adv_usd"] == pytest.approx(1e8)
    assert st["price"] == pytest.approx(102.4) and st["sigma_daily"] is not None and st["sigma_daily"] < 0.01
    assert st["cs_spread_bp"] is not None and st["cs_spread_bp"] >= 0
    assert m.corwin_schultz_bp([{"h": 1, "l": 1}]) is None


def test_option_caps_need_both_volume_and_open_interest():
    lim = m.option_limits(volume=1_000, open_interest=4_000)
    assert (lim["per_order_contracts"], lim["binding"]) == (100, "volume")  # 10% of 1,000 vs 5% of 4,000 = 200
    assert m.option_limits(volume=1_000, open_interest=None)["per_order_contracts"] is None
    cap = m.option_capacity(1_000, 4_000, 2.0, 2.2, 2.1, spot=500.0, delta=-0.4, coverage=0.5)
    assert cap["spread_bp"] == pytest.approx(0.2 / 2.1 * 1e4) and cap["capacity"]["shares_equiv"] == 10_000
    assert cap["capacity"]["book_usd"] == pytest.approx(10_000 * 0.4 * 500.0 / 0.5)


def test_pm_depth_bands_cap_and_book_walk():
    bids = [(0.49, 100.0), (0.48, 200.0), (0.45, 1_000.0)]
    asks = [(0.51, 50.0), (0.52, 150.0), (0.60, 5_000.0)]
    d = m.pm_depth(bids, asks)
    assert d["mid"] == pytest.approx(0.50)
    assert d["buy"]["1c"]["contracts"] == 50 and d["buy"]["2c"]["contracts"] == 200 and d["buy"]["5c"]["contracts"] == 200
    assert d["sell"]["2c"]["contracts"] == 300 and d["sell"]["5c"]["contracts"] == 1_300
    assert m.pm_cap(d, "buy") == 100 and m.pm_cap(d, "sell") == 150  # 50% of the depth within 2 cents
    w = m.walk_cost(asks, 100, d["mid"], "buy")
    assert w["avg_px"] == pytest.approx((50 * 0.51 + 50 * 0.52) / 100) and w["cost_cents"] == pytest.approx(1.5)
    assert m.pm_depth([], asks)["mid"] is None


# ------------------------------------------------------------------------------------------- the service


class FakeResp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def et_ms(d: dt.date, h: int, mi: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, h, mi, tzinfo=ET).timestamp() * 1000)


def sessions(n: int) -> list[dt.date]:
    d, out = dt.date(2026, 10, 2), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= dt.timedelta(days=1)
    return out[::-1]


class FakeMassive:
    """A Massive client: daily bars (1M shares at $100), 5-minute bars (the 09:30 bar 40,000 shares), last quote."""

    def __init__(self, quote=True, fail=()):
        days = sessions(25)
        self.daily = [{"v": 1_000_000, "vw": 100.0, "c": 100.0 + (i % 3) * 0.5, "h": 101.5, "l": 99.0,
                       "t": et_ms(d, 0, 0)} for i, d in enumerate(days)]
        self.five = []
        for d in days[-20:]:
            self.five += [{"v": 5_000, "t": et_ms(d, 4, 0)}, {"v": 40_000, "t": et_ms(d, 9, 30)},
                          {"v": 20_000, "t": et_ms(d, 9, 35)}]
        self.quote, self.fail, self.paths = quote, set(fail), []
        self.session = SimpleNamespace(get=self.get)

    def get(self, url, params=None, timeout=None):
        self.paths.append(url)
        if "/range/1/day/" in url:
            return FakeResp({"results": self.daily}, 500 if "daily" in self.fail else 200)
        if "/range/5/minute/" in url:
            return FakeResp({"results": self.five})
        if "/v3/quotes/" in url:
            if not self.quote:
                return FakeResp({"results": []})
            ts = int(dt.datetime(2026, 10, 2, 14, 0, tzinfo=dt.timezone.utc).timestamp() * 1e9)
            return FakeResp({"status": "DELAYED", "results": [{"bid_price": 99.99, "ask_price": 100.01,
                                                               "sip_timestamp": ts}]})
        return FakeResp({}, 404)


def run(coro):
    return asyncio.run(coro)


def test_equity_liquidity_from_massive_bars_and_quote():
    s = LiquidityService(client_factory=lambda: FakeMassive())
    out = run(s.equity("spy", coverage=0.5))
    assert out["available"] and out["ticker"] == "SPY"
    assert out["adv_shares"] == 1_000_000 and out["open5_median_shares"] == 40_000
    assert out["per_order_shares"] == 4_000 and out["per_day_shares"] == 10_000 and out["max_order_shares"] == 4_000
    assert out["spread_bp"] == pytest.approx(0.02 / 100.0 * 1e4) and out["spread_source"] == "quote"
    assert out["sources"]["spread"]["phase"] == "regular" and out["sources"]["open5"]["sessions"] == 20
    assert out["capacity"]["book_usd"] == pytest.approx(4_000 * out["price"] / 0.5)
    assert out["cost_model"]["k"] == 1.0 and "sqrt" in out["cost_model"]["formula"]
    assert out["freshness"]["cache_stale"] is False
    # the gate reads the cache, no network
    raw, age = s.cached_equity("SPY")
    assert raw["open5_median_shares"] == 40_000 and age is not None


def test_the_partial_current_session_bar_is_kept_out_of_adv_and_sigma():
    """Massive's daily range runs through today: during the session the last bar is a partial day. It is excluded
    from ADV / sigma (completed sessions only) but still prices the ticker; after the close it counts."""
    mon = dt.date(2026, 10, 5)
    fake = FakeMassive()
    fake.daily.append({"v": 200_000, "vw": 104.0, "c": 105.0, "h": 105.5, "l": 100.0, "t": et_ms(mon, 0, 0)})
    s = LiquidityService(client_factory=lambda: fake)
    s._wall = lambda: dt.datetime(2026, 10, 5, 11, 0, tzinfo=ET)  # Monday, mid-session
    raw = run(s._fetch_equity("SPY"))
    assert raw["adv_shares"] == 1_000_000 and raw["adv_sessions"] == 20
    assert raw["price"] == 105.0 and raw["price_basis"] == "current_session_partial_bar"
    assert raw["partial_session_excluded"] is True and raw["bars_as_of"].startswith("2026-10-02")
    s._wall = lambda: dt.datetime(2026, 10, 5, 16, 30, tzinfo=ET)  # after the close: the bar is complete
    raw = run(s._fetch_equity("SPY"))
    assert raw["adv_shares"] == pytest.approx((19 * 1_000_000 + 200_000) / 20)
    assert raw["partial_session_excluded"] is False and raw["price_basis"] == "last_completed_close"


def test_no_quote_falls_back_to_the_corwin_schultz_estimate_labelled():
    out = run(LiquidityService(client_factory=lambda: FakeMassive(quote=False)).equity("SPY"))
    assert out["spread_source"] == "corwin_schultz_estimate" and out["spread_bp"] > 0
    assert "Corwin-Schultz" in out["sources"]["spread"]["note"]


def test_a_failed_refresh_serves_the_last_value_marked_stale():
    fake = FakeMassive()
    s = LiquidityService(client_factory=lambda: fake)
    assert run(s.equity("SPY"))["available"]
    fake.fail.add("daily")
    out = run(s.equity("SPY", refresh=True))
    assert out["available"] and out["freshness"]["cache_stale"] is True


def test_no_key_is_unavailable_not_an_error():
    out = run(LiquidityService(client_factory=lambda: None).equity("SPY"))
    assert out["available"] is False and "MASSIVE_API_KEY" in out["reason"]


def test_pm_depth_from_the_polymarket_book_and_the_kalshi_twin(monkeypatch):
    from app.twins.store import Twin

    def handler(req: httpx.Request):
        if req.url.path == "/book":
            assert req.url.params["token_id"] == "tokYES"
            return httpx.Response(200, json={"bids": [{"price": "0.49", "size": "100"}, {"price": "0.47", "size": "300"}],
                                             "asks": [{"price": "0.51", "size": "80"}, {"price": "0.56", "size": "900"}]})
        if req.url.path.endswith("/orderbook"):
            return httpx.Response(200, json={"orderbook": {"yes_dollars": [["0.48", 500]], "no_dollars": [["0.50", 400]]}})
        return httpx.Response(404)

    monkeypatch.setattr(svc_mod, "default_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    import app.twins as twins_pkg
    monkeypatch.setattr(twins_pkg, "twin_of", lambda s, i, t=None: Twin("kalshi", "KX-REC"))
    out = run(LiquidityService(client_factory=lambda: None).pm("polymarket", "516710", "tokYES"))
    assert out["available"] and out["depth"]["mid"] == pytest.approx(0.50)
    assert out["depth"]["buy"]["2c"]["contracts"] == 80 and out["depth"]["sell"]["2c"]["contracts"] == 100
    assert out["max_order_contracts"] == {"buy": 40, "sell": 50}
    assert out["est_cost_at_cap"]["buy"]["avg_px"] == pytest.approx(0.51)
    tw = out["twin"]
    assert tw["source"] == "kalshi" and tw["available"] and tw["depth"]["mid"] == pytest.approx(0.49)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_routes_answer_unavailable_offline_and_never_500(client, monkeypatch):
    r = client.get("/liquidity/SPY")
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["caps"]["per_day"].startswith("<= 1%")
    r = client.get("/liquidity/option", params={"underlying": "SPY", "strike": 500, "expiry": "2026-12-18",
                                                "right": "put"})
    assert r.status_code == 200 and r.json()["available"] is False
    r = client.get("/liquidity/pm", params={"source": "polymarket", "id": "516710", "token_id": "123"})
    assert r.status_code == 200 and r.json()["available"] is False and "unavailable" in r.json()["reason"]
    assert client.get("/liquidity/option", params={"underlying": "SPY", "strike": 500, "expiry": "12/18",
                                                   "right": "put"}).status_code == 422
    assert client.get("/liquidity/pm", params={"source": "nyse", "id": "x"}).status_code == 422

    async def boom(*a, **k):
        raise RuntimeError("bad")
    monkeypatch.setattr(service_for(client.app), "equity", boom)
    r = client.get("/liquidity/SPY")
    assert r.status_code == 200 and r.json()["available"] is False and "RuntimeError" in r.json()["reason"]


def test_equity_route_with_a_pinned_massive_client(client):
    client.app.state.liquidity = LiquidityService(client_factory=lambda: FakeMassive())
    j = client.get("/liquidity/SPY", params={"coverage": 0.25, "qty": 1000}).json()
    assert j["available"] and j["capacity"]["coverage"] == 0.25 and j["cost"]["qty"] == 1000


def test_option_route_reads_open_interest_volume_and_spread(client, monkeypatch):
    from app.options import chain as ch

    q = ch.OptionQuote(ticker="O:SPY261218P00500000", kind="put", strike=500.0, expiry="2026-12-18", bid=4.0,
                       ask=4.4, mid=4.2, mark_source="quote", open_interest=20_000, volume=3_000, delta=-0.3)
    chain = ch.Chain(underlying="SPY", fetched_at=0.0, quotes=[q], spot=560.0)

    async def get_chain(*a, **k):
        return chain, False
    monkeypatch.setattr(ch, "get_chain", get_chain)
    client.app.state.liquidity = LiquidityService(client_factory=lambda: object())
    j = client.get("/liquidity/option", params={"underlying": "spy", "strike": 500, "expiry": "2026-12-18",
                                                "right": "put", "coverage": 0.5}).json()
    assert j["available"] and j["contract"] == q.ticker and (j["open_interest"], j["volume"]) == (20_000, 3_000)
    assert j["per_order_contracts"] == 300 and j["binding"] == "volume"  # 10% of 3,000 < 5% of 20,000
    assert j["spread_bp"] == pytest.approx(0.4 / 4.2 * 1e4) and j["capacity"]["delta_shares_equiv"] == pytest.approx(9_000)


# ------------------------------------------------------------------------------------------------- the gate


def pinned_app(open5=1_000.0, adv=50_000.0, price=500.0):
    app = create_app()
    service_for(app).set_equity("SPY", {"price": price, "adv_shares": adv, "sigma_daily": 0.01,
                                        "open5_median_shares": open5, "spread_bp": 1.0, "spread_source": "quote"})
    return app


def test_equity_check_caps_per_order_then_per_day():
    app = pinned_app(open5=1_000.0, adv=50_000.0)  # per order 100, per day 500
    ok = gate.equity_check(app, "SPY", 80, day="2026-10-05")
    assert ok["status"] == "within_caps" and ok["allowed"] == 80
    c = gate.equity_check(app, "SPY", 300, day="2026-10-05")
    assert c["status"] == "capped" and c["allowed"] == 100 and c["limit"] == "per_order_open5"
    assert c["reason"] == "liquidity_capped" and c["capped_from"] == 300
    gate.record_equity(app, "SPY", 450, day="2026-10-05")
    c = gate.equity_check(app, "SPY", 100, day="2026-10-05")
    assert c["allowed"] == 50 and c["limit"] == "per_day_adv"
    assert gate.equity_check(app, "SPY", 100, day="2026-10-06")["status"] == "within_caps"  # a new session
    assert gate.equity_check(app, "SPY", 100, scope="sandbox:b1", day="2026-10-05")["status"] == "within_caps"
    assert gate.equity_check(create_app(), "SPY", 10**6)["status"] == "unknown"


def test_pm_check_on_tick_book_levels():
    f = {"bid_px_0": 0.49, "bid_qty_0": 100.0, "ask_px_0": 0.51, "ask_qty_0": 60.0, "ask_px_1": 0.60, "ask_qty_1": 999}
    c = gate.pm_check(f, "buy", 100)
    assert c["status"] == "capped" and c["allowed"] == 30 and c["limit"] == "pm_depth_2c"
    assert gate.pm_check({"yes_bid": 0.5, "yes_ask": 0.5}, "buy", 100)["status"] == "unknown"  # mid-only replay tick


def test_option_check_caps_by_the_thinnest_leg():
    legs = [SimpleNamespace(ticker="A", volume=1_000.0, open_interest=10_000.0),
            SimpleNamespace(ticker="B", volume=50.0, open_interest=10_000.0)]
    c = gate.option_check(legs, 20)
    assert c["status"] == "capped" and c["allowed"] == 5 and c["leg"] == "B" and c["limit"] == "option_volume"
    assert gate.option_check([SimpleNamespace(ticker="A", volume=float("nan"), open_interest=1.0)], 3)["status"] == "unknown"


class LiveTicks:
    """A live source of four ticks with an equity price (the algo needs under_px)."""

    def __init__(self, *a, **k):
        pass

    def __aiter__(self):
        async def gen():
            from app.ticks import Tick, mid_only_fields
            for i in range(4):
                f = mid_only_fields(0.4)
                f["under_px"] = 500.0
                yield Tick(1_000 + i, 0.4, f)
        return gen()


def live_algo_app(tmp_path, monkeypatch, script, **pin):
    from app import bridges
    from app.broker import SimBroker
    from app.broker.quotes import Quote
    from tests.test_bridges_algo import CATALOG, FakeAlgo
    from tests.test_broker_support import FakeQuotes

    app = pinned_app(**pin)
    app.state.broker = SimBroker(tmp_path / "s.json", FakeQuotes(equity={"SPY": Quote(500.0, None, "q")}))
    app.state.live_source_factory = LiveTicks
    FakeAlgo.script, FakeAlgo.instances = script, []
    monkeypatch.setattr(bridges, "_load_engine", lambda: SimpleNamespace(catalog=lambda: CATALOG, Algo=FakeAlgo))
    return app


def test_bridge_equity_orders_are_capped_with_reason_liquidity_capped(tmp_path, monkeypatch):
    """A live algo bridge whose sell is above 10% of the opening 5-minute volume: the order is capped and says so."""
    from tests.test_bridges import _events
    from tests.test_bridges_algo import FakeAlgo, proposal

    app = live_algo_app(tmp_path, monkeypatch, {2: {"side": -1, "qty": 300.0}}, open5=1_000.0, adv=1_000_000.0)
    with TestClient(app) as c:
        p = proposal(c, {"family": "macro_fed_hedge"})
        r = c.post("/bridges", json={"proposal_id": p["id"], "source": "live"})
        assert r.status_code == 201, r.text
        ev = _events(c, r.json()["bridge_id"])
        f = next(d for k, d in ev if k == "fill")
        assert f["status"] == "filled" and f["qty"] == 100 and f["capped_from"] == 300
        g = next(x for x in f["gates"] if x["reason"] == "liquidity_capped")
        assert g["limit"] == "per_order_open5" and g["limit_qty"] == 100
        assert f["evidence"] == "unvalidated (acknowledged)"
        assert all(d["evidence"] == "unvalidated (acknowledged)" for k, d in ev if k == "decision")
        assert FakeAlgo.instances[0].fills == [("equity", -100.0, pytest.approx(499.95, abs=0.1))]
        s = c.get(f"/bridges/{r.json()['bridge_id']}").json()
        assert s["liquidity_capped"] == 1 and s["reasons"]["liquidity_capped"] == 1
        assert s["evidence"]["validated"] is False and s["evidence_label"] == "unvalidated (acknowledged)"


def test_a_staged_plan_is_capped_by_the_opening_five_minute_volume(tmp_path):
    from tests.test_closed_staged import approved_proposal, make_app

    app = make_app(tmp_path)
    service_for(app).set_equity("SPY", {"price": 500.0, "adv_shares": 1_000_000.0, "sigma_daily": 0.01,
                                        "open5_median_shares": 2_000.0, "spread_bp": 1.0})
    prop = approved_proposal(app)
    with TestClient(app) as c:
        o = c.post("/staged/plan", json={"proposal_id": prop.id, "pm_move_pp": 5.0,
                                         "rate_bp_per_pp": 7.523237932200106}).json()
        assert o["status"] == "staged" and o["qty"] == 200  # 376 wanted, 10% of the 2,000-share opening bar
        assert "LIQUIDITY_CAPPED" in [d["code"] for d in o["decisions"]]
        assert o["sizing"]["liquidity"]["limit"] == "per_order_open5" and o["liquidity"]["capped_from"] == 376


def test_hedge_a_pm_leg_is_capped_at_half_the_depth_within_two_cents():
    """Hedge A's simulated PM leg obeys the PM participation cap on a tick with book depth."""
    from collections import Counter

    from app.closed.bridge_mode import HedgeA

    class Algo:
        def __init__(self):
            self.fills, self.rejects = [], []

        def on_tick(self, tick, now):
            return {"action": "order", "instrument": "pred_yes", "side": 1, "qty": 500.0, "reason": "enter"}

        def on_fill(self, inst, qty, px):
            self.fills.append((inst, qty, px))

        def on_reject(self, inst):
            self.rejects.append(inst)

    h = HedgeA.__new__(HedgeA)
    h.algo, h.contracts, h.cash, h.mark, h.s, h.fills = Algo(), 0.0, 0.0, None, None, []
    h.reasons, h.last_signal, h.liquidity_capped = Counter(), None, 0
    book = {"yes_bid": 0.49, "yes_ask": 0.51, "bid_px_0": 0.49, "bid_qty_0": 100.0, "ask_px_0": 0.51,
            "ask_qty_0": 120.0, "ask_px_1": 0.52, "ask_qty_1": 80.0, "ask_px_2": 0.70, "ask_qty_2": 10_000.0}
    rec = h.step(book, 1, 1, 0, 500.0, lambda f, ts, v: f)
    assert rec["qty"] == 100.0 and rec["capped_from"] == 500.0  # 50% of the 200 contracts within 2 cents
    assert rec["gates"][0]["reason"] == "liquidity_capped" and rec["gates"][0]["limit"] == "pm_depth_2c"
    assert h.algo.fills == [("pred_yes", 100.0, 0.51)] and h.liquidity_capped == 1
    mid_only = {"yes_bid": 0.5, "yes_ask": 0.5}
    rec = h.step(mid_only, 2, 2, 0, 500.0, lambda f, ts, v: f)
    assert rec["qty"] == 500.0 and rec["liquidity"]["status"] == "unknown"  # a replay tick: no depth, labelled


def test_a_replay_trading_the_account_counts_toward_todays_account_ledger():
    """Participation per day: a sandboxed replay counts under its replayed date (its own ledger); a replay that trades
    the account (replay_to_account) sends its orders to the account today, so they count under today's wall-clock
    session date, where live bridges share the account-wide 1%-of-ADV cap."""
    from app import bridges
    from app.closed import staged

    wall = dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.timezone.utc)  # Wednesday
    app = SimpleNamespace(state=SimpleNamespace(staged_clock=lambda: wall))
    replayed = int(dt.datetime(2025, 4, 4, 15, 0, tzinfo=dt.timezone.utc).timestamp() * 1e9)
    tick = SimpleNamespace(recorded_ts_ns=replayed)

    def bridge(to_account):
        return SimpleNamespace(id="b", app=app, effective_source="replay", last_replay_ts_ns=replayed,
                               replay_to_account=to_account, _sandboxed=lambda: not to_account)
    assert bridges._liq_day(bridge(False), tick) == "2025-04-04"
    assert bridges._liq_day(bridge(True), tick) == "2026-10-07"
    assert bridges._liq_scope(bridge(True)) == "account"
    at = dt.datetime(2025, 4, 7, 13, 31, tzinfo=dt.timezone.utc)
    assert staged._liq_day(app, "replay", bridge(False), at) == "2025-04-07"
    assert staged._liq_day(app, "replay", bridge(True), at) == "2026-10-07"
    assert staged._liq_day(app, "wall", None, dt.date(2026, 10, 12)) == "2026-10-12"
