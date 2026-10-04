import math
from statistics import NormalDist

import pytest

from app.options.chain import Chain, OptionQuote
from app.options.implied import (bracket, delta_prob, flip, forward_from_parity, implied_for_threshold,
                                 implied_prob_above, jsonable, nearest_expiry, year_frac)

NAN = math.nan
T, R = 0.25, 0.04
DF = math.exp(-R * T)


def q(mid=NAN, bid=NAN, ask=NAN, iv=NAN, delta=NAN):
    return {"mid": mid, "bid": bid, "ask": ask, "iv": iv, "delta": delta}


def calls_slice():
    return {145.0: {"call": q(8.0, 7.9, 8.1, 0.30, 0.60)},
            150.0: {"call": q(5.0, 4.9, 5.1, 0.30, 0.50)},
            155.0: {"call": q(3.0, 2.9, 3.1, 0.30, 0.40)}}


def test_call_spread_centred_on_listed_strike_matches_hand_computation():
    res = implied_prob_above(calls_slice(), 150.0, T, R)
    assert res["method"] == "call_spread"
    assert (res["k_lo"], res["k_hi"], res["center"]) == (145.0, 155.0, 150.0)
    assert res["prob"] == pytest.approx(0.5 / DF, rel=1e-12)
    assert res["prob"] == pytest.approx(0.5050252, abs=1e-6)
    assert res["spread_mid"] == pytest.approx(5.0)
    assert res["notes"] == []


def test_bid_ask_bounds_bracket_the_mid_estimate():
    res = implied_prob_above(calls_slice(), 150.0, T, R)
    assert res["lo"] == pytest.approx((7.9 - 3.1) / 10 / DF)
    assert res["hi"] == pytest.approx((8.1 - 2.9) / 10 / DF)
    assert res["lo"] < res["prob"] < res["hi"]
    assert (res["spread_bid"], res["spread_ask"]) == (pytest.approx(4.8), pytest.approx(5.2))


def test_bounds_are_nan_without_quotes_not_invented():
    sl = {145.0: {"call": q(8.0)}, 155.0: {"call": q(3.0)}}
    res = implied_prob_above(sl, 150.0, T, R)
    assert res["prob"] == pytest.approx(0.5 / DF)
    assert math.isnan(res["lo"]) and math.isnan(res["hi"])


def test_bounds_clamped_to_unit_interval():
    sl = {145.0: {"call": q(9.95, 9.0, 10.9)}, 155.0: {"call": q(0.05, 0.0, 0.1)}}
    res = implied_prob_above(sl, 150.0, T, R)
    assert 0.0 <= res["lo"] <= res["hi"] <= 1.0
    assert res["hi"] == 1.0


def test_unlisted_threshold_uses_nearest_bracket_and_says_so():
    res = implied_prob_above(calls_slice(), 152.0, T, R)
    assert (res["k_lo"], res["k_hi"]) == (150.0, 155.0)
    assert res["prob"] == pytest.approx((5.0 - 3.0) / 5 / DF)
    assert any("centred at 152.5" in n for n in res["notes"])


def test_put_call_parity_fallback_from_put_spread():
    sl = {145.0: {"put": q(2.0, 1.9, 2.1)}, 155.0: {"put": q(6.5, 6.4, 6.6)}}
    res = implied_prob_above(sl, 150.0, T, R)
    assert res["method"] == "put_spread_parity"
    assert res["prob"] == pytest.approx(1 - 0.45 / DF)
    assert res["lo"] == pytest.approx(1 - (6.6 - 1.9) / 10 / DF)
    assert res["hi"] == pytest.approx(1 - (6.4 - 2.1) / 10 / DF)
    assert res["lo"] < res["prob"] < res["hi"]


def test_parity_synthetic_call_from_put_and_forward():
    sl = {145.0: {"put": q(2.0)}, 150.0: {"call": q(5.0), "put": q(4.0)}, 155.0: {"call": q(3.0)}}
    F = forward_from_parity(sl, DF)
    assert F == pytest.approx(150 + 1.0 / DF)
    res = implied_prob_above(sl, 150.0, T, R)
    assert res["method"] == "parity_synthetic"
    c145 = 2.0 + DF * (F - 145)
    assert res["prob"] == pytest.approx((c145 - 3.0) / 10 / DF)


def test_delta_approximation_n_d2():
    res = implied_prob_above(calls_slice(), 150.0, T, R)
    assert res["delta"] == pytest.approx(0.5)
    assert res["iv"] == pytest.approx(0.30)
    assert res["delta_prob"] == pytest.approx(NormalDist().cdf(0.0 - 0.30 * math.sqrt(T)))
    assert res["delta_prob"] == pytest.approx(0.440382, abs=1e-6)


def test_delta_used_when_no_spread_prices():
    sl = {145.0: {"call": q(delta=0.6, iv=0.3)}, 155.0: {"call": q(delta=0.4, iv=0.3)}}
    res = implied_prob_above(sl, 150.0, T, R)
    assert res["method"] == "delta"
    assert res["prob"] == pytest.approx(NormalDist().cdf(-0.15))


def test_delta_prob_edge_cases():
    assert math.isnan(delta_prob(NAN, 0.3, T))
    assert delta_prob(0.42, NAN, T) == pytest.approx(0.42)
    assert delta_prob(1.7, 0.3, T) == 1.0
    sl = {145.0: {"put": q(delta=-0.4)}, 155.0: {"put": q(delta=-0.6)}}
    assert implied_prob_above(sl, 150.0, T, R)["delta"] == pytest.approx(0.5)


def test_arbitrage_violating_spread_is_rejected_not_clamped():
    sl = {145.0: {"call": q(3.0)}, 155.0: {"call": q(8.0)}}
    res = implied_prob_above(sl, 150.0, T, R)
    assert math.isnan(res["prob"]) and res["method"] is None
    assert any("no-arbitrage" in n for n in res["notes"])


@pytest.mark.parametrize("sl,K,Tt", [
    ({}, 150.0, T),
    (calls_slice(), 500.0, T),
    (calls_slice(), NAN, T),
    (calls_slice(), 150.0, NAN),
    ({145.0: {"call": None}, 155.0: {}}, 150.0, T),
    ({145.0: {"call": {"mid": "abc"}}, 155.0: {"call": {"mid": None}}}, 150.0, T),
    ({145.0: {"call": q(math.inf)}, 155.0: {"call": q(3.0)}}, 150.0, T),
])
def test_nan_safe_never_raises(sl, K, Tt):
    res = implied_prob_above(sl, K, Tt, R)
    assert math.isnan(res["prob"])
    assert res["notes"]


def test_bracket():
    assert bracket([140, 145, 150, 155], 150) == (145, 155)
    assert bracket([140, 145, 155], 150) == (145, 155)
    assert bracket([150, 155], 150) is None
    assert bracket([140, 145], 150) is None
    assert bracket([], 150) is None


def test_nearest_expiry_to_resolution_date():
    ex = ["2026-12-18", "2026-12-24", "2027-01-15"]
    assert nearest_expiry(ex, "2026-12-31") == "2026-12-24"
    assert nearest_expiry(ex, "2027-01-10") == "2027-01-15"
    assert nearest_expiry(["2026-12-28", "2027-01-03"], "2026-12-31") == "2027-01-03"
    assert nearest_expiry(ex, "2026-12-31", as_of="2026-12-20") == "2026-12-24"
    assert nearest_expiry(ex, "2026-12-01", as_of="2027-02-01") is None
    assert nearest_expiry([], "2026-12-31") is None
    assert nearest_expiry(ex, "garbage") is None


def test_year_frac():
    assert year_frac("2026-12-31", "2026-10-02") == pytest.approx(90 / 365)
    assert year_frac("2026-10-02", "2026-10-02") == pytest.approx(1 / 365)
    assert math.isnan(year_frac("nope", "2026-10-02"))


def test_flip_for_below_questions():
    res = implied_prob_above(calls_slice(), 150.0, T, R)
    b = flip(res)
    assert b["prob"] == pytest.approx(1 - res["prob"])
    assert b["lo"] == pytest.approx(1 - res["hi"]) and b["hi"] == pytest.approx(1 - res["lo"])
    assert b["delta"] == pytest.approx(-0.5)


def _chain(expiries):
    ch = Chain(underlying="NVDA", fetched_at=0.0)
    for e in expiries:
        for k, c in ((145.0, 8.0), (150.0, 5.0), (155.0, 3.0)):
            ch.quotes.append(OptionQuote(ticker="x", kind="call", strike=k, expiry=e, mid=c, delta=0.5, iv=0.3))
    return ch


def test_implied_for_threshold_picks_nearest_expiry_and_reports_gap():
    ch = _chain(["2026-11-20", "2026-12-18"])
    res = implied_for_threshold(ch, 150.0, "2026-12-31", as_of="2026-10-02")
    assert res["expiry"] == "2026-12-18" and res["expiry_gap_days"] == -13
    assert res["T"] == pytest.approx(77 / 365)
    assert res["prob"] == pytest.approx(0.5 / math.exp(-0.04 * 77 / 365))
    assert any("-13 days" in n for n in res["notes"])
    below = implied_for_threshold(ch, 150.0, "2026-12-31", above=False, as_of="2026-10-02")
    assert below["prob"] == pytest.approx(1 - res["prob"]) and below["direction"] == "below"


def test_implied_for_threshold_without_chain():
    res = implied_for_threshold(None, 150.0, "2026-12-31", as_of="2026-10-02")
    assert math.isnan(res["prob"]) and res["expiry"] is None


def test_jsonable_replaces_nan():
    assert jsonable({"a": NAN, "b": 1.0, "c": [1]}) == {"a": None, "b": 1.0, "c": [1]}
