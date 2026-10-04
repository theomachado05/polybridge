import datetime as dt
import math
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app.cache import TTLCache
from app.main import create_app
from app.options import chain as ch
from app.options import hedge as hq
from app.options import live as lv
from app.options import mark as mk
from app.options import quotes as qt
from app.options import router as rt

UTC = dt.timezone.utc
WED = dt.datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
SAT = dt.datetime(2026, 10, 3, 19, 0, tzinfo=UTC)
FRI_CLOSE_NS = int(dt.datetime(2026, 10, 2, 19, 59, 58, tzinfo=UTC).timestamp() * 1e9)
THU_NS = int(dt.datetime(2026, 10, 1, 15, 0, tzinfo=UTC).timestamp() * 1e9)
FRESH_NS = int((WED - dt.timedelta(minutes=5)).timestamp() * 1e9)
EXP_NEAR, EXP_HEDGE = "2026-10-02", "2026-10-30"


def occ(und, exp, kind, k):
    return f"O:{und}{exp[2:4]}{exp[5:7]}{exp[8:10]}{'C' if kind == 'call' else 'P'}{int(k * 1000):08d}"


def orow(kind, k, exp, fmv, *, iv=0.25, delta=None, greeks=True, oi=1000, vol=50, spot=100.0, ts=FRESH_NS, und="XYZ"):
    r = {"details": {"contract_type": kind, "strike_price": k, "expiration_date": exp, "ticker": occ(und, exp, kind, k),
                     "exercise_style": "american", "shares_per_contract": 100},
         "fmv": fmv, "fmv_last_updated": ts, "open_interest": oi,
         "day": {"close": fmv, "volume": vol, "last_updated": ts},
         "underlying_asset": {"price": spot, "timeframe": "DELAYED", "ticker": und}}
    if iv is not None:
        r["implied_volatility"] = iv
    if greeks:
        r["greeks"] = {"delta": delta if delta is not None else (0.5 if kind == "call" else -0.5),
                       "gamma": 0.05, "theta": -0.04, "vega": 0.1}
    return r


ROWS = [
    orow("put", 85, EXP_HEDGE, 0.40), orow("put", 90, EXP_HEDGE, 1.00, delta=-0.15),
    orow("put", 95, EXP_HEDGE, 2.00, delta=-0.30), orow("put", 100, EXP_HEDGE, 4.00, delta=-0.50),
    orow("call", 100, EXP_HEDGE, 4.00), orow("call", 105, EXP_HEDGE, 2.10, delta=0.30),
    orow("call", 110, EXP_HEDGE, 1.00, iv=None, greeks=False),
    orow("call", 100, EXP_NEAR, 1.50), orow("put", 100, EXP_NEAR, 1.40),
    orow("call", 105, EXP_NEAR, 0.20, oi=20, vol=0),
]
NBBO = {occ("XYZ", EXP_HEDGE, "put", 95): (1.90, 2.10), occ("XYZ", EXP_HEDGE, "call", 105): (2.00, 2.20),
        occ("XYZ", EXP_HEDGE, "put", 90): (0.90, 1.10), occ("XYZ", EXP_NEAR, "call", 100): (1.45, 1.55),
        occ("XYZ", EXP_NEAR, "put", 100): (1.35, 1.45), occ("XYZ", EXP_NEAR, "call", 105): (0.10, 0.30)}
STOCK = {"ticker": {"ticker": "XYZ", "todaysChangePerc": 0.5, "updated": FRESH_NS,
                    "day": {"c": 100.0}, "lastTrade": {"p": 100.0, "t": FRESH_NS},
                    "lastQuote": {"p": 99.99, "P": 100.01}, "prevDay": {"c": 99.5}}}


class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeMassive:

    def __init__(self, rows=ROWS, nbbo=NBBO, stock=STOCK, dividends=None, fail=False, nbbo_ts=FRESH_NS):
        self.rows, self.nbbo, self.stock, self.fail, self.nbbo_ts = rows, nbbo, stock, fail, nbbo_ts
        self.dividends = dividends if dividends is not None else []
        self.calls: list[str] = []
        self.session = self

    def get(self, url, params=None, timeout=None):
        path = urlparse(url).path
        self.calls.append(path)
        if self.fail:
            raise TimeoutError("stalled")
        p = params or {}
        parts = path.strip("/").split("/")
        if path.startswith("/v3/snapshot/options/") and len(parts) == 4:
            out = [r for r in self.rows
                   if (p.get("expiration_date.gte") is None or r["details"]["expiration_date"] >= p["expiration_date.gte"])
                   and (p.get("expiration_date.lte") is None or r["details"]["expiration_date"] <= p["expiration_date.lte"])
                   and (p.get("strike_price.gte") is None or r["details"]["strike_price"] >= p["strike_price.gte"])
                   and (p.get("strike_price.lte") is None or r["details"]["strike_price"] <= p["strike_price.lte"])]
            return _Resp({"results": out})
        if path.startswith("/v3/snapshot/options/") and len(parts) == 5:
            hit = next((r for r in self.rows if r["details"]["ticker"] == parts[4]), None)
            return _Resp({"results": hit} if hit else {"status": "NOT_FOUND"}, 200 if hit else 404)
        if path.startswith("/v3/quotes/"):
            ba = self.nbbo.get(parts[2])
            res = [{"bid_price": ba[0], "ask_price": ba[1], "bid_size": 10, "ask_size": 10,
                    "sip_timestamp": self.nbbo_ts}] if ba else []
            return _Resp({"results": res, "status": "DELAYED"})
        if path.startswith("/v2/snapshot/"):
            return _Resp(self.stock) if self.stock else _Resp({}, 404)
        if path.startswith("/v2/aggs/"):
            return _Resp({"results": [{"c": 99.5, "t": 1790971200000}]})
        if path.startswith("/v3/reference/dividends"):
            return _Resp({"results": self.dividends})
        return _Resp({}, 404)


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    monkeypatch.setattr(ch, "_CACHE", TTLCache(60))
    monkeypatch.setattr(ch, "_LAST", {})
    qt.reset_caches()
    mk.reset_cache()
    hq.reset_cache()
    yield


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_parse_occ():
    assert qt.parse_occ("O:AAPL261023P00300000") == {"ticker": "O:AAPL261023P00300000", "underlying": "AAPL",
                                                     "expiry": "2026-10-23", "right": "put", "strike": 300.0}
    assert qt.parse_occ("brkb261023c00412500")["strike"] == 412.5
    assert qt.parse_occ("AAPL") is None and qt.parse_occ("O:AAPL261340P00300000") is None


def test_market_state_and_staleness_rules():
    sat, wed = qt.market_state(SAT), qt.market_state(WED)
    assert sat["market_open"] is False and sat["phase"] == "weekend"
    assert wed["market_open"] is True
    assert qt.is_stale(FRI_CLOSE_NS, sat, SAT) == (False, None)
    assert qt.is_stale(THU_NS, sat, SAT)[0] is True
    assert qt.is_stale(FRESH_NS, wed, WED) == (False, None)
    assert qt.is_stale(int((WED - dt.timedelta(minutes=45)).timestamp() * 1e9), wed, WED)[0] is True
    assert qt.is_stale(None, wed, WED) == (True, "no timestamp")


def test_liquidity_flags_grades():
    assert qt.liquidity_flags(bid=1.9, ask=2.1, mid=2.0, oi=5000, volume=100) == ([], "liquid")
    f, g = qt.liquidity_flags(bid=1.0, ask=1.5, mid=1.25, oi=50, volume=0, contracts=20)
    assert {"very_wide_spread", "low_open_interest", "no_volume_last_session", "size_vs_open_interest"} <= set(f)
    assert g == "illiquid"
    f, g = qt.liquidity_flags(bid=math.nan, ask=math.nan, mid=1.0, oi=0, volume=10, quoted=False)
    assert "no_live_quote" in f and "no_open_interest" in f and g == "illiquid"
    assert qt.liquidity_flags(bid=0.5, ask=0.8, mid=0.65, oi=2000, volume=5)[0] == ["very_wide_spread"]


def test_dividends_declared_projected_none():
    rows = [{"ex_dividend_date": "2026-08-10", "cash_amount": 0.27, "frequency": 4}]
    start, end = dt.date(2026, 10, 3), dt.date(2026, 11, 30)
    proj = qt.parse_dividends({"results": rows}, start, end)
    assert proj["status"] == "projected" and proj["ex_date"] == "2026-11-09" and proj["amount"] == 0.27
    decl = qt.parse_dividends({"results": rows + [{"ex_dividend_date": "2026-11-12", "cash_amount": 0.28}]}, start, end)
    assert decl["status"] == "declared" and decl["ex_date"] == "2026-11-12"
    assert qt.parse_dividends({"results": rows}, start, dt.date(2026, 10, 20))["status"] == "none_in_horizon"
    assert qt.parse_dividends({"results": []}, start, end)["status"] == "no_dividend_history"


def test_parse_spot_prefers_last_trade_when_open_close_otherwise():
    assert qt.parse_spot(STOCK, None, True)["source"] == "last_trade"
    closed = qt.parse_spot(STOCK, None, False)
    assert closed["source"] == "session_close" and closed["bid"] == 99.99 and closed["ask"] == 100.01
    prev = qt.parse_spot(None, {"results": [{"c": 99.5, "t": 1}]}, False)
    assert prev["price"] == 99.5 and prev["source"] == "prev_close"
    wide = {"ticker": {**STOCK["ticker"], "lastQuote": {"p": 90.0, "P": 110.0}}}
    assert qt.parse_spot(wide, None, False)["bid"] is None


def test_chain_rows_have_quotes_greeks_and_labels():
    fm = FakeMassive()
    r = run(lv.live_chain("XYZ", client=fm, expiry=dt.date(2026, 10, 30), strikes=3, now=WED))
    assert r["available"] is True and r["market_open"] is True and r["expiry"] == EXP_HEDGE
    assert r["underlying_price"]["price"] == 100.0 and r["underlying_price"]["source"] == "massive_option_snapshot"
    assert sorted({c["strike"] for c in r["contracts"]}) == [95.0, 100.0, 105.0]
    p95 = next(c for c in r["contracts"] if c["right"] == "put" and c["strike"] == 95)
    assert (p95["bid"], p95["ask"], p95["mid"]) == (1.9, 2.1, 2.0)
    assert p95["mark_source"] == "quote" and p95["quote_source"] == "massive_last_nbbo"
    assert p95["greeks_source"] == "massive" and p95["delta"] == -0.30 and p95["open_interest"] == 1000
    assert p95["last"] == 2.0 and p95["last_source"] == "day_close" and p95["stale"] is False
    c100 = next(c for c in r["contracts"] if c["right"] == "call" and c["strike"] == 100)
    assert c100["bid"] is None and c100["mark_source"] == "fmv" and c100["quote_source"] == "nbbo_unavailable"
    assert "no_live_quote" in c100["liquidity_flags"]
    assert r["n_contracts"] == 4
    assert r["freshness"]["has_quotes"] is True and r["freshness"]["n_quoted"] == 2
    assert "live session snapshot" in r["snapshot_label"]


def test_chain_computes_greeks_when_massive_has_none():
    r = run(lv.live_chain("XYZ", client=FakeMassive(), expiry=dt.date(2026, 10, 30), strikes=7, now=WED))
    c110 = next(c for c in r["contracts"] if c["right"] == "call" and c["strike"] == 110)
    assert c110["greeks_source"] == "computed" and c110["iv_source"] == "computed"
    T = qt.years_to_expiry(EXP_HEDGE, WED)
    from app.options import bs
    assert bs.price(100.0, 110.0, T, 0.04, c110["iv"], True) == pytest.approx(1.0, abs=1e-4)
    assert c110["delta"] == pytest.approx(bs.greeks(100.0, 110.0, T, 0.04, c110["iv"], True)["delta"], abs=1e-6)
    assert any("computed" in n for n in r["notes"])


def test_chain_defaults_to_nearest_live_expiry_and_weekend_label():
    rows = [dict(r, fmv_last_updated=FRI_CLOSE_NS) for r in ROWS]
    sat_rows = [orow("call", 100, "2026-10-09", 1.5, ts=FRI_CLOSE_NS), orow("put", 100, "2026-10-09", 1.4, ts=THU_NS)]
    fm = FakeMassive(rows=rows + sat_rows, nbbo={}, nbbo_ts=FRI_CLOSE_NS)
    r = run(lv.live_chain("XYZ", client=fm, now=SAT))
    assert r["available"] and r["market_open"] is False and r["expiry"] == "2026-10-09"
    assert r["snapshot_label"].startswith("last close snapshot")
    stale = {c["right"]: c["stale"] for c in r["contracts"]}
    assert stale == {"call": False, "put": True}


def test_chain_never_raises_no_key_outage_empty():
    assert run(lv.live_chain("XYZ", client=None, now=WED))["reason"] == "MASSIVE_API_KEY not set"
    out = run(lv.live_chain("XYZ", client=FakeMassive(fail=True), now=WED))
    assert out["available"] is False and "Massive unavailable" in out["reason"]
    empty = run(lv.live_chain("XYZ", client=FakeMassive(rows=[]), now=WED))
    assert empty["available"] is False and empty["contracts"] == []


def test_mark_quote_nbbo_estimated_expired():
    q = ch.parse_result(orow("put", 95, EXP_HEDGE, 2.0))
    m = mk.mark_quote(q, nbbo={"bid": 1.9, "ask": 2.1, "updated_ns": FRESH_NS}, spot=100.0, now=WED)
    assert m["mark"] == pytest.approx(2.0) and m["half_spread"] == pytest.approx(0.1)
    assert m["spread_source"] == "nbbo" and m["exit_long"] == 1.9 and m["exit_short"] == 2.1
    assert m["mark_per_contract"] == pytest.approx(200.0) and m["stale"] is False
    est = mk.mark_quote(q, spot=100.0, now=WED)
    assert est["spread_source"] == "estimated" and est["half_spread"] == pytest.approx(0.08)
    assert est["bid"] is None and est["exit_long"] == pytest.approx(1.92)
    thin = mk.mark_quote(ch.parse_result(orow("put", 95, EXP_HEDGE, 2.0, oi=50)), spot=100.0, now=WED)
    assert thin["half_spread"] == pytest.approx(0.16)
    exp = mk.mark_quote(ch.parse_result(orow("put", 100, EXP_NEAR, 1.4)), spot=97.0, now=SAT)
    assert exp["expired"] and exp["mark"] == 3.0 and exp["mark_source"] == "intrinsic_expired"
    assert mk.mark_quote(None)["available"] is False


def test_mark_fetches_caches_and_degrades():
    fm = FakeMassive()
    m = run(mk.mark("O:XYZ261030P00095000", client=fm, now=WED))
    assert m["available"] and m["mark"] == pytest.approx(2.0) and m["spread_source"] == "nbbo"
    assert m["underlying_price"] == 100.0 and m["delta"] == -0.30 and m["cache_stale"] is False
    n = len(fm.calls)
    run(mk.mark("XYZ261030P00095000", client=fm, now=WED))
    assert len(fm.calls) == n
    fm.fail = True
    mk._MARKS._data = {k: (v[0] - 999, v[1]) for k, v in mk._MARKS._data.items()}
    stale = run(mk.mark("O:XYZ261030P00095000", client=fm, now=WED))
    assert stale["available"] and stale["cache_stale"] is True
    mk.reset_cache()
    down = run(mk.mark("O:XYZ261030P00095000", client=FakeMassive(fail=True), now=WED))
    assert down["available"] is False and "Massive unavailable" in down["reason"]
    assert run(mk.mark("nonsense", client=None))["reason"] == "not an OCC option symbol"
    assert run(mk.mark("O:XYZ261030P00095000", client=None))["reason"] == "MASSIVE_API_KEY not set"


def hedge(fm=None, **kw):
    args = dict(ticker="XYZ", shares=200, horizon_days=30, protection_pct=0.05)
    args.update(kw)
    return run(hq.hedge_quote(args.pop("ticker"), args.pop("shares"), args.pop("horizon_days"),
                              args.pop("protection_pct"), client=fm or FakeMassive(), now=WED, **args))


def test_hedge_quote_hand_computed_costs():
    h = hedge()
    assert h["available"] and h["expiry"] == EXP_HEDGE and h["expiry_covers_horizon"] is True
    assert h["notional_usd"] == 20000.0 and h["spot"]["price"] == 100.0
    s = h["strategies"]
    pp = s["protective_put"]
    assert [lg["ticker"] for lg in pp["legs"]] == [occ("XYZ", EXP_HEDGE, "put", 95)]
    assert pp["upfront_usd"] == pytest.approx(421.30) and pp["upfront_bp"] == pytest.approx(210.65)
    assert pp["expected_cost_usd"] == pytest.approx(21.30) and pp["expected_cost_bp"] == pytest.approx(10.65)
    assert pp["delta_equivalent_shares"] == pytest.approx(60.0) and pp["hedge_ratio"] == pytest.approx(0.30)
    assert pp["protection"]["floor_price"] == 95.0 and pp["spread_source"] == "nbbo"
    assert pp["breakeven_price"] == pytest.approx(100 + 2.10 + 1.30 / 200)
    co = s["collar"]
    assert [(lg["strike"], lg["side"]) for lg in co["legs"]] == [(95.0, "buy"), (105.0, "sell")]
    assert co["upfront_usd"] == pytest.approx(22.60) and co["expected_cost_bp"] == pytest.approx(21.30)
    assert co["upside"]["cap_price"] == 105.0 and co["delta_equivalent_shares"] == pytest.approx(120.0)
    ps = s["put_spread"]
    assert [(lg["strike"], lg["side"]) for lg in ps["legs"]] == [(95.0, "buy"), (90.0, "sell")]
    assert ps["upfront_usd"] == pytest.approx(242.60) and ps["upfront_bp"] == pytest.approx(121.30)
    assert ps["expected_cost_usd"] == pytest.approx(42.60) and ps["protection"]["max_payout_usd"] == pytest.approx(1000)
    ss = s["short_stock"]
    assert ss["cost_breakdown"]["borrow_usd"] == pytest.approx(4.931507, abs=1e-5)
    assert ss["cost_breakdown"]["spread_round_trip_usd"] == pytest.approx(4.0)
    assert ss["expected_cost_usd"] == pytest.approx(10.331507, abs=1e-5)
    assert ss["expected_cost_bp"] == pytest.approx(5.165753, abs=1e-5)
    assert ss["capital"]["margin_initial_usd"] == pytest.approx(10000.0)
    assert "borrow_rate_assumed" in ss["liquidity_flags"]
    assert h["ranking"]["order"] == ["short_stock", "protective_put", "collar", "put_spread"]
    assert h["contracts"] == {"protective_put": 2, "collar": 2, "put_spread": 2}


def test_hedge_scenarios_at_horizon():
    h = hedge()
    pp = {r["move"]: r for r in h["strategies"]["protective_put"]["scenarios"]}
    assert pp[-0.3]["pnl_usd"] == pytest.approx(-6000 + 5000 - 421.30, abs=1.0)
    assert pp[0.2]["pnl_usd"] == pytest.approx(4000 - 421.30, abs=1.0)
    co = {r["move"]: r for r in h["strategies"]["collar"]["scenarios"]}
    assert co[0.2]["pnl_usd"] == pytest.approx(1000 - 22.60, abs=1.0)
    ss = {r["move"]: r["pnl_usd"] for r in h["strategies"]["short_stock"]["scenarios"]}
    assert set(round(v, 6) for v in ss.values()) == {round(-10.331507, 6)}
    assert {r["move"]: r["pnl_usd"] for r in h["unhedged_scenarios"]}[-0.1] == pytest.approx(-2000)


def test_hedge_estimated_spreads_liquidity_and_caveats():
    rows = [dict(r, open_interest=40) if r["details"]["strike_price"] == 95 else r for r in ROWS]
    h = hedge(FakeMassive(rows=rows, nbbo={}))
    pp = h["strategies"]["protective_put"]
    leg = pp["legs"][0]
    assert leg["spread_source"] == "estimated" and leg["exec_px"] == pytest.approx(2.0 + 0.16)
    assert {"no_live_quote", "low_open_interest"} <= set(pp["liquidity_flags"]) and pp["liquidity"] in ("thin", "illiquid")
    assert pp["spread_source"] == "estimated"
    assert any("American" in c for c in h["caveats"]) and any("Borrow" in c for c in h["caveats"])


def test_hedge_small_position_and_borrow_override_and_dividend():
    divs = [{"ex_dividend_date": "2026-10-20", "cash_amount": 0.5, "frequency": 4}]
    h = hedge(FakeMassive(dividends=divs), shares=50, borrow_rate=0.10)
    s = h["strategies"]
    assert s["collar"]["available"] is False and "100 shares" in s["collar"]["reason"]
    assert s["protective_put"]["contracts"] == 1 and "over_hedged" in s["protective_put"]["liquidity_flags"]
    ss = s["short_stock"]
    assert ss["cost_breakdown"]["borrow_usd"] == pytest.approx(50 * 100 * 0.10 * 30 / 365)
    assert "borrow_rate_assumed" not in ss["liquidity_flags"] and "dividend_owed_on_short" in ss["liquidity_flags"]
    assert ss["dividend"]["cash_owed_usd"] == pytest.approx(25.0)
    assert any("Ex-dividend 2026-10-20" in c for c in h["caveats"])


def test_hedge_ssr_flag_and_no_covering_expiry():
    stock = {"ticker": {**STOCK["ticker"], "todaysChangePerc": -12.0}}
    h = hedge(FakeMassive(stock=stock), horizon_days=60)
    assert "ssr_uptick_rule_active" in h["strategies"]["short_stock"]["liquidity_flags"]
    assert h["expiry"] == EXP_HEDGE and h["expiry_covers_horizon"] is False
    assert any("rolled" in c for c in h["caveats"])


def test_hedge_never_raises():
    nokey = run(hq.hedge_quote("XYZ", 100, 30, 0.05, client=None, now=WED))
    assert nokey["available"] is False and nokey["strategies"]["collar"]["reason"] == "MASSIVE_API_KEY not set"
    down = hedge(FakeMassive(fail=True))
    assert down["available"] is False and "no underlying price" in down["reason"]
    no_opts = hedge(FakeMassive(rows=[]))
    assert no_opts["strategies"]["short_stock"]["available"] is True
    assert no_opts["strategies"]["protective_put"]["available"] is False
    assert no_opts["ranking"]["order"] == ["short_stock"]


@pytest.fixture
def client(monkeypatch):
    def _make(massive):
        monkeypatch.setattr(rt, "make_client", lambda: massive)
        monkeypatch.setattr(qt, "now_utc", lambda: WED)
        return TestClient(create_app())
    return _make


def test_routes_validate_and_never_500(client):
    c = client(None)
    assert c.get("/options/chain/xyz").json()["reason"] == "MASSIVE_API_KEY not set"
    assert c.get("/options/chain/XYZ?strikes=0").status_code == 422
    assert c.get("/options/chain/XYZ?window=2").status_code == 422
    assert c.get("/options/chain/XYZ?expiry=10-30").status_code == 422
    assert c.get("/options/chain/bad$$").status_code == 422
    assert c.get("/options/hedge-quote?ticker=XYZ&shares=0").status_code == 422
    assert c.get("/options/hedge-quote?ticker=XYZ&shares=100&protection_pct=5").status_code == 422
    assert c.get("/options/hedge-quote?ticker=XYZ&shares=100&horizon_days=0").status_code == 422
    assert c.get("/options/hedge-quote?ticker=XYZ&shares=100&borrow_rate=-1").status_code == 422
    r = c.get("/options/hedge-quote?ticker=XYZ&shares=100")
    assert r.status_code == 200 and r.json()["available"] is False
    assert c.get("/options/mark/AAPL").status_code == 422
    assert c.get("/options/mark/O:XYZ261030P00095000").json()["reason"] == "MASSIVE_API_KEY not set"
    down = client(FakeMassive(fail=True))
    for url in ("/options/chain/XYZ", "/options/hedge-quote?ticker=XYZ&shares=100", "/options/mark/O:XYZ261030P00095000"):
        resp = down.get(url)
        assert resp.status_code == 200 and resp.json()["available"] is False


def test_routes_with_mocked_massive(client):
    c = client(FakeMassive())
    r = c.get("/options/chain/XYZ?expiry=2026-10-30&strikes=2").json()
    assert r["available"] and r["expiry"] == EXP_HEDGE and r["n_contracts"] == 3
    assert all(set(("strike", "right", "bid", "ask", "mid", "last", "volume", "open_interest", "iv", "delta", "gamma",
                    "theta", "vega")) <= set(row) for row in r["contracts"])
    m = c.get("/options/mark/O:XYZ261030P00095000").json()
    assert m["available"] and m["mark"] == pytest.approx(2.0)


def test_hedge_cache_keeps_good_quotes_not_outages(monkeypatch):
    monkeypatch.setattr(qt, "now_utc", lambda: WED)
    down = run(hq.hedge_quote("XYZ", 200, 30, 0.05, client=FakeMassive(fail=True)))
    assert down["available"] is False
    good_fm = FakeMassive()
    good = run(hq.hedge_quote("XYZ", 200, 30, 0.05, client=good_fm))
    assert good["available"] is True
    n = len(good_fm.calls)
    again = run(hq.hedge_quote("XYZ", 200, 30, 0.05, client=good_fm))
    assert again == good and len(good_fm.calls) == n


def test_hedge_quote_says_where_option_orders_go():
    sim = hedge(FakeMassive())
    assert sim["label"] == hq.LABEL and sim["options_route"] == "simulator"
    assert hq.SIM_OPTIONS_CAVEAT in sim["caveats"] and hq.BROKER_OPTIONS_CAVEAT not in sim["caveats"]
    wb = run(hq.hedge_quote("XYZ", 200, 30, 0.05, client=FakeMassive(), now=WED, options_at_broker=True))
    assert wb["label"] == hq.LABEL_BROKER and wb["options_route"] == "webull-paper"
    assert hq.BROKER_OPTIONS_CAVEAT in wb["caveats"] and hq.SIM_OPTIONS_CAVEAT not in wb["caveats"]
