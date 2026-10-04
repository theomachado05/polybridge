import asyncio
import math

import pytest

from app.cache import TTLCache
from app.options import chain as ch


def row(kind, strike, expiry="2026-12-18", bid=None, ask=None, fmv=None, close=None, iv=0.3, delta=0.5,
        spot=None, timeframe="DELAYED", upd=1_790_970_000_000_000_000):
    r = {"details": {"contract_type": kind, "strike_price": strike, "expiration_date": expiry,
                     "ticker": f"O:NVDA261218{kind[0].upper()}{int(strike * 1000):08d}", "exercise_style": "american"},
         "greeks": {"delta": delta}, "implied_volatility": iv, "open_interest": 100,
         "day": {"close": close, "volume": 5, "last_updated": upd},
         "underlying_asset": {"ticker": "NVDA", "timeframe": timeframe, **({"price": spot} if spot else {})}}
    if bid is not None or ask is not None:
        r["last_quote"] = {"bid": bid, "ask": ask, "last_updated": upd}
    if fmv is not None:
        r["fmv"], r["fmv_last_updated"] = fmv, upd
    return r


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, pages, fail=False):
        self.pages, self.fail, self.calls = list(pages), fail, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if self.fail:
            raise TimeoutError("stalled")
        return FakeResp(self.pages.pop(0) if self.pages else {"results": []})


class FakeClient:
    def __init__(self, pages=(), fail=False):
        self.session = FakeSession(pages, fail)


def test_parse_result_prefers_quotes_then_fmv_then_close():
    q = ch.parse_result(row("call", 150, bid=4.9, ask=5.1, fmv=5.3, close=5.5))
    assert (q.bid, q.ask, q.mid, q.mark_source) == (4.9, 5.1, pytest.approx(5.0), "quote")
    q = ch.parse_result(row("call", 150, fmv=5.3, close=5.5))
    assert math.isnan(q.bid) and math.isnan(q.ask) and (q.mid, q.mark_source) == (5.3, "fmv")
    q = ch.parse_result(row("put", 150, close=5.5))
    assert (q.mid, q.mark_source, q.kind) == (5.5, "day_close", "put")
    q = ch.parse_result(row("put", 150))
    assert math.isnan(q.mid) and q.mark_source is None


def test_parse_result_drops_crossed_book_and_bad_rows():
    q = ch.parse_result(row("call", 150, bid=5.2, ask=5.0, fmv=5.1))
    assert math.isnan(q.bid) and math.isnan(q.ask) and q.mark_source == "fmv"
    assert ch.parse_result({"details": {"contract_type": "future"}}) is None
    assert ch.parse_result({"details": {"contract_type": "call", "strike_price": "x", "expiration_date": "2026-12-18"}}) is None
    assert ch.parse_result({}) is None
    q = ch.parse_result(row("call", 150, fmv=5.0, iv=-1, delta="nan"))
    assert math.isnan(q.iv) and math.isnan(q.delta)


def test_fetch_follows_next_url_and_bypasses_disk_cache():
    pages = [{"results": [row("call", 145, fmv=8.0, spot=150.2)], "next_url": "https://api.massive.com/v3/next?cursor=1"},
             {"results": [row("call", 155, fmv=3.0), row("put", 145, fmv=2.0)]}]
    client = FakeClient(pages)
    c = ch.fetch_chain_sync("nvda".upper(), ch.snapshot_params("2026-12-01", "2026-12-31", 140, 160), client=client)
    assert len(c.quotes) == 3 and c.spot == 150.2 and c.timeframe == "DELAYED"
    url0, params0, timeout0 = client.session.calls[0]
    assert url0 == "https://api.massive.com/v3/snapshot/options/NVDA"
    assert params0["expiration_date.gte"] == "2026-12-01" and params0["strike_price.lte"] == 160
    assert params0["limit"] == ch.PAGE_LIMIT and timeout0 == 6.0
    assert client.session.calls[1][0].endswith("cursor=1") and client.session.calls[1][1] is None
    assert c.expiries() == ["2026-12-18"]
    sl = c.slice("2026-12-18")
    assert list(sl) == [145.0, 155.0] and set(sl[145.0]) == {"call", "put"}
    assert ch.last_chain("NVDA") is c


def test_max_pages_bound():
    pages = [{"results": [row("call", 100 + i, fmv=1.0)], "next_url": "https://x/next"} for i in range(20)]
    c = ch.fetch_chain_sync("NVDA", {}, client=FakeClient(pages))
    assert len(c.quotes) == ch.MAX_PAGES


def test_snapshot_params_skips_missing_values():
    assert ch.snapshot_params() == {}
    assert ch.snapshot_params(strike_min=float("nan"), contract_type="straddle") == {}
    assert ch.snapshot_params(contract_type="put") == {"contract_type": "put"}


def test_get_chain_caches_and_serves_stale_on_error():
    t = [0.0]
    cache = TTLCache(60, clock=lambda: t[0])
    client = FakeClient([{"results": [row("call", 150, fmv=5.0)]}])
    c1, stale1 = asyncio.run(ch.get_chain("NVDA", strike_min=140, client=client, cache=cache))
    c2, stale2 = asyncio.run(ch.get_chain("NVDA", strike_min=140, client=client, cache=cache))
    assert c1 is c2 and not stale1 and not stale2 and len(client.session.calls) == 1
    t[0] = 120.0
    client.session.fail = True
    c3, stale3 = asyncio.run(ch.get_chain("NVDA", strike_min=140, client=client, cache=cache))
    assert c3 is c1 and stale3


def test_get_chain_without_key_raises_noclient(monkeypatch):
    monkeypatch.setattr(ch, "make_client", lambda: None)
    with pytest.raises(ch.NoClient):
        asyncio.run(ch.get_chain("NVDA", cache=TTLCache(60)))


def test_get_chain_error_with_nothing_cached_raises():
    with pytest.raises(Exception):
        asyncio.run(ch.get_chain("NVDA", client=FakeClient(fail=True), cache=TTLCache(60)))


def test_staleness_labels():
    upd_s = 1_000_000.0
    c = ch.parse_snapshot("NVDA", [{"results": [row("call", 150, fmv=5.0, upd=int(upd_s * 1e9))]}], fetched_at=upd_s)
    assert ch.staleness(c, False, now=upd_s + 60)["staleness"] == "delayed"
    s = ch.staleness(c, False, now=upd_s + 86400)
    assert s["staleness"] == "prior_session" and s["data_age_s"] == 86400 and s["mark_sources"] == ["fmv"]
    assert s["has_quotes"] is False and s["source"] == "massive_snapshot"
    assert ch.staleness(c, True, now=upd_s)["staleness"] == "stale_cache"
    rt = ch.parse_snapshot("NVDA", [{"results": [row("call", 150, bid=1, ask=2, timeframe="REAL-TIME", upd=int(upd_s * 1e9))]}])
    assert ch.staleness(rt, False, now=upd_s + 1)["staleness"] == "live"
    assert ch.staleness(ch.Chain("NVDA", 0.0), False)["staleness"] == "unknown"


def test_to_dict_is_json_safe():
    import json
    c = ch.parse_snapshot("NVDA", [{"results": [row("call", 150, fmv=5.0)]}])
    json.dumps(c.to_dict(), allow_nan=False)
