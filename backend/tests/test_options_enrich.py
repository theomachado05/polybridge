"""enrich(): MarketTick option fields, NaN-safety, refresh() windowing (app/options/enrich.py). Offline."""
import asyncio
import datetime as dt
import math

import pytest

from app.cache import TTLCache
from app.options import chain as ch
from app.options import enrich as en

NAN = math.nan
EXP = "2026-12-18"


@pytest.fixture(autouse=True)
def _no_cached_chains(monkeypatch):
    monkeypatch.setattr(ch, "_LAST", {})


def make_chain(underlying="NVDA"):
    c = ch.Chain(underlying=underlying, fetched_at=0.0)
    for k, cm, pm, cd, pd_ in ((145.0, 8.0, 2.0, 0.6, -0.4), (150.0, 5.0, 4.0, 0.5, -0.5), (155.0, 3.0, 6.5, 0.4, -0.6)):
        c.quotes.append(ch.OptionQuote("c", "call", k, EXP, bid=cm - 0.1, ask=cm + 0.1, mid=cm, mark_source="quote",
                                       iv=0.3, delta=cd))
        c.quotes.append(ch.OptionQuote("p", "put", k, EXP, mid=pm, mark_source="fmv", iv=0.3, delta=pd_))
    return c


def ts(date: str) -> int:
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp() * 1e9)


def test_enrich_fills_option_fields_for_above():
    tick = {"ts_ns": ts("2026-10-02"), "yes_bid": 0.4, "yes_ask": 0.42}
    out, det = en.enrich_detail(tick, "NVDA", 150.0, "2026-12-18", chain=make_chain())
    T = 77 / 365
    assert out["opt_implied_prob"] == pytest.approx(0.5 / math.exp(-0.04 * T))
    assert out["opt_mid"] == pytest.approx(5.0)          # call spread C(145) - C(155)
    assert out["opt_delta"] == pytest.approx(0.5) and out["opt_iv"] == pytest.approx(0.3)
    assert out["yes_bid"] == 0.4 and tick.get("opt_mid") is None   # input untouched, other fields kept
    assert det["available"] and det["expiry"] == EXP


def test_enrich_below_uses_put_spread_and_flipped_prob():
    out = en.enrich({"ts_ns": ts("2026-10-02")}, "NVDA", 150.0, EXP, above=False, chain=make_chain())
    above = en.enrich({"ts_ns": ts("2026-10-02")}, "NVDA", 150.0, EXP, chain=make_chain())
    assert out["opt_implied_prob"] == pytest.approx(1 - above["opt_implied_prob"])
    assert out["opt_mid"] == pytest.approx(6.5 - 2.0)    # put spread P(155) - P(145)
    assert out["opt_delta"] == pytest.approx(-0.5)


def test_enrich_uses_last_cached_chain_without_network():
    c = make_chain("ZZZQ")
    ch.remember(c)
    out = en.enrich({}, "zzzq", 150.0, EXP, as_of="2026-10-02")
    assert math.isfinite(out["opt_implied_prob"])


@pytest.mark.parametrize("tick,und,K,exp,chain", [
    (None, "NOCHAIN_A", 150.0, EXP, None),                 # no tick, no chain
    ({}, "NOCHAIN_TICKER", 150.0, EXP, None),              # nothing cached
    ({"ts_ns": "garbage"}, "NVDA", "abc", EXP, "chain"),   # bad K
    ({}, "NVDA", NAN, EXP, "chain"),
    ({}, "NVDA", 150.0, "not-a-date", "chain"),
    ({}, "NVDA", 999.0, EXP, "chain"),                     # outside listed strikes
    ({"opt_mid": "x", "opt_iv": None}, "NVDA", 150.0, EXP, ch.Chain("NVDA", 0.0)),  # empty chain
])
def test_enrich_nan_safe(tick, und, K, exp, chain):
    c = make_chain() if chain == "chain" else chain
    out = en.enrich(tick, und, K, exp, chain=c, as_of="2026-10-02")
    for f in en.OPT_FIELDS:
        assert isinstance(out[f], float) and math.isnan(out[f])


def test_enrich_keeps_existing_values_when_no_estimate():
    out = en.enrich({"opt_iv": 0.25}, "NOCHAIN_TICKER", 150.0, EXP)
    assert out["opt_iv"] == 0.25


def test_enrich_survives_a_broken_chain_object():
    class Broken:
        def expiries(self):
            raise RuntimeError("boom")
    out, det = en.enrich_detail({}, "NVDA", 150.0, EXP, chain=Broken())
    assert math.isnan(out["opt_implied_prob"]) and not det["available"]
    assert "enrich failed" in det["notes"][0]


def test_enrich_fills_eightk_score_when_asked():
    from app.options import eightk as ek
    rows = [{"ticker": "NVDA", "filing_date": "2026-10-01", "tags": ["restructuring_plan"]}]
    orig = ek.load_filings
    ek._FILE_CACHE = rows
    try:
        out = en.enrich({"ts_ns": ts("2026-10-02")}, "NVDA", 150.0, EXP, chain=make_chain(), eightk_ticker="NVDA")
        assert out["eightk_score"] == pytest.approx(1 - 1 / 30)
    finally:
        ek._FILE_CACHE = None
        assert ek.load_filings is orig


class _Resp:
    def __init__(self, p):
        self.p = p

    def json(self):
        return self.p

    def raise_for_status(self):
        pass


class WindowClient:
    """Returns contracts only when the requested expiry window is at least `need_days` wide on each side."""

    def __init__(self, need_lo: str):
        self.need_lo, self.calls = need_lo, []
        self.session = self

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if params["expiration_date.gte"] <= self.need_lo:
            return _Resp({"results": [{"details": {"contract_type": "call", "strike_price": 150,
                                                   "expiration_date": self.need_lo, "ticker": "O:X"}, "fmv": 5.0}]})
        return _Resp({"results": []})


def test_refresh_widens_expiry_window_until_contracts_found():
    client = WindowClient(need_lo="2026-12-10")
    got = asyncio.run(en.refresh("NVDA", 150.0, "2026-12-31", as_of="2026-10-02", client=client, cache=TTLCache(60)))
    assert got is not None and got[0].quotes and got[1] is False
    widths = [p["expiration_date.gte"] for p in client.calls]
    assert widths == ["2026-12-28", "2026-12-21", "2026-12-01"]    # 3, 10, then 30 days either side
    assert client.calls[0]["strike_price.gte"] == pytest.approx(135.0)
    assert client.calls[0]["strike_price.lte"] == pytest.approx(165.0)
    assert ch.last_chain("NVDA") is got[0]


def test_refresh_none_on_bad_input_or_nothing_listed():
    client = WindowClient(need_lo="2000-01-01")
    assert asyncio.run(en.refresh("NVDA", 150.0, "2026-12-31", as_of="2026-10-02", client=client, cache=TTLCache(60))) is None
    assert len(client.calls) == len(en.EXPIRY_STEPS)
    assert asyncio.run(en.refresh("NVDA", "x", "2026-12-31", client=client)) is None
    assert asyncio.run(en.refresh("NVDA", 150.0, None, client=client)) is None


def test_refresh_none_on_massive_failure():
    class Failing:
        def __init__(self):
            self.session = self

        def get(self, *a, **k):
            raise TimeoutError
    assert asyncio.run(en.refresh("NVDA", 150.0, "2026-12-31", client=Failing(), cache=TTLCache(60))) is None
