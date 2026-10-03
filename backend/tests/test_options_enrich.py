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
    from app.options import eightk as ek
    monkeypatch.setattr(ch, "_LAST", {})
    monkeypatch.setattr(ch, "_FOR", {})
    monkeypatch.setattr(ek, "_LIVE", {})


def make_chain(underlying="NVDA", expiry=EXP, scale=1.0):
    c = ch.Chain(underlying=underlying, fetched_at=0.0)
    for k, cm, pm, cd, pd_ in ((145.0, 8.0, 2.0, 0.6, -0.4), (150.0, 5.0, 4.0, 0.5, -0.5), (155.0, 3.0, 6.5, 0.4, -0.6)):
        cm *= scale
        c.quotes.append(ch.OptionQuote("c", "call", k, expiry, bid=cm - 0.1, ask=cm + 0.1, mid=cm,
                                       mark_source="quote", iv=0.3, delta=cd))
        c.quotes.append(ch.OptionQuote("p", "put", k, expiry, mid=pm, mark_source="fmv", iv=0.3, delta=pd_))
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


class Live8K:
    def get_all(self, path, params):
        if params["tertiary_category"] == "restructuring_plan":
            return [{"tickers": ["NVDA"], "accession_number": "1", "filing_date": "2026-10-01"}]
        return []


def test_enrich_eightk_is_nan_for_a_live_date_until_refreshed():
    tick = {"ts_ns": ts("2026-10-02")}
    out, det = en.enrich_detail(tick, "NVDA", 150.0, EXP, chain=make_chain(), eightk_ticker="NVDA")
    assert math.isnan(out["eightk_score"]) and det["eightk_coverage"] is None     # no data, not "no filing"
    assert asyncio.run(en.refresh_eightk("2026-10-02", client=Live8K())) == "live"
    out, det = en.enrich_detail(tick, "NVDA", 150.0, EXP, chain=make_chain(), eightk_ticker="NVDA")
    assert out["eightk_score"] == pytest.approx(1 - 1 / 30) and det["eightk_coverage"] == "live"
    assert en.enrich(tick, "AAPL", 150.0, EXP, chain=make_chain(), eightk_ticker="AAPL")["eightk_score"] == 0.0


def test_enrich_eightk_in_sample_date_reads_bundled_file():
    out = en.enrich({"ts_ns": ts("2025-06-30")}, "NVDA", 150.0, EXP, eightk_ticker="NO_SUCH_TICKER")
    assert out["eightk_score"] == 0.0


# ---------------------------------------------------------------- chain selection and the expiry guard

def test_two_markets_on_one_underlying_read_their_own_chains():
    dec = make_chain("NVDA", "2026-12-31")
    mar = make_chain("NVDA", "2027-03-19", scale=0.5)
    ch.remember_for("NVDA", 150.0, "2026-12-31", dec)
    ch.remember(dec)
    ch.remember_for("NVDA", 150.0, "2027-03-19", mar)
    ch.remember(mar)                       # the latest snapshot for NVDA is now the March one
    out, det = en.enrich_detail({}, "NVDA", 150.0, "2026-12-31", as_of="2026-10-02")
    assert det["expiry"] == "2026-12-31" and det["chain_origin"] == "query"
    assert out["opt_mid"] == pytest.approx(5.0)
    out, det = en.enrich_detail({}, "NVDA", 150.0, "2027-03-19", as_of="2026-10-02")
    assert det["expiry"] == "2027-03-19" and out["opt_mid"] == pytest.approx(2.5)


def test_fallback_chain_with_wrong_expiry_leaves_fields_nan():
    ch.remember(make_chain("NVDA", "2027-03-19"))     # only another market's chain is cached
    out, det = en.enrich_detail({}, "NVDA", 150.0, "2026-12-31", as_of="2026-10-02")
    assert det["chain_origin"] == "underlying_latest" and det["expiry_gap_days"] == 78
    assert det["expiry_gap_ok"] is False and det["available"] is False
    assert all(math.isnan(out[f]) for f in en.OPT_FIELDS)
    assert any("different date" in n for n in det["notes"])


def test_expiry_gap_guard_scales_with_horizon():
    from app.options.implied import max_expiry_gap_days
    assert max_expiry_gap_days("2026-10-10", "2026-10-02") == 7         # short horizon: floor of 7 days
    assert max_expiry_gap_days("2026-12-31", "2026-10-02") == 18        # 90 days out: 20% of the horizon
    # Dec 31 question, Dec 18 monthly, 3 months out: 13 days, accepted
    out, det = en.enrich_detail({}, "NVDA", 150.0, "2026-12-31", chain=make_chain(), as_of="2026-10-02")
    assert det["expiry_gap_days"] == -13 and det["expiry_gap_ok"] and math.isfinite(out["opt_implied_prob"])
    # the same 13-day gap two weeks before resolution is a different date: rejected
    out, det = en.enrich_detail({}, "NVDA", 150.0, "2026-12-31", chain=make_chain(), as_of="2026-12-10")
    assert not det["expiry_gap_ok"] and math.isnan(out["opt_implied_prob"])


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
    client = WindowClient(need_lo="2026-12-15")
    got = asyncio.run(en.refresh("NVDA", 150.0, "2026-12-31", as_of="2026-10-02", client=client, cache=TTLCache(60)))
    assert got is not None and got[0].quotes and got[1] is False
    widths = [p["expiration_date.gte"] for p in client.calls]
    assert widths == ["2026-12-28", "2026-12-21", "2026-12-13"]    # 3, 10, then the 18-day gap limit
    assert client.calls[0]["strike_price.gte"] == pytest.approx(135.0)
    assert client.calls[0]["strike_price.lte"] == pytest.approx(165.0)
    assert ch.last_chain("NVDA") is got[0]
    assert ch.chain_for("NVDA", 150.0, "2026-12-31") is got[0] and ch.chain_for("NVDA", 155.0, "2026-12-31") is None


class TruncatingClient:
    """Always says there are more pages; returns contracts in every window."""

    def __init__(self):
        self.calls = []
        self.session = self

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        lo = (params or {}).get("strike_price.gte")
        return _Resp({"results": [{"details": {"contract_type": "call", "strike_price": 150,
                                               "expiration_date": "2026-12-31", "ticker": "O:X"}, "fmv": 5.0}],
                      "next_url": f"https://api.massive.com/next?lo={lo}"})


def test_refresh_refetches_narrower_band_when_truncated():
    client = TruncatingClient()
    got = asyncio.run(en.refresh("I:SPX", 7000.0, "2026-12-31", as_of="2026-10-02", client=client,
                                 cache=TTLCache(60)))
    assert got is not None and got[0].truncated
    firsts = [p for p in client.calls if p]
    assert firsts[0]["strike_price.gte"] == pytest.approx(6300.0)
    assert firsts[1]["strike_price.gte"] == pytest.approx(7000 * (1 - en.NARROW_PAD))
    assert ch.staleness(got[0], False)["truncated"] is True


def test_refresh_none_on_bad_input_or_nothing_listed():
    client = WindowClient(need_lo="2000-01-01")
    assert asyncio.run(en.refresh("NVDA", 150.0, "2026-12-31", as_of="2026-10-02", client=client, cache=TTLCache(60))) is None
    assert len(client.calls) == 3       # 3, 10 and 18 days (the gap limit for a 90-day horizon)
    assert asyncio.run(en.refresh("NVDA", "x", "2026-12-31", client=client)) is None
    assert asyncio.run(en.refresh("NVDA", 150.0, None, client=client)) is None


def test_refresh_none_on_massive_failure():
    class Failing:
        def __init__(self):
            self.session = self

        def get(self, *a, **k):
            raise TimeoutError
    assert asyncio.run(en.refresh("NVDA", 150.0, "2026-12-31", client=Failing(), cache=TTLCache(60))) is None


# ---------------------------------------------------------------- enrich_market (one call for the bridge loop)

class BookClient:
    def __init__(self, rows):
        self.rows, self.calls = rows, []
        self.session = self

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return _Resp({"results": self.rows})

    def get_all(self, path, params):
        return []


def _row(kind, k, mid, exp="2026-12-31"):
    return {"details": {"contract_type": kind, "strike_price": k, "expiration_date": exp, "ticker": "O:X"},
            "fmv": mid, "implied_volatility": 0.3, "greeks": {"delta": 0.5}}


def test_enrich_market_matches_refreshes_and_fills():
    client = BookClient([_row("call", 245, 12.0), _row("call", 255, 8.0)])
    tick = {"ts_ns": ts("2026-10-02")}
    out, det = asyncio.run(en.enrich_market(tick, "Will NVDA close above $250 on Dec 31?",
                                            "2027-01-01T04:59:00Z", client=client))
    assert det["supported"] and det["match"]["expiry"] == "2026-12-31" and det["underlying_used"] == "NVDA"
    assert out["opt_implied_prob"] == pytest.approx(0.4 / math.exp(-0.04 * 90 / 365))
    assert out["eightk_score"] == 0.0 and det["eightk_coverage"] == "live"


def test_enrich_market_unsupported_question_leaves_nan():
    out, det = asyncio.run(en.enrich_market({}, "Will Tesla fall below $200 by December 31?", None,
                                            client=BookClient([])))
    assert det["supported"] is False and "path question" in det["reason"]
    assert all(math.isnan(out[f]) for f in en.OPT_FIELDS)
